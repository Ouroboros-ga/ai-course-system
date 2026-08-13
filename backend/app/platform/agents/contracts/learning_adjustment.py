"""Deterministic learner-review proposal dependency for TeachingAgent."""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from app.schemas.learning_adjustment import (
    LearningAdjustmentProposal,
    QuestionObservation,
)


class LearningAdjustmentPort(Protocol):
    """Resolve a release-pinned review proposal without model authority."""

    async def propose(
        self,
        *,
        student_id: str,
        course_id: str,
        observation: QuestionObservation,
        teaching_action: str,
        teaching_action_reason: str,
        current_concept_id: str | None,
        prerequisites: Sequence[Mapping[str, Any]],
        weak_concepts: Sequence[Mapping[str, Any]],
        source_trace_id: str,
    ) -> LearningAdjustmentProposal | None: ...


__all__ = ["LearningAdjustmentPort"]
