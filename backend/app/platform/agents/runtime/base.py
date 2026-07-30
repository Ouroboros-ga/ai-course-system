"""Generic LangGraph agent runtime.

The generic runtime wraps any compiled LangGraph workflow and provides:
    - common field initialization (``trace_id``, ``warnings``, ``errors``, ...)
    - per-call timeout enforcement (optional)
    - request-scoped trace propagation
    - fail-closed error handling that never raises to the caller

Design rules (per adopted migration plan):
    - The runtime does NOT own tool instances; it only holds a compiled graph.
      Tool assembly is the responsibility of the agent-specific composition
      root (see ``ToolCatalog`` for description/assembly metadata).
    - The runtime does NOT replace ``ConversationContextPort``; persistence of
      session summaries stays an agent-specific concern.
    - The runtime does NOT generalize ``student_id`` to ``actor_id``; the
      execution context preserves domain-specific identifiers and only the
      governance/audit ports use generic actor semantics.
    - Cache keys (``RuntimeKey``) need not permanently carry ``actor_id``;
      agents that do not need per-actor isolation use a coarser scope.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Mapping, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class RunnableGraph(Protocol):
    """Minimal protocol satisfied by a compiled LangGraph workflow."""

    async def ainvoke(self, input: Mapping[str, Any], config: Any = ...) -> Mapping[str, Any]: ...


class AgentRunContext:
    """Request-scoped execution context.

    Carries the caller-provided identifiers into the runtime. The runtime
    copies these into the initial state under domain-specific keys; it does
    NOT rename ``student_id`` to ``actor_id``. Agents that do not have a
    ``student_id`` (e.g. 备课 agent operating on a draft) leave it ``None``.
    """

    __slots__ = (
        "agent_type",
        "scope",
        "session_id",
        "student_id",
        "course_id",
        "teacher_id",
        "user_message",
        "resource_id",
        "exercise_id",
        "code_submission_id",
        "extras",
    )

    def __init__(
        self,
        *,
        agent_type: str,
        scope: tuple[str, ...] = (),
        session_id: str | None = None,
        student_id: str | None = None,
        course_id: str | None = None,
        teacher_id: str | None = None,
        user_message: str | None = None,
        resource_id: str | None = None,
        exercise_id: str | None = None,
        code_submission_id: str | None = None,
        extras: Mapping[str, Any] | None = None,
    ) -> None:
        self.agent_type = agent_type
        self.scope = tuple(scope)
        self.session_id = session_id
        self.student_id = student_id
        self.course_id = course_id
        self.teacher_id = teacher_id
        self.user_message = user_message
        self.resource_id = resource_id
        self.exercise_id = exercise_id
        self.code_submission_id = code_submission_id
        self.extras: Mapping[str, Any] = dict(extras) if extras else {}

    def trace_id(self) -> str:
        return str(uuid.uuid4())


class LangGraphAgentRuntime:
    """Generic runtime wrapping a compiled LangGraph workflow.

    The runtime is agnostic of the agent type. An ``AgentProfile`` describes
    how to build the initial state from an ``AgentRunContext`` and which
    common fields to initialize. The actual workflow graph is supplied by
    the agent's composition root.

    Contract:
        - ``respond(ctx)`` never raises; failures land in ``state["errors"]``
          with a ``status`` field identifying the failure mode.
        - Optional ``timeout_seconds`` cancels the underlying ``ainvoke``;
          timeout is recorded as a degraded service, not an exception.
    """

    def __init__(
        self,
        *,
        graph: RunnableGraph,
        profile: "AgentProfile",  # noqa: F821 - forward ref to .profile
        timeout_seconds: float | None = None,
    ) -> None:
        self._graph = graph
        self._profile = profile
        self._timeout = timeout_seconds

    async def respond(self, ctx: AgentRunContext) -> Mapping[str, Any]:
        """Invoke the wrapped graph with a profile-built initial state.

        The profile's ``build_initial_state`` is responsible for mapping the
        context's domain-specific identifiers into the agent's state schema.
        The runtime only adds ``trace_id`` and fail-closed error handling.
        """
        trace_id = ctx.trace_id()
        try:
            initial = self._profile.build_initial_state(ctx, trace_id=trace_id)
        except Exception as error:  # noqa: BLE001 - never raise to caller
            logger.warning(
                "AgentRuntime[%s]: initial state build failed: %s: %s",
                self._profile.agent_type, type(error).__name__, error,
            )
            return {
                "trace_id": trace_id,
                "errors": ["RUNTIME_STATE_BUILD_FAILED"],
                "status": "runtime_error",
                "trace": [{"node": "runtime", "error": type(error).__name__}],
            }

        if self._timeout is None:
            try:
                return await self._graph.ainvoke(initial)
            except asyncio.TimeoutError:
                return self._timeout_payload(initial, trace_id)
            except Exception as error:  # noqa: BLE001 - fail-closed
                return self._error_payload(initial, trace_id, error)
        else:
            try:
                return await asyncio.wait_for(
                    self._graph.ainvoke(initial), timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                return self._timeout_payload(initial, trace_id)
            except Exception as error:  # noqa: BLE001 - fail-closed
                return self._error_payload(initial, trace_id, error)

    @staticmethod
    def _timeout_payload(state: Mapping[str, Any], trace_id: str) -> Mapping[str, Any]:
        return {
            **state,
            "trace_id": trace_id,
            "errors": [*state.get("errors", []), "RUNTIME_TIMEOUT"],
            "degraded_services": [*state.get("degraded_services", []), "runtime"],
            "status": "timeout",
            "trace": [*state.get("trace", []), {"node": "runtime", "error": "TimeoutError"}],
        }

    @staticmethod
    def _error_payload(state: Mapping[str, Any], trace_id: str, error: BaseException) -> Mapping[str, Any]:
        return {
            **state,
            "trace_id": trace_id,
            "errors": [*state.get("errors", []), "RUNTIME_INTERNAL_ERROR"],
            "status": "runtime_error",
            "trace": [*state.get("trace", []), {"node": "runtime", "error": type(error).__name__}],
        }
