"""LangGraph workflow for the Initial course build pipeline.

A single-node graph (``execute_initial_build``) that:
    1. Reads the build request from ``state["request"]``.
    2. Builds a ``StageEmitter`` bound to ``state["meta"]`` (``run_id`` /
       ``trace_id``) and obtains the ``on_stage`` callback.
    3. Calls ``deps.initial_prep.build(...)`` through the adapted port.
    4. Writes the ``DraftAssetResult``-shaped output into ``state["result"]``
       and folds build warnings into ``state["meta"]["warnings"]``.

Fail-closed contract (per the generic runtime): the node never raises. Any
exception from the port is recorded in ``state["meta"]["errors"]`` with a
``status`` field and the matching degraded-service flag, so the runtime can
surface a terminal ``run.failed`` without propagating the exception.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..stage_emitter import StageEmitter
from .dependencies import InitialPrepDependencies
from .state import InitialPrepState

logger = logging.getLogger(__name__)


def build_initial_workflow(deps: InitialPrepDependencies):
    """Compile the Initial course build LangGraph workflow.

    The graph is a single node that delegates to ``InitialCoursePrepPort``.
    All business invariants (corpus snapshot integrity, outline/script
    generation, graph-candidate batching) remain owned by the service; this
    node only provides state management, stage-event bridging, and
    fail-closed error handling.
    """

    async def execute_initial_build(state: InitialPrepState) -> dict[str, Any]:
        """Call ``InitialCoursePrepPort.build()`` and store the result.

        Fail-closed: any exception lands in ``meta.errors`` with a ``status``
        field; the node never raises to the runtime.
        """
        meta = dict(state.get("meta") or {})
        request = state.get("request") or {}
        teacher_id = request.get("teacher_id", "")
        course_id = request.get("course_id", "")
        corpus_snapshot_id = request.get("corpus_snapshot_id", "")
        build_task_id = request.get("build_task_id")

        if not (teacher_id and course_id and corpus_snapshot_id):
            return {
                "meta": {
                    **meta,
                    "errors": [*meta.get("errors", []), "INITIAL_BUILD_MISSING_REQUEST_FIELDS"],
                    "status": "input_error",
                },
            }

        run_id = meta.get("run_id", "")
        trace_id = meta.get("trace_id", "")
        emitter = StageEmitter(
            run_store=deps.common.run_store,
            event_port=deps.common.event_port,
            run_id=run_id,
            trace_id=trace_id,
        )
        on_stage = emitter.make_callback()

        try:
            result = await deps.initial_prep.build(
                teacher_id=teacher_id,
                course_id=course_id,
                corpus_snapshot_id=corpus_snapshot_id,
                build_task_id=build_task_id,
                on_stage=on_stage,
                replace_unreviewed_initial=False,
            )
        except Exception as error:  # noqa: BLE001 - fail-closed
            logger.warning(
                "InitialPrep: build() raised: %s: %s",
                type(error).__name__, error,
            )
            return {
                "meta": {
                    **meta,
                    "errors": [*meta.get("errors", []), f"INITIAL_BUILD_FAILED:{type(error).__name__}"],
                    "degraded_services": [*meta.get("degraded_services", []), "initial_build"],
                    "status": "build_error",
                },
            }

        build_warnings = list(result.warnings or [])
        return {
            "result": {
                "outline_version_id": result.outline_version_id,
                "script_version_id": result.script_version_id,
                "graph_candidate_batch_id": result.graph_candidate_batch_id,
                "warnings": build_warnings,
            },
            "meta": {
                **meta,
                "warnings": [*meta.get("warnings", []), *build_warnings],
            },
        }

    graph = StateGraph(InitialPrepState)
    graph.add_node("execute_initial_build", execute_initial_build)
    graph.add_edge(START, "execute_initial_build")
    graph.add_edge("execute_initial_build", END)
    return graph.compile()


__all__ = ["build_initial_workflow"]
