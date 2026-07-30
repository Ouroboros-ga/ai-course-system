"""LangGraph workflow for the Incremental draft modification pipeline.

A single-node graph (``execute_incremental_plan``) that:
    1. Reads the planning request from ``state["request"]``.
    2. Calls ``deps.incremental_prep.plan(...)`` through the adapted port.
    3. Writes the ``CoursePrepAgentResult``-shaped output into
       ``state["result"]``.

Persistence boundary: the node does NOT create ``PatchProposal`` rows.
That is the endpoint layer's responsibility, matching the existing service
behaviour.

Fail-closed contract (per the generic runtime): the node never raises. Any
exception from the port is recorded in ``state["meta"]["errors"]`` with a
``status`` field and the matching degraded-service flag, so the runtime can
surface a terminal ``run.failed`` without propagating the exception.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from .dependencies import IncrementalPrepDependencies
from .state import IncrementalPrepState

logger = logging.getLogger(__name__)


def build_incremental_workflow(deps: IncrementalPrepDependencies):
    """Compile the Incremental draft modification LangGraph workflow.

    The graph is a single node that delegates to ``IncrementalPrepPort``.
    All business invariants (latest-draft loading, locked-node exclusion,
    evidence retrieval, LLM planning with strict JSON schema validation,
    evidence_refs hard gate, deterministic fallback) remain owned by the
    service; this node only provides state management and fail-closed
    error handling.
    """

    async def execute_incremental_plan(state: IncrementalPrepState) -> dict[str, Any]:
        """Call ``IncrementalPrepPort.plan()`` and store the result.

        Fail-closed: any exception lands in ``meta.errors`` with a ``status``
        field; the node never raises to the runtime.
        """
        meta = dict(state.get("meta") or {})
        request = state.get("request") or {}
        instruction = (request.get("instruction") or "").strip()
        course_id = request.get("course_id", "")
        outline_node_id = request.get("outline_node_id")

        if not instruction:
            return {
                "meta": {
                    **meta,
                    "errors": [*meta.get("errors", []), "INCREMENTAL_PLAN_INSTRUCTION_EMPTY"],
                    "status": "input_error",
                },
            }

        if not course_id:
            return {
                "meta": {
                    **meta,
                    "errors": [*meta.get("errors", []), "INCREMENTAL_PLAN_MISSING_COURSE_ID"],
                    "status": "input_error",
                },
            }

        try:
            result = await deps.incremental_prep.plan(
                course_id=course_id,
                instruction=instruction,
                outline_node_id=outline_node_id,
            )
        except Exception as error:  # noqa: BLE001 - fail-closed
            logger.warning(
                "IncrementalPrep: plan() raised: %s: %s",
                type(error).__name__, error,
            )
            return {
                "meta": {
                    **meta,
                    "errors": [*meta.get("errors", []), f"INCREMENTAL_PLAN_FAILED:{type(error).__name__}"],
                    "degraded_services": [*meta.get("degraded_services", []), "incremental_planner"],
                    "status": "planning_error",
                },
            }

        return {
            "result": {
                "summary": result.summary,
                "operations": list(result.operations),
                "evidence": list(result.evidence),
                "excluded_locked_targets": list(result.excluded_locked_targets),
                "planner": result.planner,
            },
            "context": {
                "excluded_locked_targets": list(result.excluded_locked_targets),
            },
        }

    graph = StateGraph(IncrementalPrepState)
    graph.add_node("execute_incremental_plan", execute_incremental_plan)
    graph.add_edge(START, "execute_incremental_plan")
    graph.add_edge("execute_incremental_plan", END)
    return graph.compile()


__all__ = ["build_incremental_workflow"]
