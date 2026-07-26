"""阶段5 题库导入、AI 生成草稿、个性化练习推荐与正式学习证据链接 API 路由。

路由前缀：
- /api/v1/practice/course/{course_id}/recommendations                创建/列表推荐运行
- /api/v1/practice/course/{course_id}/recommendations/{recommendation_id}  获取/启动
- /api/v1/practice/attempts/{attempt_id}/submit                       学生提交答题
- /api/v1/practice/course/{course_id}/drafts                          AI 草稿列表/审核
- /api/v1/practice/course/{course_id}/drafts/{draft_id}/approve       教师通过草稿
- /api/v1/practice/course/{course_id}/drafts/{draft_id}/reject        教师拒绝草稿
- /api/v1/practice/course/{course_id}/import-runs                     题库导入运行
- /api/v1/practice/course/{course_id}/policies                        评分策略

facade:
- /api/v1/facade/course/{course_id}/learning-actions/complete         学习动作完成

约束：
- AI 生成草稿**不可直接面向学生发布**，必须经教师审核升级为 QuestionBankItem
- 每次推荐携带 policy_version, reason_codes, evidence_refs, confidence, six_dimensions, question_source
- 数据不足返回 unknown / evidence_needed，不把提问次数或观看时长当掌握度
- 未归属、未映射、未发布、教师拒绝的题目不能被学生检索或推荐
- 跨课程严格隔离：所有查询都按 course_id 过滤
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import (
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
    unified_response,
)
from app.core.security import get_current_user
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.database import get_session
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
    QuestionAttempt,
    QuestionBankItem,
    QuestionStatus,
    QuestionType,
)
from app.services.cognitive_service import (
    get_latest_cognitive_state,
    record_scored_evidence,
)
from app.services.course_access_service import require_course_permission
from app.services.practice_recommendation_service import (
    PRACTICE_POLICY_VERSION,
    assessment_policy_service,
    learning_evidence_link_service,
    practice_recommendation_service,
    question_generation_draft_service,
    question_import_service,
)


# ---------------------------------------------------------------------------
# 路由器
# ---------------------------------------------------------------------------


practice_router = APIRouter()
facade_learning_actions_router = APIRouter()


# ---------------------------------------------------------------------------
# 请求体 schema
# ---------------------------------------------------------------------------


class RecommendationCreateRequest(BaseModel):
    """创建推荐运行请求体"""

    node_id: Optional[int] = Field(None, description="目标知识点，可空")
    purpose: str = Field(
        default="diagnose",
        description="diagnose/remediation/hint_withdrawal/post_explanation",
    )
    item_count: int = Field(default=3, ge=1, le=10, description="推荐项数量")
    allow_generation: bool = Field(
        default=True,
        description="题库不足时是否生成 AI 草稿（草稿不直接对学生发布）",
    )
    force_recompute_cognitive: bool = Field(
        default=False,
        description="是否强制重新计算认知状态（默认使用最新快照）",
    )


class RecommendationStartItemRequest(BaseModel):
    """学生开始作答推荐项"""

    pass


class AttemptSubmitRequest(BaseModel):
    """学生提交答题（统一入口）"""

    recommendation_id: Optional[str] = Field(
        None, description="来源推荐ID；如由推荐触发则填写"
    )
    item_id: Optional[str] = Field(
        None, description="来源推荐项ID；如由推荐触发则填写"
    )
    student_answer: str = Field(..., min_length=1, max_length=20_000)
    purpose: AssessmentPurpose = Field(
        default=AssessmentPurpose.DIAGNOSE,
        description="评估目的；不同目的用不同评分策略",
    )


class DraftApproveRequest(BaseModel):
    """教师审核通过 AI 草稿"""

    review_comment: str = Field(default="", max_length=500)
    publish_status: QuestionStatus = Field(
        default=QuestionStatus.PUBLISHED,
        description="升级后的题目状态；默认 published",
    )


class DraftRejectRequest(BaseModel):
    """教师拒绝 AI 草稿"""

    review_comment: str = Field(default="", max_length=500)


class ImportRunCreateRequest(BaseModel):
    """创建题库导入运行"""

    source_file: str = Field(..., min_length=1, max_length=500)
    source_object_key: str = Field(default="", max_length=500)
    total_rows: int = Field(default=0, ge=0)


class PolicyCreateRequest(BaseModel):
    """创建评分策略"""

    purpose: AssessmentPurpose
    policy_version: str = Field(default="assessment-policy-v1.0", max_length=100)
    passing_score: float = Field(default=0.6, ge=0.0, le=1.0)
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    writes_formal_evidence: bool = Field(default=True)
    max_attempts_per_node: int = Field(default=3, ge=1, le=20)
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)
    rules: dict[str, Any] = Field(default_factory=dict)


class LearningActionCompleteRequest(BaseModel):
    """学习动作完成"""

    node_id: Optional[int] = Field(None, description="关联知识点")
    action_type: str = Field(
        ..., min_length=1, max_length=100,
        description="action 类型：video_watch/note_review/visualization_interact 等",
    )
    duration_seconds: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    is_scored: bool = Field(
        default=False,
        description="是否评分型动作；非评分动作不得抬高表现分",
    )
    score: Optional[float] = Field(None, ge=0.0, le=1.0, description="评分型动作的分数")
    recommendation_id: Optional[str] = Field(None, description="来源推荐ID")


# ---------------------------------------------------------------------------
# 序列化 helpers
# ---------------------------------------------------------------------------


def _serialize_run(run: QuestionRecommendationRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "recommendation_id": run.recommendation_id,
        "course_id": run.course_id,
        "student_id": run.student_id,
        "node_id": run.node_id,
        "purpose": run.purpose,
        "policy_version": run.policy_version,
        "six_dimensions": run.six_dimensions,
        "reason_codes": run.reason_codes,
        "evidence_refs": run.evidence_refs,
        "confidence": run.confidence,
        "cognitive_state_id": run.cognitive_state_id,
        "status": run.status.value,
        "item_count": run.item_count,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def _serialize_item(item: QuestionRecommendationItem, *, student_view: bool = False) -> dict[str, Any]:
    data = {
        "item_id": item.item_id,
        "run_id": item.run_id,
        "recommendation_id": item.recommendation_id,
        "course_id": item.course_id,
        "student_id": item.student_id,
        "question_source": item.question_source.value,
        "question_id": item.question_id,
        "node_id": item.node_id,
        "reason_codes": item.reason_codes,
        "evidence_refs": item.evidence_refs,
        "confidence": item.confidence,
        "order_index": item.order_index,
        "is_started": item.is_started,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "is_consumed": item.is_consumed,
        "consumed_at": item.consumed_at.isoformat() if item.consumed_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
    if not student_view:
        data["generation_draft_id"] = item.generation_draft_id
    return data


def _serialize_draft(draft: QuestionGenerationDraft) -> dict[str, Any]:
    return {
        "draft_id": draft.draft_id,
        "course_id": draft.course_id,
        "node_id": draft.node_id,
        "question_type": draft.question_type,
        "question_text": draft.question_text,
        "answer": draft.answer,
        "options": draft.options,
        "difficulty": draft.difficulty,
        "category": draft.category,
        "generation_purpose": draft.generation_purpose,
        "cognitive_snapshot": draft.cognitive_snapshot,
        "six_dimensions": draft.six_dimensions,
        "reason_codes": draft.reason_codes,
        "evidence_refs": draft.evidence_refs,
        "confidence": draft.confidence,
        "policy_version": draft.policy_version,
        "model_version": draft.model_version,
        "status": draft.status.value,
        "reviewed_by": draft.reviewed_by,
        "reviewed_at": draft.reviewed_at.isoformat() if draft.reviewed_at else None,
        "review_comment": draft.review_comment,
        "upgraded_question_id": draft.upgraded_question_id,
        "stale_reason": draft.stale_reason,
        "stale_at": draft.stale_at.isoformat() if draft.stale_at else None,
        "generated_by": draft.generated_by,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def _serialize_import_run(run: QuestionImportRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "course_id": run.course_id,
        "task_id": run.task_id,
        "source_file": run.source_file,
        "source_object_key": run.source_object_key,
        "total_rows": run.total_rows,
        "imported_count": run.imported_count,
        "skipped_count": run.skipped_count,
        "failed_count": run.failed_count,
        "status": run.status.value,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "failure_details": run.failure_details,
        "initiated_by": run.initiated_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def _serialize_policy(policy: AssessmentPolicy) -> dict[str, Any]:
    return {
        "policy_id": policy.policy_id,
        "course_id": policy.course_id,
        "purpose": policy.purpose.value,
        "policy_version": policy.policy_version,
        "passing_score": policy.passing_score,
        "confidence_threshold": policy.confidence_threshold,
        "writes_formal_evidence": policy.writes_formal_evidence,
        "max_attempts_per_node": policy.max_attempts_per_node,
        "cooldown_minutes": policy.cooldown_minutes,
        "rules": policy.rules,
        "is_active": policy.is_active,
        "created_by": policy.created_by,
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
    }


def _normalize_objective_answer(question_type: QuestionType, value: str) -> str:
    import re
    normalized = value.strip().casefold()
    if question_type == QuestionType.MULTI_CHOICE:
        choices = {part for part in re.split(r"[,，;；\s]+", normalized) if part}
        return "|".join(sorted(choices))
    if question_type == QuestionType.TRUE_FALSE:
        if normalized in {"true", "1", "yes", "y", "对", "正确", "是"}:
            return "true"
        if normalized in {"false", "0", "no", "n", "错", "错误", "否"}:
            return "false"
    return normalized


# ---------------------------------------------------------------------------
# 推荐运行
# ---------------------------------------------------------------------------


@practice_router.post("/course/{course_id}/recommendations")
async def create_recommendation(
    course_id: int,
    payload: RecommendationCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建一次个性化推荐运行。

    - 题库优先检索；无匹配题且 allow_generation=True 时生成 AI 草稿（不直接发布）
    - 每次推荐携带 policy_version, six_dimensions, reason_codes, evidence_refs, confidence
    - 数据不足时 reason_codes 包含 insufficient_data / evidence_needed
    """
    context = require_course_permission(session, current_user, course_id, "course.question.ask")
    user_id = int(current_user["user_id"])
    if not context.analytics_eligible:
        reject_state_conflict(
            "仅课程学习者可获取个性化推荐",
            details={"analytics_eligible": False},
        )

    # 获取/计算认知状态
    if payload.force_recompute_cognitive:
        from app.services.cognitive_service import compute_cognitive_state
        cognitive_state = compute_cognitive_state(
            session, student_id=user_id, course_id=course_id, node_id=payload.node_id,
        )
    else:
        cognitive_state = get_latest_cognitive_state(
            session, student_id=user_id, course_id=course_id, node_id=payload.node_id,
        )
        if cognitive_state is None:
            from app.services.cognitive_service import compute_cognitive_state
            cognitive_state = compute_cognitive_state(
                session, student_id=user_id, course_id=course_id, node_id=payload.node_id,
            )

    run = practice_recommendation_service.create_recommendation(
        session,
        course_id=course_id,
        student_id=user_id,
        node_id=payload.node_id,
        purpose=payload.purpose,
        cognitive_state=cognitive_state,
        item_count=payload.item_count,
        allow_generation=payload.allow_generation,
    )
    session.commit()
    session.refresh(run)

    return unified_response(
        code=201,
        message="推荐运行已创建",
        data=_serialize_run(run),
    )


@practice_router.get("/course/{course_id}/recommendations/{recommendation_id}")
async def get_recommendation(
    course_id: int,
    recommendation_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取推荐运行及其推荐项。

    - 学生只能看自己的推荐
    - 教师可看本课程任意推荐
    """
    context = require_course_permission(session, current_user, course_id, "course.view")
    user_id = int(current_user["user_id"])
    is_teacher = context.allows("question_bank.manage")

    run, items = practice_recommendation_service.get_recommendation(
        session,
        course_id=course_id,
        recommendation_id=recommendation_id,
        student_id=None if is_teacher else user_id,
    )
    return unified_response(
        code=200,
        message="获取推荐运行成功",
        data={
            "run": _serialize_run(run),
            "items": [_serialize_item(it, student_view=not is_teacher) for it in items],
        },
    )


@practice_router.get("/course/{course_id}/recommendations")
async def list_student_recommendations(
    course_id: int,
    node_id: Optional[int] = Query(None, description="按知识点过滤"),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生查询自己的推荐历史。"""
    context = require_course_permission(session, current_user, course_id, "course.view")
    user_id = int(current_user["user_id"])
    runs = practice_recommendation_service.list_student_recommendations(
        session,
        course_id=course_id,
        student_id=user_id,
        node_id=node_id,
        limit=limit,
    )
    return unified_response(
        code=200,
        message="获取推荐历史成功",
        data={
            "course_id": course_id,
            "items": [_serialize_run(r) for r in runs],
            "total": len(runs),
        },
    )


@practice_router.post(
    "/course/{course_id}/recommendations/{recommendation_id}/items/{item_id}/start"
)
async def start_recommendation_item(
    course_id: int,
    recommendation_id: str,
    item_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生开始作答推荐项。

    - 标记 is_started=True
    - generated_draft 题目需教师先升级（否则拒绝）
    """
    context = require_course_permission(session, current_user, course_id, "course.question.ask")
    user_id = int(current_user["user_id"])

    item = practice_recommendation_service.start_recommendation_item(
        session,
        course_id=course_id,
        recommendation_id=recommendation_id,
        item_id=item_id,
        student_id=user_id,
    )
    session.commit()
    session.refresh(item)
    return unified_response(
        code=200,
        message="推荐项已开始",
        data=_serialize_item(item, student_view=True),
    )


# ---------------------------------------------------------------------------
# 统一答题提交
# ---------------------------------------------------------------------------


@practice_router.post("/attempts/{attempt_id}/submit")
async def submit_attempt(
    attempt_id: int,
    payload: AttemptSubmitRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生提交答题（统一入口）。

    - 自动判分（客观题）；主观题留待教师评分
    - 评分型动作（is_scored=true 或 purpose=summative/diagnose）写入正式 LearningEvidence
    - 非评分动作不写入正式证据
    - 链接到推荐运行/题目尝试上下文（LearningEvidenceLink）
    """
    attempt = session.get(QuestionAttempt, attempt_id)
    if attempt is None:
        reject_resource_not_found("答题记录不存在")

    context = require_course_permission(
        session, current_user, attempt.course_id, "question_bank.read",
    )
    user_id = int(current_user["user_id"])
    if attempt.student_id != user_id:
        reject_resource_not_found("答题记录不存在")

    item = session.get(QuestionBankItem, attempt.question_id)
    if item is None or item.course_id != attempt.course_id:
        reject_resource_not_found("题目不存在或不属于此课程")

    # 自动判分（客观题）
    normalized_answer = _normalize_objective_answer(item.question_type, payload.student_answer)
    normalized_expected = _normalize_objective_answer(item.question_type, item.answer)
    automatically_judged = item.question_type in {
        QuestionType.SINGLE_CHOICE,
        QuestionType.MULTI_CHOICE,
        QuestionType.TRUE_FALSE,
        QuestionType.FILL_BLANK,
    }
    is_correct = (
        normalized_answer == normalized_expected
        if automatically_judged
        else None
    )

    attempt.student_answer = payload.student_answer
    if automatically_judged:
        attempt.is_correct = is_correct
        attempt.score = float(is_correct) if is_correct is not None else None
        attempt.judged_by = "auto"
        attempt.judged_at = datetime.utcnow()
    session.add(attempt)
    session.flush()

    # 写入正式 LearningEvidence（仅评分型）
    evidence_record: Optional[LearningEvidenceRecord] = None
    if automatically_judged and attempt.score is not None:
        evidence_record = record_scored_evidence(session, attempt)

    # 链接到推荐运行/题目尝试上下文
    if evidence_record is not None and payload.recommendation_id:
        learning_evidence_link_service.link(
            session,
            course_id=attempt.course_id,
            student_id=user_id,
            evidence_id=evidence_record.evidence_id,
            context_type=EvidenceLinkContext.RECOMMENDATION,
            context_id=payload.recommendation_id,
            context_snapshot={
                "purpose": payload.purpose.value,
                "score": attempt.score,
                "is_correct": attempt.is_correct,
                "item_id": payload.item_id,
            },
        )
    if evidence_record is not None:
        learning_evidence_link_service.link(
            session,
            course_id=attempt.course_id,
            student_id=user_id,
            evidence_id=evidence_record.evidence_id,
            context_type=EvidenceLinkContext.QUESTION_ATTEMPT,
            context_id=str(attempt.id),
            context_snapshot={
                "purpose": payload.purpose.value,
                "score": attempt.score,
                "is_correct": attempt.is_correct,
            },
        )

    session.commit()
    session.refresh(attempt)

    return unified_response(
        code=200,
        message="答题已提交",
        data={
            "attempt_id": attempt.id,
            "judgement_status": "judged" if automatically_judged else "pending",
            "is_correct": attempt.is_correct,
            "score": attempt.score,
            "evidence_id": evidence_record.evidence_id if evidence_record else None,
            "writes_formal_evidence": evidence_record is not None,
        },
    )


# ---------------------------------------------------------------------------
# AI 草稿审核
# ---------------------------------------------------------------------------


@practice_router.get("/course/{course_id}/drafts")
async def list_drafts(
    course_id: int,
    status: Optional[GenerationDraftStatus] = Query(None),
    node_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师查看 AI 生成草稿列表。"""
    require_course_permission(session, current_user, course_id, "question_bank.manage")
    drafts = question_generation_draft_service.list_drafts(
        session, course_id=course_id, status=status, node_id=node_id,
    )
    return unified_response(
        code=200,
        message="获取草稿列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_draft(d) for d in drafts],
            "total": len(drafts),
        },
    )


@practice_router.post("/course/{course_id}/drafts/{draft_id}/approve")
async def approve_draft(
    course_id: int,
    draft_id: str,
    payload: DraftApproveRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师审核通过 AI 草稿：升级为正式 QuestionBankItem。

    - 草稿状态必须是 DRAFT 或 STALE（stale 允许重新审核）
    - 已 APPROVED/REJECTED 不可重复审核
    - 升级后的题目 is_latest=True, status=publish_status
    """
    require_course_permission(session, current_user, course_id, "question_bank.publish")
    user_id = int(current_user["user_id"])

    draft, question = question_generation_draft_service.approve_draft(
        session,
        course_id=course_id,
        draft_id=draft_id,
        reviewed_by=user_id,
        review_comment=payload.review_comment,
        publish_status=payload.publish_status,
    )
    session.commit()
    session.refresh(draft)
    session.refresh(question)

    return unified_response(
        code=200,
        message="草稿已审核通过并升级为正式题目",
        data={
            "draft": _serialize_draft(draft),
            "question": {
                "question_id": question.id,
                "question_text": question.question_text,
                "status": question.status.value,
                "version": question.version,
                "is_latest": question.is_latest,
            },
        },
    )


@practice_router.post("/course/{course_id}/drafts/{draft_id}/reject")
async def reject_draft(
    course_id: int,
    draft_id: str,
    payload: DraftRejectRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师拒绝 AI 草稿。"""
    require_course_permission(session, current_user, course_id, "question_bank.manage")
    user_id = int(current_user["user_id"])
    draft = question_generation_draft_service.reject_draft(
        session,
        course_id=course_id,
        draft_id=draft_id,
        rejected_by=user_id,
        review_comment=payload.review_comment,
    )
    session.commit()
    session.refresh(draft)
    return unified_response(
        code=200,
        message="草稿已被拒绝",
        data=_serialize_draft(draft),
    )


# ---------------------------------------------------------------------------
# 题库导入运行
# ---------------------------------------------------------------------------


@practice_router.post("/course/{course_id}/import-runs")
async def create_import_run(
    course_id: int,
    payload: ImportRunCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建题库导入运行（异步执行；返回 202 + run_id）。"""
    require_course_permission(session, current_user, course_id, "question_bank.manage")
    user_id = int(current_user["user_id"])
    run = question_import_service.create_run(
        session,
        course_id=course_id,
        source_file=payload.source_file,
        source_object_key=payload.source_object_key,
        total_rows=payload.total_rows,
        initiated_by=user_id,
    )
    session.commit()
    session.refresh(run)
    return unified_response(
        code=202,
        message="题库导入任务已创建",
        data=_serialize_import_run(run),
    )


@practice_router.get("/course/{course_id}/import-runs")
async def list_import_runs(
    course_id: int,
    status: Optional[ImportRunStatus] = Query(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出题库导入运行。"""
    require_course_permission(session, current_user, course_id, "question_bank.manage")
    runs = question_import_service.list_runs(
        session, course_id=course_id, status=status,
    )
    return unified_response(
        code=200,
        message="获取题库导入运行列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_import_run(r) for r in runs],
            "total": len(runs),
        },
    )


@practice_router.get("/course/{course_id}/import-runs/{run_id}")
async def get_import_run(
    course_id: int,
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """查询题库导入运行详情。"""
    require_course_permission(session, current_user, course_id, "question_bank.manage")
    run = session.exec(
        select(QuestionImportRun).where(
            QuestionImportRun.run_id == run_id,
            QuestionImportRun.course_id == course_id,
        )
    ).first()
    if run is None:
        reject_resource_not_found("题库导入运行不存在")
    return unified_response(
        code=200,
        message="获取题库导入运行成功",
        data=_serialize_import_run(run),
    )


# ---------------------------------------------------------------------------
# 评分策略
# ---------------------------------------------------------------------------


@practice_router.get("/course/{course_id}/policies")
async def list_policies(
    course_id: int,
    purpose: Optional[AssessmentPurpose] = Query(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出评分策略。"""
    require_course_permission(session, current_user, course_id, "question_bank.read")
    policies = assessment_policy_service.list_policies(
        session, course_id=course_id, purpose=purpose,
    )
    return unified_response(
        code=200,
        message="获取评分策略列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_policy(p) for p in policies],
            "total": len(policies),
        },
    )


@practice_router.post("/course/{course_id}/policies")
async def create_policy(
    course_id: int,
    payload: PolicyCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建评分策略（教师）。"""
    require_course_permission(session, current_user, course_id, "question_bank.manage")
    user_id = int(current_user["user_id"])
    policy = assessment_policy_service.get_or_create_policy(
        session,
        course_id=course_id,
        purpose=payload.purpose,
        created_by=user_id,
        policy_version=payload.policy_version,
        passing_score=payload.passing_score,
        confidence_threshold=payload.confidence_threshold,
        writes_formal_evidence=payload.writes_formal_evidence,
        max_attempts_per_node=payload.max_attempts_per_node,
        cooldown_minutes=payload.cooldown_minutes,
        rules=payload.rules,
    )
    session.commit()
    session.refresh(policy)
    return unified_response(
        code=201,
        message="评分策略已创建",
        data=_serialize_policy(policy),
    )


# ---------------------------------------------------------------------------
# facade: 学习动作完成
# ---------------------------------------------------------------------------


@facade_learning_actions_router.post("/course/{course_id}/learning-actions/complete")
async def complete_learning_action(
    course_id: int,
    payload: LearningActionCompleteRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """记录学习动作完成，返回锚点和是否形成正式证据。

    关键约束：
    - 非评分动作不得抬高表现分（writes_formal_evidence=False）
    - 评分型动作需通过评分策略校验后才写入正式 LearningEvidence
    - 链接到推荐运行/动作上下文（LearningEvidenceLink）便于追溯
    """
    context = require_course_permission(session, current_user, course_id, "course.question.ask")
    user_id = int(current_user["user_id"])
    if not context.analytics_eligible:
        reject_state_conflict(
            "仅课程学习者可记录学习动作",
            details={"analytics_eligible": False},
        )

    # 获取对应目的的评分策略
    policy: Optional[AssessmentPolicy] = None
    try:
        # action_type 映射到 purpose
        purpose_map = {
            "quiz": AssessmentPurpose.DIAGNOSE,
            "remediation": AssessmentPurpose.REMEDIATION,
            "hint_withdrawal": AssessmentPurpose.HINT_WITHDRAWAL,
            "post_explanation": AssessmentPurpose.POST_EXPLANATION,
            "summative": AssessmentPurpose.SUMMATIVE,
        }
        purpose = purpose_map.get(payload.action_type, AssessmentPurpose.DIAGNOSE)
        policy = assessment_policy_service.get_policy(
            session, course_id=course_id, purpose=purpose,
        )
    except Exception:
        # 策略缺失不阻断动作记录，但不写入正式证据
        policy = None

    writes_formal_evidence = (
        payload.is_scored
        and payload.score is not None
        and (policy is None or policy.writes_formal_evidence)
    )

    # 生成动作记录ID
    action_id = "la_" + uuid.uuid4().hex
    now = datetime.utcnow()

    # 若写入正式证据，需链接到 LearningEvidenceRecord
    # 此处不直接修改认知状态（认知状态由 cognitive_service 异步聚合）
    evidence_id: Optional[str] = None
    if writes_formal_evidence and policy is not None:
        # 评分型动作通过 LearningEvidenceRecord 写入
        evidence_id = "ev_" + uuid.uuid4().hex
        record = LearningEvidenceRecord(
            evidence_id=evidence_id,
            student_id=user_id,
            course_id=course_id,
            node_id=payload.node_id,
            evidence_type="learning_action_scored",
            value=payload.score,
            confidence=policy.confidence_threshold,
            label=payload.action_type,
            description=f"学习动作评分：{payload.action_type}",
            source="learning_action",
            timestamp=now.isoformat(),
            event_refs=[action_id],
            policy_version=policy.policy_version,
            created_at=now,
        )
        session.add(record)
        session.flush()

        # 链接到动作上下文
        learning_evidence_link_service.link(
            session,
            course_id=course_id,
            student_id=user_id,
            evidence_id=evidence_id,
            context_type=EvidenceLinkContext.LEARNING_ACTION,
            context_id=action_id,
            context_snapshot={
                "action_type": payload.action_type,
                "score": payload.score,
                "duration_seconds": payload.duration_seconds,
                "purpose": policy.purpose.value,
                "policy_version": policy.policy_version,
            },
        )
        # 链接到推荐运行（如有）
        if payload.recommendation_id:
            learning_evidence_link_service.link(
                session,
                course_id=course_id,
                student_id=user_id,
                evidence_id=evidence_id,
                context_type=EvidenceLinkContext.RECOMMENDATION,
                context_id=payload.recommendation_id,
                context_snapshot={
                    "action_type": payload.action_type,
                    "score": payload.score,
                },
            )

    session.commit()

    return unified_response(
        code=200,
        message="学习动作已记录",
        data={
            "action_id": action_id,
            "course_id": course_id,
            "node_id": payload.node_id,
            "action_type": payload.action_type,
            "is_scored": payload.is_scored,
            "score": payload.score,
            "writes_formal_evidence": writes_formal_evidence,
            "evidence_id": evidence_id,
            "return_anchor": {
                "node_id": payload.node_id,
                "action_type": payload.action_type,
            },
        },
    )
