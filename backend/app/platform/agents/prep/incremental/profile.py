"""AgentProfile for the Incremental draft modification pipeline.

The profile maps an ``AgentRunContext`` to the ``IncrementalPrepState``
schema. The Incremental pipeline is a fast inline planning flow: it is
dispatched as ``INLINE`` with a 120-second timeout and a concurrency cap
of 10, matching the design's Runtime Definition configuration.

Request field mapping from ``AgentRunContext``:
    - ``teacher_id``  -> ``ctx.teacher_id``
    - ``course_id``   -> ``ctx.course_id``
    - ``instruction`` -> ``ctx.user_message``
    - ``outline_node_id`` -> ``ctx.extras["outline_node_id"]`` (optional
      teacher-selected target; ``None`` means "all nodes")
"""

from __future__ import annotations

from typing import Any, Mapping

from ...runtime.base import AgentRunContext
from ...runtime.profile import AgentProfile, AgentType, ExecutionMode
from ...shared.state import empty_meta
from ..enums import PrepGraphKind


def build_incremental_profile() -> AgentProfile:
    """Build the ``AgentProfile`` for the Incremental pipeline."""

    def build_initial_state(ctx: AgentRunContext, *, trace_id: str) -> Mapping[str, Any]:
        meta = empty_meta(
            run_id=ctx.run_id,
            trace_id=trace_id,
            agent_type=AgentType.PREP.value,
            config_version=ctx.config_version,
        )
        return {
            "meta": meta,
            "graph_kind": PrepGraphKind.INCREMENTAL.value,
            "request": {
                "teacher_id": ctx.teacher_id or "",
                "course_id": ctx.course_id or "",
                "instruction": ctx.user_message or "",
                "outline_node_id": ctx.extras.get("outline_node_id"),
                "action": ctx.extras.get("action"),
            },
        }

    return AgentProfile(
        agent_type=AgentType.PREP,
        build_initial_state=build_initial_state,
        default_timeout_seconds=240.0,
        # Course-level batch edits hold a per-course endpoint lock; this
        # profile limit protects the shared LLM provider across courses.
        max_concurrency=3,
        execution_mode=ExecutionMode.INLINE,
        description=(
            "Prep Agent / Incremental pipeline: per-draft proposal planning "
            "with evidence_refs hard gate. Wraps CoursePrepAgentService.plan()."
        ),
    )


__all__ = ["build_incremental_profile"]
