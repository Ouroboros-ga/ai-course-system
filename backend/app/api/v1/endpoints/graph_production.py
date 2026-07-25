"""G9 Evidence 与知识图谱生产化 API

学生只读已发布快照；内部检索轨迹继续受控。
教师可治理知识点、别名、映射、先修关系和冲突。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.document_artifact_model import DocumentArtifact
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
    graph_target_hash,
)

router = APIRouter(tags=["G9 Evidence与图谱"])


class PublishSnapshotRequest(BaseModel):
    nodes: list[dict] = Field(default_factory=list, max_length=5000)
    relations: list[dict] = Field(default_factory=list, max_length=20000)
    label: str = Field(default="", max_length=200)


class EvidenceCreateRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=200)
    page_number: int = Field(ge=1)
    char_start: Optional[int] = Field(None, ge=0)
    char_end: Optional[int] = Field(None, ge=1)
    text_snippet: str = Field(min_length=1, max_length=20_000)
    evidence_type: str = Field(default="document_extract", max_length=100)


class GraphReviewCreateRequest(BaseModel):
    snapshot_id: Optional[str] = Field(None, max_length=200)
    target_id: str = Field(min_length=1, max_length=200)
    target_type: str = Field(pattern="^(node|relation)$")
    decision: str = Field(pattern="^(proposed|accepted|rejected|needs_review)$")
    review_comment: str = Field(default="", max_length=5000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    target_content: Optional[dict] = None


@router.post("/course/{course_id}/evidence")
async def add_evidence(
    course_id: int,
    payload: EvidenceCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师确认一条来源于当前课程课件的可定位 Evidence。"""
    require_course_permission(session, current_user, course_id, "evidence.confirm")
    artifact = session.exec(
        select(DocumentArtifact).where(
            DocumentArtifact.course_id == course_id,
            DocumentArtifact.document_id == payload.document_id,
        )
    ).first()
    if artifact is None:
        raise HTTPException(status_code=404, detail="课程课件不存在")
    try:
        evidence = create_evidence(
            session,
            course_id=course_id,
            document_id=payload.document_id,
            source_file=artifact.file_name,
            page_number=payload.page_number,
            char_start=payload.char_start,
            char_end=payload.char_end,
            text_snippet=payload.text_snippet,
            evidence_type=payload.evidence_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    evidence.reviewed_by = int(current_user["user_id"])
    evidence.reviewed_at = datetime.utcnow()
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    return unified_response(
        code=200,
        message="Evidence 已确认",
        data=serialize_evidence(evidence),
    )


@router.post("/course/{course_id}/reviews")
async def create_graph_review(
    course_id: int,
    payload: GraphReviewCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """记录教师对节点或关系的治理决定；记录只追加、不覆盖历史。"""
    require_course_permission(session, current_user, course_id, "knowledge.review")
    target_content = payload.target_content
    if payload.snapshot_id:
        snapshot = session.exec(
            select(GraphSnapshotRecord).where(
                GraphSnapshotRecord.course_id == course_id,
                GraphSnapshotRecord.snapshot_id == payload.snapshot_id,
            )
        ).first()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="图谱快照不存在")
        collection = (
            snapshot.nodes if payload.target_type == "node" else snapshot.relations
        )
        target_ids = {
            str(
                item.get("id")
                or item.get(
                    "node_id" if payload.target_type == "node" else "relation_id"
                )
                or ""
            )
            for item in collection
        }
        if payload.target_id not in target_ids:
            raise HTTPException(status_code=422, detail="治理目标不在指定快照中")
        target_content = next(
            item
            for item in collection
            if str(
                item.get("id")
                or item.get(
                    "node_id" if payload.target_type == "node" else "relation_id"
                )
                or ""
            ) == payload.target_id
        )
    if target_content is None:
        raise HTTPException(
            status_code=422,
            detail="未指定快照时必须提供完整 target_content",
        )
    content_target_id = str(
        target_content.get("id")
        or target_content.get(
            "node_id" if payload.target_type == "node" else "relation_id"
        )
        or ""
    )
    if content_target_id != payload.target_id:
        raise HTTPException(status_code=422, detail="target_content 与 target_id 不一致")
    if payload.evidence_ids:
        evidence = session.exec(
            select(CourseEvidenceRecord.evidence_id).where(
                CourseEvidenceRecord.course_id == course_id,
                CourseEvidenceRecord.evidence_id.in_(payload.evidence_ids),
                CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
            )
        ).all()
        if set(evidence) != set(payload.evidence_ids):
            raise HTTPException(status_code=422, detail="包含无效或跨课程 Evidence")

    review = GraphNodeReview(
        course_id=course_id,
        snapshot_id=payload.snapshot_id,
        target_id=payload.target_id,
        target_type=payload.target_type,
        target_content_hash=graph_target_hash(target_content),
        decision=payload.decision,
        reviewer=int(current_user["user_id"]),
        review_comment=payload.review_comment,
        evidence_ids=sorted(set(payload.evidence_ids)),
    )
    session.add(review)
    session.commit()
    session.refresh(review)
    return unified_response(
        code=200,
        message="图谱治理记录已保存",
        data={
            "id": review.id,
            "target_id": review.target_id,
            "target_type": review.target_type,
            "decision": review.decision,
            "evidence_ids": review.evidence_ids,
            "created_at": review.created_at.isoformat(),
        },
    )


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

    try:
        snapshot = publish_snapshot(
            session,
            course_id=course_id,
            nodes=payload.nodes,
            relations=payload.relations,
            label=payload.label,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    try:
        snapshot = rollback_snapshot(session, course_id, snapshot_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
