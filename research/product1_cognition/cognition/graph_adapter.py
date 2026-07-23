"""Validate an accepted cognition graph before using it for path recommendation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .kg_mest import GraphSnapshot


@dataclass(frozen=True)
class GraphAdaptationResult:
    status: str
    snapshot: GraphSnapshot | None
    error_codes: tuple[str, ...]


def adapt_cognition_graph(*, course_key: str, graph_version: str, nodes: list[Mapping[str, Any]],
                          edges: list[Mapping[str, Any]]) -> GraphAdaptationResult:
    """Accept only a course-isolated, evidence-backed prerequisite graph.

    Retrieval/structural edges remain useful for citations but are not silently
    reinterpreted as pedagogical prerequisites.
    """
    node_ids = {str(node.get("node_id")) for node in nodes if node.get("node_id")}
    errors: set[str] = set()
    prerequisites: dict[str, set[str]] = {}
    for edge in edges:
        if edge.get("status") != "accepted":
            continue
        predicate = str(edge.get("predicate") or edge.get("relation") or "")
        if predicate != "PREREQUISITE_OF":
            continue
        evidence_refs = edge.get("evidence_refs")
        has_evidence = isinstance(evidence_refs, (list, tuple)) and bool(evidence_refs)
        if not has_evidence or not edge.get("review_record_id"):
            errors.add("PREREQUISITE_ACCEPTANCE_METADATA_MISSING")
            continue
        source = str(edge.get("subject_node_id") or edge.get("source") or "")
        target = str(edge.get("object_node_id") or edge.get("target") or "")
        if not source or not target or source not in node_ids or target not in node_ids:
            errors.add("DANGLING_PREREQUISITE_EDGE")
            continue
        if edge.get("course_id") != course_key:
            errors.add("PREREQUISITE_EDGE_COURSE_SCOPE_MISSING_OR_MISMATCH")
            continue
        prerequisites.setdefault(target, set()).add(source)
    if not prerequisites:
        errors.add("PREREQUISITE_RELATIONS_UNAVAILABLE")
    if _contains_cycle(prerequisites):
        errors.add("PREREQUISITE_CYCLE_REJECTED")
    if errors:
        return GraphAdaptationResult("rejected", None, tuple(sorted(errors)))
    return GraphAdaptationResult(
        "accepted",
        GraphSnapshot(
            course_key=course_key,
            graph_version=graph_version,
            prerequisites={target: tuple(sorted(sources)) for target, sources in sorted(prerequisites.items())},
        ),
        (),
    )


def _contains_cycle(prerequisites: Mapping[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        cyclic = any(visit(parent) for parent in prerequisites.get(node, set()))
        visiting.remove(node)
        visited.add(node)
        return cyclic

    return any(visit(node) for node in prerequisites)
