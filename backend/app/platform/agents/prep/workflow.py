"""Prep Agent workflow: a thin LangGraph wrapper around CoursePrepAgentService.

The workflow has a single planning node that delegates to the existing
``CoursePrepAgentService.plan()`` method. This preserves all business logic:
    - latest-draft loading and locked-node exclusion
    - course-scoped evidence retrieval
    - LLM planning with strict JSON schema validation
    - evidence_refs hard gate (only confirmed evidence IDs survive)
    - deterministic fallback when LLM is not configured

The workflow does NOT re-implement any of these concerns. It only provides
the state management and fail-closed error handling that the
``LangGraphAgentRuntime`` expects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from langgraph.graph import END, START, StateGraph

from app.models.database import Session  # noqa: F401 — type only
from app.services.course_prep_agent_service import CoursePrepAgentService

from .state import PrepState

logger = logging.getLogger(__name__)


@dataclass
class PrepTools:
    """Dependencies injected into the Prep Agent workflow.

    The ``service`` is the existing ``CoursePrepAgentService`` singleton.
    The ``session_factory`` creates a SQLModel ``Session`` for DB access;
    the workflow closes it after the planning call.
    """

    service: CoursePrepAgentService
    session_factory: Callable[[], "Session"]


def _trace(state: Mapping[str, Any], node: str, **detail: Any) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, **detail}]


def build_prep_workflow(tools: PrepTools):
    """Compile the Prep Agent LangGraph workflow.

    The graph has a single node (``generate_plan``) that calls the service.
    This is intentional: the service already implements all safety invariants
    (locked-node exclusion, evidence_refs hard gate, latest-draft scoping).
    """

    async def generate_plan(state: PrepState) -> dict[str, Any]:
        """Call CoursePrepAgentService.plan() and store the result.

        Fail-closed: any exception lands in ``state["errors"]`` with a
        ``status`` field; the runtime never raises to the caller.
        """
        instruction = state.get("instruction", "").strip()
        if not instruction:
            return {
                "errors": [*state.get("errors", []), "PREP_INSTRUCTION_EMPTY"],
                "status": "input_error",
                "trace": _trace(state, "generate_plan", skipped=True),
            }

        course_id_str = state.get("course_id", "")
        try:
            course_id = int(course_id_str)
        except (TypeError, ValueError):
            return {
                "errors": [*state.get("errors", []), f"PREP_INVALID_COURSE_ID:{course_id_str}"],
                "status": "input_error",
                "trace": _trace(state, "generate_plan", skipped=True),
            }

        outline_node_id = state.get("outline_node_id")

        try:
            session = tools.session_factory()
            try:
                result = await tools.service.plan(
                    session,
                    course_id=course_id,
                    instruction=instruction,
                    outline_node_id=outline_node_id,
                )
            finally:
                session.close()
        except Exception as error:  # noqa: BLE001 - fail-closed
            logger.warning(
                "PrepAgent: plan() raised: %s: %s",
                type(error).__name__, error,
            )
            return {
                "errors": [*state.get("errors", []), f"PREP_PLAN_FAILED:{type(error).__name__}"],
                "degraded_services": [*state.get("degraded_services", []), "prep_planner"],
                "status": "planning_error",
                "trace": _trace(state, "generate_plan", error=type(error).__name__),
            }

        return {
            "plan_result": {
                "summary": result.summary,
                "operations": result.operations,
                "evidence": result.evidence,
                "excluded_locked_targets": result.excluded_locked_targets,
                "planner": result.planner,
            },
            "trace": _trace(state, "generate_plan", planner=result.planner, operations=len(result.operations)),
        }

    graph = StateGraph(PrepState)
    graph.add_node("generate_plan", generate_plan)
    graph.add_edge(START, "generate_plan")
    graph.add_edge("generate_plan", END)
    return graph.compile()
