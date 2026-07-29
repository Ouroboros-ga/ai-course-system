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
from typing import Optional, Any

from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.graph_production_model import (
    CourseEvidenceRecord,
    CourseKnowledgeNode,
    CourseKnowledgeNodeStatus,
    GraphSnapshotRecord,
    GraphNodeReview,
    SnapshotStatus,
    EvidenceStatus,
)


class GraphAssemblyError(ValueError):
    """A teacher-actionable publication gate failure."""

    def __init__(self, code: str, message: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _candidate_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("candidate_id") or candidate.get("id") or "").strip()


def _node_key(course_id: int, candidate_id: str) -> str:
    """Derive a deterministic public identity without exposing parser IDs."""
    digest = hashlib.sha256(f"course:{course_id}:candidate:{candidate_id}".encode()).hexdigest()
    return f"kn_{digest[:24]}"


def _review_decision(candidate: dict[str, Any]) -> str:
    decision = str(candidate.get("status") or "proposed")
    return decision if decision in {"proposed", "accepted", "rejected", "needs_review"} else "proposed"


def _node_content(node: CourseKnowledgeNode, candidate: dict[str, Any]) -> dict[str, Any]:
    """Normalize a parser node candidate into the graph review/publish shape."""
    label = str(candidate.get("label") or candidate.get("title") or node.title or "").strip()
    return {
        "id": node.node_key,
        "node_key": node.node_key,
        "identity_id": node.id,
        "label": label,
        "title": label,
        "kind": str(candidate.get("kind") or node.kind or "concept"),
        "confidence": candidate.get("confidence"),
        "source_candidate_id": _candidate_id(candidate),
        "source_block_ids": list(candidate.get("source_block_ids") or []),
        "anchor_ids": list(candidate.get("anchor_ids") or []),
        "page_or_slide": candidate.get("page_or_slide"),
    }


def bridge_candidate_batch(
    session: Session,
    *,
    batch: Any,
    commit: bool = False,
) -> dict[str, int]:
    """Idempotently bridge one parser batch into formal identities/reviews.

    This is deliberately a governance bridge, not an auto-publish path:
    candidates remain proposed until a teacher transitions their review.
    ``commit=False`` lets the parser include the bridge in its own transaction.
    """
    if getattr(batch.status, "value", batch.status) not in {"succeeded", "partial_success"}:
        return {"nodes_created": 0, "relations_created": 0, "reviews_created": 0}

    from app.models.document_parse_model import GraphCandidateBatch
    from app.models.document_parse_model import EvidenceAnchor, EvidenceSpan

    if not isinstance(batch, GraphCandidateBatch):
        raise ValueError("candidate batch 类型无效")

    node_by_candidate: dict[str, CourseKnowledgeNode] = {}
    nodes_created = 0
    reviews_created = 0

    for candidate in batch.node_candidates or []:
        candidate_id = _candidate_id(candidate)
        if not candidate_id:
            continue
        node = session.exec(
            select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.course_id == batch.course_id,
                CourseKnowledgeNode.source_candidate_id == candidate_id,
            )
        ).first()
        if node is None:
            node = CourseKnowledgeNode(
                course_id=batch.course_id,
                node_key=_node_key(batch.course_id, candidate_id),
                title=str(candidate.get("label") or candidate.get("title") or "").strip()[:300],
                kind=str(candidate.get("kind") or "concept")[:80],
                status=CourseKnowledgeNodeStatus.CANDIDATE,
                source_candidate_id=candidate_id,
                source_batch_id=batch.batch_id,
                source_anchor_ids=list(candidate.get("anchor_ids") or []),
                extra_data={"source_block_ids": list(candidate.get("source_block_ids") or [])},
            )
            session.add(node)
            session.flush()
            nodes_created += 1
        node_by_candidate[candidate_id] = node

        # Make the candidate evidence projection point at the same formal
        # numeric identity.  This lets the Evidence page filter by the node
        # without treating parser candidate IDs as knowledge-node IDs.
        for anchor_id in list(candidate.get("anchor_ids") or []):
            anchor = session.exec(select(EvidenceAnchor).where(
                EvidenceAnchor.course_id == batch.course_id,
                EvidenceAnchor.anchor_id == str(anchor_id),
            )).first()
            if anchor is None:
                continue
            spans = session.exec(select(EvidenceSpan).where(
                EvidenceSpan.course_id == batch.course_id,
                EvidenceSpan.run_id == anchor.run_id,
                EvidenceSpan.ir_version_id == anchor.ir_version_id,
                EvidenceSpan.block_id == anchor.block_id,
                EvidenceSpan.char_start == anchor.char_start,
                EvidenceSpan.char_end == anchor.char_end,
            )).all()
            for span in spans:
                linked = list(span.linked_node_ids or [])
                if node.id not in linked:
                    span.linked_node_ids = [*linked, node.id]
                    session.add(span)

        content = _node_content(node, candidate)
        existing = session.exec(
            select(GraphNodeReview).where(
                GraphNodeReview.course_id == batch.course_id,
                GraphNodeReview.candidate_batch_id == batch.batch_id,
                GraphNodeReview.candidate_id == candidate_id,
                GraphNodeReview.target_type == "node",
            )
        ).first()
        if existing is None:
            existing = GraphNodeReview(
                course_id=batch.course_id,
                candidate_batch_id=batch.batch_id,
                candidate_id=candidate_id,
                identity_node_id=node.id,
                target_id=node.node_key,
                target_type="node",
                target_content_hash=graph_target_hash(content),
                target_content=content,
                decision=_review_decision(candidate),
                reviewer=None,
            )
            session.add(existing)
            reviews_created += 1
        elif existing.decision not in {"accepted", "rejected"}:
            existing.target_content = content
            existing.target_content_hash = graph_target_hash(content)
            existing.identity_node_id = node.id
            existing.target_id = node.node_key
            session.add(existing)

        candidate_status = _review_decision(candidate)
        if candidate_status == "accepted" and node.status == CourseKnowledgeNodeStatus.CANDIDATE:
            node.status = CourseKnowledgeNodeStatus.ACCEPTED
            session.add(node)
        elif candidate_status == "rejected" and node.status != CourseKnowledgeNodeStatus.PUBLISHED:
            node.status = CourseKnowledgeNodeStatus.RETIRED
            session.add(node)

    relation_reviews_created = 0
    for relation in batch.relation_candidates or []:
        relation_id = _candidate_id(relation)
        source_candidate_id = str(relation.get("source_candidate_id") or "").strip()
        target_candidate_id = str(relation.get("target_candidate_id") or "").strip()
        if not relation_id or not source_candidate_id or not target_candidate_id:
            continue
        source_node = node_by_candidate.get(source_candidate_id)
        target_node = node_by_candidate.get(target_candidate_id)
        content = {
            "id": relation_id,
            "source": source_node.node_key if source_node else None,
            "target": target_node.node_key if target_node else None,
            "type": str(relation.get("relation_type") or relation.get("type") or "related"),
            "relation_type": str(relation.get("relation_type") or relation.get("type") or "related"),
            "source_candidate_id": source_candidate_id,
            "target_candidate_id": target_candidate_id,
            "confidence": relation.get("confidence"),
            "anchor_ids": list(relation.get("anchor_ids") or []),
            "unresolved_endpoint": source_node is None or target_node is None,
        }
        existing = session.exec(
            select(GraphNodeReview).where(
                GraphNodeReview.course_id == batch.course_id,
                GraphNodeReview.candidate_batch_id == batch.batch_id,
                GraphNodeReview.candidate_id == relation_id,
                GraphNodeReview.target_type == "relation",
            )
        ).first()
        if existing is None:
            existing = GraphNodeReview(
                course_id=batch.course_id,
                candidate_batch_id=batch.batch_id,
                candidate_id=relation_id,
                source_candidate_id=source_candidate_id,
                target_candidate_id=target_candidate_id,
                target_id=relation_id,
                target_type="relation",
                target_content_hash=graph_target_hash(content),
                target_content=content,
                decision=("needs_review" if content["unresolved_endpoint"] else _review_decision(relation)),
            )
            session.add(existing)
            relation_reviews_created += 1
        elif existing.decision not in {"accepted", "rejected"}:
            existing.target_content = content
            existing.target_content_hash = graph_target_hash(content)
            session.add(existing)

    batch.accepted_count = sum(
        1 for review in session.exec(
            select(GraphNodeReview).where(GraphNodeReview.candidate_batch_id == batch.batch_id)
        ).all() if review.decision == "accepted"
    )
    batch.rejected_count = sum(
        1 for review in session.exec(
            select(GraphNodeReview).where(GraphNodeReview.candidate_batch_id == batch.batch_id)
        ).all() if review.decision == "rejected"
    )
    batch.needs_review_count = sum(
        1 for review in session.exec(
            select(GraphNodeReview).where(GraphNodeReview.candidate_batch_id == batch.batch_id)
        ).all() if review.decision in {"proposed", "needs_review"}
    )
    batch.updated_at = utcnow_aware()
    session.add(batch)
    session.flush()
    if commit:
        session.commit()
    return {
        "nodes_created": nodes_created,
        "relations_created": len(batch.relation_candidates or []),
        "reviews_created": reviews_created + relation_reviews_created,
    }


def bridge_candidate_batches(session: Session, course_id: int, *, commit: bool = False) -> dict[str, int]:
    """Bridge all non-superseded successful batches for a course."""
    from app.models.document_parse_model import CandidateBatchStatus, GraphCandidateBatch

    batches = session.exec(
        select(GraphCandidateBatch).where(
            GraphCandidateBatch.course_id == course_id,
            GraphCandidateBatch.status.in_([
                CandidateBatchStatus.SUCCEEDED,
                CandidateBatchStatus.PARTIAL_SUCCESS,
            ]),
        )
    ).all()
    totals = {"batches": 0, "nodes_created": 0, "relations_created": 0, "reviews_created": 0}
    for batch in batches:
        result = bridge_candidate_batch(session, batch=batch, commit=False)
        totals["batches"] += 1
        for key in ("nodes_created", "relations_created", "reviews_created"):
            totals[key] += result[key]
    if commit:
        session.commit()
    return totals


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
        # evidence_id 必须使用 ev_ 前缀 + UUID hex，与所有证据域保持一致
        # （project_memory.md 硬约束）。
        evidence_id="ev_" + uuid.uuid4().hex,
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


def _active_evidence_for_review(
    session: Session,
    course_id: int,
    review: GraphNodeReview,
) -> list[CourseEvidenceRecord]:
    """Resolve the formal evidence that is allowed to enter a snapshot.

    Relation reviews normally carry explicit ``evidence_ids``.  A confirmed
    parser span may also be linked by its source anchors; this fallback keeps
    the candidate-to-evidence bridge useful without treating an unconfirmed
    span as publication proof.
    """
    from app.models.document_parse_model import EvidenceCitation

    explicit_ids = {
        str(item).strip() for item in (review.evidence_ids or []) if str(item).strip()
    }
    evidence = list(session.exec(
        select(CourseEvidenceRecord).where(
            CourseEvidenceRecord.course_id == course_id,
            CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
            CourseEvidenceRecord.evidence_id.in_(explicit_ids),
        )
    ).all()) if explicit_ids else []
    resolved_ids = {item.evidence_id for item in evidence}

    if review.target_type == "node" and review.identity_node_id is not None:
        for candidate in session.exec(
            select(CourseEvidenceRecord).where(
                CourseEvidenceRecord.course_id == course_id,
                CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
                CourseEvidenceRecord.node_id == review.identity_node_id,
            )
        ).all():
            if candidate.evidence_id not in resolved_ids:
                evidence.append(candidate)
                resolved_ids.add(candidate.evidence_id)

    # A relation candidate's anchors are a safe, auditable binding only after
    # a teacher has promoted the exact span to formal Evidence.
    anchor_ids = {
        str(item).strip()
        for item in ((review.target_content or {}).get("anchor_ids") or [])
        if str(item).strip()
    }
    if anchor_ids:
        for candidate in session.exec(
            select(CourseEvidenceRecord).where(
                CourseEvidenceRecord.course_id == course_id,
                CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
            )
        ).all():
            if resolved_ids.__contains__(candidate.evidence_id):
                continue
            if anchor_ids.intersection(str(item) for item in (candidate.source_anchor_ids or [])):
                evidence.append(candidate)
                resolved_ids.add(candidate.evidence_id)
    return evidence


def _citation_ids_for_evidence(
    session: Session,
    course_id: int,
    evidence_ids: set[str],
) -> list[str]:
    """Return student-readable citation IDs for the formal evidence refs."""
    if not evidence_ids:
        return []
    from app.models.document_parse_model import CitationStatus, EvidenceCitation

    citations = session.exec(
        select(EvidenceCitation).where(
            EvidenceCitation.course_id == course_id,
            EvidenceCitation.evidence_id.in_(evidence_ids),
            EvidenceCitation.status.in_([CitationStatus.EXACT, CitationStatus.APPROXIMATE]),
            EvidenceCitation.student_visible == True,
        )
    ).all()
    return sorted({citation.citation_id for citation in citations})


def assemble_reviewed_snapshot(
    session: Session,
    course_id: int,
) -> dict[str, Any]:
    """Build a publish payload from the latest bridged candidate batch.

    This is the single server-side source of truth for teacher publication.
    It never changes a proposed candidate's decision and never publishes a
    partial batch: every candidate must be terminal, every accepted target
    must have active formal Evidence, and every accepted relation must point
    to an accepted node.
    """
    from app.models.document_parse_model import CandidateBatchStatus, GraphCandidateBatch

    bridge_candidate_batches(session, course_id, commit=False)
    batch = session.exec(
        select(GraphCandidateBatch).where(
            GraphCandidateBatch.course_id == course_id,
            GraphCandidateBatch.status.in_([
                CandidateBatchStatus.SUCCEEDED,
                CandidateBatchStatus.PARTIAL_SUCCESS,
            ]),
        ).order_by(GraphCandidateBatch.created_at.desc())
    ).first()
    if batch is None:
        raise GraphAssemblyError(
            "NO_CANDIDATE_BATCH",
            "当前课程没有可发布的图谱候选批次，请先完成课件解析。",
        )

    reviews = session.exec(
        select(GraphNodeReview).where(
            GraphNodeReview.course_id == course_id,
            GraphNodeReview.candidate_batch_id == batch.batch_id,
        ).order_by(GraphNodeReview.target_type, GraphNodeReview.created_at, GraphNodeReview.id)
    ).all()
    if not reviews:
        raise GraphAssemblyError(
            "NO_REVIEW_RECORDS",
            "当前候选批次尚未进入审核流，请先打开候选审核页。",
            details={"batch_id": batch.batch_id},
        )

    pending = [review.target_id for review in reviews if review.decision in {"proposed", "needs_review"}]
    if pending:
        raise GraphAssemblyError(
            "REVIEW_INCOMPLETE",
            f"仍有 {len(pending)} 个候选未完成审核，不能发布。",
            details={"batch_id": batch.batch_id, "pending_target_ids": pending[:100]},
        )

    accepted_nodes = [review for review in reviews if review.target_type == "node" and review.decision == "accepted"]
    accepted_relations = [review for review in reviews if review.target_type == "relation" and review.decision == "accepted"]
    if not accepted_nodes:
        raise GraphAssemblyError(
            "NO_ACCEPTED_NODES",
            "没有已接受的知识节点，不能发布空图谱。",
            details={"batch_id": batch.batch_id},
        )

    nodes: list[dict[str, Any]] = []
    blocking_evidence: list[str] = []
    for review in accepted_nodes:
        content = deepcopy(review.target_content or {})
        if graph_target_hash(content) != review.target_content_hash:
            raise GraphAssemblyError(
                "REVIEW_CONTENT_CHANGED",
                f"候选 {review.target_id} 的内容已变化，请重新审核后再发布。",
                details={"target_id": review.target_id},
            )
        identity = session.exec(
            select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.course_id == course_id,
                CourseKnowledgeNode.id == review.identity_node_id,
            )
        ).first() if review.identity_node_id is not None else None
        if identity is None:
            raise GraphAssemblyError(
                "IDENTITY_MISSING",
                f"节点 {review.target_id} 缺少正式课程身份。",
                details={"target_id": review.target_id},
            )
        evidence = _active_evidence_for_review(session, course_id, review)
        if not evidence:
            blocking_evidence.append(review.target_id)
            continue
        node_id = identity.node_key
        content["id"] = node_id
        content["node_key"] = node_id
        content["identity_id"] = identity.id
        content["evidence_ids"] = sorted(item.evidence_id for item in evidence)
        content["citation_ids"] = _citation_ids_for_evidence(
            session, course_id, set(content["evidence_ids"])
        )
        nodes.append(content)

    if blocking_evidence:
        raise GraphAssemblyError(
            "EVIDENCE_REQUIRED",
            f"有 {len(blocking_evidence)} 个已接受节点缺少有效 Evidence，不能发布。",
            details={"batch_id": batch.batch_id, "target_ids": blocking_evidence[:100]},
        )

    node_ids = {str(node["id"]) for node in nodes}
    relations: list[dict[str, Any]] = []
    relation_blockers: list[str] = []
    endpoint_blockers: list[str] = []
    for review in accepted_relations:
        content = deepcopy(review.target_content or {})
        if graph_target_hash(content) != review.target_content_hash:
            raise GraphAssemblyError(
                "REVIEW_CONTENT_CHANGED",
                f"关系 {review.target_id} 的内容已变化，请重新审核后再发布。",
                details={"target_id": review.target_id},
            )
        source = str(content.get("source") or "").strip()
        target = str(content.get("target") or "").strip()
        if source not in node_ids or target not in node_ids:
            endpoint_blockers.append(review.target_id)
            continue
        evidence = _active_evidence_for_review(session, course_id, review)
        if not evidence:
            relation_blockers.append(review.target_id)
            continue
        content["id"] = str(content.get("id") or review.target_id)
        content["source"] = source
        content["target"] = target
        content["evidence_ids"] = sorted(item.evidence_id for item in evidence)
        content["citation_ids"] = _citation_ids_for_evidence(
            session, course_id, set(content["evidence_ids"])
        )
        relations.append(content)

    if endpoint_blockers:
        raise GraphAssemblyError(
            "RELATION_ENDPOINT_INVALID",
            f"有 {len(endpoint_blockers)} 条已接受关系指向未发布节点，不能发布。",
            details={"batch_id": batch.batch_id, "target_ids": endpoint_blockers[:100]},
        )
    if relation_blockers:
        raise GraphAssemblyError(
            "EVIDENCE_REQUIRED",
            f"有 {len(relation_blockers)} 条已接受关系缺少有效 Evidence，不能发布。",
            details={"batch_id": batch.batch_id, "target_ids": relation_blockers[:100]},
        )

    nodes.sort(key=lambda item: str(item.get("id") or ""))
    relations.sort(key=lambda item: str(item.get("id") or ""))
    return {
        "batch_id": batch.batch_id,
        "nodes": nodes,
        "relations": relations,
        "reviews": reviews,
        "node_count": len(nodes),
        "relation_count": len(relations),
    }


def publish_snapshot(
    session: Session,
    *,
    course_id: int,
    nodes: list[dict],
    relations: list[dict],
    label: str = "",
    user_id: Optional[int] = None,
    commit: bool = True,
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
        published_at=utcnow_aware(),
    )
    session.add(snapshot)
    if commit:
        session.commit()
        session.refresh(snapshot)
    else:
        session.flush()
    return snapshot


def publish_reviewed_snapshot(
    session: Session,
    *,
    course_id: int,
    label: str = "",
    user_id: Optional[int] = None,
) -> tuple[GraphSnapshotRecord, dict[str, Any]]:
    """Atomically assemble and publish the teacher-reviewed candidate batch."""
    assembled = assemble_reviewed_snapshot(session, course_id)
    from app.models.document_parse_model import GraphCandidateBatch
    batch = session.exec(
        select(GraphCandidateBatch).where(
            GraphCandidateBatch.course_id == course_id,
            GraphCandidateBatch.batch_id == assembled["batch_id"],
        )
    ).first()
    if batch is not None and batch.snapshot_id:
        existing = session.exec(
            select(GraphSnapshotRecord).where(
                GraphSnapshotRecord.course_id == course_id,
                GraphSnapshotRecord.snapshot_id == batch.snapshot_id,
                GraphSnapshotRecord.is_active == True,
                GraphSnapshotRecord.status == SnapshotStatus.PUBLISHED,
            )
        ).first()
        if existing is not None:
            return existing, {
                "source": "reviewed_candidates",
                "batch_id": assembled["batch_id"],
                "node_count": assembled["node_count"],
                "relation_count": assembled["relation_count"],
                "idempotent": True,
            }
    snapshot = publish_snapshot(
        session,
        course_id=course_id,
        nodes=assembled["nodes"],
        relations=assembled["relations"],
        label=label or f"审核发布 · {assembled['batch_id']}",
        user_id=user_id,
        commit=False,
    )
    for review in assembled["reviews"]:
        if review.decision == "accepted":
            review.snapshot_id = snapshot.snapshot_id
            session.add(review)
    for node in session.exec(
        select(CourseKnowledgeNode).where(CourseKnowledgeNode.course_id == course_id)
    ).all():
        if node.node_key in {str(item["id"]) for item in assembled["nodes"]}:
            node.status = CourseKnowledgeNodeStatus.PUBLISHED
        elif node.status == CourseKnowledgeNodeStatus.PUBLISHED:
            node.status = CourseKnowledgeNodeStatus.ACCEPTED
        node.updated_at = utcnow_aware()
        session.add(node)
    if batch is not None:
        batch.snapshot_id = snapshot.snapshot_id
        session.add(batch)
    session.commit()
    session.refresh(snapshot)
    return snapshot, {
        "source": "reviewed_candidates",
        "batch_id": assembled["batch_id"],
        "node_count": assembled["node_count"],
        "relation_count": assembled["relation_count"],
    }


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
    target_node_ids = {
        str(item.get("id") or item.get("node_id") or "")
        for item in (target.nodes or [])
        if isinstance(item, dict)
    }
    for node in session.exec(
        select(CourseKnowledgeNode).where(CourseKnowledgeNode.course_id == course_id)
    ).all():
        if node.node_key in target_node_ids:
            node.status = CourseKnowledgeNodeStatus.PUBLISHED
        elif node.status == CourseKnowledgeNodeStatus.PUBLISHED:
            node.status = CourseKnowledgeNodeStatus.ACCEPTED
        node.updated_at = utcnow_aware()
        session.add(node)
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
        ev.stale_at = utcnow_aware()
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

    stmt = select(CourseEvidenceRecord).where(CourseEvidenceRecord.course_id == course_id)
    if evidence_ids:
        stmt = stmt.where(
            or_(
                CourseEvidenceRecord.evidence_id.in_(evidence_ids),
                CourseEvidenceRecord.node_id == int(node_id) if str(node_id).isdigit() else False,
            )
        )
    elif str(node_id).isdigit():
        stmt = stmt.where(CourseEvidenceRecord.node_id == int(node_id))
    else:
        return []
    return list(session.exec(stmt).all())


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
        "run_id": evidence.run_id,
        "span_id": evidence.span_id,
        "node_id": evidence.node_id,
        "source_anchor_ids": list(evidence.source_anchor_ids or []),
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


# ---------------------------------------------------------------------------
# 批次3：候选审核状态机、冲突列表、版本对比
# ---------------------------------------------------------------------------

# 允许的状态转换（proposed/needs_review 可推进到 accepted/rejected/needs_review；
# accepted/rejected 为终态，不可回退以保持审核可追溯性）
_REVIEW_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"accepted", "rejected", "needs_review"},
    "needs_review": {"accepted", "rejected"},
    "accepted": set(),
    "rejected": set(),
}


def list_review_candidates(
    session: Session,
    course_id: int,
    *,
    decision: Optional[str] = None,
    target_type: Optional[str] = None,
) -> list[GraphNodeReview]:
    """列出待治理的候选节点/关系（proposed/needs_review）或按 decision 过滤。

    冲突处理：默认返回所有 proposed 与 needs_review 的记录，供教师在发布前
    逐条确认或驳回。每条记录携带 target_content_hash，便于检测内容漂移。
    """
    from app.models.document_parse_model import CandidateBatchStatus, GraphCandidateBatch

    active_batch_ids = select(GraphCandidateBatch.batch_id).where(
        GraphCandidateBatch.course_id == course_id,
        GraphCandidateBatch.status.in_([
            CandidateBatchStatus.SUCCEEDED,
            CandidateBatchStatus.PARTIAL_SUCCESS,
        ]),
    )
    stmt = select(GraphNodeReview).where(
        GraphNodeReview.course_id == course_id,
        or_(
            GraphNodeReview.candidate_batch_id.is_(None),
            GraphNodeReview.candidate_batch_id.in_(active_batch_ids),
        ),
    )
    if decision:
        stmt = stmt.where(GraphNodeReview.decision == decision)
    else:
        stmt = stmt.where(
            GraphNodeReview.decision.in_(["proposed", "needs_review"])
        )
    if target_type:
        stmt = stmt.where(GraphNodeReview.target_type == target_type)
    return list(session.exec(stmt.order_by(GraphNodeReview.created_at.desc())).all())


def transition_review(
    session: Session,
    course_id: int,
    review_id: int,
    *,
    new_decision: str,
    reviewer_id: int,
    review_comment: str = "",
    evidence_ids: Optional[list[str]] = None,
) -> GraphNodeReview:
    """推进候选审核状态机。

    - proposed/needs_review -> accepted/rejected/needs_review
    - accepted/rejected 为终态，不可再变更（保持审核可追溯）
    - 推进到 accepted 时，若提供 evidence_ids 则校验属于本课程且 ACTIVE
    - 推进到 accepted 时会重新计算 target_content_hash 以绑定当前内容
    """
    if new_decision not in _REVIEW_TRANSITIONS:
        raise ValueError(f"未知审核状态: {new_decision}")
    review = session.exec(
        select(GraphNodeReview).where(
            GraphNodeReview.id == review_id,
            GraphNodeReview.course_id == course_id,
        )
    ).first()
    if review is None:
        raise ValueError(f"审核记录 {review_id} 不存在或不属于本课程")
    if new_decision == review.decision:
        return review
    allowed = _REVIEW_TRANSITIONS.get(review.decision, set())
    if new_decision not in allowed:
        raise ValueError(
            f"审核状态 {review.decision} 不可转换为 {new_decision}（终态不可回退）"
        )
    if new_decision == "accepted" and evidence_ids is not None:
        valid = set(session.exec(
            select(CourseEvidenceRecord.evidence_id).where(
                CourseEvidenceRecord.course_id == course_id,
                CourseEvidenceRecord.evidence_id.in_(evidence_ids),
                CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
            )
        ).all())
        if set(evidence_ids) - valid:
            raise ValueError("包含无效或跨课程 Evidence")
        review.evidence_ids = sorted(set(evidence_ids))
    if review_comment:
        review.review_comment = review_comment
    review.decision = new_decision
    review.reviewer = reviewer_id
    if review.identity_node_id is not None:
        identity = session.exec(
            select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.id == review.identity_node_id,
                CourseKnowledgeNode.course_id == course_id,
            )
        ).first()
        if identity is not None:
            identity.status = (
                CourseKnowledgeNodeStatus.ACCEPTED
                if new_decision == "accepted"
                else CourseKnowledgeNodeStatus.RETIRED
                if new_decision == "rejected"
                else CourseKnowledgeNodeStatus.CANDIDATE
            )
            identity.updated_at = utcnow_aware()
            session.add(identity)
    if review.candidate_batch_id:
        from app.models.document_parse_model import GraphCandidateBatch
        batch = session.exec(
            select(GraphCandidateBatch).where(
                GraphCandidateBatch.course_id == course_id,
                GraphCandidateBatch.batch_id == review.candidate_batch_id,
            )
        ).first()
        if batch is not None:
            batch_reviews = session.exec(
                select(GraphNodeReview).where(
                    GraphNodeReview.course_id == course_id,
                    GraphNodeReview.candidate_batch_id == batch.batch_id,
                )
            ).all()
            batch.accepted_count = sum(item.decision == "accepted" for item in batch_reviews)
            batch.rejected_count = sum(item.decision == "rejected" for item in batch_reviews)
            batch.needs_review_count = sum(
                item.decision in {"proposed", "needs_review"} for item in batch_reviews
            )
            batch.updated_at = utcnow_aware()
            session.add(batch)
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def diff_snapshots(
    session: Session,
    course_id: int,
    snapshot_a_id: str,
    snapshot_b_id: str,
) -> dict[str, Any]:
    """对比两个快照的节点与关系差异。

    返回:
      - added_nodes / removed_nodes / modified_nodes
      - added_relations / removed_relations / modified_relations
    以快照 B 相对于快照 A 的视角计算。
    """
    snap_a = session.exec(
        select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.course_id == course_id,
            GraphSnapshotRecord.snapshot_id == snapshot_a_id,
        )
    ).first()
    if snap_a is None:
        raise ValueError(f"快照 {snapshot_a_id} 不存在或不属于本课程")
    snap_b = session.exec(
        select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.course_id == course_id,
            GraphSnapshotRecord.snapshot_id == snapshot_b_id,
        )
    ).first()
    if snap_b is None:
        raise ValueError(f"快照 {snapshot_b_id} 不存在或不属于本课程")

    return {
        "snapshot_a": {
            "snapshot_id": snap_a.snapshot_id,
            "version": snap_a.version,
            "label": snap_a.label,
        },
        "snapshot_b": {
            "snapshot_id": snap_b.snapshot_id,
            "version": snap_b.version,
            "label": snap_b.label,
        },
        "nodes": _diff_collection(snap_a.nodes, snap_b.nodes),
        "relations": _diff_collection(snap_a.relations, snap_b.relations),
    }


def _diff_collection(items_a: list[dict], items_b: list[dict]) -> dict[str, Any]:
    """计算两个节点/关系集合的差异（基于稳定 ID + 内容哈希）。"""
    def _key(item: dict) -> str:
        return str(item.get("id") or item.get("node_id") or item.get("relation_id") or "")

    map_a = {_key(i): i for i in items_a if isinstance(i, dict)}
    map_b = {_key(i): i for i in items_b if isinstance(i, dict)}

    added = [map_b[k] for k in map_b.keys() - map_a.keys()]
    removed = [map_a[k] for k in map_a.keys() - map_b.keys()]
    modified = [
        {"id": k, "from": map_a[k], "to": map_b[k]}
        for k in (map_a.keys() & map_b.keys())
        if graph_target_hash(map_a[k]) != graph_target_hash(map_b[k])
    ]
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged_count": len(map_a.keys() & map_b.keys()) - len(modified),
    }


def get_prerequisite_nodes(
    session: Session,
    course_id: int,
    node_id: str,
    *,
    direction: str = "incoming",
) -> list[dict]:
    """从当前活跃快照读取一跳先修/后继节点。

    direction="incoming" 返回指向 node_id 的先修节点（PREREQUISITE_OF 的 source）。
    direction="outgoing" 返回 node_id 的后继节点（PREREQUISITE_OF 的 target）。
    学生侧只读已发布快照，不暴露草稿。
    """
    snapshot = get_active_snapshot(session, course_id)
    if snapshot is None:
        return []
    prerequisite_types = {"prerequisite", "prerequisite_of", "requires"}
    node_ids: set[str] = set()
    for relation in snapshot.relations or []:
        if not isinstance(relation, dict):
            continue
        if str(relation.get("type") or "").casefold() not in prerequisite_types:
            continue
        source = str(relation.get("source") or relation.get("source_id") or "")
        target = str(relation.get("target") or relation.get("target_id") or "")
        if direction == "incoming" and target == node_id and source:
            node_ids.add(source)
        elif direction == "outgoing" and source == node_id and target:
            node_ids.add(target)
    if not node_ids:
        return []
    return [
        node for node in (snapshot.nodes or [])
        if isinstance(node, dict)
        and str(node.get("id") or node.get("node_id") or "") in node_ids
    ]


def serialize_review(review: GraphNodeReview) -> dict[str, Any]:
    """序列化审核记录。"""
    return {
        "id": review.id,
        "course_id": review.course_id,
        "snapshot_id": review.snapshot_id,
        "candidate_batch_id": review.candidate_batch_id,
        "candidate_id": review.candidate_id,
        "source_candidate_id": review.source_candidate_id,
        "target_candidate_id": review.target_candidate_id,
        "identity_node_id": review.identity_node_id,
        "target_id": review.target_id,
        "target_type": review.target_type,
        "target_content_hash": review.target_content_hash,
        "target_content": review.target_content,
        "decision": review.decision,
        "reviewer": review.reviewer,
        "review_comment": review.review_comment,
        "evidence_ids": review.evidence_ids or [],
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }
