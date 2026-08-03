"""AgentGateway: unified entry point for agent run lifecycle.

The gateway sits between FastAPI endpoints and the runtime layer. It:
    1. Creates an ``AgentRunContext`` from the endpoint's request.
    2. Resolves the runtime via ``AgentRuntimeRegistry`` (Phase 1+).
    3. Selects inline vs queued execution based on the agent profile.
    4. For inline: executes the runtime and returns the result.
    5. For queued: creates a run record and returns a task_id (future).
    6. Returns a unified ``AgentStartResult`` envelope.

Design rules (per migration design section 12):
    - Endpoints do NOT directly operate the registry; they go through
      the gateway.
    - The gateway routes sub-graphs via ``ctx.graph_kind`` (e.g. Prep's
      ``"initial"`` vs ``"incremental"``). This is the discrimination
      point for Prep's two pipelines.
    - The gateway is fail-closed: unavailable agents return an error
      envelope, never raise.
    - Domain response shapes remain backward-compatible; the gateway
      wraps them in a unified envelope but does not alter domain fields.

Backward compatibility:
    Phase 1 provides the gateway as infrastructure. Existing EDU endpoints
    continue to call ``registry.get_or_create`` directly until Phase 3
    migrates them. The gateway is available for new endpoints (Prep, Coding)
    immediately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .runtime.base import AgentRunContext
from .runtime.dispatcher import BaseAgentRuntime
from .runtime.errors import AgentNotAvailableError, ErrorCode
from .runtime.events import (
    AgentRunEventPort,
    NullAgentRunEventPort,
    RunStatus,
)
from .runtime.diagnostic_context import DiagnosticContext, current_diagnostic_context
from .runtime.profile import AgentType, ExecutionMode
from .runtime.registry import AgentDefinitionKey, AgentRuntimeRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentStartResult:
    """Unified execution envelope returned by ``AgentGateway.start``.

    - ``run_id``: stable run identifier for polling/audit.
    - ``agent_type``: which agent executed.
    - ``status``: ``completed`` (inline), ``queued``, or ``failed``.
    - ``trace_id``: trace identifier for log correlation.
    - ``task_id``: present only for queued execution (future).
    - ``result``: the agent's domain response (for inline completion).
    - ``error_code``: present only on failure.
    - ``error_message``: present only on failure.
    """

    run_id: str
    agent_type: str
    status: str
    trace_id: str
    task_id: str | None = None
    result: Mapping[str, Any] | None = None
    error_code: str | None = None
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict for API responses."""
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "agent_type": self.agent_type,
            "status": self.status,
            "trace_id": self.trace_id,
        }
        if self.task_id is not None:
            payload["task_id"] = self.task_id
        if self.result is not None:
            payload["result"] = dict(self.result)
        if self.error_code is not None:
            payload["error_code"] = self.error_code
        if self.error_message:
            payload["error_message"] = self.error_message
        return payload


class AgentGateway:
    """Unified agent run lifecycle entry point.

    The gateway is constructed once at bootstrap with the runtime registry
    and event ports. Endpoints call ``start`` to begin an agent run.

    Phase 1 scope:
        - Inline execution only (queued execution is future Phase 4/6).
        - Runtime resolution via ``AgentRuntimeRegistry``.
        - Event emission for run lifecycle.
        - Fail-closed error handling.

    Future phases:
        - Phase 4: queued execution for Prep initial build.
        - Phase 6: queued execution for Coding verification loop.
    """

    def __init__(
        self,
        *,
        registry: AgentRuntimeRegistry,
        event_port: AgentRunEventPort | None = None,
        run_store: Any | None = None,  # AgentRunStorePort
    ) -> None:
        self._registry = registry
        self._event_port: AgentRunEventPort = event_port or NullAgentRunEventPort()
        self._run_store = run_store

    async def start(
        self,
        *,
        agent_type: AgentType | str,
        context: AgentRunContext,
        definition_key: AgentDefinitionKey | None = None,
        initial_state: Mapping[str, Any] | None = None,
    ) -> AgentStartResult:
        """Start an agent run.

        For inline agents (default), this executes the runtime and returns
        the completed result. For queued agents (future), this creates a
        run record and returns a task_id.

        Returns an ``AgentStartResult``; never raises.
        """
        agent_type_str = agent_type.value if isinstance(agent_type, AgentType) else str(agent_type)
        run_id = context.run_id
        trace_id = context.trace_id

        # Resolve definition key (defaults to a basic key from agent_type).
        key = definition_key or AgentDefinitionKey(agent_type=agent_type_str)

        # Resolve runtime from registry.
        try:
            runtime = await self._registry.get_or_create(key)
        except AgentNotAvailableError as error:
            return AgentStartResult(
                run_id=run_id,
                agent_type=agent_type_str,
                status="failed",
                trace_id=trace_id,
                error_code=ErrorCode.AGENT_NOT_AVAILABLE.value,
                error_message=str(error),
            )

        # Check execution mode (inline vs queued).
        profile = getattr(runtime, "_profile", None)
        execution_mode = getattr(profile, "execution_mode", ExecutionMode.INLINE)

        if execution_mode == ExecutionMode.QUEUED:
            # Phase 1: queued execution is not yet implemented.
            # Return a placeholder so endpoints can detect this.
            return AgentStartResult(
                run_id=run_id,
                agent_type=agent_type_str,
                status="queued",
                trace_id=trace_id,
                task_id=None,  # No worker dispatch yet
                error_code="QUEUED_EXECUTION_NOT_IMPLEMENTED",
                error_message="Queued execution is not implemented in Phase 1",
            )

        # Inline execution.
        if self._run_store is not None:
            try:
                await self._run_store.create_run(
                    run_id=run_id, trace_id=trace_id, agent_type=agent_type_str,
                    actor_id=context.teacher_id or context.student_id or "system",
                    actor_type="teacher" if context.teacher_id else "student" if context.student_id else "system",
                    course_id=context.course_id,
                    config_version=context.config_version,
                    idempotency_key=context.idempotency_key,
                )
            except Exception:
                logger.debug("AgentGateway: unable to create run record", exc_info=True)
        return await self._execute_inline(
            runtime=runtime,
            context=context,
            agent_type_str=agent_type_str,
            run_id=run_id,
            trace_id=trace_id,
            initial_state=initial_state,
        )

    async def _execute_inline(
        self,
        *,
        runtime: BaseAgentRuntime,
        context: AgentRunContext,
        agent_type_str: str,
        run_id: str,
        trace_id: str,
        initial_state: Mapping[str, Any] | None,
    ) -> AgentStartResult:
        """Execute the runtime inline and return the completed result."""
        token = current_diagnostic_context.set(DiagnosticContext(
            run_id=run_id, trace_id=trace_id, course_id=context.course_id or "",
        ))
        try:
            result = await runtime.run(context=context, initial_state=initial_state)
        except Exception as error:  # noqa: BLE001 - gateway is fail-closed
            logger.warning(
                "AgentGateway: inline execution failed for %s: %s: %s",
                agent_type_str, type(error).__name__, error,
            )
            if self._run_store is not None:
                await self._safe_update_run(run_id, RunStatus.FAILED, errors=[{"code": ErrorCode.RUNTIME_INTERNAL_ERROR.value}], result={"stage": "runtime"})
            current_diagnostic_context.reset(token)
            return AgentStartResult(
                run_id=run_id,
                agent_type=agent_type_str,
                status="failed",
                trace_id=trace_id,
                error_code=ErrorCode.RUNTIME_INTERNAL_ERROR.value,
                error_message=str(error),
            )

        status = result.get("status", "ok")
        errors = result.get("errors", [])
        last_error = errors[-1] if errors else None
        error_code = (
            str(last_error.get("code") or ErrorCode.RUNTIME_INTERNAL_ERROR.value)
            if isinstance(last_error, Mapping)
            else str(last_error)
            if last_error is not None
            else None
        )

        await self._safe_update_run(
            run_id,
            RunStatus.COMPLETED if not errors else RunStatus.FAILED,
            errors=[item for item in errors if isinstance(item, Mapping)],
            result={"stage": "execute_incremental_plan", "status": status},
        )
        current_diagnostic_context.reset(token)
        return AgentStartResult(
            run_id=run_id,
            agent_type=agent_type_str,
            status="completed" if not errors else "failed",
            trace_id=trace_id,
            result=result,
            error_code=error_code,
            error_message=(
                str(last_error.get("message") or "")
                if isinstance(last_error, Mapping)
                else ""
            ),
        )


    async def _safe_update_run(self, run_id: str, status: RunStatus, *, errors: list[Mapping[str, Any]], result: Mapping[str, Any]) -> None:
        if self._run_store is None:
            return
        try:
            await self._run_store.update_status(run_id=run_id, status=status, errors=errors, result=result)
        except Exception:
            logger.debug("AgentGateway: unable to update run record", exc_info=True)

    async def get_run_status(self, *, run_id: str) -> Mapping[str, Any] | None:
        """Poll the status of a run (for queued execution).

        Returns None if no run store is configured or the run is not found.
        Phase 1: always returns None (no queued execution).
        """
        if self._run_store is None:
            return None
        try:
            return await self._run_store.get_run(run_id=run_id)
        except Exception:  # noqa: BLE001 - polling must not raise
            return None


__all__ = [
    "AgentGateway",
    "AgentStartResult",
]
