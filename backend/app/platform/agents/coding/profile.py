"""AgentProfile for the Coding Agent.

The profile maps an ``AgentRunContext`` to the ``CodingState`` schema. The
scope for the Coding Agent is ``(student_id, course_id)`` — like the EDU
agent, it operates per-student because code submissions are student-scoped.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..runtime.base import AgentRunContext
from ..runtime.profile import AgentProfile, AgentType


def build_coding_profile() -> AgentProfile:
    """Build the ``AgentProfile`` for the Coding Agent."""

    def build_initial_state(ctx: AgentRunContext, *, trace_id: str) -> Mapping[str, Any]:
        return {
            "trace_id": trace_id,
            "student_id": ctx.student_id or "",
            "course_id": ctx.course_id or "",
            "session_id": ctx.session_id or "",
            "user_message": ctx.user_message or "",
            "code_submission_id": ctx.code_submission_id or "",
            "exercise_id": ctx.exercise_id,
            "warnings": [],
            "errors": [],
            "degraded_services": [],
            "trace": [],
        }

    return AgentProfile(
        agent_type=AgentType.CODING,
        build_initial_state=build_initial_state,
        default_timeout_seconds=60.0,
        description="Coding Agent: per-(student, course) code diagnosis with rule-based fallback",
    )
