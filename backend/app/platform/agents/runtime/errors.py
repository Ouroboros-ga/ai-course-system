"""Runtime error layer.

Re-exports the existing agent errors for backward compatibility and adds
generic runtime-level errors that are not specific to any one agent.

Existing agent errors remain at ``app.platform.agents.errors`` and continue
to be the canonical home for ``TeachingAgentError`` and subclasses. This
module is the runtime-facing view; it must not duplicate error codes.
"""

from __future__ import annotations

from ..errors import (
    LLMUnavailableError,
    RequestValidationError,
    ScopeRejectedError,
    ServiceUnavailableError,
    TeachingAgentError,
)


class AgentRuntimeError(Exception):
    """Generic runtime-level error, not tied to a specific agent.

    Use this for failures in the runtime layer itself (cache, timeout,
    profile resolution). Agent-specific failures keep using their existing
    error classes (e.g. ``TeachingAgentError``).
    """

    code = "AGENT_RUNTIME_ERROR"


class RuntimeTimeoutError(AgentRuntimeError):
    code = "RUNTIME_TIMEOUT"


class RuntimeInitializationError(AgentRuntimeError):
    code = "RUNTIME_INITIALIZATION_FAILED"


__all__ = [
    # Re-exported legacy errors (compatibility)
    "TeachingAgentError",
    "RequestValidationError",
    "ScopeRejectedError",
    "ServiceUnavailableError",
    "LLMUnavailableError",
    # New generic runtime errors
    "AgentRuntimeError",
    "RuntimeTimeoutError",
    "RuntimeInitializationError",
]
