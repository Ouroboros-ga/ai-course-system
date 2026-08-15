"""Narrow ports for per-request teaching constraints and conversation continuity."""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence


class TeachingConstraintPort(Protocol):
    async def resolve(
        self,
        *,
        course_id: str,
        student_id: str,
        intent: str,
        concept_id: str | None,
    ) -> Mapping[str, Any]: ...

    async def record_evaluation(
        self,
        *,
        trace_id: str,
        course_id: str,
        student_id: str,
        summary: Mapping[str, Any],
    ) -> None: ...


class ConversationHistoryPort(Protocol):
    async def select_relevant_turns(
        self,
        *,
        student_id: str,
        course_id: str,
        session_id: str,
        message: str,
        concept_id: str | None,
        resource_id: str | None,
        max_chars: int,
    ) -> Sequence[Mapping[str, Any]]: ...


__all__ = ["ConversationHistoryPort", "TeachingConstraintPort"]
