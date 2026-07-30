"""Runtime error layer with unified error taxonomy.

Re-exports the existing agent errors for backward compatibility and adds
generic runtime-level errors plus a stable error-code taxonomy used across
all three agents (EDU / PREP / CODING).

Design rules:
    - Agent-specific failures keep using their existing error classes
      (e.g. ``TeachingAgentError``).
    - Runtime-layer failures use ``AgentRuntimeError`` subclasses defined here.
    - The ``ErrorCode`` enum is the single source of truth for stable error
      codes that may surface in API responses, audit records, and metrics.
    - Error codes are grouped into HARD (must abort) and SOFT (may degrade)
      categories; see the migration design's error section.

Backward compatibility:
    ``from app.platform.agents.runtime.errors import TeachingAgentError``
    continues to work.
"""

from __future__ import annotations

from enum import Enum

from ..errors import (
    LLMUnavailableError,
    RequestValidationError,
    ScopeRejectedError,
    ServiceUnavailableError,
    TeachingAgentError,
)


class ErrorCode(str, Enum):
    """Stable error codes for agent runs, audit records, and metrics.

    Grouped by severity:
        - ``HARD_*``: hard-gate violations that must abort the run.
        - ``SOFT_*``: soft-dependency failures that may degrade.
        - ``RUNTIME_*``: runtime-layer failures (timeout, cancel, internal).
    """

    # --- Hard gates (abort) ---
    INVALID_REQUEST = "INVALID_REQUEST"
    ACCESS_DENIED = "ACCESS_DENIED"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    EVIDENCE_VIOLATION = "EVIDENCE_VIOLATION"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"
    CHECKPOINT_FAILED = "CHECKPOINT_FAILED"

    # --- Soft dependencies (degrade) ---
    DEPENDENCY_TIMEOUT = "DEPENDENCY_TIMEOUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    TOOL_FAILED = "TOOL_FAILED"

    # --- Runtime layer ---
    RUNTIME_TIMEOUT = "RUNTIME_TIMEOUT"
    RUNTIME_CANCELLED = "RUNTIME_CANCELLED"
    RUNTIME_INTERNAL_ERROR = "RUNTIME_INTERNAL_ERROR"
    RUNTIME_INITIALIZATION_FAILED = "RUNTIME_INITIALIZATION_FAILED"
    AGENT_NOT_AVAILABLE = "AGENT_NOT_AVAILABLE"

    @property
    def is_hard(self) -> bool:
        """Whether this code represents a hard-gate violation that must abort."""
        return self in _HARD_CODES

    @property
    def is_soft(self) -> bool:
        """Whether this code represents a soft-dependency failure that may degrade."""
        return self in _SOFT_CODES


_HARD_CODES = frozenset({
    ErrorCode.INVALID_REQUEST,
    ErrorCode.ACCESS_DENIED,
    ErrorCode.SCOPE_VIOLATION,
    ErrorCode.EVIDENCE_VIOLATION,
    ErrorCode.TOOL_NOT_ALLOWED,
    ErrorCode.INVALID_MODEL_OUTPUT,
    ErrorCode.CHECKPOINT_FAILED,
})

_SOFT_CODES = frozenset({
    ErrorCode.DEPENDENCY_TIMEOUT,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
    ErrorCode.TOOL_FAILED,
})


class AgentRuntimeError(Exception):
    """Generic runtime-level error, not tied to a specific agent.

    Use this for failures in the runtime layer itself (cache, timeout,
    profile resolution). Agent-specific failures keep using their existing
    error classes (e.g. ``TeachingAgentError``).
    """

    code: ErrorCode = ErrorCode.RUNTIME_INTERNAL_ERROR

    def __init__(self, message: str = "", *, code: ErrorCode | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class RuntimeTimeoutError(AgentRuntimeError):
    code = ErrorCode.RUNTIME_TIMEOUT


class RuntimeCancelledError(AgentRuntimeError):
    code = ErrorCode.RUNTIME_CANCELLED


class AgentConfigurationError(Exception):
    """Raised at startup when an agent declares a capability without backing infrastructure.

    This is a *startup-time* hard gate: it must surface before any run is
    dispatched, so the system never enters a state where a profile claims
    ``supports_checkpoint=True`` but only a ``NullCheckpointPort`` is wired.

    Checks enforced:
        - ``supports_checkpoint=True`` requires a non-null CheckpointPort.
        - ``execution_mode=QUEUED`` requires a queue provider.
        - ``allowed_tool_names`` non-empty requires a ToolInvoker.
        - ``max_concurrency`` set requires a concurrency limiter.

    This error is NOT raised at run time; it is raised by
    ``validate_agent_configuration()`` called from bootstrap.
    """


class RuntimeInitializationError(AgentRuntimeError):
    code = ErrorCode.RUNTIME_INITIALIZATION_FAILED


class AgentNotAvailableError(AgentRuntimeError):
    code = ErrorCode.AGENT_NOT_AVAILABLE


class HardGateError(AgentRuntimeError):
    """A hard-gate violation that must abort the run (e.g. evidence violation)."""

    code: ErrorCode

    def __init__(self, message: str = "", *, code: ErrorCode) -> None:
        super().__init__(message)
        self.code = code


class SoftDependencyError(AgentRuntimeError):
    """A soft-dependency failure that may degrade (e.g. KG-MEST unavailable)."""

    code: ErrorCode

    def __init__(self, message: str = "", *, code: ErrorCode) -> None:
        super().__init__(message)
        self.code = code


__all__ = [
    # Re-exported legacy errors (compatibility)
    "TeachingAgentError",
    "RequestValidationError",
    "ScopeRejectedError",
    "ServiceUnavailableError",
    "LLMUnavailableError",
    # Error taxonomy
    "ErrorCode",
    # New generic runtime errors
    "AgentRuntimeError",
    "RuntimeTimeoutError",
    "RuntimeCancelledError",
    "RuntimeInitializationError",
    "AgentNotAvailableError",
    "HardGateError",
    "SoftDependencyError",
    # Startup-time configuration validation
    "AgentConfigurationError",
]
