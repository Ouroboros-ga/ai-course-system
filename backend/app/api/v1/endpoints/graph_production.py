"""G9 Evidence 与知识图谱生产化 API

学生只读已发布快照；内部检索轨迹继续受控。
教师可治理知识点、别名、映射、先修关系和冲突。
"""
from __future__ import annotations

from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.graph_production_model import (
    CourseEvidenceRecord,
    GraphSnapshotRecord,
    GraphNodeReview,
    EvidenceStatus,
)
from app.services.course_access_service import require_course_permission
from app.services.graph_production_service import (
    create_evidence,
    publish_snapshot,
    get_active_snapshot,
    list_snapshots,
    rollback_snapshot,
    mark_evidence_stale,
    get_evidence_for_node,
    serialize_snapshot,
    serialize_evidence,
)

router = APIRouter(tags=["G9 Evidence与图谱"])


class PublishSnapshotRequest(BaseModel):
    nodes: list[dict]
    relations: list[dict]
    label: str = ""


@router.get("/course/{course_id}/snapshot")
async def get_snapshot(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取课程当前活跃快照（学生只读已发布快照）"""
    require_course_permission(session, current_user, course_id, "knowledge.view")
    snapshot = get_active_snapshot(session, course_id)
    if not snapshot:
        return unified_response(code=200, message="暂无已发布快照", data=None)
    return unified_response(code=200, message="获取快照成功", data=serialize_snapshot(snapshot))


@router.post("/course/{course_id}/publish")
async def publish(
    course_id: int,
    payload: PublishSnapshotRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """发布不可变 GraphSnapshot（教师）"""
    context = require_course_permission(session, current_user, course_id, "knowledge.edit")
    user_id = int(current_user["user_id"])

    snapshot = publish_snapshot(
        session,
        course_id=course_id,
        nodes=payload.nodes,
        relations=payload.relations,
        label=payload.label,
        user_id=user_id,
    )
    return unified_response(code=200, message="快照已发布", data=serialize_snapshot(snapshot))


@router.get("/course/{course_id}/snapshots")
async def get_snapshots(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程所有快照版本（教师）"""
    require_course_permission(session, current_user, course_id, "knowledge.review")
    snapshots = list_snapshots(session, course_id)
    return unified_response(
        code=200, message="获取快照列表成功",
        data={"items": [serialize_snapshot(s) for s in snapshots], "total": len(snapshots)},
    )


@router.post("/course/{course_id}/rollback/{snapshot_id}")
async def rollback(
    course_id: int,
    snapshot_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """回滚到指定快照版本（教师）"""
    require_course_permission(session, current_user, course_id, "knowledge.edit")
    user_id = int(current_user["user_id"])
    snapshot = rollback_snapshot(session, course_id, snapshot_id, user_id)
    return unified_response(code=200, message="已回滚到指定快照", data=serialize_snapshot(snapshot))


@router.get("/course/{course_id}/evidence")
async def list_evidence(
    course_id: int,
    node_id: Optional[str] = Query(None, description="按节点筛选"),
    status: Optional[str] = Query(None, description="按状态筛选(active/stale/orphaned)"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程证据"""
    require_course_permission(session, current_user, course_id, "knowledge.view")

    if node_id:
        evidence = get_evidence_for_node(session, course_id, node_id)
    else:
        stmt = select(CourseEvidenceRecord).where(CourseEvidenceRecord.course_id == course_id)
        if status:
            stmt = stmt.where(CourseEvidenceRecord.status == EvidenceStatus(status))
        evidence = list(session.exec(stmt.order_by(CourseEvidenceRecord.created_at.desc())).all())

    return unified_response(
        code=200, message="获取证据成功",
        data={"items": [serialize_evidence(e) for e in evidence], "total": len(evidence)},
    )


@router.post("/course/{course_id}/mark-stale")
async def mark_stale(
    course_id: int,
    document_id: str = Query(..., description="课件文档UUID"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课件重新解析时标记相关 Evidence 为 stale

    课件重新解析或删除时，历史引用不会静默指向错误内容。
    """
    require_course_permission(session, current_user, course_id, "knowledge.edit")
    count = mark_evidence_stale(session, course_id, document_id)
    return unified_response(
        code=200, message=f"已标记 {count} 条证据为 stale",
        data={"stale_count": count, "document_id": document_id},
    )
