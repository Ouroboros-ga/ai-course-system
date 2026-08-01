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
        material_version_ids = list(request.get("material_version_ids") or [])
        outline_node_ids = list(request.get("outline_node_ids") or [])
        page_refs_by_material = dict(request.get("page_refs_by_material") or {})
        seed_from_evidence = bool(request.get("seed_from_evidence", True))

        if not course_id or not material_version_ids:
            return {
                "meta": {
                    **meta,
                    "errors": [*meta.get("errors", []), "PPT_MAPPING_MISSING_REQUEST_FIELDS"],
                    "status": "input_error",
                },
            }

        try:
            optimization_kwargs: dict[str, Any] = {
                "course_id": course_id,
                "material_version_ids": material_version_ids,
            }
            # Preserve the original minimal Port call for course-wide runs;
            # this keeps existing adapters/fakes compatible while scoped UI
            # actions explicitly opt into their additional constraints.
            if outline_node_ids:
                optimization_kwargs["outline_node_ids"] = outline_node_ids
            if page_refs_by_material:
                optimization_kwargs["page_refs_by_material"] = page_refs_by_material
            if not seed_from_evidence:
                optimization_kwargs["seed_from_evidence"] = False
            result = await deps.ppt_mapping.optimize_mappings(**optimization_kwargs)
        except Exception as error:  # noqa: BLE001 - fail-closed
            logger.warning(
                "PptMapping: optimize_mappings() raised: %s: %s",
                type(error).__name__, error,
            )
            return {
                "meta": {
                    **meta,
                    "errors": [
                        *meta.get("errors", []),
                        {
                            "code": getattr(error, "error_code", "PPT_MAPPING_FAILED"),
                            "message": str(error)[:500] or "PPT mapping optimization failed",
                            "node": "optimize_ppt_mappings",
                        },
                    ],
                    "degraded_services": [*meta.get("degraded_services", []), "ppt_mapping"],
                    "status": "mapping_error",
                },
            }

        suggestions_payload = [
            {
                "outline_node_id": s.outline_node_id,
                "page_refs": list(s.page_refs),
                "confidence": s.confidence,
                "reason": s.reason,
                "material_version_id": s.material_version_id,
            }
            for s in result.suggestions
        ]
        return {
            "result": {
                "total_mappings": result.total_mappings,
                "updated_count": result.updated_count,
                "suggestions": suggestions_payload,
                "material_version_ids": list(result.material_version_ids),
            },
        }

    graph = StateGraph(PptMappingState)
    graph.add_node("optimize_ppt_mappings", optimize_ppt_mappings)
    graph.add_edge(START, "optimize_ppt_mappings")
    graph.add_edge("optimize_ppt_mappings", END)
    return graph.compile()


__all__ = ["build_ppt_mapping_workflow"]
