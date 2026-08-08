"""G2 六维认知与推荐 API

使用统一权限解析器(require_course_permission)进行课程级权限校验。
- 查看认知状态: course.progress.read_self (学生) / analytics.view_course (教师)
- 获取推荐: course.question.ask (学生)
- 查看推荐历史: course.progress.read_self (学生) / analytics.view_course (教师)

不跨学生、课程读取或写入状态。
数据不足时输出 unknown 或"需要更多证据"。
"""
from __future__ import annotations

import logging
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
from app.models.access_control_model import (
    CourseMembership,
    CourseRole,
    MembershipStatus,
)
from app.services.cognitive_service import compute_cognitive_state, get_latest_cognitive_state
from app.services.recommendation_service import (
    generate_recommendation,
    get_recommendation_history,
    lock_recommendation,
    mark_recommendation_consumed,
    unlock_recommendation,
)
from app.services.course_access_service import (
    require_course_permission,
    resolve_course_access,
)
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_outline_model import CourseOutlineNode, OutlineNodeType
from app.models.graph_production_model import CourseKnowledgeNode
from app.models.unified_learning_model import LearningEventType
from app.services.unified_learning_service import record_event, refresh_course_stats

router = APIRouter(tags=["G2 六维认知与推荐"])
logger = logging.getLogger(__name__)


# ==================== 认知状态接口 ====================

@router.get("/course/{course_id}/state")
async def get_cognitive_state(
    course_id: int,
    node_id: Optional[int] = Query(None, description="节点ID(空=课程级)"),
    student_id: Optional[int] = Query(None, ge=1, description="教师查看的课程学生ID"),
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

    # 学生只能查看自己；课程教师查看他人时必须拥有分析权限，且目标必须
    # 是该课程的有效学生成员。
    if student_id is not None and student_id != user_id:
        require_course_permission(
            session, current_user, course_id, "analytics.view_member"
        )
        membership = session.exec(
            select(CourseMembership).where(
                CourseMembership.course_id == course_id,
                CourseMembership.user_id == student_id,
                CourseMembership.role == CourseRole.STUDENT,
                CourseMembership.status == MembershipStatus.ACTIVE,
            )
        ).first()
        if membership is None:
            raise HTTPException(status_code=404, detail="课程学生不存在")
        target_student = student_id
    else:
        if not context.analytics_eligible:
            raise HTTPException(
                status_code=422,
                detail="教师查看学情时必须指定课程学生 student_id",
            )
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
    if not context.analytics_eligible:
        raise HTTPException(status_code=403, detail="仅课程学习者可以生成个人认知状态")

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
    if not context.analytics_eligible:
        raise HTTPException(status_code=403, detail="仅课程学习者可以生成个性化推荐")

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

    candidate = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.recommendation_id == recommendation_id,
            RecommendationRecord.student_id == user_id,
        )
    ).first()
    if candidate is None:
        raise HTTPException(status_code=404, detail="推荐记录不存在或不属于当前用户")
    context = require_course_permission(
        session,
        current_user,
        candidate.course_id,
        "course.progress.read_self",
    )
    if not context.analytics_eligible:
        raise HTTPException(status_code=403, detail="当前成员状态不能消费学习推荐")

    record = mark_recommendation_consumed(session, recommendation_id, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="推荐记录不存在或不属于当前用户")

    # 推荐消费是学习动作的一部分，但不能让认知/推荐链路阻断学习。
    # 仅在推荐能稳定映射到当前 active release 的正式知识点时写入统一事件；
    # 课程级或未映射推荐仍保留原消费记录，前端继续按降级语义运行。
    try:
        release = session.exec(select(CourseRelease).where(
            CourseRelease.course_id == record.course_id,
            CourseRelease.status == ReleaseStatus.PUBLISHED,
            CourseRelease.is_active == True,
        )).first()
        knowledge_id = record.knowledge_node_id or record.node_id
        knowledge = None
        if knowledge_id is not None:
            knowledge = session.get(CourseKnowledgeNode, knowledge_id)
            if knowledge is not None and knowledge.course_id != record.course_id:
                knowledge = None
        outline_node = None
        if release is not None and knowledge is not None:
            outline_node = session.exec(select(CourseOutlineNode).where(
                CourseOutlineNode.outline_version_id == release.outline_version_id,
                CourseOutlineNode.node_type == OutlineNodeType.KNOWLEDGE_POINT,
                CourseOutlineNode.knowledge_graph_node_id == knowledge.node_key,
            )).first()
        if release is not None and outline_node is not None:
            record_event(
                session,
                student_id=user_id,
                course_id=record.course_id,
                release_id=release.release_id,
                outline_node_id=outline_node.outline_node_id,
                event_type=LearningEventType.RECOMMENDATION_CONSUMED,
                idempotency_key=f"recommendation-consumed:{recommendation_id}",
                payload={
                    "recommendation_id": recommendation_id,
                    "recommendation_type": record.recommendation_type,
                    "action": "accepted",
                },
                source="cognitive_recommendation",
            )
            refresh_course_stats(session, course_id=record.course_id, release_id=release.release_id)
            session.commit()
    except Exception as exc:
        logger.warning(
            "recommendation consumed but learning event projection degraded recommendation_id=%s course=%s error=%s",
            recommendation_id,
            record.course_id,
            type(exc).__name__,
        )
        session.rollback()

    return unified_response(
        code=200,
        message="推荐已标记为已消费",
        data={"recommendation_id": recommendation_id, "consumed": True},
    )


@router.post("/recommendation/{recommendation_id}/lock")
async def lock_recommendation_endpoint(
    recommendation_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师锁定推荐项（安全阀）。

    权限：``analytics.view_member`` 或 ``agent.policy.configure``（满足其一即可）。
    锁定后，``generate_recommendation`` 在同 student+course+node 下若存在
    未消费的锁定推荐，将直接返回该锁定推荐而不重新生成。
    """
    teacher_id = int(current_user["user_id"])
    record = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.recommendation_id == recommendation_id,
        )
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="推荐记录不存在")

    # 课程级权限校验：教师需具备 analytics.view_member 或 agent.policy.configure 之一
    context = resolve_course_access(session, current_user, record.course_id)
    if not (
        context.allows("analytics.view_member")
        or context.allows("agent.policy.configure")
    ):
        raise HTTPException(
            status_code=403,
            detail="需要 analytics.view_member 或 agent.policy.configure 权限才能锁定推荐",
        )

    updated = lock_recommendation(session, recommendation_id, teacher_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="推荐记录不存在")

    return unified_response(
        code=200,
        message="推荐已锁定",
        data=_serialize_recommendation(updated),
    )


@router.post("/recommendation/{recommendation_id}/unlock")
async def unlock_recommendation_endpoint(
    recommendation_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师解锁推荐项。

    权限：``analytics.view_member`` 或 ``agent.policy.configure``（满足其一即可）。
    解锁后，``generate_recommendation`` 可重新生成同 student+course+node 的推荐。
    """
    record = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.recommendation_id == recommendation_id,
        )
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="推荐记录不存在")

    context = resolve_course_access(session, current_user, record.course_id)
    if not (
        context.allows("analytics.view_member")
        or context.allows("agent.policy.configure")
    ):
        raise HTTPException(
            status_code=403,
            detail="需要 analytics.view_member 或 agent.policy.configure 权限才能解锁推荐",
        )

    updated = unlock_recommendation(session, recommendation_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="推荐记录不存在")

    return unified_response(
        code=200,
        message="推荐已解锁",
        data=_serialize_recommendation(updated),
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
        "graph_snapshot_id": record.graph_snapshot_id,
        "knowledge_node_id": record.knowledge_node_id,
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
        "is_locked": record.is_locked,
        "locked_by": record.locked_by,
        "locked_at": record.locked_at.isoformat() if record.locked_at else None,
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
