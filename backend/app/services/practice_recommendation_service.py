"""阶段5 服务层：题库导入、AI 生成草稿、个性化练习推荐与正式学习证据链接

完成"题库优先检索 → 无匹配题则约束生成草稿 → 教师审核/发布"的编排链路。

关键约束：
- AI 生成草稿**不可直接面向学生发布**：必须经教师审核升级为 QuestionBankItem 后才能进入推荐池
- 每次推荐携带 policy_version, reason_codes, evidence_refs, confidence, six_dimensions, question_source
- 数据不足返回 unknown / evidence_needed，不把提问次数或观看时长当掌握度
- 未归属、未映射、未发布、教师拒绝的题目不能被学生检索或推荐
- 跨课程严格隔离：所有查询都按 course_id 过滤
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.exceptions import (
    reject_course_access_denied,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import utcnow_aware
from app.models.cognitive_state_model import (
    CognitiveState,
    COGNITIVE_POLICY_VERSION,
    LearningEvidenceRecord,
)
from app.models.practice_recommendation_model import (
    AssessmentPolicy,
    AssessmentPurpose,
    EvidenceLinkContext,
    GenerationDraftStatus,
    ImportRunStatus,
    LearningEvidenceLink,
    QuestionGenerationDraft,
    QuestionImportRun,
    QuestionRecommendationItem,
    QuestionRecommendationRun,
    QuestionSource,
    RecommendationRunStatus,
)
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionStatus,
)
from app.services.question_generation_llm import (
    GENERATION_POLICY_VERSION as LLM_GEN_POLICY_VERSION,
    generate_question_sync,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 题库导入服务
# ---------------------------------------------------------------------------


PRACTICE_POLICY_VERSION = "practice-recommendation-v1.0"


class QuestionImportService:
    """Excel 题库导入服务

    - 创建导入运行（关联任务中心 task_id）
    - 行级失败明细写入 failure_details，便于审计
    - 导入的题目 import_batch_id 与本运行 run_id 对齐
    """

    def create_run(
        self,
        session: Session,
        *,
        course_id: int,
        source_file: str,
        source_object_key: str = "",
        total_rows: int = 0,
        initiated_by: int,
        task_id: Optional[str] = None,
    ) -> QuestionImportRun:
        run = QuestionImportRun(
            course_id=course_id,
            task_id=task_id,
            source_file=source_file,
            source_object_key=source_object_key,
            total_rows=total_rows,
            status=ImportRunStatus.PENDING,
            initiated_by=initiated_by,
        )
        session.add(run)
        session.flush()
        return run

    def mark_running(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
    ) -> QuestionImportRun:
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        if run.status != ImportRunStatus.PENDING:
            reject_state_conflict(
                f"导入运行状态 {run.status.value} 不能转移到 running",
                details={"current_status": run.status.value},
            )
        run.status = ImportRunStatus.RUNNING
        run.started_at = utcnow_aware()
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

    def mark_succeeded(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        imported_count: int = 0,
        skipped_count: int = 0,
    ) -> QuestionImportRun:
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        run.status = ImportRunStatus.SUCCEEDED
        run.imported_count = imported_count
        run.skipped_count = skipped_count
        run.finished_at = utcnow_aware()
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

    def mark_failed(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        error_code: str,
        error_message: str,
        failure_details: Optional[list] = None,
    ) -> QuestionImportRun:
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        run.status = ImportRunStatus.FAILED
        run.error_code = error_code
        run.error_message = error_message[:500]
        if failure_details is not None:
            run.failure_details = failure_details
        run.finished_at = utcnow_aware()
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

    def _require_run(self, session: Session, *, run_id: str, course_id: int) -> QuestionImportRun:
        run = session.exec(
            select(QuestionImportRun).where(
                QuestionImportRun.run_id == run_id,
                QuestionImportRun.course_id == course_id,
            )
        ).first()
        if run is None:
            reject_resource_not_found("题库导入运行不存在")
        return run

    def list_runs(
        self,
        session: Session,
        *,
        course_id: int,
        status: Optional[ImportRunStatus] = None,
    ) -> list[QuestionImportRun]:
        stmt = select(QuestionImportRun).where(
            QuestionImportRun.course_id == course_id
        ).order_by(QuestionImportRun.created_at.desc())
        if status is not None:
            stmt = stmt.where(QuestionImportRun.status == status)
        return list(session.exec(stmt).all())

    # ------------------------------------------------------------------
    # 执行导入（由 Task Worker 调用）
    # ------------------------------------------------------------------

    def execute_run(
        self,
        session: Session,
        *,
        run_id: str,
        course_id: int,
    ) -> QuestionImportRun:
        """执行 Excel 题库导入。

        流程：
        1. 标记 run 为 RUNNING
        2. 读取 Excel 内容（优先从 source_object_key 经对象存储读取，
           否则回退到本地 source_file 路径）
        3. 计算文件 SHA256；幂等键 = ``excel-sha256-{sha256}``
        4. 同课程+同 batch_id 已存在题目标记为"已导入过"，跳过新增
        5. 逐行解析并创建 QuestionBankItem（course_id=run.course_id,
           status=UNASSIGNED，未发布不可被学生检索）
        6. 行级失败写入 failure_details
        7. 标记 run 为 SUCCEEDED / PARTIAL_SUCCESS / FAILED

        约束：
        - 题目默认 status=UNASSIGNED，需要教师通过题源映射或题目管理
          升级为 PUBLISHED 后才能进入推荐池
        - 跨课程严格隔离：导入的题目 course_id 与 run.course_id 一致
        - 失败不伪装成功：解析错误或读取错误都标记为 FAILED 并保留原 error_code
        """
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        if run.status not in (ImportRunStatus.PENDING,):
            reject_state_conflict(
                f"导入运行状态 {run.status.value} 不可重复执行",
                details={"current_status": run.status.value},
            )

        # 1. 标记 RUNNING
        run.status = ImportRunStatus.RUNNING
        run.started_at = utcnow_aware()
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()

        try:
            content = self._load_excel_bytes(run)
        except FileNotFoundError as exc:
            return self.mark_failed(
                session,
                course_id=course_id,
                run_id=run_id,
                error_code="SOURCE_FILE_NOT_FOUND",
                error_message=str(exc)[:500],
            )
        except Exception as exc:
            return self.mark_failed(
                session,
                course_id=course_id,
                run_id=run_id,
                error_code="SOURCE_READ_FAILED",
                error_message=f"{type(exc).__name__}: {exc}"[:500],
            )

        # 2. 计算 SHA256 并构造 batch_id
        from app.tools.import_question_bank import _bytes_sha256
        source_hash = _bytes_sha256(content)
        batch_id = f"excel-sha256-{source_hash}"

        # 3. 解析 Excel
        from app.tools.import_question_bank import (
            _read_excel_rows_from_bytes,
            _map_row_to_item,
            MAX_IMPORT_BYTES,
        )
        if len(content) > MAX_IMPORT_BYTES:
            return self.mark_failed(
                session,
                course_id=course_id,
                run_id=run_id,
                error_code="SOURCE_FILE_TOO_LARGE",
                error_message=(
                    f"Excel 文件超过 {MAX_IMPORT_BYTES // (1024 * 1024)} MiB 上限"
                ),
            )

        try:
            rows = _read_excel_rows_from_bytes(content)
        except ValueError as exc:
            # 缺少必需列等结构问题
            return self.mark_failed(
                session,
                course_id=course_id,
                run_id=run_id,
                error_code="EXCEL_STRUCTURE_INVALID",
                error_message=str(exc)[:500],
            )
        except Exception as exc:
            return self.mark_failed(
                session,
                course_id=course_id,
                run_id=run_id,
                error_code="EXCEL_PARSE_FAILED",
                error_message=f"{type(exc).__name__}: {exc}"[:500],
            )

        run.total_rows = len(rows)
        session.add(run)
        session.flush()

        # 4. 幂等检查：同 course_id + batch_id 已存在题目则跳过新增
        existing = session.exec(
            select(QuestionBankItem.id).where(
                QuestionBankItem.course_id == course_id,
                QuestionBankItem.import_batch_id == batch_id,
            ).limit(1)
        ).first()
        if existing is not None:
            # 已导入过：标记成功但 imported_count=0，skipped=total_rows
            return self.mark_succeeded(
                session,
                course_id=course_id,
                run_id=run_id,
                imported_count=0,
                skipped_count=len(rows),
            )

        # 5. 逐行创建 QuestionBankItem
        imported_count = 0
        skipped_count = 0
        failure_details: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=2):  # Excel 行号从 2 开始
            # openpyxl 对空单元格返回 None；统一转为空字符串再 strip
            raw_text = row.get("标准问题")
            question_text = (str(raw_text).strip() if raw_text is not None else "")
            if not question_text:
                skipped_count += 1
                failure_details.append({
                    "row": index,
                    "reason": "question_text 为空",
                })
                continue
            try:
                item = _map_row_to_item(
                    row, index, batch_id, course_id=course_id,
                )
                session.add(item)
                imported_count += 1
            except Exception as exc:
                skipped_count += 1
                failure_details.append({
                    "row": index,
                    "reason": f"{type(exc).__name__}: {exc}",
                })

        run.imported_count = imported_count
        run.skipped_count = skipped_count
        run.failed_count = len(failure_details)
        if failure_details:
            # 只保留前 50 条以避免大字段
            run.failure_details = failure_details[:50]

        # 6. 状态判定
        if imported_count == 0 and skipped_count > 0:
            run.status = ImportRunStatus.FAILED
            run.error_code = "ALL_ROWS_SKIPPED"
            run.error_message = (
                f"全部 {skipped_count} 行被跳过，无题目被导入"
            )
        elif imported_count > 0 and skipped_count > 0:
            run.status = ImportRunStatus.PARTIAL_SUCCESS
        else:
            run.status = ImportRunStatus.SUCCEEDED

        run.finished_at = utcnow_aware()
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

    def _load_excel_bytes(self, run: QuestionImportRun) -> bytes:
        """读取 Excel 文件内容为字节。

        优先从 source_object_key 经对象存储读取（生产路径）；
        否则回退到本地 source_file 路径（CLI / 测试路径）。
        """
        object_key = (run.source_object_key or "").strip()
        if object_key:
            from app.services.object_storage import get_object_storage
            provider = get_object_storage()
            return provider.get(object_key)

        file_path = (run.source_file or "").strip()
        if not file_path:
            raise FileNotFoundError(
                "导入运行未提供 source_object_key 或 source_file"
            )
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Excel 文件不存在: {file_path}")
        if os.path.splitext(file_path)[1].lower() != ".xlsx":
            raise ValueError("仅允许导入 .xlsx 文件")
        with open(file_path, "rb") as source:
            return source.read()


# ---------------------------------------------------------------------------
# AI 生成草稿服务
# ---------------------------------------------------------------------------


class QuestionGenerationDraftService:
    """AI 约束生成草稿服务

    严格规则：
    - 草稿不可直接面向学生发布
    - 教师审核通过后升级为 QuestionBankItem（status=published 或 teacher_edited）
    - 上下文（图谱/认知状态）变化后标记为 stale，提示教师复核
    """

    def create_draft(
        self,
        session: Session,
        *,
        course_id: int,
        node_id: Optional[int],
        question_type: str,
        question_text: str,
        answer: str,
        options: Optional[list] = None,
        difficulty: str = "medium",
        category: str = "",
        generation_purpose: str = "diagnose",
        cognitive_snapshot: Optional[dict] = None,
        six_dimensions: Optional[dict] = None,
        reason_codes: Optional[list] = None,
        evidence_refs: Optional[list] = None,
        confidence: float = 0.0,
        generated_by: int,
        policy_version: str = PRACTICE_POLICY_VERSION,
        model_version: str = "question-gen-v1.0",
    ) -> QuestionGenerationDraft:
        draft = QuestionGenerationDraft(
            course_id=course_id,
            node_id=node_id,
            question_type=question_type,
            question_text=question_text,
            answer=answer,
            options=options or [],
            difficulty=difficulty,
            category=category,
            generation_purpose=generation_purpose,
            cognitive_snapshot=cognitive_snapshot or {},
            six_dimensions=six_dimensions or {},
            reason_codes=reason_codes or [],
            evidence_refs=evidence_refs or [],
            confidence=confidence,
            policy_version=policy_version,
            model_version=model_version,
            status=GenerationDraftStatus.DRAFT,
            generated_by=generated_by,
        )
        session.add(draft)
        session.flush()
        return draft

    def approve_draft(
        self,
        session: Session,
        *,
        course_id: int,
        draft_id: str,
        reviewed_by: int,
        review_comment: str = "",
        publish_status: QuestionStatus = QuestionStatus.PUBLISHED,
    ) -> tuple[QuestionGenerationDraft, QuestionBankItem]:
        """教师审核通过：升级草稿为正式 QuestionBankItem。

        - 草稿状态必须是 DRAFT 或 STALE（stale 允许重新审核）
        - 已 APPROVED/REJECTED 不可重复审核
        - 升级后的题目 is_latest=True, status=publish_status
        """
        draft = self._require_draft(session, draft_id=draft_id, course_id=course_id)
        if draft.status == GenerationDraftStatus.APPROVED:
            reject_state_conflict("草稿已审核通过，无需重复审核")
        if draft.status == GenerationDraftStatus.REJECTED:
            reject_state_conflict("草稿已被拒绝，不可再通过")

        # 创建正式 QuestionBankItem
        question = QuestionBankItem(
            question_text=draft.question_text,
            answer=draft.answer,
            options=draft.options,
            question_type=draft.question_type,
            difficulty=draft.difficulty,
            category=draft.category,
            course_id=course_id,
            knowledge_node_ids=[draft.node_id] if draft.node_id else [],
            status=publish_status,
            version=1,
            is_latest=True,
            generated_by="ai_constrained",
            generation_metadata={
                "draft_id": draft.draft_id,
                "generation_purpose": draft.generation_purpose,
                "six_dimensions": draft.six_dimensions,
                "reason_codes": draft.reason_codes,
                "evidence_refs": draft.evidence_refs,
                "confidence": draft.confidence,
                "policy_version": draft.policy_version,
                "model_version": draft.model_version,
            },
            created_by=reviewed_by,
            created_at=utcnow_aware(),
            updated_at=utcnow_aware(),
            published_at=utcnow_aware() if publish_status == QuestionStatus.PUBLISHED else None,
            published_by=reviewed_by if publish_status == QuestionStatus.PUBLISHED else None,
        )
        session.add(question)
        session.flush()

        draft.status = GenerationDraftStatus.APPROVED
        draft.reviewed_by = reviewed_by
        draft.reviewed_at = utcnow_aware()
        draft.review_comment = review_comment
        draft.upgraded_question_id = question.id
        draft.updated_at = utcnow_aware()
        session.add(draft)
        session.flush()
        return draft, question

    def reject_draft(
        self,
        session: Session,
        *,
        course_id: int,
        draft_id: str,
        rejected_by: int,
        review_comment: str = "",
    ) -> QuestionGenerationDraft:
        draft = self._require_draft(session, draft_id=draft_id, course_id=course_id)
        if draft.status in (GenerationDraftStatus.APPROVED, GenerationDraftStatus.REJECTED):
            reject_state_conflict(
                f"草稿状态 {draft.status.value} 不可拒绝",
                details={"current_status": draft.status.value},
            )
        draft.status = GenerationDraftStatus.REJECTED
        draft.reviewed_by = rejected_by
        draft.reviewed_at = utcnow_aware()
        draft.review_comment = review_comment
        draft.updated_at = utcnow_aware()
        session.add(draft)
        session.flush()
        return draft

    def mark_stale(
        self,
        session: Session,
        *,
        course_id: int,
        draft_id: str,
        stale_reason: str,
    ) -> QuestionGenerationDraft:
        """上下文变化后标记草稿为 stale，提示教师复核。"""
        draft = self._require_draft(session, draft_id=draft_id, course_id=course_id)
        if draft.status != GenerationDraftStatus.DRAFT:
            reject_state_conflict(
                f"草稿状态 {draft.status.value} 不可标记 stale",
                details={"current_status": draft.status.value},
            )
        draft.status = GenerationDraftStatus.STALE
        draft.stale_reason = stale_reason
        draft.stale_at = utcnow_aware()
        draft.updated_at = utcnow_aware()
        session.add(draft)
        session.flush()
        return draft

    def _require_draft(
        self, session: Session, *, draft_id: str, course_id: int,
    ) -> QuestionGenerationDraft:
        draft = session.exec(
            select(QuestionGenerationDraft).where(
                QuestionGenerationDraft.draft_id == draft_id,
                QuestionGenerationDraft.course_id == course_id,
            )
        ).first()
        if draft is None:
            reject_resource_not_found("AI 生成草稿不存在")
        return draft

    def list_drafts(
        self,
        session: Session,
        *,
        course_id: int,
        status: Optional[GenerationDraftStatus] = None,
        node_id: Optional[int] = None,
    ) -> list[QuestionGenerationDraft]:
        stmt = select(QuestionGenerationDraft).where(
            QuestionGenerationDraft.course_id == course_id
        )
        if status is not None:
            stmt = stmt.where(QuestionGenerationDraft.status == status)
        if node_id is not None:
            stmt = stmt.where(QuestionGenerationDraft.node_id == node_id)
        stmt = stmt.order_by(QuestionGenerationDraft.created_at.desc())
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# 个性化练习推荐服务
# ---------------------------------------------------------------------------


class PracticeRecommendationService:
    """个性化练习推荐服务

    编排流程：
    1. 题库优先检索：从课程已发布题库按 node_id/difficulty/purpose 检索
    2. 无匹配题时约束生成草稿：调用 QuestionGenerationDraftService 创建草稿，
       **不直接对学生发布**
    3. 教师审核草稿：升级为正式 QuestionBankItem 后才能进入学生可见池
    4. 学生开始推荐项：标记 is_started，转化为 QuestionAttempt（不在本服务实现）

    每次推荐运行承载 policy_version, six_dimensions, reason_codes, evidence_refs,
    confidence，便于审计与回放。
    """

    # 默认每个推荐运行产生的推荐项数量
    DEFAULT_ITEM_COUNT = 3
    # 低置信度阈值
    LOW_CONFIDENCE_THRESHOLD = 0.4

    def create_recommendation(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        node_id: Optional[int] = None,
        purpose: str = "diagnose",
        cognitive_state: Optional[CognitiveState] = None,
        item_count: int = DEFAULT_ITEM_COUNT,
        allow_generation: bool = True,
    ) -> QuestionRecommendationRun:
        """创建一次推荐运行。

        - 题库优先检索：命中已发布题库题
        - 无匹配题且 allow_generation=True：创建 AI 草稿（不直接发布）
        - 每个推荐项携带 question_source=bank|generated_draft
        - 数据不足时返回 unknown 语义（confidence < LOW_CONFIDENCE_THRESHOLD）
        """
        recommendation_id = "rec_" + uuid.uuid4().hex
        now = utcnow_aware()

        # 抽取认知快照与六维诊断
        cognitive_snapshot: dict = {}
        six_dimensions: dict = {}
        reason_codes: list = []
        evidence_refs: list = []
        confidence = 0.0
        if cognitive_state is not None:
            cognitive_snapshot = {
                "observed_performance_score": cognitive_state.observed_performance_score,
                "evidence_confidence": cognitive_state.evidence_confidence,
                "confusion_risk": cognitive_state.confusion_risk,
                "inquiry_depth": cognitive_state.inquiry_depth,
                "hint_dependency": cognitive_state.hint_dependency,
                "explanation_need": cognitive_state.explanation_need,
                "mastery_level": cognitive_state.mastery_level,
                "sample_size": cognitive_state.sample_size,
                "policy_version": cognitive_state.policy_version,
            }
            six_dimensions = {
                "observed_performance_score": cognitive_state.observed_performance_score,
                "evidence_confidence": cognitive_state.evidence_confidence,
                "confusion_risk": cognitive_state.confusion_risk,
                "inquiry_depth": cognitive_state.inquiry_depth,
                "hint_dependency": cognitive_state.hint_dependency,
                "explanation_need": cognitive_state.explanation_need,
            }
            reason_codes = list(cognitive_state.reason_codes or [])
            evidence_refs = list(cognitive_state.evidence_refs or [])
            confidence = cognitive_state.evidence_confidence or 0.0
            # 数据不足时增加 reason_code
            if cognitive_state.sample_size is not None and cognitive_state.sample_size < 3:
                if "insufficient_data" not in reason_codes:
                    reason_codes.append("insufficient_data")
            if (cognitive_state.evidence_confidence or 0) < self.LOW_CONFIDENCE_THRESHOLD:
                if "evidence_needed" not in reason_codes:
                    reason_codes.append("evidence_needed")

        run = QuestionRecommendationRun(
            course_id=course_id,
            student_id=student_id,
            node_id=node_id,
            recommendation_id=recommendation_id,
            purpose=purpose,
            policy_version=PRACTICE_POLICY_VERSION,
            six_dimensions=six_dimensions,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            confidence=confidence,
            cognitive_state_id=cognitive_state.id if cognitive_state else None,
            status=RecommendationRunStatus.PENDING,
            started_at=now,
        )
        session.add(run)
        session.flush()

        # 题库优先检索
        items_created = 0
        bank_questions = self._search_bank_questions(
            session,
            course_id=course_id,
            node_id=node_id,
            limit=item_count,
        )
        for idx, q in enumerate(bank_questions[:item_count]):
            item = QuestionRecommendationItem(
                run_id=run.run_id,
                course_id=course_id,
                student_id=student_id,
                recommendation_id=recommendation_id,
                question_source=QuestionSource.BANK,
                question_id=q.id,
                node_id=node_id,
                reason_codes=reason_codes,
                evidence_refs=evidence_refs,
                confidence=confidence,
                order_index=idx,
            )
            session.add(item)
            items_created += 1

        # 题库不足时通过 LLM 生成个性化草稿（不直接发布）
        if items_created < item_count and allow_generation:
            # 读取学生近期提问反推信号（来自 Conversation Domain 的结构化投影，不含原文）。
            # 失败不阻塞出题：inference 不可用时降级为不带提问信号。
            question_signals: Optional[list] = None
            try:
                from app.services.conversation_service import derive_question_inference_signals
                inference = derive_question_inference_signals(
                    session,
                    student_id=student_id,
                    course_id=course_id,
                    concept_id=str(node_id) if node_id else None,
                    lookback_days=14,
                )
                question_signals = inference.get("signals") or None
            except Exception:
                question_signals = None
            remaining = item_count - items_created
            for i in range(remaining):
                # P1-5: 调用 LLM 生成个性化题目；LLM 不可用时返回带明确标记的占位草稿
                gen = generate_question_sync(
                    session,
                    course_id=course_id,
                    node_id=node_id,
                    purpose=purpose,
                    difficulty="medium",
                    cognitive_snapshot=cognitive_snapshot,
                    six_dimensions=six_dimensions,
                    reason_codes=reason_codes,
                    question_signals=question_signals,
                )
                # 合并 LLM 返回的 reason_codes 与运行级 reason_codes
                merged_reasons = list(reason_codes)
                for rc in gen.get("reason_codes", []):
                    if rc not in merged_reasons:
                        merged_reasons.append(rc)
                # 草稿置信度取 LLM 返回值与运行级置信度的较低者，
                # 避免在数据不足时仍宣称高置信度
                draft_confidence = min(
                    float(gen.get("confidence", 0.0) or 0.0),
                    confidence if confidence > 0 else 1.0,
                )
                draft = question_generation_draft_service.create_draft(
                    session,
                    course_id=course_id,
                    node_id=node_id,
                    question_type="short_answer",
                    question_text=gen["question_text"],
                    answer=gen["answer"],
                    options=gen.get("options") or [],
                    difficulty=gen.get("difficulty") or "medium",
                    category=gen.get("category") or "",
                    generation_purpose=purpose,
                    cognitive_snapshot=cognitive_snapshot,
                    six_dimensions=six_dimensions,
                    reason_codes=merged_reasons,
                    evidence_refs=evidence_refs,
                    confidence=draft_confidence,
                    generated_by=student_id,  # 由学生触发生成，但草稿不直接对学生可见
                    policy_version=PRACTICE_POLICY_VERSION,
                    model_version=LLM_GEN_POLICY_VERSION,
                )
                item = QuestionRecommendationItem(
                    run_id=run.run_id,
                    course_id=course_id,
                    student_id=student_id,
                    recommendation_id=recommendation_id,
                    question_source=QuestionSource.GENERATED_DRAFT,
                    generation_draft_id=draft.draft_id,
                    node_id=node_id,
                    reason_codes=merged_reasons,
                    evidence_refs=evidence_refs,
                    confidence=draft_confidence,
                    order_index=items_created + i,
                )
                session.add(item)
                items_created += 1

        run.item_count = items_created
        run.status = RecommendationRunStatus.SUCCEEDED if items_created > 0 else RecommendationRunStatus.PARTIAL_SUCCESS
        run.finished_at = utcnow_aware()
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

    def _search_bank_questions(
        self,
        session: Session,
        *,
        course_id: int,
        node_id: Optional[int],
        limit: int,
    ) -> list[QuestionBankItem]:
        """从课程已发布题库检索题目。

        严格规则：
        - 仅 status=PUBLISHED 且 is_latest=True 的题目
        - 未归属、未映射、未发布、教师拒绝的题目不能被检索
        - 跨课程严格隔离
        """
        stmt = select(QuestionBankItem).where(
            QuestionBankItem.course_id == course_id,
            QuestionBankItem.status == QuestionStatus.PUBLISHED,
            QuestionBankItem.is_latest == True,  # noqa: E712
        )
        if node_id is not None:
            stmt = stmt.where(QuestionBankItem.knowledge_node_ids.contains([node_id]))
        stmt = stmt.limit(limit)
        return list(session.exec(stmt).all())

    def get_recommendation(
        self,
        session: Session,
        *,
        course_id: int,
        recommendation_id: str,
        student_id: Optional[int] = None,
    ) -> tuple[QuestionRecommendationRun, list[QuestionRecommendationItem]]:
        """获取推荐运行及其推荐项。

        - 跨用户拒绝：student_id 不匹配时返回 404
        - 学生只能看自己的推荐
        """
        run = session.exec(
            select(QuestionRecommendationRun).where(
                QuestionRecommendationRun.recommendation_id == recommendation_id,
                QuestionRecommendationRun.course_id == course_id,
            )
        ).first()
        if run is None:
            reject_resource_not_found("推荐运行不存在")
        if student_id is not None and run.student_id != student_id:
            # 跨用户访问拒绝，统一返回 404 避免泄露存在性
            reject_resource_not_found("推荐运行不存在")
        items = list(session.exec(
            select(QuestionRecommendationItem).where(
                QuestionRecommendationItem.run_id == run.run_id,
                QuestionRecommendationItem.course_id == course_id,
            ).order_by(QuestionRecommendationItem.order_index)
        ).all())
        return run, items

    def start_recommendation_item(
        self,
        session: Session,
        *,
        course_id: int,
        recommendation_id: str,
        item_id: str,
        student_id: int,
    ) -> QuestionRecommendationItem:
        """学生开始作答推荐项。

        - 标记 is_started=True
        - bank 题目可正常开始；generated_draft 题目需教师先升级（否则拒绝）
        """
        run, items = self.get_recommendation(
            session,
            course_id=course_id,
            recommendation_id=recommendation_id,
            student_id=student_id,
        )
        item = next((it for it in items if it.item_id == item_id), None)
        if item is None:
            reject_resource_not_found("推荐项不存在")
        if item.is_started:
            reject_state_conflict("推荐项已开始")
        if item.question_source == QuestionSource.GENERATED_DRAFT:
            # 草稿未升级前不可开始作答
            draft = session.exec(
                select(QuestionGenerationDraft).where(
                    QuestionGenerationDraft.draft_id == item.generation_draft_id,
                    QuestionGenerationDraft.course_id == course_id,
                )
            ).first()
            if draft is None or draft.status != GenerationDraftStatus.APPROVED:
                reject_state_conflict(
                    "AI 生成草稿尚未经教师审核，不可开始作答",
                    details={"draft_status": draft.status.value if draft else "missing"},
                )
            # 升级后改写 question_id
            item.question_id = draft.upgraded_question_id
        item.is_started = True
        item.started_at = utcnow_aware()
        item.updated_at = utcnow_aware()
        session.add(item)
        session.flush()
        return item

    def list_student_recommendations(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        node_id: Optional[int] = None,
        limit: int = 20,
    ) -> list[QuestionRecommendationRun]:
        """学生查询自己的推荐历史。"""
        stmt = select(QuestionRecommendationRun).where(
            QuestionRecommendationRun.course_id == course_id,
            QuestionRecommendationRun.student_id == student_id,
        )
        if node_id is not None:
            stmt = stmt.where(QuestionRecommendationRun.node_id == node_id)
        stmt = stmt.order_by(QuestionRecommendationRun.created_at.desc()).limit(limit)
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# 评分策略服务
# ---------------------------------------------------------------------------


class AssessmentPolicyService:
    """评分策略版本化服务

    策略与课程严格隔离：所有查询都按 course_id 过滤，避免课程 A 的策略
    泄漏到课程 B 的策略列表。
    """

    def get_or_create_policy(
        self,
        session: Session,
        *,
        course_id: int,
        purpose: AssessmentPurpose,
        created_by: int,
        policy_version: str = "assessment-policy-v1.0",
        passing_score: float = 0.6,
        confidence_threshold: float = 0.5,
        writes_formal_evidence: bool = True,
        max_attempts_per_node: int = 3,
        cooldown_minutes: int = 30,
        rules: Optional[dict] = None,
    ) -> AssessmentPolicy:
        existing = session.exec(
            select(AssessmentPolicy).where(
                AssessmentPolicy.course_id == course_id,
                AssessmentPolicy.purpose == purpose,
                AssessmentPolicy.policy_version == policy_version,
            )
        ).first()
        if existing is not None:
            return existing
        policy = AssessmentPolicy(
            course_id=course_id,
            purpose=purpose,
            policy_version=policy_version,
            passing_score=passing_score,
            confidence_threshold=confidence_threshold,
            writes_formal_evidence=writes_formal_evidence,
            max_attempts_per_node=max_attempts_per_node,
            cooldown_minutes=cooldown_minutes,
            rules=rules or {},
            created_by=created_by,
        )
        session.add(policy)
        session.flush()
        return policy

    def get_policy(
        self,
        session: Session,
        *,
        course_id: int,
        purpose: AssessmentPurpose,
    ) -> AssessmentPolicy:
        policy = session.exec(
            select(AssessmentPolicy).where(
                AssessmentPolicy.course_id == course_id,
                AssessmentPolicy.purpose == purpose,
                AssessmentPolicy.is_active == True,  # noqa: E712
            ).order_by(AssessmentPolicy.created_at.desc())
        ).first()
        if policy is None:
            reject_resource_not_found(f"未找到 {purpose.value} 的有效评分策略")
        return policy

    def list_policies(
        self,
        session: Session,
        *,
        course_id: int,
        purpose: Optional[AssessmentPurpose] = None,
    ) -> list[AssessmentPolicy]:
        stmt = select(AssessmentPolicy).where(
            AssessmentPolicy.course_id == course_id,
            AssessmentPolicy.is_active == True,  # noqa: E712
        )
        if purpose is not None:
            stmt = stmt.where(AssessmentPolicy.purpose == purpose)
        stmt = stmt.order_by(AssessmentPolicy.purpose, AssessmentPolicy.created_at.desc())
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# 学习证据链接服务
# ---------------------------------------------------------------------------


class LearningEvidenceLinkService:
    """学习证据链接服务

    将 LearningEvidenceRecord 链接到推荐运行、题目尝试、动作完成等上下文，
    便于"为什么这条证据被采纳"的追溯。
    """

    def link(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        evidence_id: str,
        context_type: EvidenceLinkContext,
        context_id: str,
        context_snapshot: Optional[dict] = None,
    ) -> LearningEvidenceLink:
        link = LearningEvidenceLink(
            course_id=course_id,
            student_id=student_id,
            evidence_id=evidence_id,
            context_type=context_type,
            context_id=context_id,
            context_snapshot=context_snapshot or {},
        )
        session.add(link)
        session.flush()
        return link

    def list_links_for_evidence(
        self,
        session: Session,
        *,
        course_id: int,
        evidence_id: str,
    ) -> list[LearningEvidenceLink]:
        return list(session.exec(
            select(LearningEvidenceLink).where(
                LearningEvidenceLink.course_id == course_id,
                LearningEvidenceLink.evidence_id == evidence_id,
            ).order_by(LearningEvidenceLink.linked_at.desc())
        ).all())

    def list_links_for_context(
        self,
        session: Session,
        *,
        course_id: int,
        context_type: EvidenceLinkContext,
        context_id: str,
    ) -> list[LearningEvidenceLink]:
        return list(session.exec(
            select(LearningEvidenceLink).where(
                LearningEvidenceLink.course_id == course_id,
                LearningEvidenceLink.context_type == context_type,
                LearningEvidenceLink.context_id == context_id,
            ).order_by(LearningEvidenceLink.linked_at.desc())
        ).all())


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

question_import_service = QuestionImportService()
question_generation_draft_service = QuestionGenerationDraftService()
practice_recommendation_service = PracticeRecommendationService()
assessment_policy_service = AssessmentPolicyService()
learning_evidence_link_service = LearningEvidenceLinkService()
