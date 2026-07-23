"""Contract-focused ablation for the versioned KG-MEST fixture.

This is deliberately not an accuracy benchmark.  The fixture has no real
student labels, so the only honest claims are about reproducibility and
contract violations under counterfactual designs.
"""

from __future__ import annotations

from dataclasses import replace
from json import loads
from pathlib import Path
from typing import Any

from cognition.kg_mest import (
    AssessmentEvidenceExtractor,
    BetaCell,
    CodeEvidenceExtractor,
    Dimension,
    GraphEvidenceGrounder,
    GraphSnapshot,
    LearningEvent,
    LearningPathRecommender,
    MeasurementRole,
    MultiSourceEvidenceEngine,
    HALF_LIFE_DAYS,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "kg_mest_course_v1.json"
TARGET = "binary-search-boundary"
PREREQUISITE = "loop-invariant"


def _fixture() -> tuple[dict[str, Any], GraphSnapshot, list[LearningEvent]]:
    raw = loads(FIXTURE.read_text(encoding="utf-8"))
    graph = GraphSnapshot(course_key=raw["course_key"], **raw["graph"])
    events = []
    for item in raw["events"]:
        item = dict(item)
        item["measurement_role"] = MeasurementRole(item["measurement_role"])
        events.append(LearningEvent(**item))
    return raw, graph, events


def _ground(events: list[LearningEvent], graph: GraphSnapshot) -> list[LearningEvent]:
    grounder = GraphEvidenceGrounder(graph)
    return [grounded for event in events if (grounded := grounder.ground(event)) is not None]


def _state(engine: MultiSourceEvidenceEngine, events: list[LearningEvent], course_key: str, concept_id: str):
    signals, _ = engine.extract(events)
    return engine.build_state(
        student_key="student-synthetic-01",
        course_key=course_key,
        concept_id=concept_id,
        explicit_signals=[signal for signal in signals if signal.concept_id == concept_id],
        data_version="synthetic-course-v1",
    )


def _raw_no_dedupe_score(events: list[LearningEvent]) -> tuple[float | None, int]:
    assessment, code = AssessmentEvidenceExtractor(), CodeEvidenceExtractor()
    signals = []
    for event in events:
        signals.extend(code.extract(event) if event.event_type == "code_submission" else assessment.extract(event))
    mastery = sorted((signal for signal in signals if signal.concept_id == TARGET and signal.dimension == Dimension.MASTERY),
                     key=lambda signal: (signal.sequence_number, signal.evidence_id))
    if not mastery:
        return None, 0
    cell = BetaCell()
    for signal in mastery:
        cell = cell.update(signal, HALF_LIFE_DAYS[Dimension.MASTERY])
    return round(cell.mean, 4), len(mastery)


def run() -> dict[str, Any]:
    raw, graph, events = _fixture()
    engine = MultiSourceEvidenceEngine()
    grounded = _ground(events, graph)
    baseline = _state(engine, grounded, raw["course_key"], TARGET)
    prerequisite = _state(engine, grounded, raw["course_key"], PREREQUISITE)
    recommendation = LearningPathRecommender(graph).recommend(baseline, {PREREQUISITE: prerequisite})[0]

    no_q_graph = replace(graph, task_q_matrix={}, task_discrimination={})
    no_q_target = _state(engine, _ground(events, no_q_graph), raw["course_key"], TARGET)
    no_q_recommendation = LearningPathRecommender(no_q_graph).recommend(no_q_target, {})[0]

    _, interaction = engine.extract(grounded)
    interaction_count = sum(item.concept_id == TARGET for item in interaction)
    # This intentionally invalid counterfactual represents the legacy mistake:
    # treating dialogue label volume as positive performance evidence.
    invalid_interaction_leakage_score = round(min(1.0, (baseline.observed_performance_score or 0.0) + 0.1 * interaction_count), 4)

    migrated = next(event for event in grounded if event.event_id == "boundary-assessment-2")
    duplicate = replace(
        migrated,
        event_id="boundary-assessment-migration-copy",
        sequence_number=6,
        occurred_at="2026-07-05T10:00:00+00:00",
        payload={**migrated.payload, "observed_score": 1.0},
    )
    deduped = _state(engine, [*grounded, duplicate], raw["course_key"], TARGET)
    raw_score, raw_count = _raw_no_dedupe_score([*grounded, duplicate])

    return {
        "benchmark": "kg-mest-contract-ablation/1.0",
        "data_version": raw["data_version"],
        "baseline": {
            "observed_performance_score": baseline.observed_performance_score,
            "confidence": baseline.confidence,
            "action": recommendation.action_type,
            "evidence_count": len(baseline.evidence_refs),
        },
        "without_q_matrix": {
            "observed_performance_score": no_q_target.observed_performance_score,
            "confidence": no_q_target.confidence,
            "action": no_q_recommendation.action_type,
            "contract_effect": "unanchored_scored_tasks_produce_no_performance_evidence",
        },
        "invalid_interaction_leakage": {
            "counterfactual_score": invalid_interaction_leakage_score,
            "baseline_score": baseline.observed_performance_score,
            "interaction_evidence_count": interaction_count,
            "contract_effect": "violates_performance_interaction_separation",
        },
        "invalid_no_source_deduplication": {
            "baseline_deduplicated_score": deduped.observed_performance_score,
            "invalid_raw_score": raw_score,
            "deduplicated_mastery_evidence_count": len([item for item in deduped.evidence_refs if item.endswith(":mastery")]),
            "invalid_raw_mastery_evidence_count": raw_count,
            "contract_effect": "migration_copy_changes_score_when_source_deduplication_is_removed",
        },
    }


if __name__ == "__main__":
    from json import dumps
    print(dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
