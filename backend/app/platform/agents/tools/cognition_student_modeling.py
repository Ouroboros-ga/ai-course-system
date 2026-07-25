"""Student-modeling adapter backed by formal read-only cognition state."""

from __future__ import annotations

from typing import Any, Mapping


class CognitionStudentModelingPort:
    """Use current cognition when present; otherwise return an explicit unknown.

    This is a read adapter. It does not cause formal cognitive state changes.
    """

    def __init__(self, cognition: Any) -> None:
        self._cognition = cognition

    async def get_concept_state(self, *, student_id: str, course_id: str, concept_id: str) -> Mapping[str, Any]:
        state = await self._cognition.get_state(student_id=student_id, course_id=course_id, node_id=concept_id)
        if state is not None:
            return dict(state)
        return {"state_status": "unknown", "confidence": None, "reason_codes": ["FORMAL_COGNITION_NOT_AVAILABLE"]}

    async def get_weak_concepts(self, *, student_id: str, course_id: str) -> list[Mapping[str, Any]]:
        recommendation = await self._cognition.get_recommendation(student_id=student_id, course_id=course_id, node_id=None)
        if not recommendation:
            return []
        return [dict(item) for item in recommendation.get("confirmed_weak_prerequisite_set", []) if isinstance(item, Mapping)]


class UnknownStudentModelingPort:
    """Explicit no-data adapter used only when no read-only cognition port exists."""

    async def get_concept_state(self, *, student_id: str, course_id: str, concept_id: str) -> Mapping[str, Any]:
        return {"state_status": "unknown", "confidence": None, "reason_codes": ["FORMAL_COGNITION_NOT_AVAILABLE"]}

    async def get_weak_concepts(self, *, student_id: str, course_id: str) -> list[Mapping[str, Any]]:
        return []
