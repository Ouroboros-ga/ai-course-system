"""Cognition and student-state ports: learner modeling, cognitive state, history.

These ports all read learner-subject state for a course. They retain
``student_id`` for compatibility with persisted cognition records, where it
means the learner subject rather than the caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


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


class TrajectoryPort(Protocol):
    """学习轨迹端口（M7）：追加 + 读紧凑历史。

    只存数值/枚举/ID 快照，绝不携带问答原文；``append`` 以 ``dedup_key``
    幂等（如 trace_id），``get_compact_history`` 返回供 LLM 注入的紧凑上下文。
    """

    async def get_compact_history(
        self, *, student_id: str, course_id: str, concept_id: str | None = None,
    ) -> Mapping[str, Any]: ...

    async def append(
        self, *,
        student_id: str,
        course_id: str,
        event_type: str,
        concept_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        dedup_key: str | None = None,
    ) -> None: ...


__all__ = ["CognitionPort", "StudentHistoryPort", "StudentModelingPort", "TrajectoryPort"]
