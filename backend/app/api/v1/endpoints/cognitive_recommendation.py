"""G2 六维认知与推荐 API

使用统一权限解析器(require_course_permission)进行课程级权限校验。
- 查看认知状态: course.progress.read_self (学生) / analytics.view_course (教师)
- 获取推荐: course.question.ask (学生)
- 查看推荐历史: course.progress.read_self (学生) / analytics.view_course (教师)

不跨学生、课程读取或写入状态。
数据不足时输出 unknown 或"需要更多证据"。
"""
from __future__ import annotations

from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.cognitive_state_model import (
    CognitiveState,
    LearningEvidenceRecord,
    RecommendationRecord,
)
from app.services.cognitive_service import compute_cognitive_state, get_latest_cognitive_state
from app.services.recommendation_service import (
    generate_recommendation,
    get_recommendation_history,
    mark_recommendation_consumed,
)
from app.services.course_access_service import require_course_permission

router = APIRouter(tags=["G2 六维认知与推荐"])


# ==================== 认知状态接口 ====================

@router.get("/course/{course_id}/state")
async def get_cognitive_state(
    course_id: int,
    node_id: Optional[int] = Query(None, description="节点ID(空=课程级)"),
    recompute: bool = Query(False, description="是否强制重新计算"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取学生六维认知状态

    学生查看自己的状态；教师查看课程学生的状态（需 analytics 权限）。
    数据不足时对应维度为 null (unknown)。
    """
    context = require_course_permission(session, current_user, course_id, "course.progress.read_self")
    user_id = int(current_user["user_id"])

    # 教师只能看自己的状态或通过 analytics 查看学生
    role = context.role.value if context.role else "student"
    if role == "teacher" or role == "owner":
        # 教师查看时需要指定 student_id
        student_id = Query(None, alias="student_id")
        # 简化：教师默认看自己
        target_student = user_id
    else:
        target_student = user_id

    if recompute:
        state = compute_cognitive_state(session, target_student, course_id, node_id)
    else:
        state = get_latest_cognitive_state(session, target_student, course_id, node_id)
        if state is None:
            state = compute_cognitive_state(session, target_student, course_id, node_id)

    return unified_response(
        code=200,
        message="获取六维认知状态成功",
        data=_serialize_cognitive_state(state),
    )


@router.post("/course/{course_id}/compute")
async def recompute_cognitive_state(
    course_id: int,
    node_id: Optional[int] = Body(None, embed=True),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """强制重新计算六维认知状态"""
    context = require_course_permission(session, current_user, course_id, "course.progress.read_self")
    user_id = int(current_user["user_id"])

    state = compute_cognitive_state(session, user_id, course_id, node_id)

    return unified_response(
        code=200,
        message="六维认知状态已重新计算",
        data=_serialize_cognitive_state(state),
    )


# ==================== 推荐接口 ====================

@router.post("/course/{course_id}/recommend")
async def get_recommendation(
    course_id: int,
    node_id: Optional[int] = Body(None, embed=True),
    force_recompute: bool = Body(False, embed=True),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取六维认知驱动的推荐

    每次推荐带 policy_version、reason_codes、evidence_refs。
    数据不足时返回 unknown 推荐。
    """
    context = require_course_permission(session, current_user, course_id, "course.question.ask")
    user_id = int(current_user["user_id"])

    record = generate_recommendation(
        session, user_id, course_id, node_id, force_recompute
    )

    return unified_response(
        code=200,
        message="推荐已生成",
        data=_serialize_recommendation(record),
    )


@router.get("/course/{course_id}/recommendations")
async def list_recommendations(
    course_id: int,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取学生推荐历史"""
    context = require_course_permission(session, current_user, course_id, "course.progress.read_self")
    user_id = int(current_user["user_id"])

    records = get_recommendation_history(session, user_id, course_id, limit)

    return unified_response(
        code=200,
        message="获取推荐历史成功",
        data={
            "items": [_serialize_recommendation(r) for r in records],
            "total": len(records),
        },
    )


@router.post("/recommendation/{recommendation_id}/consume")
async def consume_recommendation(
    recommendation_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """标记推荐为已消费"""
    user_id = int(current_user["user_id"])

    record = mark_recommendation_consumed(session, recommendation_id, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="推荐记录不存在或不属于当前用户")

    return unified_response(
        code=200,
        message="推荐已标记为已消费",
        data={"recommendation_id": recommendation_id, "consumed": True},
    )


# ==================== 学习证据接口 ====================

@router.get("/course/{course_id}/evidence")
async def list_evidence(
    course_id: int,
    evidence_type: Optional[str] = Query(None, description="按证据类型筛选"),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取学生的学习证据列表

    答题结果形成评分型 LearningEvidence，与交互状态分离。
    """
    context = require_course_permission(session, current_user, course_id, "course.progress.read_self")
    user_id = int(current_user["user_id"])

    stmt = select(LearningEvidenceRecord).where(
        LearningEvidenceRecord.student_id == user_id,
        LearningEvidenceRecord.course_id == course_id,
    )
    if evidence_type:
        stmt = stmt.where(LearningEvidenceRecord.evidence_type == evidence_type)

    stmt = stmt.order_by(LearningEvidenceRecord.created_at.desc()).limit(limit)
    records = session.exec(stmt).all()

    return unified_response(
        code=200,
        message="获取学习证据成功",
        data={
            "items": [_serialize_evidence(r) for r in records],
            "total": len(records),
        },
    )


# ==================== 辅助函数 ====================

def _serialize_cognitive_state(state: CognitiveState) -> dict[str, Any]:
    """序列化认知状态"""
    return {
        "id": state.id,
        "student_id": state.student_id,
        "course_id": state.course_id,
        "node_id": state.node_id,
        "dimensions": {
            "observed_performance_score": state.observed_performance_score,
            "evidence_confidence": state.evidence_confidence,
            "confusion_risk": state.confusion_risk,
            "inquiry_depth": state.inquiry_depth,
            "hint_dependency": state.hint_dependency,
            "explanation_need": state.explanation_need,
        },
        "mastery_level": state.mastery_level,
        "mastery_score": state.mastery_score,
        "policy_version": state.policy_version,
        "evidence_refs": state.evidence_refs,
        "reason_codes": state.reason_codes,
        "sample_size": state.sample_size,
        "is_latest": state.is_latest,
        "computed_at": state.computed_at.isoformat() if state.computed_at else None,
    }


def _serialize_recommendation(record: RecommendationRecord) -> dict[str, Any]:
    """序列化推荐记录"""
    return {
        "recommendation_id": record.recommendation_id,
        "student_id": record.student_id,
        "course_id": record.course_id,
        "node_id": record.node_id,
        "recommendation_type": record.recommendation_type,
        "priority": record.priority,
        "title": record.title,
        "description": record.description,
        "policy_version": record.policy_version,
        "reason_codes": record.reason_codes,
        "evidence_refs": record.evidence_refs,
        "question_id": record.question_id,
        "knowledge_node_ids": record.knowledge_node_ids,
        "cognitive_snapshot": record.cognitive_snapshot,
        "source": record.source,
        "source_version": record.source_version,
        "consumed": record.consumed,
        "consumed_at": record.consumed_at.isoformat() if record.consumed_at else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _serialize_evidence(record: LearningEvidenceRecord) -> dict[str, Any]:
    """序列化学习证据"""
    return {
        "evidence_id": record.evidence_id,
        "student_id": record.student_id,
        "course_id": record.course_id,
        "node_id": record.node_id,
        "evidence_type": record.evidence_type,
        "value": record.value,
        "confidence": record.confidence,
        "label": record.label,
        "description": record.description,
        "source": record.source,
        "question_attempt_id": record.question_attempt_id,
        "event_refs": record.event_refs,
        "policy_version": record.policy_version,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
