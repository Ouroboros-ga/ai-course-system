"""Agent actor and execution-mode shared types.

``AgentActor`` is a governance/audit abstraction that wraps domain-specific
identifiers (``student_id``, ``teacher_id``) into a generic ``(actor_id,
actor_type)`` pair. It is used by audit, governance, and event ports so
those ports do not need to know whether the caller is a student or a teacher.

Design rule (per migration plan):
    ``RunContext`` does NOT replace domain parameters. Student modeling
    still receives ``student_id``; teacher prep still receives ``teacher_id``.
    ``AgentActor`` is only for cross-cutting concerns (audit, governance).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActorType(str, Enum):
    """The kind of actor initiating an agent run."""

    STUDENT = "student"
    TEACHER = "teacher"
    SYSTEM = "system"


@dataclass(frozen=True)
class AgentActor:
    """Generic actor identity for audit and governance.

    - ``actor_id``: the user/system identifier (same as ``student_id`` or
      ``teacher_id`` in the domain layer).
    - ``actor_type``: ``student`` / ``teacher`` / ``system``.
    """

    actor_id: str
    actor_type: ActorType

    @classmethod
    def student(cls, student_id: str) -> "AgentActor":
        return cls(actor_id=student_id, actor_type=ActorType.STUDENT)

    @classmethod
    def teacher(cls, teacher_id: str) -> "AgentActor":
        return cls(actor_id=teacher_id, actor_type=ActorType.TEACHER)

    @classmethod
    def system(cls, system_id: str = "system") -> "AgentActor":
        return cls(actor_id=system_id, actor_type=ActorType.SYSTEM)


__all__ = [
    "ActorType",
    "AgentActor",
]
