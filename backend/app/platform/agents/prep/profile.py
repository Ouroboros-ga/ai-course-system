"""AgentProfile for the Prep Agent.

The profile maps an ``AgentRunContext`` to the ``PrepState`` schema. The
scope for the Prep Agent is ``(course_id,)`` — it operates at course level
(per-draft), not per-student like the EDU agent.

The ``outline_node_id`` is passed via ``ctx.extras`` because it is an
optional teacher-selected target that does not have a dedicated field in
``AgentRunContext``.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..runtime.base import AgentRunContext
from ..runtime.profile import AgentProfile, AgentType


def build_prep_profile() -> AgentProfile:
    """Build the ``AgentProfile`` for the Prep Agent."""

    def build_initial_state(ctx: AgentRunContext, *, trace_id: str) -> Mapping[str, Any]:
        return {
            "trace_id": trace_id,
            "course_id": ctx.course_id or "",
            "teacher_id": ctx.teacher_id or "",
            "session_id": ctx.session_id or "",
            "instruction": ctx.user_message or "",
            "outline_node_id": ctx.extras.get("outline_node_id"),
            "warnings": [],
            "errors": [],
            "degraded_services": [],
            "trace": [],
        }

    return AgentProfile(
        agent_type=AgentType.PREP,
        build_initial_state=build_initial_state,
        default_timeout_seconds=120.0,
        description="备课 Agent: per-course/draft proposal planning with evidence_refs hard gate",
    )
