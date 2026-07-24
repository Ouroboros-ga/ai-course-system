"""G9 Evidence 与知识图谱生产化服务

核心能力：
  1. 发布不可变 GraphSnapshot（教师可治理）
  2. 学生只读已发布快照
  3. 版本差异与回滚
  4. 课件重新解析/删除时标记 stale（历史引用不静默指向错误内容）
  5. 每个图谱关系可回溯 Evidence 或教师确认记录
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Optional, Any

from sqlmodel import Session, select

from app.models.graph_production_model import (
    CourseEvidenceRecord,
    GraphSnapshotRecord,
    GraphNodeReview,
    SnapshotStatus,
    EvidenceStatus,
)


def create_evidence(
    session: Session,
    *,
    course_id: int,
    document_id: Optional[str] = None,
    source_file: str = "",
    page_number: Optional[int] = None,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
    text_snippet: str = "",
    evidence_type: str = "document_extract",
) -> CourseEvidenceRecord:
    """创建可校验 Evidence"""
    content_hash = hashlib.sha256(text_snippet.encode()).hexdigest()[:32]
    evidence = CourseEvidenceRecord(
        evidence_id=str(uuid.uuid4()),
        course_id=course_id,
        document_id=document_id,
        source_file=source_file,
        page_number=page_number,
        char_start=char_start,
        char_end=char_end,
        text_snippet=text_snippet,
        evidence_type=evidence_type,
        content_hash=content_hash,
        status=EvidenceStatus.ACTIVE,
    )
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    return evidence


def publish_snapshot(
    session: Session,
    *,
    course_id: int,
    nodes: list[dict],
    relations: list[dict],
    label: str = "",
    user_id: Optional[int] = None,
) -> GraphSnapshotRecord:
    """发布不可变 GraphSnapshot

    发布后标记前一活跃快照为 SUPERSEDED。
    新快照变为活跃快照，学生可读。
    """
    # 标记前一活跃快照为 SUPERSEDED
    prev_active = session.exec(
        select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.course_id == course_id,
            GraphSnapshotRecord.is_active == True,
        )
    ).first()
    prev_snapshot_id = None
    if prev_active:
        prev_active.is_active = False
        prev_active.status = SnapshotStatus.SUPERSEDED
        session.add(prev_active)
        prev_snapshot_id = prev_active.snapshot_id

    # 计算版本号
    all_snapshots = session.exec(
        select(GraphSnapshotRecord).where(GraphSnapshotRecord.course_id == course_id)
    ).all()
    version = len(all_snapshots) + 1

    snapshot = GraphSnapshotRecord(
        snapshot_id=str(uuid.uuid4()),
        course_id=course_id,
        nodes=nodes,
        relations=relations,
        version=version,
        prev_snapshot_id=prev_snapshot_id,
        status=SnapshotStatus.PUBLISHED,
        is_active=True,
        label=label or f"v{version}",
        node_count=len(nodes),
        relation_count=len(relations),
        created_by=user_id,
        published_at=datetime.utcnow(),
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def get_active_snapshot(session: Session, course_id: int) -> Optional[GraphSnapshotRecord]:
    """获取课程当前活跃快照（学生只读此快照）"""
    return session.exec(
        select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.course_id == course_id,
            GraphSnapshotRecord.is_active == True,
            GraphSnapshotRecord.status == SnapshotStatus.PUBLISHED,
        )
    ).first()


def list_snapshots(session: Session, course_id: int) -> list[GraphSnapshotRecord]:
    """列出课程所有快照"""
    return list(session.exec(
        select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.course_id == course_id,
        ).order_by(GraphSnapshotRecord.version.desc())
    ).all())


def rollback_snapshot(
    session: Session,
    course_id: int,
    snapshot_id: str,
    user_id: Optional[int] = None,
) -> GraphSnapshotRecord:
    """回滚到指定快照版本"""
    # 标记当前活跃快照为 ROLLED_BACK
    current = get_active_snapshot(session, course_id)
    if current:
        current.is_active = False
        current.status = SnapshotStatus.ROLLED_BACK
        session.add(current)

    # 激活目标快照
    target = session.exec(
        select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.snapshot_id == snapshot_id,
            GraphSnapshotRecord.course_id == course_id,
        )
    ).first()
    if not target:
        raise ValueError(f"快照 {snapshot_id} 不存在")

    target.is_active = True
    target.status = SnapshotStatus.PUBLISHED
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


def mark_evidence_stale(
    session: Session,
    course_id: int,
    document_id: str,
    reason: str = "courseware_reparse",
):
    """课件重新解析时标记相关 Evidence 为 stale

    课件重新解析或删除时，历史引用不会静默指向错误内容。
    """
    evidences = session.exec(
        select(CourseEvidenceRecord).where(
            CourseEvidenceRecord.course_id == course_id,
            CourseEvidenceRecord.document_id == document_id,
            CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
        )
    ).all()
    for ev in evidences:
        ev.status = EvidenceStatus.STALE
        ev.stale_reason = reason
        ev.stale_at = datetime.utcnow()
        session.add(ev)
    session.commit()
    return len(evidences)


def get_evidence_for_node(
    session: Session,
    course_id: int,
    node_id: str,
) -> list[CourseEvidenceRecord]:
    """获取节点关联的证据（回溯 Evidence）"""
    reviews = session.exec(
        select(GraphNodeReview).where(
            GraphNodeReview.course_id == course_id,
            GraphNodeReview.target_id == node_id,
        )
    ).all()
    evidence_ids: list[str] = []
    for review in reviews:
        evidence_ids.extend(review.evidence_ids or [])

    if not evidence_ids:
        return []

    return list(session.exec(
        select(CourseEvidenceRecord).where(
            CourseEvidenceRecord.course_id == course_id,
            CourseEvidenceRecord.evidence_id.in_(evidence_ids),
        )
    ).all())


def serialize_snapshot(snapshot: GraphSnapshotRecord) -> dict[str, Any]:
    """序列化快照"""
    return {
        "id": snapshot.id,
        "snapshot_id": snapshot.snapshot_id,
        "course_id": snapshot.course_id,
        "version": snapshot.version,
        "ontology_version": snapshot.ontology_version,
        "status": snapshot.status.value,
        "is_active": snapshot.is_active,
        "label": snapshot.label,
        "node_count": snapshot.node_count,
        "relation_count": snapshot.relation_count,
        "nodes": snapshot.nodes,
        "relations": snapshot.relations,
        "prev_snapshot_id": snapshot.prev_snapshot_id,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "published_at": snapshot.published_at.isoformat() if snapshot.published_at else None,
    }


def serialize_evidence(evidence: CourseEvidenceRecord) -> dict[str, Any]:
    """序列化证据"""
    return {
        "evidence_id": evidence.evidence_id,
        "course_id": evidence.course_id,
        "document_id": evidence.document_id,
        "source_file": evidence.source_file,
        "page_number": evidence.page_number,
        "char_start": evidence.char_start,
        "char_end": evidence.char_end,
        "text_snippet": evidence.text_snippet[:200],
        "evidence_type": evidence.evidence_type,
        "content_hash": evidence.content_hash,
        "status": evidence.status.value,
        "stale_reason": evidence.stale_reason,
        "stale_at": evidence.stale_at.isoformat() if evidence.stale_at else None,
        "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
    }
