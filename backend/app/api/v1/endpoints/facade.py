"""Phase A 前后端契约对齐门面层

新增门面端点，返回统一的 ViewModel，不暴露 Shadow DTO 或数据库 ID。
前端应消费此层而非直接消费零散的 V1 端点响应。

ViewModel 契约:
  - HomeViewModel: 工作首页聚合视图，含继续学习、我建设的、待审核、系统任务
  - CourseCard: 课程列表读模型（learning/building/hall 视图）
  - CourseOverviewViewModel: 课程概览，含能力声明、统一 document_id、结构摘要
  - CitationViewModel: 引用定位，含稳定 document_id (UUID)
  - QuizViewModel: 题目视图，含知识点关联和发布状态

所有端点使用 require_course_permission 进行课程级权限校验。
"""
from __future__ import annotations

import logging
from typing import Optional, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.core.config import settings
from app.models.database import get_session
from app.models.course_model import (
    Course,
    CourseScript,
    DoclingDocument,
    DoclingText,
    ScriptNode,
    StudentEnrollment,
)
from app.models.access_control_model import CourseMembership
from app.models.user_model import User
from app.models.document_artifact_model import DocumentArtifact
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionStatus,
)
from app.services.course_access_service import (
    require_course_permission,
    serialize_access_context,
    ALL_PERMISSIONS,
)
from app.services.facade_home_service import facade_home_service
from app.models.course_build_model import CourseRelease
from app.models.access_control_model import MembershipStatus
from app.models.unified_learning_model import LearningEventType, StudentLearningProjection, CourseLearningStatsProjection, ExposureStatus
from app.models.cognitive_state_model import CognitiveState, LearningEvidenceRecord, RecommendationRecord
from app.models.graph_production_model import CourseKnowledgeNode
from app.services.unified_learning_service import active_release, release_nodes, record_event, student_context, refresh_course_stats
from pydantic import BaseModel, Field

router = APIRouter(tags=["Phase A 门面层"])
logger = logging.getLogger(__name__)

class LearningEventRequest(BaseModel):
    release_id: str
    outline_node_id: str
    event_type: LearningEventType
    idempotency_key: str = Field(min_length=8, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: Optional[datetime] = None
    source: str = Field(default="learn_page", max_length=64)


def _attach_cognition(session: Session, *, student_id: int, course_id: int, item: dict[str, Any]) -> None:
    key = item.get("knowledge_node_key")
    if not key:
        item["cognition"] = {
            "status": "not_available",
            "reason_codes": ["knowledge_node_unmapped"],
        }
        return
    try:
        knowledge = session.exec(select(CourseKnowledgeNode).where(
            CourseKnowledgeNode.course_id == course_id,
            CourseKnowledgeNode.node_key == key,
        )).first()
    except Exception as exc:
        session.rollback()
        logger.warning(
            "learning-context knowledge mapping degraded course=%s student=%s node_key=%s error=%s",
            course_id,
            student_id,
            key,
            type(exc).__name__,
        )
        item["cognition"] = {
            "status": "degraded",
            "node_key": key,
            "reason_codes": ["cognition_service_unavailable"],
            "evidence_count": 0,
            "sample_size": 0,
        }
        item["recommendation"] = {
            "status": "degraded",
            "reason_codes": ["recommendation_service_unavailable"],
        }
        return
    if knowledge is None:
        item["cognition"] = {
            "status": "not_available",
            "reason_codes": ["knowledge_node_unmapped"],
        }
        item["recommendation"] = {
            "status": "not_available",
            "reason_codes": ["knowledge_node_unmapped"],
        }
        return
    try:
        state = session.exec(select(CognitiveState).where(CognitiveState.student_id == student_id, CognitiveState.course_id == course_id, CognitiveState.node_id == knowledge.id, CognitiveState.is_latest == True).order_by(CognitiveState.computed_at.desc())).first()
        recommendation = session.exec(select(RecommendationRecord).where(
            RecommendationRecord.student_id == student_id,
            RecommendationRecord.course_id == course_id,
            RecommendationRecord.consumed == False,
            (RecommendationRecord.knowledge_node_id == knowledge.id) | (RecommendationRecord.node_id == knowledge.id),
        ).order_by(RecommendationRecord.created_at.desc())).first()
    except Exception as exc:
        # 认知/推荐表或服务不可用时，学习上下文仍必须返回；前端显示 degraded。
        session.rollback()
        logger.warning(
            "learning-context cognition/recommendation degraded course=%s student=%s node_key=%s error=%s",
            course_id,
            student_id,
            key,
            type(exc).__name__,
        )
        item["cognition"] = {
            "status": "degraded",
            "node_id": knowledge.id,
            "node_key": knowledge.node_key,
            "reason_codes": ["cognition_service_unavailable"],
            "evidence_count": 0,
            "sample_size": 0,
        }
        item["recommendation"] = {"status": "degraded", "reason_codes": ["recommendation_service_unavailable"]}
        return
    if state:
        evidence_count = len(state.evidence_refs or [])
        if evidence_count == 0 and state.sample_size:
            evidence_count = state.sample_size
        evidence_rows = []
        evidence_ids = [str(ref) for ref in (state.evidence_refs or []) if ref]
        if evidence_ids:
            try:
                evidence_records = session.exec(select(LearningEvidenceRecord).where(
                    LearningEvidenceRecord.student_id == student_id,
                    LearningEvidenceRecord.course_id == course_id,
                    LearningEvidenceRecord.evidence_id.in_(evidence_ids),
                )).all()
                evidence_by_id = {str(row.evidence_id): row for row in evidence_records}
                for evidence_id in evidence_ids[:10]:
                    row = evidence_by_id.get(evidence_id)
                    evidence_rows.append({
                        "evidence_id": evidence_id,
                        "type": row.evidence_type if row else "unknown",
                        "confidence": row.confidence if row else None,
                        "source": row.source if row else "cognitive_state",
                        "question_attempt_id": row.question_attempt_id if row else None,
                    })
            except Exception as exc:
                session.rollback()
                logger.warning(
                    "learning-context evidence detail degraded course=%s student=%s node_key=%s error=%s",
                    course_id,
                    student_id,
                    key,
                    type(exc).__name__,
                )
        item["cognition"] = {
            "status": "available",
            "node_id": knowledge.id,
            "node_key": knowledge.node_key,
            "mastery_level": state.mastery_level,
            "mastery_score": state.mastery_score,
            "evidence_confidence": state.evidence_confidence,
            "reason_codes": state.reason_codes or [],
            "evidence_count": evidence_count,
            "evidence": evidence_rows,
            "sample_size": state.sample_size,
            "computed_at": state.computed_at.isoformat() if state.computed_at else None,
        }
    else:
        item["cognition"] = {
            "status": "unknown",
            "node_id": knowledge.id,
            "node_key": knowledge.node_key,
            "mastery_level": "unknown",
            "reason_codes": ["insufficient_evidence"],
            "evidence_count": 0,
            "sample_size": 0,
            "evidence": [],
        }
    if recommendation:
        item["recommendation"] = {
            "status": "available",
            "recommendation_id": recommendation.recommendation_id,
            "type": recommendation.recommendation_type,
            "priority": recommendation.priority,
            "title": recommendation.title,
            "description": recommendation.description,
            "reason_codes": recommendation.reason_codes,
            "evidence_refs": recommendation.evidence_refs,
        }


@router.get("/course/{course_id}/learning-context")
async def get_learning_context(course_id: int, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.learn")
    data = student_context(session, student_id=context.user_id, course_id=course_id)
    for item in data.get("items", []):
        _attach_cognition(session, student_id=context.user_id, course_id=course_id, item=item)
    return unified_response(200, "获取统一学习上下文成功", data)


@router.post("/course/{course_id}/learning-events")
async def create_learning_event(course_id: int, payload: LearningEventRequest, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.learn")
    release = active_release(session, course_id)
    if release is None or release.release_id != payload.release_id:
        raise HTTPException(status_code=409, detail="RELEASE_NOT_ACTIVE")
    try:
        event, projection = record_event(session, student_id=context.user_id, course_id=course_id, release_id=payload.release_id, outline_node_id=payload.outline_node_id, event_type=payload.event_type, idempotency_key=payload.idempotency_key, payload=payload.payload, occurred_at=payload.occurred_at, source=payload.source)
        refresh_course_stats(session, course_id=course_id, release_id=payload.release_id)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    return unified_response(200, "学习事件已记录", {"event_id": event.event_id, "release_id": projection.release_id, "outline_node_id": projection.outline_node_id, "status": projection.exposure_status.value, "completion_ratio": projection.completion_ratio, "completion_reason": projection.completion_reason})


@router.post("/course/{course_id}/learning-actions/complete")
async def complete_learning_action(course_id: int, release_id: str, outline_node_id: str, idempotency_key: str, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.learn")
    release = active_release(session, course_id)
    if release is None or release.release_id != release_id:
        raise HTTPException(status_code=409, detail="RELEASE_NOT_ACTIVE")
    try:
        event, projection = record_event(session, student_id=context.user_id, course_id=course_id, release_id=release_id, outline_node_id=outline_node_id, event_type=LearningEventType.EXPLICIT_COMPLETE, idempotency_key=idempotency_key, payload={"action": "complete"}, source="learn_page")
        refresh_course_stats(session, course_id=course_id, release_id=release_id)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    return unified_response(200, "知识点已完成", {"event_id": event.event_id, "outline_node_id": projection.outline_node_id, "status": projection.exposure_status.value})


@router.get("/course/{course_id}/analytics")
async def get_learning_analytics(course_id: int, release_id: Optional[str] = Query(None), session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "analytics.view_course")
    release = active_release(session, course_id) if release_id is None else session.exec(select(CourseRelease).where(CourseRelease.course_id == course_id, CourseRelease.release_id == release_id)).first()
    if release is None:
        raise HTTPException(status_code=409, detail="RELEASE_NOT_FOUND")
    # Analytics is a projection read. Refresh it against the current active,
    # analytics-eligible membership set before serializing so removed/excluded
    # learners cannot survive in a stale aggregate row.
    refresh_course_stats(session, course_id=course_id, release_id=release.release_id)
    session.commit()
    nodes = release_nodes(session, release)
    memberships = session.exec(select(CourseMembership).where(CourseMembership.course_id == course_id, CourseMembership.status == MembershipStatus.ACTIVE)).all()
    students = [m for m in memberships if m.role.value == "student" and not m.analytics_excluded]
    student_ids = [membership.user_id for membership in students]
    projection_query = select(StudentLearningProjection).where(
        StudentLearningProjection.course_id == course_id,
        StudentLearningProjection.release_id == release.release_id,
    )
    if student_ids:
        projection_query = projection_query.where(StudentLearningProjection.student_id.in_(student_ids))
    else:
        projection_query = projection_query.where(StudentLearningProjection.student_id == -1)
    projections = session.exec(projection_query).all()
    stats_rows = session.exec(select(CourseLearningStatsProjection).where(
        CourseLearningStatsProjection.course_id == course_id,
        CourseLearningStatsProjection.release_id == release.release_id,
    )).all()
    stats_by_node = {row.outline_node_id: row for row in stats_rows}
    by_node: dict[str, list[StudentLearningProjection]] = {}
    for row in projections:
        by_node.setdefault(row.outline_node_id, []).append(row)
    items = []
    for node in nodes:
        rows = by_node.get(node.outline_node_id, [])
        counts = {status.value: 0 for status in ExposureStatus}
        for row in rows:
            counts[row.exposure_status.value] += 1
        stat = stats_by_node.get(node.outline_node_id)
        not_started = stat.not_started_count if stat else max(0, len(students) - counts["in_progress"] - counts["completed"])
        completed = stat.completed_count if stat else counts["completed"]
        items.append({
            "outline_node_id": node.outline_node_id,
            "title": node.title,
            "total_students": len(students),
            "not_started": not_started,
            "in_progress": stat.in_progress_count if stat else counts["in_progress"],
            "completed": completed,
            "completion_rate": completed / len(students) if students else 0.0,
            "mastery_distribution": stat.mastery_distribution if stat else {},
            "unknown_mastery_count": stat.unknown_mastery_count if stat else 0,
            "low_confidence_count": stat.low_confidence_count if stat else 0,
            "pending_recommendation_count": stat.pending_recommendation_count if stat else 0,
        })
    student_summaries = []
    for membership in students:
        student_rows = [row for row in projections if row.student_id == membership.user_id]
        completed = sum(row.exposure_status == ExposureStatus.COMPLETED for row in student_rows)
        student_summaries.append({
            "student_id": membership.user_id,
            "completed": completed,
            "total": len(nodes),
            "completion_rate": completed / len(nodes) if nodes else 0.0,
        })
    return unified_response(200, "获取课程学习统计成功", {
        "course_id": course_id,
        "release_id": release.release_id,
        "student_count": len(students),
        "knowledge_points": items,
        "students": student_summaries,
    })


@router.get("/course/{course_id}/analytics/students/{student_id}")
async def get_student_learning_analytics(course_id: int, student_id: int, release_id: Optional[str] = Query(None), session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "analytics.view_member")
    membership = session.exec(select(CourseMembership).where(CourseMembership.course_id == course_id, CourseMembership.user_id == student_id, CourseMembership.status == MembershipStatus.ACTIVE)).first()
    if membership is None or membership.role.value != "student" or membership.analytics_excluded:
        raise HTTPException(status_code=404, detail="STUDENT_NOT_FOUND")
    data = student_context(session, student_id=student_id, course_id=course_id, release_id=release_id)
    for item in data.get("items", []):
        _attach_cognition(session, student_id=student_id, course_id=course_id, item=item)
    data["student_id"] = student_id
    return unified_response(200, "获取学生学习统计成功", data)


# ==================== HomeViewModel（阶段1） ====================

@router.get("/home")
async def get_home(
    mode: Optional[str] = Query(None, description="强制视图：student 或 teacher"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """工作首页聚合 ViewModel

    返回 HomeViewModel，包含：
    - active_mode: student/teacher/mixed，由当前用户的课程成员关系推导
    - continue_learning: 最近学习的课程（学生视角）
    - building_courses: 我建设的课程（教师视角）
    - pending_reviews: 待处理审核（教师视角）
    - system_tasks: 失败/进行中任务（所有视角）

    所有数据基于 CourseMembership 严格隔离，跨用户/跨课程不可见。
    """
    data = facade_home_service.get_home(
        session,
        current_user,
        mode=mode,
    )
    return unified_response(
        code=200,
        message="获取工作首页成功",
        data=data,
    )


# ==================== CourseCard（阶段1课程列表读模型） ====================

@router.get("/courses")
async def list_courses(
    view: str = Query(..., description="列表视图：learning/building/hall"),
    cursor: Optional[str] = Query(None, description="上一页返回的 next_cursor"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，1..100"),
    query: Optional[str] = Query(None, description="按标题模糊搜索"),
    subject: Optional[str] = Query(None, description="按学科过滤（hall 视图预留）"),
    status: Optional[str] = Query(None, description="按状态过滤（learning/building 视图）"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课程列表读模型

    - view=learning: 当前用户作为学生可学习的课程
    - view=building: 当前用户有 course.edit 或建设职责的课程
    - view=hall: 课程大厅，仅返回允许发现的已发布课程；草稿不进入大厅

    返回 items / next_cursor / total / has_next；游标分页协议与 §1.2 一致。
    """
    data = facade_home_service.list_courses(
        session,
        current_user,
        view=view,
        cursor=cursor,
        page_size=page_size,
        query=query,
        subject=subject,
        status_filter=status,
    )
    return unified_response(
        code=200,
        message="获取课程列表成功",
        data=data,
    )


# ==================== CourseOverviewViewModel ====================

@router.get("/course/{course_id}/overview")
async def get_course_overview(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课程概览门面 ViewModel

    聚合课程信息、能力声明、统一 document_id、结构摘要。
    前端消费此 ViewModel，不直接消费 V1 端点的零散响应。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")
    user_id = int(current_user["user_id"])

    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    # 统一 document_id (DocumentArtifact.document_id UUID)
    artifact = session.exec(
        select(DocumentArtifact).where(DocumentArtifact.course_id == course_id)
    ).first()
    document_id = artifact.document_id if artifact else None

    # 能力声明
    capabilities = context.capabilities

    # 结构摘要
    active_script = session.exec(
        select(CourseScript).where(
            CourseScript.course_id == course_id,
            CourseScript.is_active == True,
        )
    ).first()

    node_count = 0
    chapter_count = 0
    if active_script:
        nodes = session.exec(
            select(ScriptNode).where(ScriptNode.script_id == active_script.id)
        ).all()
        node_count = len(nodes)
        chapter_ids = {n.chapter_id for n in nodes if n.chapter_id}
        chapter_count = len(chapter_ids)

    # 进度摘要（学生）
    progress_summary = None
    if context.role and context.role.value == "student":
        enrollment = session.exec(
            select(StudentEnrollment).where(
                StudentEnrollment.student_id == user_id,
                StudentEnrollment.course_id == course_id,
            )
        ).first()
        if enrollment:
            progress_summary = {
                "overall_progress": enrollment.overall_progress or 0,
                "avg_understanding_score": enrollment.avg_understanding_score or 0,
                "total_study_minutes": enrollment.total_study_minutes or 0,
            }

    # 权限视图
    access_view = serialize_access_context(context, ALL_PERMISSIONS)

    return unified_response(
        code=200,
        message="获取课程概览成功",
        data={
            "course_id": course_id,
            "title": course.title,
            "description": course.description or "",
            "status": course.status.value if course.status else "draft",
            "teacher_id": course.teacher_id,
            "document_id": document_id,
            "capabilities": capabilities,
            "access": access_view,
            "structure": {
                "node_count": node_count,
                "chapter_count": chapter_count,
                "total_pages": course.total_pages or 0,
                "total_duration": course.total_duration or 0,
            },
            "progress": progress_summary,
            "role": context.role.value if context.role else None,
            "participation_mode": context.participation_mode.value if context.participation_mode else None,
            "analytics_eligible": context.analytics_eligible,
        },
    )


# ==================== CitationViewModel ====================

@router.get("/course/{course_id}/citation/{node_id}")
async def get_citation_view(
    course_id: int,
    node_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """引用定位门面 ViewModel

    返回统一 document_id (UUID)，与 GET /document/{document_id} 契约一致。
    不暴露 DoclingDocument 整数主键。
    """
    require_course_permission(session, current_user, course_id, "course.citation.read")

    # 查询节点
    node = session.get(ScriptNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    # 验证节点属于该课程
    script = session.get(CourseScript, node.script_id) if node.script_id else None
    if not script or script.course_id != course_id:
        raise HTTPException(status_code=404, detail="节点不属于该课程")

    # 查询 DocumentArtifact 获取统一 document_id
    artifact = session.exec(
        select(DocumentArtifact).where(DocumentArtifact.course_id == course_id)
    ).first()
    document_id = artifact.document_id if artifact else None

    # 查询原文片段
    docling_doc = session.exec(
        select(DoclingDocument).where(DoclingDocument.course_id == course_id)
    ).first()

    page_start = node.page_start
    page_end = node.page_end
    snippet = None

    if docling_doc and page_start is not None:
        texts = session.exec(
            select(DoclingText)
            .where(DoclingText.doc_id == docling_doc.id)
            .where(DoclingText.page_no == page_start)
        ).all()
        if texts:
            snippet = " ".join(t.text for t in texts[:5])[:500]

    return unified_response(
        code=200,
        message="获取引用定位成功",
        data={
            "document_id": document_id,
            "course_id": course_id,
            "node_id": node_id,
            "node_title": node.title or node.content[:50] if node.content else "",
            "page_start": page_start,
            "page_end": page_end,
            "snippet": snippet,
            "source_file": artifact.file_name if artifact else (docling_doc.origin_filename if docling_doc else ""),
            "return_anchor": {
                "node_id": node_id,
                "label": node.title or "",
            },
        },
    )


# ==================== QuizViewModel ====================

@router.get("/course/{course_id}/quiz")
async def get_quiz_view(
    course_id: int,
    node_id: Optional[int] = Query(None, description="按知识点筛选"),
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """题目视图门面 ViewModel

    返回统一格式的题目列表，学生仅可见 published。
    关联知识点和返回锚点。
    """
    context = require_course_permission(session, current_user, course_id, "question_bank.read")

    stmt = select(QuestionBankItem).where(
        QuestionBankItem.course_id == course_id,
        QuestionBankItem.is_latest == True,
    )

    # 学生只能看 published
    if context.role and context.role.value == "student":
        stmt = stmt.where(QuestionBankItem.status == QuestionStatus.PUBLISHED)

    if node_id:
        stmt = stmt.where(QuestionBankItem.knowledge_node_ids.contains([node_id]))

    stmt = stmt.limit(limit)
    items = session.exec(stmt).all()

    return unified_response(
        code=200,
        message="获取题目视图成功",
        data={
            "course_id": course_id,
            "items": [
                _serialize_quiz_item(
                    q,
                    include_answer=not (
                        context.role and context.role.value in {"student", "observer"}
                    ),
                )
                for q in items
            ],
            "total": len(items),
            "role": context.role.value if context.role else None,
        },
    )


def _serialize_quiz_item(
    q: QuestionBankItem,
    *,
    include_answer: bool,
) -> dict[str, Any]:
    """序列化题目为 QuizViewModel"""
    data = {
        "question_id": q.id,
        "question_text": q.question_text,
        "options": q.options,
        "question_type": q.question_type.value,
        "difficulty": q.difficulty.value,
        "knowledge_node_ids": q.knowledge_node_ids,
        "status": q.status.value,
        "version": q.version,
        "return_anchor": {
            "node_id": q.knowledge_node_ids[0] if q.knowledge_node_ids else None,
            "label": q.category or "",
        },
    }
    if include_answer:
        data["answer"] = q.answer
    return data


# ==================== R2 检索能力检查 ====================

@router.get("/course/{course_id}/retrieval-capability")
async def get_retrieval_capability(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """检查课程的 R2 检索能力

    前端通过此端点识别是否可显示引用与检索轨迹。
    采用课程白名单/能力开关，支持一键回退。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")

    # 检查课程能力开关
    evidence_capable = context.capabilities.get("evidence", False)

    # 检查 Feature Flag
    r2_enabled = False
    r2_mode = "v1_only"
    try:
        from app.core.feature_flags import (
            DOCUMENT_KG_RUNTIME_MODE,
            resolve_effective_modes,
        )
        configured = {
            DOCUMENT_KG_RUNTIME_MODE: getattr(settings, DOCUMENT_KG_RUNTIME_MODE, "v1_only"),
        }
        effective = resolve_effective_modes(configured)
        r2_mode = effective[DOCUMENT_KG_RUNTIME_MODE].effective
        r2_enabled = (
            r2_mode == "v2_shadow"
            and settings.R2_STUDENT_ANSWER_ENABLED
        )
    except Exception:
        pass

    # 检查课程侧车是否存在
    sidecar_exists = False
    try:
        from app.platform.shadow.course_evidence_sidecar import CourseEvidenceSidecarStore
        store = CourseEvidenceSidecarStore()
        sidecar_exists = store.read_course(str(course_id)) is not None
    except Exception:
        pass

    # 综合判定
    retrieval_available = evidence_capable and r2_enabled and sidecar_exists

    return unified_response(
        code=200,
        message="获取检索能力成功",
        data={
            "course_id": course_id,
            "retrieval_available": retrieval_available,
            "evidence_capability": evidence_capable,
            "r2_mode": r2_mode,
            "r2_enabled": r2_enabled,
            "student_answer_gate_enabled": settings.R2_STUDENT_ANSWER_ENABLED,
            "sidecar_exists": sidecar_exists,
            "can_show_citations": retrieval_available,
            "policy_version": "r2-retrieval-v1.0",
            "fallback_to_v1": not retrieval_available,
        },
    )


# ==================== 阶段2：成员/设置聚合读模型 ====================

@router.get("/course/{course_id}/members")
async def get_course_members_view(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """成员页面聚合读模型

    返回 members / groups / pending_join_requests / recent_sync_runs / audit_summary。
    跨课程严格隔离；非教师角色看不到 pending_join_requests。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")
    user_id = int(current_user["user_id"])

    from app.models.course_lifecycle_model import (
        CourseGroup,
        CourseJoinRequest,
        CourseSettingVersion,
        IntegrationSyncRun,
        JoinRequestStatus,
        SyncRunStatus,
    )
    from app.services.course_lifecycle_service import (
        course_group_service,
        fanya_sync_service,
        join_request_service,
    )

    # 成员列表（基于 CourseMembership）
    memberships = session.exec(
        select(CourseMembership)
        .where(CourseMembership.course_id == course_id)
        .order_by(CourseMembership.role, CourseMembership.user_id)
    ).all()
    member_user_ids = [m.user_id for m in memberships]
    users_map = {
        u.id: u for u in session.exec(select(User).where(User.id.in_(member_user_ids))).all()
    } if member_user_ids else {}

    members_view = []
    for m in memberships:
        u = users_map.get(m.user_id)
        members_view.append({
            "user_id": m.user_id,
            "username": u.username if u else None,
            "role": m.role.value,
            "status": m.status.value,
            "analytics_excluded": m.analytics_excluded,
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            "left_at": m.left_at.isoformat() if m.left_at else None,
        })

    # 分组
    groups = course_group_service.list_groups(session, course_id=course_id)
    groups_view = [
        {
            "group_id": g.group_id,
            "name": g.name,
            "description": g.description,
            "group_type": g.group_type,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        }
        for g in groups
    ]

    # 待处理加入申请（仅教师可见）
    pending_requests = []
    if context.allows("membership.role.change"):
        reqs = join_request_service.list_requests(
            session,
            course_id=course_id,
            status_filter=JoinRequestStatus.PENDING,
        )
        pending_requests = [
            {
                "request_id": r.request_id,
                "applicant_user_id": r.applicant_user_id,
                "apply_reason": r.apply_reason,
                "channel": r.channel.value,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
            for r in reqs
        ]

    # 最近同步运行
    sync_runs = fanya_sync_service.list_runs(session, course_id=course_id, limit=5)
    sync_view = [
        {
            "sync_run_id": r.sync_run_id,
            "status": r.status.value,
            "applied_added": r.applied_added,
            "applied_removed": r.applied_removed,
            "applied_skipped": r.applied_skipped,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error_message": r.error_message,
        }
        for r in sync_runs
    ]

    return unified_response(
        code=200,
        message="获取成员页面聚合读模型成功",
        data={
            "course_id": course_id,
            "members": members_view,
            "groups": groups_view,
            "pending_join_requests": pending_requests,
            "recent_sync_runs": sync_view,
            "can_review_join_requests": context.allows("membership.role.change"),
            "viewer_role": context.role.value if context.role else None,
        },
    )


@router.get("/course/{course_id}/settings")
async def get_course_settings_view(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """设置页面聚合读模型

    返回当前活跃设置版本 + 能力声明 + 教师可编辑范围。
    跨课程严格隔离；非教师角色 can_edit=False。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")

    from app.services.course_lifecycle_service import course_settings_service

    current_setting = course_settings_service.get_current(session, course_id=course_id)
    setting_view = None
    if current_setting is not None:
        setting_view = {
            "setting_version_id": current_setting.setting_version_id,
            "version": current_setting.version,
            "profile": current_setting.profile,
            "publish": current_setting.publish,
            "agent_policy": current_setting.agent_policy,
            "safety": current_setting.safety,
            "sandbox": current_setting.sandbox,
            "integration": current_setting.integration,
            "created_by": current_setting.created_by,
            "created_at": current_setting.created_at.isoformat() if current_setting.created_at else None,
        }

    course = session.get(Course, course_id)
    course_profile = {
        "title": course.title if course else None,
        "description": getattr(course, "description", "") if course else None,
        "cover_url": getattr(course, "cover_url", None) if course else None,
        "status": course.status.value if course else None,
        "invite_code": course.invite_code if course else None,
    } if course else None

    return unified_response(
        code=200,
        message="获取设置页面聚合读模型成功",
        data={
            "course_id": course_id,
            "course_profile": course_profile,
            "current_setting": setting_view,
            "capabilities": context.capabilities,
            "can_edit": context.allows("course.edit"),
            "can_publish": context.allows("course.publish"),
            "viewer_role": context.role.value if context.role else None,
        },
    )


# ==================== 阶段3：课程建设聚合读模型 ====================

@router.get("/course/{course_id}/build")
async def get_course_build_view(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课程建设聚合读模型

    返回七步建设状态 + 质量门禁 + 发布历史。
    跨课程严格隔离；非教师角色 can_build=False。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")

    from app.services.course_build_service import course_build_service

    # 教师视角自动初始化草稿
    if context.allows("course.edit"):
        course_build_service.get_or_create_draft(
            session,
            course_id=course_id,
            actor_user_id=context.user_id,
        )
        session.commit()

    build_view = course_build_service.get_build_view(session, course_id=course_id)
    build_view["can_build"] = context.allows("course.edit")
    build_view["can_publish"] = context.allows("course.publish")
    build_view["viewer_role"] = context.role.value if context.role else None
    return unified_response(
        code=200,
        message="获取课程建设聚合读模型成功",
        data=build_view,
    )
