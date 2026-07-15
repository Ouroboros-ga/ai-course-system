"""Product 1 V2 knowledge-graph shadow (G3E1).

Triggered from ``document_service.process_document`` AFTER V1 RAG
retrieval succeeds. Runs the V2 P1-05 graph pipeline in shadow:
generates ``EducationalUnit`` / ``GraphNode`` / ``GraphRelation``
candidates from the V1 RAG-extracted knowledge points (offline, no LLM),
writes them to an ISOLATED shadow graph store (an in-memory P1-05
``GraphStore`` serialized to JSON), and optionally ACCEPTS
evidence-backed nodes via ``GraphStore.accept_node`` -- which requires
an ``EvidenceBundle``, enforcing the invariant that every accepted node
traces to evidence.

ADR-0006 §G3E1 HARD CONSTRAINTS:
- Trigger only when ``KNOWLEDGE_GRAPH_PIPELINE_VERSION`` is effectively
  ``v2_shadow`` (conflict-aware: requires ``DOCUMENT_KG_RUNTIME_MODE``
  and ``DOCUMENT_PIPELINE_VERSION`` also effectively v2_shadow).
- Does NOT touch V1 ``KnowledgePoint`` / ``KnowledgeRelation`` tables.
  Shadow writes only to its isolated JSON store; it never calls
  ``KnowledgePointService`` nor ``session.add(KnowledgePoint/...)``.
- Graph failures must NOT break document retrieval. The seam is placed
  AFTER ``rag_processor.process`` (retrieval already done); the shadow
  catches ALL errors (business-level fail-closed, V1 continues).
- Accepted nodes/edges MUST trace to Evidence. ``accept_node`` requires
  an ``EvidenceBundle``; in the default offline document-time scenario
  no evidence is available (``evidence_block_ids`` empty), so all
  candidates stay PROPOSED and the invariant holds (no accepts without
  evidence). The trace records ``accepted_traces_evidence`` as a
  runtime self-check of the invariant.
- No LLM call (``llm_calls`` always 0). Candidates are derived offline
  from V1 RAG knowledge points (``RAGProcessor._extract_knowledge_points``).

G3E scope: contract/integration diff only (NOT a quality comparison).
Real graph quality = G5 canary.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.core.feature_flags import (
    KNOWLEDGE_GRAPH_PIPELINE_VERSION,
    resolve_effective_modes,
    shadow_runtime_fail_closed,
)

logger = logging.getLogger(__name__)

DEFAULT_GRAPH_SHADOW_ROOT = "./p1_shadow_graph"


# ---------------------------------------------------------------------------
# Shadow trigger result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphShadowResult:
    """Outcome of a G3E1 knowledge-graph shadow trigger.

    ``triggered`` is True when a V2 graph candidate trace was written.
    When the flag is disabled, conflict-downgraded, or a runtime error
    occurred, ``triggered`` is False and ``fallback_reason`` explains
    why. V1 is never affected. ``llm_calls`` is always 0.
    """

    triggered: bool
    effective_mode: str
    trace_path: Optional[str] = None
    shadow_run_id: Optional[str] = None
    unit_count: int = 0
    node_count: int = 0
    relation_count: int = 0
    accepted_count: int = 0
    evidence_backed_count: int = 0
    accepted_traces_evidence: bool = True
    fallback_reason: Optional[str] = None
    llm_calls: int = 0
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Shadow trace store (isolated)
# ---------------------------------------------------------------------------


class GraphShadowStore:
    """Writes V2 graph shadow traces to an isolated directory.

    Path-traversal safe, atomic. Does NOT touch V1 tables, V1 RAG
    registry, V1 KnowledgePoint/KnowledgeRelation, or any V1 store.
    """

    def __init__(self, base_dir: str | Path = DEFAULT_GRAPH_SHADOW_ROOT) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, run_id: str) -> Path:
        if not run_id or not all(c in "0123456789abcdef-" for c in run_id):
            raise ValueError(f"unsafe run_id: {run_id!r}")
        return self._base / f"{run_id}.json"

    def write(self, run_id: str, payload: Dict[str, Any]) -> Path:
        path = self._safe_path(run_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def base_dir(self) -> Path:
        return self._base


# ---------------------------------------------------------------------------
# Configured-mode reader
# ---------------------------------------------------------------------------


def _configured_modes() -> Dict[str, str]:
    try:
        from app.core.config import settings
        from app.core.feature_flags import ALL_FLAGS

        return {f: getattr(settings, f) for f in ALL_FLAGS}
    except Exception:
        return {}


def _effective_graph_mode():
    return resolve_effective_modes(_configured_modes())[KNOWLEDGE_GRAPH_PIPELINE_VERSION]


# ---------------------------------------------------------------------------
# V2 candidate construction (offline, from V1 RAG knowledge points)
# ---------------------------------------------------------------------------


def _stable_suffix(*parts: str) -> str:
    raw = ":".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _build_graph_candidates(
    knowledge_points: List[Dict[str, Any]],
    course_id: Optional[Any],
    evidence_block_ids: Optional[Set[str]],
) -> Dict[str, Any]:
    """Build V2 EducationalUnit/GraphNode/GraphRelation candidates.

    Offline: derives P1-05 graph objects from V1 RAG knowledge points.
    No LLM. No real vector model. Structural ``CONTAINS`` relations are
    inferred from the knowledge-point path hierarchy (deterministic, do
    not require evidence). Semantic relations are NOT synthesized (they
    would need evidence).

    Imports P1-05 / P1-03 contracts lazily so a missing contract is a
    runtime fail-closed, not an import error.
    """
    from app.domain.education_graph.enums import (
        EducationalUnitType,
        NodeType,
        RelationType,
    )
    from app.domain.education_graph.models import (
        EducationalUnit,
        GraphNode,
        GraphRelation,
    )
    from app.platform.evidence.contracts import (
        EvidenceBundle,
        EvidenceSpan,
        EvidenceStatus,
    )
    from app.platform.graph.fakes import InMemoryGraphStore

    store = InMemoryGraphStore()
    evidence_block_ids = evidence_block_ids or set()
    course_key = str(course_id) if course_id is not None else "nocourse"
    doc_id = f"doc_shadow_{course_key}"

    # path -> node_id (first occurrence wins; best-effort hierarchy).
    path_to_node: Dict[str, str] = {}
    nodes_meta: List[Dict[str, Any]] = []
    units_meta: List[Dict[str, Any]] = []
    accepted_count = 0
    evidence_backed_count = 0

    for i, kp in enumerate(knowledge_points):
        title = kp.get("title") or f"知识点_{kp.get('id', i)}"
        content = kp.get("content", "") or ""
        path = kp.get("path", "") or title
        level = kp.get("level")

        suffix = _stable_suffix(course_key, i, path)
        unit_id = f"unit_shadow_{suffix}"
        node_id = f"node_shadow_{suffix}"
        block_id = f"blk_shadow_{suffix}"

        # EducationalUnit referencing synthesized DocumentIR block_ids.
        unit = EducationalUnit(
            unit_id=unit_id,
            unit_type=EducationalUnitType.SECTION,
            title=title,
            doc_id=doc_id,
            block_ids=[block_id],
            ordinal=level if isinstance(level, int) else None,
        )
        store.create_unit(unit)
        units_meta.append({
            "unit_id": unit_id,
            "title": title,
            "block_ids": [block_id],
            "unit_type": unit.unit_type.value,
        })

        # GraphNode (PROPOSED by default).
        node = GraphNode(
            node_id=node_id,
            unit_id=unit_id,
            node_type=NodeType.KNOWLEDGE_POINT,
            label=title,
        )
        store.create_node(node)

        # Evidence-backed accept: ONLY when a real evidence block_id is
        # available. accept_node requires an EvidenceBundle, enforcing
        # "accepted -> evidence" at the GraphStore API level.
        if block_id in evidence_block_ids:
            span = EvidenceSpan(
                artifact_id=f"art_shadow_{suffix}",
                document_id=doc_id,
                unit_id=unit_id,
                block_id=block_id,
                text_snippet=content[:200] if content else None,
                status=EvidenceStatus.ACTIVE,
            )
            bundle = EvidenceBundle(
                bundle_id=f"evd_shadow_{suffix}",
                items=[span],
                sources=[doc_id],
            )
            store.accept_node(node_id, bundle, reviewer="g3e1-shadow")
            accepted_count += 1
            evidence_backed_count += 1

        path_to_node.setdefault(path, node_id)
        nodes_meta.append({
            "node_id": node_id,
            "unit_id": unit_id,
            "label": title,
            "node_type": node.node_type.value,
            "status": node.status.value,
            "evidence_ids": list(node.evidence_ids),
            "block_id": block_id,
        })

    # Structural CONTAINS relations from path hierarchy (best-effort).
    relations_meta: List[Dict[str, Any]] = []
    for i, kp in enumerate(knowledge_points):
        path = kp.get("path", "") or (kp.get("title") or f"知识点_{kp.get('id', i)}")
        if "/" not in path:
            continue
        parent_path = path.rsplit("/", 1)[0]
        parent_node_id = path_to_node.get(parent_path)
        child_suffix = _stable_suffix(course_key, i, path)
        child_node_id = f"node_shadow_{child_suffix}"
        if parent_node_id is None or parent_node_id == child_node_id:
            continue
        rel_id = f"rel_shadow_{_stable_suffix(parent_node_id, child_node_id)}"
        relation = GraphRelation(
            relation_id=rel_id,
            source_id=parent_node_id,
            target_id=child_node_id,
            relation_type=RelationType.CONTAINS,  # structural, deterministic
        )
        try:
            store.create_relation(relation)
            relations_meta.append({
                "relation_id": rel_id,
                "source_id": parent_node_id,
                "target_id": child_node_id,
                "relation_type": relation.relation_type.value,
                "directed": relation.directed,
                "status": relation.status.value,
                "evidence_ids": list(relation.evidence_ids),
            })
        except Exception:
            # Duplicate / missing endpoint -> skip this best-effort edge.
            continue

    # Invariant self-check: every ACCEPTED node MUST have evidence_ids.
    accepted_nodes = [n for n in nodes_meta if n["status"] == "accepted"]
    invariant_ok = all(n["evidence_ids"] for n in accepted_nodes)

    return {
        "doc_id": doc_id,
        "course_key": course_key,
        "units": units_meta,
        "nodes": nodes_meta,
        "relations": relations_meta,
        "accepted_count": accepted_count,
        "evidence_backed_count": evidence_backed_count,
        "accepted_traces_evidence": invariant_ok,
    }


# ---------------------------------------------------------------------------
# Public trigger API (called from document_service seam)
# ---------------------------------------------------------------------------


def trigger_graph_shadow(
    knowledge_points: List[Dict[str, Any]],
    course_id: Optional[Any] = None,
    evidence_block_ids: Optional[Set[str]] = None,
    store: Optional[GraphShadowStore] = None,
) -> GraphShadowResult:
    """Trigger a V2 knowledge-graph shadow run after V1 RAG retrieval.

    Called from ``document_service.process_document`` AFTER
    ``rag_processor.process`` returns (retrieval already done). NEVER
    raises into V1: all shadow errors are caught and returned as
    ``fallback_reason`` (business-level fail-closed).

    HARD CONSTRAINT (ADR §G3E1): does NOT touch V1
    KnowledgePoint/KnowledgeRelation. ``llm_calls`` is always 0.

    Parameters
    ----------
    knowledge_points : list of dict
        V1 RAG knowledge points (``RAGProcessor._extract_knowledge_points``
        output: id/title/content/path/level). Read only.
    course_id : Any, optional
        Course scope (document may be course-scoped or not).
    evidence_block_ids : set of str, optional
        Real evidence block_ids. Nodes whose synthesized block_id is in
        this set are ACCEPTED with an EvidenceBundle. Default None ->
        no accepts (all PROPOSED); invariant holds vacuously.
    store : GraphShadowStore, optional
        Inject for tests.
    """
    start = time.time()
    store = store or GraphShadowStore()

    # 1. Flag check (conflict-aware: requires upstream doc/runtime v2_shadow).
    effective = _effective_graph_mode()
    if effective.effective != "v2_shadow":
        return GraphShadowResult(
            triggered=False,
            effective_mode=effective.effective,
            fallback_reason=effective.fallback_reason or "flag_not_v2_shadow",
            duration_ms=(time.time() - start) * 1000,
        )

    run_id = str(uuid.uuid4())
    try:
        v2 = _build_graph_candidates(knowledge_points, course_id, evidence_block_ids)

        # 2. Build the V1-vs-V2 comparison trace (contract/integration diff,
        #    NOT a quality comparison).
        trace = {
            "shadow_run_id": run_id,
            "triggered_at": time.time(),
            "course_id": str(course_id) if course_id is not None else None,
            "effective_mode": "v2_shadow",
            "llm_calls": 0,  # HARD CONSTRAINT: no LLM call
            "v1_knowledge_point_count": len(knowledge_points),
            "v2_units": v2["units"],
            "v2_nodes": v2["nodes"],
            "v2_relations": v2["relations"],
            "v2_accepted_count": v2["accepted_count"],
            "v2_evidence_backed_count": v2["evidence_backed_count"],
            "accepted_traces_evidence": v2["accepted_traces_evidence"],
            "v1_tables_touched": False,  # invariant: never V1 KnowledgePoint/Relation
            "diff": {
                "v1_kp_count": len(knowledge_points),
                "v2_unit_count": len(v2["units"]),
                "v2_node_count": len(v2["nodes"]),
                "v2_relation_count": len(v2["relations"]),
                "v2_accepted_count": v2["accepted_count"],
                "v2_evidence_backed_count": v2["evidence_backed_count"],
                "note": "contract/integration diff (not quality comparison)",
            },
        }
        path = store.write(run_id, trace)

        return GraphShadowResult(
            triggered=True,
            effective_mode="v2_shadow",
            trace_path=str(path),
            shadow_run_id=run_id,
            unit_count=len(v2["units"]),
            node_count=len(v2["nodes"]),
            relation_count=len(v2["relations"]),
            accepted_count=v2["accepted_count"],
            evidence_backed_count=v2["evidence_backed_count"],
            accepted_traces_evidence=v2["accepted_traces_evidence"],
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        # Business-level fail-closed: any shadow error -> V1 continues.
        fc = shadow_runtime_fail_closed(
            KNOWLEDGE_GRAPH_PIPELINE_VERSION, "v2_shadow", f"runtime:{type(e).__name__}:{e}"
        )
        logger.warning(f"[G3E1 graph shadow] runtime error: {e}", exc_info=True)
        return GraphShadowResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )
