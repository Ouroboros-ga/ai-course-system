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
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.graph_production_model import (
    CourseEvidenceRecord,
    GraphSnapshotRecord,
    GraphNodeReview,
    SnapshotStatus,
    EvidenceStatus,
)


def graph_target_hash(target: dict[str, Any]) -> str:
    canonical = json.dumps(
        target,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    if not text_snippet.strip():
        raise ValueError("Evidence 原文片段不能为空")
    if page_number is not None and page_number < 1:
        raise ValueError("Evidence 页码必须大于等于 1")
    if (char_start is None) != (char_end is None):
        raise ValueError("Evidence 字符定位必须同时提供起止位置")
    if char_start is not None and (
        char_start < 0 or char_end is None or char_end <= char_start
    ):
        raise ValueError("Evidence 字符定位范围无效")
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
    _validate_snapshot_content(session, course_id, nodes, relations)

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
    max_version = session.exec(
        select(func.max(GraphSnapshotRecord.version)).where(
            GraphSnapshotRecord.course_id == course_id
        )
    ).one()
    version = int(max_version or 0) + 1

    snapshot = GraphSnapshotRecord(
        snapshot_id=str(uuid.uuid4()),
        course_id=course_id,
        nodes=deepcopy(nodes),
        relations=deepcopy(relations),
        version=version,
        prev_snapshot_id=prev_snapshot_id,
        status=SnapshotStatus.PUBLISHED,
        is_active=True,
        label=label or f"v{version}",
        node_count=len(nodes),
        relation_count=len(relations),
        created_by=user_id,
        published_at=datetime.now(timezone.utc),
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
    # 先验证目标，避免失败请求在会话中留下已失活的当前快照。
    target = session.exec(
        select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.snapshot_id == snapshot_id,
            GraphSnapshotRecord.course_id == course_id,
        )
    ).first()
    if not target:
        raise ValueError(f"快照 {snapshot_id} 不存在")
    _validate_snapshot_content(session, course_id, target.nodes, target.relations)
    current = get_active_snapshot(session, course_id)
    if current and current.snapshot_id == target.snapshot_id:
        return current
    if current:
        current.is_active = False
        current.status = SnapshotStatus.ROLLED_BACK
        session.add(current)

    target.is_active = True
    target.status = SnapshotStatus.PUBLISHED
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


def _validate_snapshot_content(
    session: Session,
    course_id: int,
    nodes: list[dict],
    relations: list[dict],
) -> None:
    """Validate graph structure and relation traceability before publication."""
    if not nodes:
        raise ValueError("图谱快照至少需要一个节点")

    node_ids: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("图谱节点必须是对象")
        node_id = str(node.get("id") or node.get("node_id") or "").strip()
        if not node_id:
            raise ValueError("图谱节点缺少稳定 ID")
        node_ids.append(node_id)
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("图谱节点 ID 重复")
    node_id_set = set(node_ids)

    relation_ids: list[str] = []
    referenced_evidence: set[str] = set()
    relation_by_id: dict[str, dict] = {}
    for relation in relations:
        if not isinstance(relation, dict):
            raise ValueError("图谱关系必须是对象")
        relation_id = str(
            relation.get("id") or relation.get("relation_id") or ""
        ).strip()
        source = str(relation.get("source") or relation.get("source_id") or "").strip()
        target = str(relation.get("target") or relation.get("target_id") or "").strip()
        if not relation_id or not source or not target:
            raise ValueError("图谱关系必须包含稳定 ID、source 和 target")
        if source not in node_id_set or target not in node_id_set:
            raise ValueError(f"关系 {relation_id} 指向快照外节点")
        relation_ids.append(relation_id)
        relation_by_id[relation_id] = relation
        evidence_ids = relation.get("evidence_ids") or []
        if not isinstance(evidence_ids, list):
            raise ValueError(f"关系 {relation_id} 的 evidence_ids 必须是数组")
        referenced_evidence.update(str(item) for item in evidence_ids if str(item))
    if len(relation_ids) != len(set(relation_ids)):
        raise ValueError("图谱关系 ID 重复")
    _validate_prerequisite_dag(node_id_set, list(relation_by_id.values()))

    active_evidence_ids = set()
    if referenced_evidence:
        active_evidence_ids = set(session.exec(
            select(CourseEvidenceRecord.evidence_id).where(
                CourseEvidenceRecord.course_id == course_id,
                CourseEvidenceRecord.evidence_id.in_(referenced_evidence),
                CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
            )
        ).all())

    accepted_reviews = {
        (review.target_id, review.target_content_hash)
        for review in session.exec(
            select(GraphNodeReview).where(
                GraphNodeReview.course_id == course_id,
                GraphNodeReview.target_type == "relation",
                GraphNodeReview.decision == "accepted",
            )
        ).all()
    }
    for relation_id, relation in relation_by_id.items():
        evidence_ids = {str(item) for item in (relation.get("evidence_ids") or []) if str(item)}
        if evidence_ids and evidence_ids.issubset(active_evidence_ids):
            continue
        if (relation_id, graph_target_hash(relation)) in accepted_reviews:
            continue
        raise ValueError(
            f"关系 {relation_id} 缺少本课程有效 Evidence 或教师确认记录"
        )


def _validate_prerequisite_dag(
    node_ids: set[str],
    relations: list[dict],
) -> None:
    prerequisite_types = {"prerequisite", "prerequisite_of", "requires"}
    adjacency = {node_id: [] for node_id in node_ids}
    for relation in relations:
        if str(relation.get("type") or "").casefold() not in prerequisite_types:
            continue
        source = str(relation.get("source") or relation.get("source_id"))
        target = str(relation.get("target") or relation.get("target_id"))
        if source == target:
            raise ValueError("先修关系不能形成自环")
        adjacency[source].append(target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("先修关系存在环，不能发布")
        if node_id in visited:
            return
        visiting.add(node_id)
        for target_id in sorted(adjacency[node_id]):
            visit(target_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(node_ids):
        visit(node_id)


def mark_evidence_stale(
    session: Session,
    course_id: int,
    document_id: str,
    reason: str = "courseware_reparse",
    *,
    commit: bool = True,
) -> int:
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
        ev.stale_at = datetime.now(timezone.utc)
        session.add(ev)
    # A document lifecycle operation may need this change to be part of its
    # larger transaction.  The public graph endpoint keeps the default.
    if commit:
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
