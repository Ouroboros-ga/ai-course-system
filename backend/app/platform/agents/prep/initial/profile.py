"""AgentProfile for the Initial course build pipeline.

The profile maps an ``AgentRunContext`` to the ``InitialPrepState`` schema.
Unlike the inline Prep planning profile, the Initial pipeline is a long-running
first-time course generation flow: it is dispatched as ``QUEUED`` with a
generous timeout and a tight concurrency cap (3) to avoid saturating the LLM /
graph-candidate pipelines with parallel full builds.

Request field mapping from ``AgentRunContext``:
    - ``teacher_id``  -> ``ctx.teacher_id``
    - ``course_id``   -> ``ctx.course_id``
    - ``corpus_snapshot_id`` -> ``ctx.extras["corpus_snapshot_id"]`` (no
      dedicated field on the generic context)
    - ``build_task_id`` -> ``ctx.task_id`` (queued-execution hint), falling
      back to ``ctx.extras["build_task_id"]``
"""

from __future__ import annotations

from typing import Any, Mapping

from ...runtime.base import AgentRunContext
from ...runtime.profile import AgentProfile, AgentType, ExecutionMode
from ...shared.state import empty_meta
from ..enums import PrepGraphKind


def build_initial_profile() -> AgentProfile:
    """Build the ``AgentProfile`` for the Initial course build pipeline."""

    def build_initial_state(ctx: AgentRunContext, *, trace_id: str) -> Mapping[str, Any]:
        meta = empty_meta(
            run_id=ctx.run_id,
            trace_id=trace_id,
            agent_type=AgentType.PREP.value,
            config_version=ctx.config_version,
        )
        build_task_id = ctx.task_id or ctx.extras.get("build_task_id")
        return {
            "meta": meta,
            "graph_kind": PrepGraphKind.INITIAL.value,
            "request": {
                "teacher_id": ctx.teacher_id or "",
                "course_id": ctx.course_id or "",
                "corpus_snapshot_id": ctx.extras.get("corpus_snapshot_id") or "",
                "build_task_id": build_task_id,
                "replace_unreviewed_initial": bool(
                    ctx.extras.get("replace_unreviewed_initial", False)
                ),
                "stage_callback": ctx.extras.get("stage_callback"),
            },
        }

    return AgentProfile(
        agent_type=AgentType.PREP,
        build_initial_state=build_initial_state,
        default_timeout_seconds=600.0,
        max_concurrency=3,
        execution_mode=ExecutionMode.QUEUED,
        description=(
            "Prep Agent / Initial pipeline: first-time course generation "
            "(outline + script + graph-candidate batch) via "
            "InitialCoursePrepService.build()"
        ),
    )


__all__ = ["build_initial_profile"]
