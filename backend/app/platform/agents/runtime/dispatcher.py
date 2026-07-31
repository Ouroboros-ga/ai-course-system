"""BaseAgentRuntime: unified runtime with timeout, concurrency, and cancellation.

This is the Phase 1 ``BaseAgentRuntime`` described in the migration design.
It wraps any compiled LangGraph workflow and provides:

    - Common state initialization via ``AgentProfile.build_initial_state``
    - Total run timeout via ``asyncio.timeout``
    - Per-agent-type concurrency limiting via ``AgentConcurrencyLimiter``
    - Cancellation propagation (``asyncio.CancelledError``)
    - Run lifecycle events via ``AgentRunEventPort``
    - Stable error mapping via ``ErrorCode`` taxonomy
    - Fail-closed: ``run()`` never raises to the caller

Design rules:
    - The runtime does NOT own tool instances; it holds a compiled graph and
      delegates state initialization to the profile.
    - The runtime does NOT replace ``LangGraphAgentRuntime`` (base.py); it
      extends it with concurrency and event emission. ``LangGraphAgentRuntime``
      remains for backward compatibility.
    - Phase 1 defaults are intentionally loose: high timeout, high concurrency.
      This preserves existing TeachingAgent behavior while providing the
      framework for future tightening.

Backward compatibility:
    ``LangGraphAgentRuntime`` (in base.py) continues to work. ``BaseAgentRuntime``
    is the new preferred runtime for agents registered via
    ``AgentRuntimeRegistry``. Existing legacy EDU runtime is unaffected.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Mapping

from .base import AgentRunContext, RunnableGraph
from .concurrency import AgentConcurrencyLimiter
from .errors import (
    AgentRuntimeError,
    ErrorCode,
    RuntimeCancelledError,
    RuntimeTimeoutError,
)
from .events import AgentRunEventPort, NullAgentRunEventPort, RunEventType, RunStatus
from .profile import AgentProfile
from ..shared.state import empty_meta

logger = logging.getLogger(__name__)


class BaseAgentRuntime:
    """Unified runtime wrapping a compiled LangGraph workflow.

    The runtime is agnostic of the agent type. An ``AgentProfile`` describes
    how to build the initial state from an ``AgentRunContext`` and which
    common fields to initialize. The actual workflow graph is supplied by
    the agent's composition root.

    Contract:
        - ``run()`` never raises; failures land in ``state["errors"]``
          with a ``status`` field identifying the failure mode.
        - ``timeout_seconds`` cancels the underlying ``ainvoke``;
          timeout is recorded as a degraded service, not an exception.
        - Concurrency is bounded by ``AgentConcurrencyLimiter``; when
          exhausted, the run fails with ``AGENT_NOT_AVAILABLE``.
        - Lifecycle events are emitted to ``event_port``; failures in
          event emission do NOT abort the run.
    """

    def __init__(
        self,
        *,
        profile: AgentProfile,
        graph: RunnableGraph,
        concurrency_limiter: AgentConcurrencyLimiter | None = None,
        event_port: AgentRunEventPort | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._profile = profile
        self._graph = graph
        self._limiter = concurrency_limiter or AgentConcurrencyLimiter()
        self._event_port: AgentRunEventPort = event_port or NullAgentRunEventPort()
        # If no explicit timeout, use the profile's default.
        self._timeout = timeout_seconds if timeout_seconds is not None else profile.default_timeout_seconds

    async def run(
        self,
        *,
        context: AgentRunContext,
        initial_state: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Invoke the wrapped graph with a profile-built initial state.

        The profile's ``build_initial_state`` is responsible for mapping the
        context's domain-specific identifiers into the agent's state schema.
        The runtime wraps this with timeout, concurrency, and event emission.

        Returns a fail-closed state dict; never raises.
        """
        trace_id = context.trace_id
        run_id = context.run_id
        agent_type_value = self._profile.agent_type.value

        # Emit run.started (best-effort, never aborts).
        await self._safe_emit(
            run_id=run_id, trace_id=trace_id,
            event_type=RunEventType.RUN_STARTED,
            payload={"agent_type": agent_type_value, "scope": list(context.scope)},
        )

        # Build initial state (may fail if the profile builder raises).
        try:
            if initial_state is not None:
                state = dict(initial_state)
            else:
                state = dict(self._profile.build_initial_state(context, trace_id=trace_id))
            # Ensure RuntimeMeta fields are present.
            state.setdefault("trace_id", trace_id)
            state.setdefault("warnings", [])
            state.setdefault("errors", [])
            state.setdefault("degraded_services", [])
            state.setdefault("trace", [])
        except Exception as error:  # noqa: BLE001 - never raise to caller
            logger.warning(
                "BaseAgentRuntime[%s]: initial state build failed: %s: %s",
                agent_type_value, type(error).__name__, error,
            )
            return self._error_state(
                trace_id=trace_id, run_id=run_id,
                code=ErrorCode.RUNTIME_INITIALIZATION_FAILED,
                error=error, agent_type=agent_type_value,
            )

        # Acquire concurrency slot (if max_concurrency is set) and run with timeout.
        try:
            async with self._limiter.acquire(
                agent_type_value,
                limit=self._profile.max_concurrency,
            ):
                return await self._invoke_with_timeout(
                    state=state, context=context,
                    run_id=run_id, trace_id=trace_id,
                    agent_type=agent_type_value,
                )
        except RuntimeTimeoutError:
            return self._timeout_state(state, trace_id, run_id, agent_type_value)
        except RuntimeCancelledError:
            return self._cancelled_state(state, trace_id, run_id, agent_type_value)
        except AgentRuntimeError as error:
            return self._error_state(
                trace_id=trace_id, run_id=run_id,
                code=error.code, error=error, agent_type=agent_type_value,
                extra_state=state,
            )
        except Exception as error:  # noqa: BLE001 - fail-closed
            return self._error_state(
                trace_id=trace_id, run_id=run_id,
                code=ErrorCode.RUNTIME_INTERNAL_ERROR, error=error,
                agent_type=agent_type_value, extra_state=state,
            )

    async def _invoke_with_timeout(
        self,
        *,
        state: dict[str, Any],
        context: AgentRunContext,
        run_id: str,
        trace_id: str,
        agent_type: str,
    ) -> Mapping[str, Any]:
        """Run the graph with timeout enforcement."""
        started_at = datetime.now(UTC).isoformat()

        if self._timeout is None:
            result = await self._graph.ainvoke(state)
        else:
            try:
                result = await asyncio.wait_for(
                    self._graph.ainvoke(state),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                return self._timeout_state(state, trace_id, run_id, agent_type, started_at)

        # Merge result with meta.
        result = dict(result)
        meta = result.get("meta")
        if isinstance(meta, Mapping):
            # Initial state includes empty top-level runtime lists. LangGraph
            # preserves those keys, so setdefault() would hide errors emitted
            # only inside the canonical meta block.
            for field in ("errors", "warnings", "degraded_services"):
                combined: list[Any] = []
                for item in [
                    *list(result.get(field, [])),
                    *list(meta.get(field, [])),
                ]:
                    if item not in combined:
                        combined.append(item)
                result[field] = combined
            meta_status = meta.get("status")
            if meta_status and meta_status != "ok":
                result["status"] = meta_status
            else:
                result.setdefault("status", meta_status or "ok")
        result.setdefault("trace_id", trace_id)
        result.setdefault("status", "ok")

        # Emit the terminal event that matches the state. Workflow nodes use
        # meta.errors for fail-closed failures, so those must not be reported
        # as successful run.completed events.
        event_type = (
            RunEventType.RUN_FAILED
            if result.get("errors")
            else RunEventType.RUN_COMPLETED
        )
        await self._safe_emit(
            run_id=run_id, trace_id=trace_id,
            event_type=event_type,
            payload={"status": result.get("status", "ok")},
        )
        return result

    # ------------------------------------------------------------------ #
    # Terminal-state builders
    # ------------------------------------------------------------------ #

    @staticmethod
    def _timeout_state(
        state: Mapping[str, Any],
        trace_id: str,
        run_id: str,
        agent_type: str,
        started_at: str | None = None,
    ) -> Mapping[str, Any]:
        return {
            **state,
            "trace_id": trace_id,
            "errors": [*state.get("errors", []), ErrorCode.RUNTIME_TIMEOUT.value],
            "degraded_services": [*state.get("degraded_services", []), "runtime"],
            "status": "timeout",
            "trace": [*state.get("trace", []), {"node": "runtime", "error": "TimeoutError"}],
        }

    @staticmethod
    def _cancelled_state(
        state: Mapping[str, Any],
        trace_id: str,
        run_id: str,
        agent_type: str,
    ) -> Mapping[str, Any]:
        return {
            **state,
            "trace_id": trace_id,
            "errors": [*state.get("errors", []), ErrorCode.RUNTIME_CANCELLED.value],
            "status": "cancelled",
            "trace": [*state.get("trace", []), {"node": "runtime", "error": "CancelledError"}],
        }

    @staticmethod
    def _error_state(
        *,
        trace_id: str,
        run_id: str,
        code: ErrorCode,
        error: BaseException,
        agent_type: str,
        extra_state: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        base = dict(extra_state) if extra_state else {}
        return {
            **base,
            "trace_id": trace_id,
            "errors": [*base.get("errors", []), code.value],
            "status": "runtime_error" if not code.is_hard else "rejected",
            "trace": [*base.get("trace", []), {
                "node": "runtime",
                "error": type(error).__name__,
                "code": code.value,
            }],
        }

    # ------------------------------------------------------------------ #
    # Best-effort event emission
    # ------------------------------------------------------------------ #

    async def _safe_emit(
        self,
        *,
        run_id: str,
        trace_id: str,
        event_type: RunEventType,
        payload: Mapping[str, Any],
    ) -> None:
        """Emit an event; never raise. Failures are logged at debug level."""
        try:
            await self._event_port.emit(
                run_id=run_id, trace_id=trace_id,
                event_type=event_type, payload=payload,
            )
        except Exception:  # noqa: BLE001 - events must not abort runs
            logger.debug(
                "AgentRunEventPort.emit failed for %s (run_id=%s); run continues.",
                event_type.value, run_id,
                exc_info=True,
            )


__all__ = ["BaseAgentRuntime"]
