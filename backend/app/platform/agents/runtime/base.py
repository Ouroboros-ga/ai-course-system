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

    Identity fields (single source of truth):
        - ``student_id`` / ``teacher_id`` / ``course_id`` / ``session_id``:
          domain-specific identifiers. These ARE the facts; ``actor`` is
          derived from them and MUST NOT be set independently.
        - ``actor``: READ-ONLY property derived from teacher_id/student_id.
          Governance/audit ports use ``ctx.actor``; domain nodes use the
          domain IDs directly. Never pass ``actor`` to the constructor.

    Runtime identity fields:
        - ``run_id``: stable run identifier for audit/metrics. Auto-generated
          if not provided.
        - ``trace_id``: per-run trace identifier. Auto-generated if not
          provided. This is a *property*, not a method, to avoid the
          method/field name collision that occurred when both ``trace_id``
          field and ``trace_id()`` method existed.
        - ``config_version``: configuration version that built the runtime.

    Optional execution hint fields (no domain semantics):
        - ``idempotency_key``: optional idempotency key for deduplication.
        - ``task_id``: optional task identifier for queued execution.

    Domain-specific routing (Prep's initial vs incremental, Coding's hint
    level, etc.) is NOT carried in this context. Domain payloads pass
    through ``extras`` and are interpreted by the gateway/agent-specific
    composition root. This prevents the generic context from accumulating
    agent-specific fields.
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
        # Runtime identity (lazily generated)
        "_run_id",
        "_trace_id",
        "config_version",
        # Optional execution hints
        "idempotency_key",
        "task_id",
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
        # Runtime identity (all optional, backward compatible)
        run_id: str | None = None,
        trace_id: str | None = None,
        config_version: str = "v1",
        # Optional execution hints
        idempotency_key: str | None = None,
        task_id: str | None = None,
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
        # Runtime identity
        self._run_id = run_id
        self._trace_id = trace_id
        self.config_version = config_version
        # Optional execution hints
        self.idempotency_key = idempotency_key
        self.task_id = task_id

    @property
    def run_id(self) -> str:
        """Stable run identifier, lazily generated and cached."""
        if self._run_id is None:
            self._run_id = f"run_{uuid.uuid4().hex[:16]}"
        return self._run_id

    @property
    def trace_id(self) -> str:
        """Per-run trace identifier, lazily generated and cached.

        This is a *property* (not a method) so that ``ctx.trace_id`` is
        consistent with other field accesses and avoids the method/field
        name collision that occurred when both existed.
        """
        if self._trace_id is None:
            self._trace_id = str(uuid.uuid4())
        return self._trace_id

    @property
    def actor(self) -> "AgentActor":
        """Derive an ``AgentActor`` for governance/audit (READ-ONLY).

        Derived from domain IDs; preference order: teacher_id > student_id
        > system. This does NOT replace domain IDs; it only provides a
        generic view for cross-cutting concerns. The actor is NOT settable
        — to change the actor, set ``teacher_id`` or ``student_id``.
        """
        from .context import AgentActor  # local import to avoid cycle

        if self.teacher_id:
            return AgentActor.teacher(self.teacher_id)
        if self.student_id:
            return AgentActor.student(self.student_id)
        return AgentActor.system()


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
        trace_id = ctx.trace_id
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
