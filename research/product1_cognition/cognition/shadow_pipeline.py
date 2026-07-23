"""End-to-end, read-only KG-MEST Shadow orchestration for governed exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .education_graph_release_adapter import adapt_education_graph_release
from .kg_mest import (
    ConceptState,
    GraphEvidenceGrounder,
    InteractionState,
    LearningPathRecommender,
    MultiSourceEvidenceEngine,
    Recommendation,
    ScopeMismatchError,
)
from .learning_event_release_adapter import adapt_learning_event_release


@dataclass(frozen=True)
class ReadOnlyShadowResult:
    status: str
    states: Mapping[str, ConceptState]
    interactions: Mapping[str, InteractionState]
    recommendations: Mapping[str, tuple[Recommendation, ...]]
    unmapped_event_refs: tuple[str, ...]
    error_codes: tuple[str, ...]


def run_read_only_shadow(
    *,
    course_key: str,
    graph_snapshot_id: str,
    graph_nodes: list[Mapping[str, Any]],
    graph_relations: list[Mapping[str, Any]],
    review_decisions: list[Mapping[str, Any]],
    source_student_id: int,
    source_course_id: int,
    student_key: str,
    data_version: str,
    learning_events: list[Mapping[str, Any]],
) -> ReadOnlyShadowResult:
    """Run the research pipeline against read-only, governed exports.

    Any graph or event release rejection returns no partial state or
    recommendation. An otherwise valid scored event whose task has no accepted
    Q-Matrix row is reported as unmapped and creates no evidence.
    """
    graph_release = adapt_education_graph_release(
        course_key=course_key, snapshot_id=graph_snapshot_id, nodes=graph_nodes,
        relations=graph_relations, review_decisions=review_decisions,
    )
    if graph_release.status != "accepted":
        return _rejected(graph_release.error_codes)
    event_release = adapt_learning_event_release(
        source_student_id=source_student_id, source_course_id=source_course_id,
        student_key=student_key, course_key=course_key, data_version=data_version,
        events=learning_events,
    )
    if event_release.status != "accepted":
        return _rejected(event_release.reason_codes)

    graph = graph_release.graph.snapshot
    grounder = GraphEvidenceGrounder(graph)
    grounded_events = []
    unmapped: list[str] = []
    try:
        for event in event_release.events:
            grounded = grounder.ground(event)
            if grounded is None:
                unmapped.append(event.event_id)
            else:
                grounded_events.append(grounded)
    except ScopeMismatchError:
        return _rejected(("SHADOW_EVENT_GRAPH_SCOPE_MISMATCH",))

    engine = MultiSourceEvidenceEngine()
    explicit, interaction = engine.extract(grounded_events)
    concept_ids = sorted({signal.concept_id for signal in explicit} | {signal.concept_id for signal in interaction})
    states = {
        concept_id: engine.build_state(
            student_key=student_key, course_key=course_key, concept_id=concept_id,
            explicit_signals=[signal for signal in explicit if signal.concept_id == concept_id],
            data_version=data_version,
        )
        for concept_id in concept_ids
    }
    interactions = {
        concept_id: engine.build_interaction_state(
            student_key=student_key, course_key=course_key, concept_id=concept_id,
            interaction_signals=[signal for signal in interaction if signal.concept_id == concept_id],
        )
        for concept_id in concept_ids
    }
    recommender = LearningPathRecommender(graph)
    recommendations = {
        concept_id: recommender.recommend(state, states)
        for concept_id, state in sorted(states.items())
    }
    return ReadOnlyShadowResult(
        "ok", states, interactions, recommendations, tuple(sorted(unmapped)), (),
    )


def _rejected(error_codes: tuple[str, ...]) -> ReadOnlyShadowResult:
    return ReadOnlyShadowResult("rejected", {}, {}, {}, (), tuple(sorted(error_codes)))
