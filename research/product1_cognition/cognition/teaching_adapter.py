"""Research-only read adapter from KG-MEST states to TeachingAgent Port data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .kg_mest import ConceptState, Dimension


CONFIDENCE_NUMERIC = {"unknown": 0.0, "low": 0.25, "medium": 0.65, "high": 0.90}


def state_to_teaching_view(state: ConceptState) -> Mapping[str, object]:
    """Translate without discarding policy versions or explanations.

    This function is a research compatibility adapter, not a production
    provider.  It maps the current TeachingAgent field names to the frozen
    KG-MEST semantics and never writes state.
    """
    values = state.values
    return {
        "mastery_score": state.observed_performance_score,
        "confidence": CONFIDENCE_NUMERIC[state.confidence],
        "repeated_error_risk": values.get(Dimension.RECURRING_ERROR_RISK.value),
        "hint_dependency": values.get(Dimension.HINT_DEPENDENCY.value),
        "transfer_score": values.get(Dimension.TRANSFER.value),
        "state_status": state.status,
        "evidence_refs": state.evidence_refs,
        "reason_codes": state.reason_codes,
        "policy_versions": dict(state.policy_versions),
        "data_version": state.data_version,
    }


@dataclass
class SyntheticKGMetStudentModelingPort:
    """A test double implementing TeachingAgent's read-only student Port."""

    states: Mapping[str, ConceptState]
    confirmed_weak_concept_ids: tuple[str, ...] = ()

    async def get_concept_state(self, *, concept_id: str, **_: object) -> Mapping[str, object]:
        return state_to_teaching_view(self.states[concept_id])

    async def get_weak_concepts(self, **_: object) -> list[Mapping[str, object]]:
        return [
            {
                "concept_id": concept_id,
                "evidence_refs": self.states[concept_id].evidence_refs,
                "reason_codes": self.states[concept_id].reason_codes,
            }
            for concept_id in self.confirmed_weak_concept_ids
        ]
