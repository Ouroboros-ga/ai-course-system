"""Agent run event and store ports.

These ports define the persistence interface for agent run lifecycle
events. The runtime emits events (started, node_entered, node_exited,
completed, failed, cancelled) that an ``AgentRunStorePort`` implementation
persists for audit, observability, and resumption.

Design rules:
    - These are Protocol definitions (contracts), not implementations.
    - Implementations live in ``providers/`` and are injected at bootstrap.
    - The runtime calls these ports but does NOT depend on any specific
      storage backend (DB, file, in-memory).
    - Events are append-only; the store never mutates past events.
    - Sensitive data (API keys, hidden tests, full code) must be redacted
      before persistence; see ``tools/safety.py`` for redaction helpers.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable


class RunStatus(str, Enum):
    """Lifecycle status of an agent run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    QUEUED = "queued"


class RunEventType(str, Enum):
    """Types of events emitted during an agent run."""

    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_TIMEOUT = "run.timeout"
    NODE_ENTERED = "node.entered"
    NODE_EXITED = "node.exited"
    TOOL_INVOKED = "tool.invoked"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    DEGRADED = "service.degraded"


@runtime_checkable
class AgentRunEventPort(Protocol):
    """Emit agent run lifecycle events.

    The runtime calls ``emit`` at each lifecycle transition. Implementations
    are expected to be non-blocking; failures in event emission must NOT
    abort the agent run (fail-closed for the run, fail-open for events).
    """

    async def emit(
        self,
        *,
        run_id: str,
        trace_id: str,
        event_type: RunEventType,
        payload: Mapping[str, Any],
    ) -> None:
        """Emit one lifecycle event. Must not raise."""
        ...


@runtime_checkable
class AgentRunStorePort(Protocol):
    """Persist and query agent run records.

    The store is the source of truth for run status, enabling:
        - Queue workers to resume after crash
        - API endpoints to poll run status
        - Audit to reconstruct run history

    Implementations must be idempotent: re-writing the same run_id with
    the same status is a no-op, not an error.
    """

    async def create_run(
        self,
        *,
        run_id: str,
        trace_id: str,
        agent_type: str,
        actor_id: str,
        actor_type: str,
        course_id: str | None,
        config_version: str,
        idempotency_key: str | None = None,
    ) -> None:
        """Create a new run record. Idempotent on run_id."""
        ...

    async def update_status(
        self,
        *,
        run_id: str,
        status: RunStatus,
        errors: list[Mapping[str, Any]] | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> None:
        """Update the terminal status of a run. Idempotent."""
        ...

    async def get_run(self, *, run_id: str) -> Mapping[str, Any] | None:
        """Read a run record by run_id. Returns None if not found."""
        ...

    async def list_runs(
        self,
        *,
        agent_type: str | None = None,
        actor_id: str | None = None,
        course_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        """List runs matching the given filters."""
        ...


class NullAgentRunEventPort:
    """No-op event port for environments without event persistence.

    This implementation silently drops all events. It is suitable for:
        - Local development
        - Unit tests
        - Environments where run lifecycle events are not required

    Production WARNING:
        Using this in production means agent runs have NO event trail.
        The ``AgentConfigurationError`` validation will flag agents that
        declare capabilities requiring events (e.g. checkpoint) while
        only a Null port is wired. For agents without such capabilities,
        Null is acceptable but means no observability.

    To use in tests/dev: pass an instance directly.
    To prevent accidental production use: bootstrap validates that
    production agents have real ports when capabilities require them.
    """

    async def emit(
        self,
        *,
        run_id: str,
        trace_id: str,
        event_type: RunEventType,
        payload: Mapping[str, Any],
    ) -> None:
        pass


class NullAgentRunStorePort:
    """No-op run store for environments without run persistence.

    See ``NullAgentRunEventPort`` for usage and production warnings.
    """

    async def create_run(self, **kwargs: Any) -> None:
        pass

    async def update_status(self, **kwargs: Any) -> None:
        pass

    async def get_run(self, *, run_id: str) -> Mapping[str, Any] | None:
        return None

    async def list_runs(self, **kwargs: Any) -> list[Mapping[str, Any]]:
        return []


__all__ = [
    "RunStatus",
    "RunEventType",
    "AgentRunEventPort",
    "AgentRunStorePort",
    "NullAgentRunEventPort",
    "NullAgentRunStorePort",
]
