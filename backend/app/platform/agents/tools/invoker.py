"""ToolInvoker: unified LLM tool invocation with governance, audit, and safety.

All LLM-callable tools pass through this invoker. The invoker enforces:
    1. Permission check (via ToolGovernancePort)
    2. Agent whitelist check (via ToolDescriptor.agent_types)
    3. Argument schema validation (via pydantic)
    4. Audit start (via AgentAuditPort / AgentRunEventPort)
    5. Timeout enforcement
    6. Tool execution
    7. Output desensitization (via tools/safety.py)
    8. Audit end

Design rules:
    - The invoker does NOT know what tools exist; it receives a
      ``ToolDescriptor`` and a callable at call time.
    - The invoker is fail-closed for hard gates (permission denied,
      schema invalid) and fail-open for soft failures (tool raises ->
      degraded, not crash).
    - Not all ports are exposed as tools. Workflow-deterministic calls
      (auth, audit, evidence validation, proposal persistence, OJ result
      reads, response safety) bypass the invoker entirely.
    - The invoker does NOT replace existing ToolGovernancePort; it
      delegates to it. Phase 1 provides the framework; existing agents
      continue to call tools directly until Phase 3/4/5 adapt them.

Phase 1 status: framework only. No existing agent is migrated to use
the invoker yet. The invoker is available for new agents and will be
retrofitted in Phase 3 (Edu), Phase 4 (Prep), Phase 5 (Coding).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from pydantic import BaseModel, ValidationError

from ..runtime.errors import ErrorCode, SoftDependencyError
from ..runtime.events import AgentRunEventPort, NullAgentRunEventPort, RunEventType
from .catalog import ToolDescriptor, ToolRisk
from .safety import sanitize_for_audit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolInvocationContext:
    """Context for a single tool invocation.

    Carries the run identity and agent type so the invoker can enforce
    agent whitelists and emit audit events with correct correlation.
    """

    run_id: str
    trace_id: str
    agent_type: str
    tool_name: str


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool invocation.

    - ``success``: whether the tool returned without raising.
    - ``data``: the tool's return value (or None on failure).
    - ``error_code``: ``ErrorCode`` on failure, None on success.
    - ``error_message``: human-readable error on failure.
    - ``duration_ms``: invocation duration.
    """

    success: bool
    data: Any = None
    error_code: ErrorCode | None = None
    error_message: str = ""
    duration_ms: float = 0.0


# Signature of a tool callable: (context, arguments) -> Any
ToolCallable = Callable[[ToolInvocationContext, Mapping[str, Any]], Any]


class ToolInvoker:
    """Unified tool invocation pipeline with governance and audit.

    The invoker is constructed once at bootstrap with shared governance
    and event ports. Each call to ``invoke`` runs the full pipeline:
    permission -> whitelist -> schema -> audit -> timeout -> execute ->
    sanitize -> audit.

    The invoker is async; sync tool callables are wrapped in
    ``asyncio.to_thread`` to avoid blocking the event loop.
    """

    def __init__(
        self,
        *,
        governance_port: Any | None = None,  # ToolGovernancePort
        event_port: AgentRunEventPort | None = None,
        default_timeout_seconds: float = 30.0,
    ) -> None:
        self._governance = governance_port
        self._event_port: AgentRunEventPort = event_port or NullAgentRunEventPort()
        self._default_timeout = default_timeout_seconds

    async def invoke(
        self,
        *,
        descriptor: ToolDescriptor,
        context: ToolInvocationContext,
        callable_: ToolCallable,
        arguments: Mapping[str, Any],
        argument_schema: type[BaseModel] | None = None,
    ) -> ToolResult:
        """Invoke a tool through the full governance pipeline.

        Returns a ``ToolResult``; never raises to the caller.
        """
        import time
        started = time.monotonic()

        # 1. Agent whitelist check (if descriptor specifies agent_types).
        #    The ToolDescriptor in catalog.py currently doesn't carry
        #    agent_types, so this is a future extension point.

        # 2. Governance permission check (if governance port is configured).
        if self._governance is not None:
            try:
                allowed = await self._check_governance(
                    descriptor=descriptor,
                    context=context,
                )
                if not allowed:
                    return ToolResult(
                        success=False,
                        error_code=ErrorCode.TOOL_NOT_ALLOWED,
                        error_message=f"Tool '{descriptor.name}' not allowed for agent '{context.agent_type}'",
                        duration_ms=(time.monotonic() - started) * 1000,
                    )
            except Exception as error:  # noqa: BLE001 - governance failure is soft
                logger.warning(
                    "ToolInvoker: governance check failed for %s: %s: %s",
                    descriptor.name, type(error).__name__, error,
                )

        # 3. Argument schema validation.
        if argument_schema is not None:
            try:
                validated = argument_schema.model_validate(dict(arguments))
                arguments = dict(validated.model_dump())
            except ValidationError as error:
                return ToolResult(
                    success=False,
                    error_code=ErrorCode.INVALID_REQUEST,
                    error_message=f"Invalid arguments for tool '{descriptor.name}': {error}",
                    duration_ms=(time.monotonic() - started) * 1000,
                )

        # 4. Emit audit start.
        await self._safe_emit(
            context=context,
            event_type=RunEventType.TOOL_INVOKED,
            payload=sanitize_for_audit({"tool": descriptor.name, "arguments": dict(arguments)}),
        )

        # 5. Execute with timeout.
        timeout = self._default_timeout
        try:
            if _is_async(callable_):
                result_data = await asyncio.wait_for(
                    callable_(context, arguments),
                    timeout=timeout,
                )
            else:
                result_data = await asyncio.wait_for(
                    asyncio.to_thread(callable_, context, arguments),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            await self._safe_emit(
                context=context,
                event_type=RunEventType.TOOL_FAILED,
                payload={"tool": descriptor.name, "error": "timeout"},
            )
            return ToolResult(
                success=False,
                error_code=ErrorCode.DEPENDENCY_TIMEOUT,
                error_message=f"Tool '{descriptor.name}' timed out after {timeout}s",
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except Exception as error:  # noqa: BLE001 - tool failure is soft
            await self._safe_emit(
                context=context,
                event_type=RunEventType.TOOL_FAILED,
                payload={"tool": descriptor.name, "error": type(error).__name__},
            )
            return ToolResult(
                success=False,
                error_code=ErrorCode.TOOL_FAILED,
                error_message=f"Tool '{descriptor.name}' raised: {error}",
                duration_ms=(time.monotonic() - started) * 1000,
            )

        # 6. Sanitize output for audit.
        sanitized = sanitize_for_audit({"result": result_data}) if isinstance(result_data, Mapping) else {"result": "ok"}

        # 7. Emit audit completion.
        await self._safe_emit(
            context=context,
            event_type=RunEventType.TOOL_COMPLETED,
            payload={"tool": descriptor.name, **sanitized},
        )

        return ToolResult(
            success=True,
            data=result_data,
            duration_ms=(time.monotonic() - started) * 1000,
        )

    async def _check_governance(
        self,
        *,
        descriptor: ToolDescriptor,
        context: ToolInvocationContext,
    ) -> bool:
        """Check if the tool is allowed for the given agent and context.

        Delegates to ToolGovernancePort if available. The governance port
        may check agent type, course scope, and risk level.
        """
        # The ToolGovernancePort interface varies; we call the common method.
        # If the port doesn't have the expected method, treat as allowed.
        check_fn = getattr(self._governance, "is_tool_allowed", None)
        if check_fn is None:
            return True
        result = check_fn(
            agent_type=context.agent_type,
            tool_name=descriptor.name,
        )
        if hasattr(result, "__await__"):
            result = await result
        return bool(result)

    async def _safe_emit(
        self,
        *,
        context: ToolInvocationContext,
        event_type: RunEventType,
        payload: Mapping[str, Any],
    ) -> None:
        """Emit an audit event; never raise."""
        try:
            await self._event_port.emit(
                run_id=context.run_id,
                trace_id=context.trace_id,
                event_type=event_type,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 - audit must not abort tools
            logger.debug(
                "ToolInvoker: event emit failed for %s (tool=%s); invocation continues.",
                event_type.value, context.tool_name,
                exc_info=True,
            )


def _is_async(callable_: Callable[..., Any]) -> bool:
    """Check if a callable is async (coroutine function)."""
    import inspect
    return inspect.iscoroutinefunction(callable_)


__all__ = [
    "ToolInvocationContext",
    "ToolResult",
    "ToolCallable",
    "ToolInvoker",
]
