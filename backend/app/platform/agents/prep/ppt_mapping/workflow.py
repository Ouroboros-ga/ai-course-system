"""LangGraph workflow for the PPT mapping optimization pipeline.

A single-node graph (``optimize_ppt_mappings``) that:
    1. Reads the optimization request from ``state["request"]``.
    2. Calls ``deps.ppt_mapping.optimize_mappings(...)`` through the
       adapted port.
    3. Writes the optimization summary into ``state["result"]``.

Persistence: the Service updates ``CoursePptMapping`` rows in place
(``status="draft"``). Mappings with ``teacher_locked=True`` are never
modified. No ``PatchProposal`` is created.

Fail-closed contract (per the generic runtime): the node never raises. Any
exception from the port is recorded in ``state["meta"]["errors"]`` with a
``status`` field and the matching degraded-service flag, so the runtime can
surface a terminal ``run.failed`` without propagating the exception.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from .dependencies import PptMappingDependencies
from .state import PptMappingState

logger = logging.getLogger(__name__)


def build_ppt_mapping_workflow(deps: PptMappingDependencies):
    """Compile the PPT mapping optimization LangGraph workflow.

    The graph is a single node that delegates to
    ``PptMappingOptimizationPort``. All business invariants (OCR block
    loading, outline-node ID validation, teacher_locked exclusion,
    LLM suggestion parsing, in-place mapping updates) remain owned by
    the service; this node only provides state management and fail-closed
    error handling.
    """

    async def optimize_ppt_mappings(state: PptMappingState) -> dict[str, Any]:
        """Call ``PptMappingOptimizationPort.optimize_mappings()`` and store the result.

        Fail-closed: any exception lands in ``meta.errors`` with a ``status``
        field; the node never raises to the runtime.
        """
        meta = dict(state.get("meta") or {})
        request = state.get("request") or {}
        course_id = request.get("course_id", "")
        material_version_id = request.get("material_version_id", "")

        if not course_id or not material_version_id:
            return {
                "meta": {
                    **meta,
                    "errors": [*meta.get("errors", []), "PPT_MAPPING_MISSING_REQUEST_FIELDS"],
                    "status": "input_error",
                },
            }

        try:
            result = await deps.ppt_mapping.optimize_mappings(
                course_id=course_id,
                material_version_id=material_version_id,
            )
        except Exception as error:  # noqa: BLE001 - fail-closed
            logger.warning(
                "PptMapping: optimize_mappings() raised: %s: %s",
                type(error).__name__, error,
            )
            return {
                "meta": {
                    **meta,
                    "errors": [*meta.get("errors", []), f"PPT_MAPPING_FAILED:{type(error).__name__}"],
                    "degraded_services": [*meta.get("degraded_services", []), "ppt_mapping"],
                    "status": "mapping_error",
                },
            }

        suggestions_payload = [
            {
                "outline_node_id": s.outline_node_id,
                "page_start": s.page_start,
                "page_end": s.page_end,
                "confidence": s.confidence,
                "reason": s.reason,
            }
            for s in result.suggestions
        ]
        return {
            "result": {
                "total_mappings": result.total_mappings,
                "updated_count": result.updated_count,
                "suggestions": suggestions_payload,
            },
        }

    graph = StateGraph(PptMappingState)
    graph.add_node("optimize_ppt_mappings", optimize_ppt_mappings)
    graph.add_edge(START, "optimize_ppt_mappings")
    graph.add_edge("optimize_ppt_mappings", END)
    return graph.compile()


__all__ = ["build_ppt_mapping_workflow"]
