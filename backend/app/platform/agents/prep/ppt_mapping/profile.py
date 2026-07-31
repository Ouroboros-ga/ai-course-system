"""AgentProfile for the PPT mapping optimization pipeline.

The profile maps an ``AgentRunContext`` to the ``PptMappingState`` schema.
The PPT mapping pipeline is a fast inline optimization flow: it is
dispatched as ``INLINE`` with a 60-second timeout and a concurrency cap
of 5, matching the design's Runtime Definition configuration.

Request field mapping from ``AgentRunContext``:
    - ``teacher_id``  -> ``ctx.teacher_id``
    - ``course_id``   -> ``ctx.course_id``
    - ``material_version_id`` -> ``ctx.extras["material_version_id"]``
"""

from __future__ import annotations

from typing import Any, Mapping

from ...runtime.base import AgentRunContext
from ...runtime.profile import AgentProfile, AgentType, ExecutionMode
from ...shared.state import empty_meta
from ..enums import PrepGraphKind


def build_ppt_mapping_profile() -> AgentProfile:
    """Build the ``AgentProfile`` for the PPT mapping pipeline."""

    def build_initial_state(ctx: AgentRunContext, *, trace_id: str) -> Mapping[str, Any]:
        meta = empty_meta(
            run_id=ctx.run_id,
            trace_id=trace_id,
            agent_type=AgentType.PREP.value,
            config_version=ctx.config_version,
        )
        return {
            "meta": meta,
            "graph_kind": PrepGraphKind.PPT_MAPPING.value,
            "request": {
                "teacher_id": ctx.teacher_id or "",
                "course_id": ctx.course_id or "",
                "material_version_id": ctx.extras.get("material_version_id") or "",
            },
        }

    return AgentProfile(
        agent_type=AgentType.PREP,
        build_initial_state=build_initial_state,
        default_timeout_seconds=240.0,
        max_concurrency=5,
        execution_mode=ExecutionMode.INLINE,
        description=(
            "Prep Agent / PPT mapping pipeline: optimises CoursePptMapping "
            "rows via LLM OCR-text matching. Wraps "
            "PptMappingOptimizationService.optimize_mappings()."
        ),
    )


__all__ = ["build_ppt_mapping_profile"]
