"""阶段4 服务层：课程材料解析、Evidence、Citation 与图谱候选

不重复实现已有 graph_production_service 的能力（CourseEvidenceRecord/GraphSnapshotRecord/GraphNodeReview），
而是补全解析流水线、候选证据、学生可读 Citation、图谱候选批次、release 关联。

关键约束：
- 跨课程严格隔离：所有查询都按 course_id 过滤
- 教师确认才升级为正式证据：EvidenceSpan.confirm → 生成 CourseEvidenceRecord + EvidenceCitation
- 重解析不静默失效：旧 EvidenceSpan/EvidenceCitation 按 stale_strategy 标记
- 图谱不可用时降级：parse_run 失败不影响已有 Citation 查询
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.exceptions import (
    reject_course_access_denied,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import utcnow_aware
from app.models.document_parse_model import (
    CandidateBatchStatus,
    CitationStatus,
    DocumentBlock,
    DocumentIRVersion,
    DocumentParseRun,
    EvidenceCitation,
    EvidenceAnchor,
    RetrievalIndexSnapshot,
    RetrievalChunk,
    EvidenceRenderAsset,
    EvidenceSpan,
    EvidenceSpanStatus,
    GraphCandidateBatch,
    GraphReleaseLink,
    ParsePipeline,
    ParseRunStatus,
    StaleStrategy,
)
from app.models.document_artifact_model import DocumentArtifact
from app.models.course_build_model import SourceMaterial, SourceMaterialVersion
from app.models.graph_production_model import (
    CourseEvidenceRecord,
    CourseKnowledgeNode,
    EvidenceStatus,
    GraphSnapshotRecord,
    SnapshotStatus,
)
from app.platform.document_intelligence.canonical.block_noise import classify_noise_blocks


# ---------------------------------------------------------------------------
# 解析流水线服务
# ---------------------------------------------------------------------------


class DocumentParseService:
    """课程材料解析流水线服务

    负责创建解析任务、记录运行、写入文档块、抽取候选证据、生成学生可读 Citation。
    解析本身通过统一任务中心异步执行；本服务负责持久化运行元数据与产物。
    """

    def create_run(
        self,
        session: Session,
        *,
        course_id: int,
        material_id: str,
        material_version_id: Optional[str] = None,
        document_id: Optional[str] = None,
        task_id: Optional[str] = None,
        pipeline: ParsePipeline = ParsePipeline.FULL,
        stale_strategy: StaleStrategy = StaleStrategy.MARK_STALE,
        parse_profile: str = "standard",
        reparse_scope: Optional[dict] = None,
        initiated_by: int,
    ) -> DocumentParseRun:
        """创建解析运行。

        - 同一 material_version 不允许并发 pending/running 运行（避免重复解析）
        - 若存在历史 succeeded 运行，记录 prev_run_id 形成链
        """
        # 并发保护
        existing_active = session.exec(
            select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.material_id == material_id,
                DocumentParseRun.status.in_([
                    ParseRunStatus.PENDING, ParseRunStatus.RUNNING,
                ]),
            )
        ).first()
        if existing_active is not None:
            reject_state_conflict(
                "该材料已有正在进行的解析任务",
                details={"existing_run_id": existing_active.run_id},
            )

        # 链接上一运行（用于重解析追溯）
        prev_run = session.exec(
            select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.material_id == material_id,
                DocumentParseRun.status.in_([
                    ParseRunStatus.SUCCEEDED, ParseRunStatus.PARTIAL_SUCCESS,
                ]),
            ).order_by(DocumentParseRun.finished_at.desc())
        ).first()

        run = DocumentParseRun(
            course_id=course_id,
            material_id=material_id,
            material_version_id=material_version_id,
            document_id=document_id,
            task_id=task_id,
            prev_run_id=prev_run.run_id if prev_run else None,
            pipeline=pipeline,
            status=ParseRunStatus.PENDING,
            stale_strategy=stale_strategy,
            parse_profile=parse_profile,
            reparse_scope=reparse_scope or {},
            initiated_by=initiated_by,
        )
        session.add(run)
        session.flush()
        if task_id:
            self.bind_task(
                session,
                course_id=course_id,
                run_id=run.run_id,
                task_id=task_id,
            )

        # Keep the currently published evidence usable until the replacement
        # parse succeeds and a teacher explicitly applies its diff.
        return run

    def apply_reparse(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
    ) -> DocumentParseRun:
        """Apply a successful reparse's explicit stale strategy exactly once."""
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        if run.status not in (ParseRunStatus.SUCCEEDED, ParseRunStatus.PARTIAL_SUCCESS):
            reject_state_conflict("重解析尚未成功，不能替换旧证据")
        if not run.prev_run_id:
            reject_state_conflict("首次解析没有可替换的旧证据")
        if run.reparse_applied:
            return run
        affected = self._mark_old_evidence_stale(
            session,
            course_id=course_id,
            run_id=run.prev_run_id,
            stale_strategy=run.stale_strategy,
        )
        self._activate_retrieval_snapshot(
            session, course_id=course_id, ir_version_id=run.document_ir_version_id,
        )
        run.affected_evidence_count = affected
        run.reparse_applied = True
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

    @staticmethod
    def bind_task(
        session: Session,
        *,
        course_id: int,
        run_id: str,
        task_id: str,
    ) -> None:
        """Persist the parse run ID in its task so retries remain executable."""
        from app.models.task_model import TaskRecord

        task = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).first()
        if task is None:
            raise ValueError(f"TaskRecord not found: {task_id}")
        if task.task_type != "document_parse" or task.course_id != course_id:
            raise ValueError("TaskRecord is not a course-scoped document_parse task")
        try:
            payload = json.loads(task.input_payload or "{}")
        except (TypeError, ValueError):
            payload = {}
        payload["course_id"] = course_id
        payload["run_id"] = run_id
        task.input_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        task.updated_at = utcnow_aware()
        session.add(task)

    def activate_initial_retrieval_snapshot(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
    ) -> None:
        """Publish the first parse's formal index once its task succeeds."""
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        if run.prev_run_id is None:
            self._activate_retrieval_snapshot(
                session, course_id=course_id, ir_version_id=run.document_ir_version_id,
            )

    @staticmethod
    def _activate_retrieval_snapshot(
        session: Session, *, course_id: int, ir_version_id: Optional[str],
    ) -> None:
        if not ir_version_id:
            return
        target = session.exec(select(RetrievalIndexSnapshot).where(
            RetrievalIndexSnapshot.course_id == course_id,
            RetrievalIndexSnapshot.ir_version_id == ir_version_id,
        )).first()
        if target is None:
            return
        now = utcnow_aware()
        active = session.exec(select(RetrievalIndexSnapshot).where(
            RetrievalIndexSnapshot.course_id == course_id,
            RetrievalIndexSnapshot.status == "active",
        )).all()
        for snapshot in active:
            if snapshot.snapshot_id != target.snapshot_id:
                snapshot.status = "superseded"
                snapshot.superseded_at = now
                session.add(snapshot)
        target.status = "active"
        target.activated_at = now
        session.add(target)
        chunks = session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == course_id,
            RetrievalChunk.ir_version_id == ir_version_id,
        )).all()
        for chunk in chunks:
            # Retrieval remains evidence-gated. Candidate anchors are not
            # searchable merely because their enclosing snapshot is active.
            if chunk.status == "draft":
                chunk.status = "candidate"
                session.add(chunk)

    def _mark_old_evidence_stale(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        stale_strategy: StaleStrategy,
    ) -> int:
        """根据 stale_strategy 处理旧证据。

        - mark_stale: EvidenceSpan.status=stale, EvidenceCitation.status=source_updated
        - orphan: EvidenceSpan.status=orphaned, EvidenceCitation.status=source_invalid
        - delete: 物理删除（默认不使用）
        """
        now = utcnow_aware()
        affected = 0
        if stale_strategy == StaleStrategy.DELETE:
            # 仅在明确授权时使用，默认不删除
            spans = session.exec(
                select(EvidenceSpan).where(
                    EvidenceSpan.course_id == course_id,
                    EvidenceSpan.run_id == run_id,
                    EvidenceSpan.status.in_([
                        EvidenceSpanStatus.CANDIDATE, EvidenceSpanStatus.CONFIRMED,
                    ]),
                )
            ).all()
            for span in spans:
                session.delete(span)
                affected += 1
            citations = session.exec(
                select(EvidenceCitation).where(
                    EvidenceCitation.course_id == course_id,
                    EvidenceCitation.run_id == run_id,
                    EvidenceCitation.status.in_([
                        CitationStatus.EXACT, CitationStatus.APPROXIMATE,
                    ]),
                )
            ).all()
            for cit in citations:
                session.delete(cit)
                affected += 1
            formal_records = session.exec(select(CourseEvidenceRecord).where(
                CourseEvidenceRecord.course_id == course_id,
                CourseEvidenceRecord.run_id == run_id,
            )).all()
            for formal in formal_records:
                session.delete(formal)
                affected += 1
            return affected

        new_span_status = (
            EvidenceSpanStatus.STALE if stale_strategy == StaleStrategy.MARK_STALE
            else EvidenceSpanStatus.ORPHANED
        )
        new_citation_status = (
            CitationStatus.SOURCE_UPDATED if stale_strategy == StaleStrategy.MARK_STALE
            else CitationStatus.SOURCE_INVALID
        )
        reason = "courseware_reparse" if stale_strategy == StaleStrategy.MARK_STALE else "courseware_orphaned"

        spans = session.exec(
            select(EvidenceSpan).where(
                EvidenceSpan.course_id == course_id,
                EvidenceSpan.run_id == run_id,
                EvidenceSpan.status.in_([
                    EvidenceSpanStatus.CANDIDATE, EvidenceSpanStatus.CONFIRMED,
                ]),
            )
        ).all()
        for span in spans:
            span.status = new_span_status
            span.stale_reason = reason
            span.stale_at = now
            span.updated_at = now
            session.add(span)
            self._set_canonical_projection_status(session, span=span, status=new_span_status.value)
            affected += 1

        citations = session.exec(
            select(EvidenceCitation).where(
                EvidenceCitation.course_id == course_id,
                EvidenceCitation.run_id == run_id,
                EvidenceCitation.status.in_([
                    CitationStatus.EXACT, CitationStatus.APPROXIMATE,
                ]),
            )
        ).all()
        for cit in citations:
            cit.status = new_citation_status
            cit.stale_reason = reason
            cit.stale_at = now
            cit.updated_at = now
            session.add(cit)
            affected += 1

        formal_records = session.exec(select(CourseEvidenceRecord).where(
            CourseEvidenceRecord.course_id == course_id,
            CourseEvidenceRecord.run_id == run_id,
            CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
        )).all()
        for formal in formal_records:
            formal.status = (
                EvidenceStatus.STALE
                if stale_strategy == StaleStrategy.MARK_STALE
                else EvidenceStatus.ORPHANED
            )
            formal.stale_reason = reason
            formal.stale_at = now
            session.add(formal)
            affected += 1
        return affected

    def mark_running(
        self,
        session: Session,
        *,
        run_id: str,
        course_id: int,
    ) -> DocumentParseRun:
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        if run.status != ParseRunStatus.PENDING:
            reject_state_conflict(
                f"解析运行状态 {run.status.value} 不能转移到 running",
                details={"current_status": run.status.value},
            )
        run.status = ParseRunStatus.RUNNING
        run.started_at = utcnow_aware()
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

    def mark_succeeded(
        self,
        session: Session,
        *,
        run_id: str,
        course_id: int,
        block_count: int = 0,
        evidence_span_count: int = 0,
        graph_candidate_count: int = 0,
    ) -> DocumentParseRun:
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        if run.status not in (ParseRunStatus.PENDING, ParseRunStatus.RUNNING):
            reject_state_conflict(
                f"解析运行状态 {run.status.value} 不能转移到 succeeded",
                details={"current_status": run.status.value},
            )
        version = None
        if run.document_ir_version_id:
            version = session.exec(select(DocumentIRVersion).where(
                DocumentIRVersion.ir_version_id == run.document_ir_version_id,
            )).first()
        requires_review = bool(version and (
            version.needs_review
            or version.parse_outcome in {
                "partial_success", "manual_review_required", "unsupported_visual_structure",
            }
        ))
        run.status = (
            ParseRunStatus.PARTIAL_SUCCESS if requires_review
            else ParseRunStatus.SUCCEEDED
        )
        run.block_count = block_count
        run.evidence_span_count = evidence_span_count
        run.graph_candidate_count = graph_candidate_count
        run.finished_at = utcnow_aware()
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

    def mark_failed(
        self,
        session: Session,
        *,
        run_id: str,
        course_id: int,
        error_code: str,
        error_message: str,
    ) -> DocumentParseRun:
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        run.status = ParseRunStatus.FAILED
        run.error_code = error_code
        run.error_message = error_message[:500]
        run.finished_at = utcnow_aware()
        run.updated_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

    def _require_run(self, session: Session, *, run_id: str, course_id: int) -> DocumentParseRun:
        run = session.exec(
            select(DocumentParseRun).where(
                DocumentParseRun.run_id == run_id,
                DocumentParseRun.course_id == course_id,
            )
        ).first()
        if run is None:
            reject_resource_not_found("解析运行不存在")
        return run

    def list_runs(
        self,
        session: Session,
        *,
        course_id: int,
        material_id: Optional[str] = None,
        status: Optional[ParseRunStatus] = None,
    ) -> list[DocumentParseRun]:
        stmt = select(DocumentParseRun).where(
            DocumentParseRun.course_id == course_id
        ).order_by(DocumentParseRun.created_at.desc())
        if material_id is not None:
            stmt = stmt.where(DocumentParseRun.material_id == material_id)
        if status is not None:
            stmt = stmt.where(DocumentParseRun.status == status)
        return list(session.exec(stmt).all())

    # --- 文档块与证据片段 ---------------------------------------------

    def add_block(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        document_id: Optional[str],
        page_number: int,
        block_type: str,
        text: str,
        bbox: Optional[dict] = None,
        char_start: int = 0,
        char_end: int = 0,
        order_index: int = 0,
        material_version_id: Optional[str] = None,
        page_or_slide: int = 0,
        source_kind: str = "",
        confidence: float = 0.0,
        provider_version: str = "",
        heading_level: Optional[int] = None,
        semantic_role: str = "",
        style_hints: Optional[dict] = None,
        parent_block_id: Optional[str] = None,
        reading_order: int = 0,
        visual_description: Optional[str] = None,
    ) -> DocumentBlock:
        """写入文档块，带内容哈希。

        Step 3：保留解析溯源字段（material_version_id/page_or_slide/source_kind/
        confidence/provider_version），使组合式解析（原生文本 + OCR 经 Reconciler
        合并）可追溯每块文本来源。
        """
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
        block = DocumentBlock(
            course_id=course_id,
            run_id=run_id,
            document_id=document_id,
            page_number=page_number,
            block_type=block_type,
            text=text,
            bbox=bbox,
            char_start=char_start,
            char_end=char_end,
            content_hash=content_hash,
            order_index=order_index,
            material_version_id=material_version_id,
            page_or_slide=page_or_slide or page_number,
            source_kind=source_kind,
            confidence=confidence,
            provider_version=provider_version,
            heading_level=heading_level,
            semantic_role=semantic_role,
            style_hints=style_hints,
            parent_block_id=parent_block_id,
            reading_order=reading_order,
            visual_description=visual_description,
        )
        session.add(block)
        session.flush()
        return block

    def add_evidence_span(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        block_id: str,
        document_id: Optional[str],
        page_number: int,
        text_snippet: str,
        bbox: Optional[dict] = None,
        char_start: int = 0,
        char_end: int = 0,
        linked_node_ids: Optional[list] = None,
    ) -> EvidenceSpan:
        """写入候选证据片段（status=candidate）。"""
        content_hash = hashlib.sha256(text_snippet.encode("utf-8")).hexdigest() if text_snippet else ""
        span = EvidenceSpan(
            course_id=course_id,
            run_id=run_id,
            block_id=block_id,
            document_id=document_id,
            page_number=page_number,
            text_snippet=text_snippet,
            bbox=bbox,
            char_start=char_start,
            char_end=char_end,
            content_hash=content_hash,
            status=EvidenceSpanStatus.CANDIDATE,
            linked_node_ids=linked_node_ids or [],
        )
        session.add(span)
        session.flush()
        return span

    def confirm_evidence_span(
        self,
        session: Session,
        *,
        course_id: int,
        span_id: str,
        confirmed_by: int,
        source_file: str = "",
        source_type: str = "document",
        node_id: Optional[int] = None,
        identity_node_key: Optional[str] = None,
    ) -> tuple[EvidenceSpan, CourseEvidenceRecord, EvidenceCitation]:
        """教师确认候选证据：升级为正式 CourseEvidenceRecord + 学生可读 EvidenceCitation。

        - 已 confirmed 的不可重复确认
        - rejected 的不可再确认（需重新生成）
        """
        span = self._require_span(session, span_id=span_id, course_id=course_id)
        if span.status == EvidenceSpanStatus.CONFIRMED:
            reject_state_conflict("证据片段已确认，无需重复确认")
        if span.status != EvidenceSpanStatus.CANDIDATE:
            reject_state_conflict(
                f"证据片段状态 {span.status.value} 不可确认",
                details={"current_status": span.status.value},
            )

        source_blocks = list(session.exec(select(DocumentBlock).where(
            DocumentBlock.course_id == course_id,
            DocumentBlock.run_id == span.run_id,
        )).all())
        backing_block = next(
            (block for block in source_blocks if block.block_id == span.block_id),
            None,
        )
        if backing_block is None:
            reject_validation_failed(
                "证据片段缺少可核验的 Canonical 原文块",
                details={"span_id": span.span_id, "exclusion_reason": "missing_source_block"},
            )
        exclusion_reason = classify_noise_blocks(source_blocks).get(span.block_id)
        if exclusion_reason:
            reject_validation_failed(
                "该片段不具备独立教育意义，不能升级为正式证据",
                details={
                    "span_id": span.span_id,
                    "block_id": span.block_id,
                    "exclusion_reason": exclusion_reason,
                },
            )

        now = utcnow_aware()
        if identity_node_key:
            identity = session.exec(select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.course_id == course_id,
                CourseKnowledgeNode.node_key == identity_node_key,
            )).first()
            if identity is None:
                reject_resource_not_found("关联的课程知识节点不存在")
            node_id = identity.id
        # ``node_id`` remains a compatibility input for older question-bank
        # mappings.  New graph flows pass ``identity_node_key`` and are
        # strictly resolved above; legacy numeric mappings are preserved until
        # the node-identity migration completes.

        source_file = source_file.strip() or self._source_file_for_span(session, span)
        source_type = source_type.strip()
        if not source_type or source_type == "document":
            source_type = self._source_type_for_file(source_file)
        source_anchor_ids = [
            anchor.anchor_id
            for anchor in session.exec(select(EvidenceAnchor).where(
                EvidenceAnchor.course_id == course_id,
                EvidenceAnchor.run_id == span.run_id,
                EvidenceAnchor.ir_version_id == span.ir_version_id,
                EvidenceAnchor.block_id == span.block_id,
                EvidenceAnchor.char_start == span.char_start,
                EvidenceAnchor.char_end == span.char_end,
            )).all()
        ]
        span.status = EvidenceSpanStatus.CONFIRMED
        span.confirmed_by = confirmed_by
        span.confirmed_at = now
        span.updated_at = now
        if node_id is not None and node_id not in span.linked_node_ids:
            span.linked_node_ids = [*span.linked_node_ids, node_id]
        session.add(span)
        self._set_canonical_projection_status(session, span=span, status="active")

        # 生成正式 CourseEvidenceRecord
        evidence_id = "ev_" + __import__("uuid").uuid4().hex
        formal = CourseEvidenceRecord(
            evidence_id=evidence_id,
            course_id=course_id,
            run_id=span.run_id,
            span_id=span.span_id,
            node_id=node_id,
            source_anchor_ids=source_anchor_ids,
            document_id=span.document_id,
            source_file=source_file,
            page_number=span.page_number,
            char_start=span.char_start,
            char_end=span.char_end,
            text_snippet=span.text_snippet,
            evidence_type="document_extract",
            content_hash=span.content_hash,
            status=EvidenceStatus.ACTIVE,
            reviewed_by=confirmed_by,
            reviewed_at=now,
            created_at=now,
        )
        session.add(formal)

        # 生成学生可读 Citation
        citation = EvidenceCitation(
            course_id=course_id,
            evidence_id=evidence_id,
            span_id=span.span_id,
            run_id=span.run_id,
            document_id=span.document_id,
            node_id=node_id,
            source_file=source_file,
            source_type=source_type,
            page_number=span.page_number,
            bbox=span.bbox,
            source_anchor_ids=source_anchor_ids,
            text_snippet=span.text_snippet,
            char_start=span.char_start,
            char_end=span.char_end,
            version=1,
            status=CitationStatus.EXACT,
            student_visible=True,
        )
        session.add(citation)

        span.linked_evidence_id = evidence_id
        session.add(span)
        session.flush()
        return span, formal, citation

    @staticmethod
    def _source_file_for_span(session: Session, span: EvidenceSpan) -> str:
        """Resolve a display filename without exposing storage object keys."""
        if span.document_id:
            artifact = session.exec(select(DocumentArtifact).where(
                DocumentArtifact.course_id == span.course_id,
                DocumentArtifact.document_id == span.document_id,
            )).first()
            if artifact and artifact.file_name:
                return artifact.file_name
        run = session.exec(select(DocumentParseRun).where(
            DocumentParseRun.course_id == span.course_id,
            DocumentParseRun.run_id == span.run_id,
        )).first()
        if run and run.material_version_id:
            version = session.exec(select(SourceMaterialVersion).where(
                SourceMaterialVersion.course_id == span.course_id,
                SourceMaterialVersion.version_id == run.material_version_id,
            )).first()
            if version:
                material = session.exec(select(SourceMaterial).where(
                    SourceMaterial.material_id == version.material_id,
                    SourceMaterial.course_id == span.course_id,
                )).first()
                if material and material.name:
                    return material.name
        return "未命名课件"

    @staticmethod
    def _source_type_for_file(source_file: str) -> str:
        suffix = source_file.lower().rsplit(".", 1)[-1] if "." in source_file else ""
        return {
            "ppt": "ppt", "pptx": "ppt", "pdf": "textbook",
            "doc": "textbook", "docx": "textbook",
        }.get(suffix, "document")

    def reject_evidence_span(
        self,
        session: Session,
        *,
        course_id: int,
        span_id: str,
        rejected_by: int,
        reject_reason: str = "",
    ) -> EvidenceSpan:
        span = self._require_span(session, span_id=span_id, course_id=course_id)
        if span.status in (EvidenceSpanStatus.CONFIRMED, EvidenceSpanStatus.REJECTED,
                            EvidenceSpanStatus.ORPHANED):
            reject_state_conflict(
                f"证据片段状态 {span.status.value} 不可拒绝",
                details={"current_status": span.status.value},
            )
        span.status = EvidenceSpanStatus.REJECTED
        span.rejected_by = rejected_by
        span.rejected_at = utcnow_aware()
        span.reject_reason = reject_reason
        span.updated_at = utcnow_aware()
        session.add(span)
        self._set_canonical_projection_status(session, span=span, status="rejected")
        session.flush()
        return span

    @staticmethod
    def _set_canonical_projection_status(
        session: Session, *, span: EvidenceSpan, status: str,
    ) -> None:
        """Keep Canonical IR retrieval eligible only after evidence review."""
        anchors = session.exec(select(EvidenceAnchor).where(
            EvidenceAnchor.course_id == span.course_id,
            EvidenceAnchor.run_id == span.run_id,
            EvidenceAnchor.ir_version_id == span.ir_version_id,
            EvidenceAnchor.block_id == span.block_id,
            EvidenceAnchor.char_start == span.char_start,
            EvidenceAnchor.char_end == span.char_end,
        )).all()
        for anchor in anchors:
            anchor.status = status
            session.add(anchor)
            chunks = session.exec(select(RetrievalChunk).where(
                RetrievalChunk.course_id == span.course_id,
                RetrievalChunk.ir_version_id == anchor.ir_version_id,
            )).all()
            for chunk in chunks:
                if anchor.anchor_id in (chunk.anchor_ids or []):
                    chunk.status = status
                    session.add(chunk)

    def _require_span(self, session: Session, *, span_id: str, course_id: int) -> EvidenceSpan:
        span = session.exec(
            select(EvidenceSpan).where(
                EvidenceSpan.span_id == span_id,
                EvidenceSpan.course_id == course_id,
            )
        ).first()
        if span is None:
            reject_resource_not_found("证据片段不存在")
        return span

    def list_evidence_spans(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: Optional[str] = None,
        status: Optional[EvidenceSpanStatus] = None,
        node_id: Optional[int] = None,
        include_history: bool = False,
    ) -> list[EvidenceSpan]:
        stmt = select(EvidenceSpan).where(EvidenceSpan.course_id == course_id)
        if run_id is not None:
            stmt = stmt.where(EvidenceSpan.run_id == run_id)
        elif not include_history:
            active_snapshot = session.exec(select(RetrievalIndexSnapshot).where(
                RetrievalIndexSnapshot.course_id == course_id,
                RetrievalIndexSnapshot.status == "active",
            ).order_by(RetrievalIndexSnapshot.activated_at.desc())).first()
            if active_snapshot is not None:
                stmt = stmt.where(EvidenceSpan.ir_version_id == active_snapshot.ir_version_id)
        if status is not None:
            stmt = stmt.where(EvidenceSpan.status == status)
        if node_id is not None:
            stmt = stmt.where(EvidenceSpan.linked_node_ids.contains([node_id]))
        stmt = stmt.order_by(EvidenceSpan.created_at.desc())
        spans = list(session.exec(stmt).all())

        # Historical projections may predate the projector gate.  Reclassify
        # each run at read time so the teacher list and facade cannot surface
        # known fragments even before a deterministic projection replay.
        excluded_by_run: dict[str, set[str]] = {}
        for span in spans:
            if span.run_id in excluded_by_run:
                continue
            blocks = list(session.exec(select(DocumentBlock).where(
                DocumentBlock.course_id == course_id,
                DocumentBlock.run_id == span.run_id,
            )).all())
            excluded_by_run[span.run_id] = set(classify_noise_blocks(blocks))
        return [
            span for span in spans
            if span.block_id not in excluded_by_run.get(span.run_id, set())
        ]

    # --- 学生可读 Citation --------------------------------------------

    def list_citations(
        self,
        session: Session,
        *,
        course_id: int,
        node_id: Optional[int] = None,
        student_visible: Optional[bool] = None,
        include_stale: bool = False,
    ) -> list[EvidenceCitation]:
        """学生端查询原文引用。

        - 学生默认仅看 student_visible=True 且 status in (exact, approximate)
        - 教师可看全部（include_stale=True 包含 source_updated/source_invalid）
        """
        stmt = select(EvidenceCitation).where(EvidenceCitation.course_id == course_id)
        if node_id is not None:
            stmt = stmt.where(EvidenceCitation.node_id == node_id)
        if student_visible is not None:
            stmt = stmt.where(EvidenceCitation.student_visible == student_visible)
        if not include_stale:
            stmt = stmt.where(
                EvidenceCitation.status.in_([CitationStatus.EXACT, CitationStatus.APPROXIMATE])
            )
        stmt = stmt.order_by(EvidenceCitation.created_at.desc())
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# 图谱候选批次服务
# ---------------------------------------------------------------------------


class GraphCandidateService:
    """图谱候选批次服务

    - 创建候选批次，记录节点/关系候选数
    - 教师审核通过后，绑定已发布 GraphSnapshot
    - 与课程 release 关联（GraphReleaseLink）
    """

    def create_batch(
        self,
        session: Session,
        *,
        course_id: int,
        parse_run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        initiated_by: int,
        model_version: str = "graph-candidate-v1.0",
    ) -> GraphCandidateBatch:
        # 旧活跃批次标记为 superseded
        old_batches = session.exec(
            select(GraphCandidateBatch).where(
                GraphCandidateBatch.course_id == course_id,
                GraphCandidateBatch.status.in_([
                    CandidateBatchStatus.PENDING, CandidateBatchStatus.RUNNING,
                    CandidateBatchStatus.SUCCEEDED, CandidateBatchStatus.PARTIAL_SUCCESS,
                ]),
            )
        ).all()
        prev_batch_id = None
        for old in old_batches:
            if old.status in (CandidateBatchStatus.PENDING, CandidateBatchStatus.RUNNING,
                              CandidateBatchStatus.SUCCEEDED, CandidateBatchStatus.PARTIAL_SUCCESS):
                prev_batch_id = old.batch_id
                old.status = CandidateBatchStatus.SUPERSEDED
                old.updated_at = utcnow_aware()
                session.add(old)

        batch = GraphCandidateBatch(
            course_id=course_id,
            parse_run_id=parse_run_id,
            task_id=task_id,
            prev_batch_id=prev_batch_id,
            status=CandidateBatchStatus.PENDING,
            initiated_by=initiated_by,
            model_version=model_version,
        )
        session.add(batch)
        session.flush()
        return batch

    def mark_succeeded(
        self,
        session: Session,
        *,
        course_id: int,
        batch_id: str,
        node_candidate_count: int = 0,
        relation_candidate_count: int = 0,
        node_candidates: Optional[list[dict]] = None,
        relation_candidates: Optional[list[dict]] = None,
    ) -> GraphCandidateBatch:
        batch = self._require_batch(session, batch_id=batch_id, course_id=course_id)
        batch.status = CandidateBatchStatus.SUCCEEDED
        batch.node_candidate_count = node_candidate_count
        batch.relation_candidate_count = relation_candidate_count
        if node_candidates is not None:
            batch.node_candidates = node_candidates
        if relation_candidates is not None:
            batch.relation_candidates = relation_candidates
        batch.finished_at = utcnow_aware()
        batch.updated_at = utcnow_aware()
        session.add(batch)
        session.flush()
        # The parser remains candidate-only, but the successful payload is
        # immediately projected into the teacher governance model.  The bridge
        # is idempotent and participates in the caller's transaction.
        from app.services.graph_production_service import bridge_candidate_batch
        bridge_candidate_batch(session, batch=batch, commit=False)
        return batch

    def link_snapshot(
        self,
        session: Session,
        *,
        course_id: int,
        batch_id: str,
        snapshot_id: str,
    ) -> GraphCandidateBatch:
        """教师审核通过后，将候选批次绑定到已发布 GraphSnapshot。"""
        batch = self._require_batch(session, batch_id=batch_id, course_id=course_id)
        # 校验快照归属同课程
        snapshot = session.exec(
            select(GraphSnapshotRecord).where(
                GraphSnapshotRecord.snapshot_id == snapshot_id,
                GraphSnapshotRecord.course_id == course_id,
            )
        ).first()
        if snapshot is None:
            reject_resource_not_found("图谱快照不存在或不属于该课程")
        batch.snapshot_id = snapshot_id
        batch.updated_at = utcnow_aware()
        session.add(batch)
        session.flush()
        return batch

    def _require_batch(
        self, session: Session, *, batch_id: str, course_id: int,
    ) -> GraphCandidateBatch:
        batch = session.exec(
            select(GraphCandidateBatch).where(
                GraphCandidateBatch.batch_id == batch_id,
                GraphCandidateBatch.course_id == course_id,
            )
        ).first()
        if batch is None:
            reject_resource_not_found("图谱候选批次不存在")
        return batch

    def list_batches(
        self,
        session: Session,
        *,
        course_id: int,
        status: Optional[CandidateBatchStatus] = None,
    ) -> list[GraphCandidateBatch]:
        stmt = select(GraphCandidateBatch).where(
            GraphCandidateBatch.course_id == course_id
        ).order_by(GraphCandidateBatch.created_at.desc())
        if status is not None:
            stmt = stmt.where(GraphCandidateBatch.status == status)
        return list(session.exec(stmt).all())

    @staticmethod
    def review_payload(
        session: Session,
        *,
        batch: GraphCandidateBatch,
    ) -> Optional[dict[str, Any]]:
        """Return a read-only, noise-safe view of a persisted batch payload.

        Older batches predate the shared evidence gate and must remain stored
        unchanged for audit.  The teacher-facing projection removes a concept
        when its title/source block is now deterministically excluded, removes
        excluded supporting blocks/anchors from retained concepts, and drops
        relations that reference a removed concept.
        """
        if not batch.parse_run_id:
            return None
        blocks = list(session.exec(select(DocumentBlock).where(
            DocumentBlock.course_id == batch.course_id,
            DocumentBlock.run_id == batch.parse_run_id,
        )).all())
        if not blocks:
            return None
        excluded_block_ids = set(classify_noise_blocks(blocks))
        if not excluded_block_ids:
            return None
        excluded_anchor_ids = {
            anchor.anchor_id
            for anchor in session.exec(select(EvidenceAnchor).where(
                EvidenceAnchor.course_id == batch.course_id,
                EvidenceAnchor.run_id == batch.parse_run_id,
                EvidenceAnchor.block_id.in_(excluded_block_ids),
            )).all()
        }

        nodes: list[dict[str, Any]] = []
        removed_candidate_ids: set[str] = set()
        for raw_node in batch.node_candidates or []:
            node = dict(raw_node)
            source_block_ids = list(node.get("source_block_ids") or [])
            if source_block_ids and source_block_ids[0] in excluded_block_ids:
                candidate_id = str(node.get("candidate_id") or "")
                if candidate_id:
                    removed_candidate_ids.add(candidate_id)
                continue
            node["source_block_ids"] = [
                block_id for block_id in source_block_ids
                if block_id not in excluded_block_ids
            ]
            node["anchor_ids"] = [
                anchor_id for anchor_id in (node.get("anchor_ids") or [])
                if anchor_id not in excluded_anchor_ids
            ]
            nodes.append(node)

        relations = []
        for raw_relation in batch.relation_candidates or []:
            relation = dict(raw_relation)
            if (
                str(relation.get("source_candidate_id") or "") in removed_candidate_ids
                or str(relation.get("target_candidate_id") or "") in removed_candidate_ids
            ):
                continue
            relation["anchor_ids"] = [
                anchor_id for anchor_id in (relation.get("anchor_ids") or [])
                if anchor_id not in excluded_anchor_ids
            ]
            relations.append(relation)
        return {
            "node_candidates": nodes,
            "relation_candidates": relations,
            "node_candidate_count": len(nodes),
            "relation_candidate_count": len(relations),
        }


# ---------------------------------------------------------------------------
# 图谱快照 ↔ 课程 release 关联服务
# ---------------------------------------------------------------------------


class GraphReleaseLinkService:
    """图谱快照与课程 release 关联服务

    保证图谱与课程内容版本一致；release 回滚时图谱同步回滚。
    """

    def link(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
        snapshot_id: str,
        linked_by: int,
    ) -> GraphReleaseLink:
        # 校验快照归属同课程
        snapshot = session.exec(
            select(GraphSnapshotRecord).where(
                GraphSnapshotRecord.snapshot_id == snapshot_id,
                GraphSnapshotRecord.course_id == course_id,
            )
        ).first()
        if snapshot is None:
            reject_resource_not_found("图谱快照不存在或不属于该课程")
        existing = session.exec(
            select(GraphReleaseLink).where(
                GraphReleaseLink.course_id == course_id,
                GraphReleaseLink.release_id == release_id,
            )
        ).first()
        if existing is not None:
            # 幂等更新 snapshot
            existing.snapshot_id = snapshot_id
            existing.linked_by = linked_by
            existing.linked_at = utcnow_aware()
            session.add(existing)
            session.flush()
            return existing
        link = GraphReleaseLink(
            course_id=course_id,
            release_id=release_id,
            snapshot_id=snapshot_id,
            linked_by=linked_by,
        )
        session.add(link)
        session.flush()
        return link

    def get_link(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
    ) -> Optional[GraphReleaseLink]:
        return session.exec(
            select(GraphReleaseLink).where(
                GraphReleaseLink.course_id == course_id,
                GraphReleaseLink.release_id == release_id,
            )
        ).first()

    def list_links(
        self,
        session: Session,
        *,
        course_id: int,
    ) -> list[GraphReleaseLink]:
        return list(session.exec(
            select(GraphReleaseLink).where(
                GraphReleaseLink.course_id == course_id,
            ).order_by(GraphReleaseLink.linked_at.desc())
        ).all())


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

document_parse_service = DocumentParseService()
graph_candidate_service = GraphCandidateService()
graph_release_link_service = GraphReleaseLinkService()
