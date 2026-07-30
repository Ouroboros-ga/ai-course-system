"""Cognition and student-state ports: learner modeling, cognitive state, history.

These ports all read learner-subject state for a course. They retain
``student_id`` for compatibility with persisted cognition records, where it
means the learner subject rather than the caller.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class StudentModelingPort(Protocol):
    """Read-only state for the learner subject in a course."""
    async def get_concept_state(self, *, student_id: str, course_id: str, concept_id: str) -> Mapping[str, Any]: ...
    async def get_weak_concepts(self, *, student_id: str, course_id: str) -> list[Mapping[str, Any]]: ...


class CognitionPort(Protocol):
    """六维认知状态读取端口（只读）。"""

    async def get_state(self, *, student_id: str, course_id: str, node_id: str | None = None) -> Mapping[str, Any] | None: ...
    async def get_recommendation(self, *, student_id: str, course_id: str, node_id: str | None = None) -> Mapping[str, Any] | None: ...


class StudentHistoryPort(Protocol):
    """返回有界、去原文的学习历史快照。"""

    async def get_history(
        self, *, student_id: str, course_id: str, concept_id: str | None = None,
    ) -> Mapping[str, Any]: ...


__all__ = ["StudentModelingPort", "CognitionPort", "StudentHistoryPort"]
