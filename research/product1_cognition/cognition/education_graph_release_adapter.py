"""Adapt a governed education-graph export into a KG-MEST course snapshot.

The production-domain graph models use ``GraphNode``, ``GraphRelation`` and
``ReviewDecision``.  This research-side adapter intentionally accepts only
plain exported mappings, so it neither imports ``backend/app`` nor reads a
database.  It validates the release evidence before passing it to the
KG-MEST graph adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from .graph_adapter import GraphAdaptationResult, adapt_cognition_graph


@dataclass(frozen=True)
class EducationGraphReleaseResult:
    status: str
    graph: GraphAdaptationResult | None
    error_codes: tuple[str, ...]


def adapt_education_graph_release(
    *,
    course_key: str,
    snapshot_id: str,
    nodes: list[Mapping[str, Any]],
    relations: list[Mapping[str, Any]],
    review_decisions: list[Mapping[str, Any]],
) -> EducationGraphReleaseResult:
    """Accept a course-scoped, evidence-backed export of domain graph records.

    Required export fields reflect the existing domain contracts:

    * nodes: ``node_id``, ``course_id``, ``status``, ``evidence_ids``;
    * prerequisite and ``TESTS`` relations: ``relation_id``, ``source_id``,
      ``target_id``, ``relation_type``, ``course_id``, ``status``,
      ``evidence_ids``;
    * review decisions: ``decision_id``, ``target_id``, ``target_type``,
      ``decision``, ``evidence_bundle_id``.

    ``PREREQUISITE_OF`` supplies path constraints. ``TESTS`` supplies the
    frozen Q-Matrix (exercise/task -> knowledge component) used to ground
    scored events.  A release is rejected as a whole when either kind lacks a
    valid accepted endpoint, evidence, course scope or review decision. The
    result is still read-only and does not write a snapshot pointer.
    """
    errors: set[str] = set()
    accepted_nodes: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        node_id = node.get("node_id")
        if not node_id:
            errors.add("EDUCATION_GRAPH_NODE_ID_MISSING")
            continue
        if node.get("course_id") != course_key:
            errors.add("EDUCATION_GRAPH_NODE_COURSE_SCOPE_MISMATCH")
            continue
        if _value(node.get("status")) != "accepted":
            errors.add("EDUCATION_GRAPH_PREREQUISITE_NODE_NOT_ACCEPTED")
            continue
        if not _non_empty_sequence(node.get("evidence_ids")):
            errors.add("EDUCATION_GRAPH_PREREQUISITE_NODE_EVIDENCE_MISSING")
            continue
        accepted_nodes[str(node_id)] = node

    accepted_reviews = {
        str(decision.get("target_id")): decision
        for decision in review_decisions
        if decision.get("target_id")
        and str(decision.get("target_type") or "") == "relation"
        and _value(decision.get("decision")) == "accepted"
        and decision.get("decision_id")
        and decision.get("evidence_bundle_id")
    }

    graph_edges: list[dict[str, Any]] = []
    q_matrix: dict[str, set[str]] = {}
    task_discrimination: dict[str, float] = {}
    for relation in relations:
        is_prerequisite = _is_prerequisite_relation(relation.get("relation_type"))
        is_tests = _is_tests_relation(relation.get("relation_type"))
        if not is_prerequisite and not is_tests:
            continue
        prefix = "PREREQUISITE" if is_prerequisite else "Q_MATRIX"
        relation_id = relation.get("relation_id")
        source = relation.get("source_id")
        target = relation.get("target_id")
        if not relation_id or not source or not target:
            errors.add(f"EDUCATION_GRAPH_{prefix}_IDENTITY_MISSING")
            continue
        if relation.get("course_id") != course_key:
            errors.add(f"EDUCATION_GRAPH_{prefix}_COURSE_SCOPE_MISMATCH")
            continue
        if _value(relation.get("status")) != "accepted":
            errors.add(f"EDUCATION_GRAPH_{prefix}_NOT_ACCEPTED")
            continue
        if str(source) not in accepted_nodes or str(target) not in accepted_nodes:
            errors.add(f"EDUCATION_GRAPH_{prefix}_ENDPOINT_NOT_ACCEPTED")
            continue
        evidence_ids = relation.get("evidence_ids")
        if not _non_empty_sequence(evidence_ids):
            errors.add(f"EDUCATION_GRAPH_{prefix}_EVIDENCE_MISSING")
            continue
        review = accepted_reviews.get(str(relation_id))
        if review is None:
            errors.add(f"EDUCATION_GRAPH_{prefix}_REVIEW_MISSING")
            continue
        if is_prerequisite:
            graph_edges.append({
                "subject_node_id": str(source),
                "object_node_id": str(target),
                "predicate": "PREREQUISITE_OF",
                "course_id": course_key,
                "status": "accepted",
                "evidence_refs": tuple(sorted(str(item) for item in evidence_ids)),
                "review_record_id": str(review["decision_id"]),
            })
        else:
            discrimination = _task_discrimination(relation)
            if discrimination is None:
                errors.add("EDUCATION_GRAPH_Q_MATRIX_TASK_DISCRIMINATION_INVALID")
                continue
            q_matrix.setdefault(str(source), set()).add(str(target))
            task_discrimination[str(source)] = discrimination

    if errors:
        return EducationGraphReleaseResult("rejected", None, tuple(sorted(errors)))
    graph = adapt_cognition_graph(
        course_key=course_key,
        graph_version=snapshot_id,
        nodes=[{"node_id": node_id} for node_id in sorted(accepted_nodes)],
        edges=graph_edges,
    )
    if graph.status != "accepted":
        return EducationGraphReleaseResult("rejected", graph, graph.error_codes)
    snapshot = replace(
        graph.snapshot,
        task_q_matrix={task_id: tuple(sorted(concepts)) for task_id, concepts in sorted(q_matrix.items())},
        task_discrimination={task_id: task_discrimination[task_id] for task_id in sorted(task_discrimination)},
    )
    return EducationGraphReleaseResult("accepted", replace(graph, snapshot=snapshot), ())


def _value(value: Any) -> str:
    """Support string enums from the domain export without importing them."""
    return str(getattr(value, "value", value) or "")


def _non_empty_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and bool(value)


def _is_prerequisite_relation(value: Any) -> bool:
    """Bridge domain enum values and the research graph's canonical predicate."""
    return _value(value) in {"prerequisite_of", "PREREQUISITE_OF"}


def _is_tests_relation(value: Any) -> bool:
    return _value(value) in {"tests", "TESTS"}


def _task_discrimination(relation: Mapping[str, Any]) -> float | None:
    raw = relation.get("task_discrimination", relation.get("properties", {}).get("task_discrimination", 0.7))
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if 0.0 <= value <= 1.0 else None
