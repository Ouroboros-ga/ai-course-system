"""Request-scoped adapter for deterministic learning-adjustment proposals."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping, Sequence

from app.schemas.learning_adjustment import (
    LearningAdjustmentProposal,
    QuestionObservation,
)
from app.services.learning_adjustment_service import learning_adjustment_service


class SessionScopedLearningAdjustmentPort:
    """Open a fresh database session for each proposal attempt.

    The runtime registry is shared across learner requests, so this adapter
    never retains a SQLModel ``Session`` on the runtime object.
    """

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

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
        requested_concept_id: str | None = None,
    ) -> LearningAdjustmentProposal | None:
        try:
            student_id_int = int(student_id)
            course_id_int = int(course_id)
        except (TypeError, ValueError):
            return None

        reason_codes = tuple(
            dict.fromkeys(
                code
                for code in (
                    f"TEACHING_ACTION_{str(teaching_action).upper()}",
                    str(teaching_action_reason).upper(),
                )
                if code and code.replace("_", "").isalnum() and len(code) <= 64
            )
        )
        if not reason_codes:
            return None

        def _write() -> LearningAdjustmentProposal | None:
            with self._session_factory() as session:
                return learning_adjustment_service.create_proposal(
                    session,
                    course_id=course_id_int,
                    student_id=student_id_int,
                    observation=observation,
                    teaching_action=teaching_action,
                    current_concept_id=current_concept_id,
                    prerequisites=prerequisites,
                    weak_concepts=weak_concepts,
                    reason_codes=reason_codes,
                    source_trace_id=source_trace_id,
                    requested_concept_id=requested_concept_id,
                )

        return await asyncio.to_thread(_write)


def make_session_scoped_learning_adjustment_port(
    session_factory: Callable[[], Any],
) -> SessionScopedLearningAdjustmentPort:
    return SessionScopedLearningAdjustmentPort(session_factory)


__all__ = [
    "SessionScopedLearningAdjustmentPort",
    "make_session_scoped_learning_adjustment_port",
]
