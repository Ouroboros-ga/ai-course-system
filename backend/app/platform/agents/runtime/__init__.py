"""Agent Runtime package.

Provides a generic LangGraph-based runtime that can host any agent workflow,
alongside the legacy ``TeachingAgentRuntime`` for backward compatibility.

Public API (stable):
    - ``TeachingAgentRuntime``: legacy per-course/student runtime (Commit 1 keeps it)
    - ``LangGraphAgentRuntime``: generic runtime wrapping a compiled LangGraph
    - ``BaseAgentRuntime``: Phase 1 unified runtime with timeout/concurrency/events
    - ``AgentProfile``, ``AgentType``, ``ExecutionMode``: declarative agent description
    - ``RuntimeKey``: cache key for runtime instances (scope-based)
    - ``AgentDefinitionKey``: cache key for stateless runtimes (definition-based)
    - ``AgentRuntimeRegistry``: definition-keyed runtime cache
    - ``AgentRunContext``: request-scoped execution context
    - ``AgentActor``, ``ActorType``: generic actor identity for audit/governance
    - ``AgentConcurrencyLimiter``: per-agent-type concurrency bounding
    - ``AgentRunEventPort``, ``AgentRunStorePort``, ``RunStatus``, ``RunEventType``
    - ``CheckpointPort``, ``NullCheckpointPort``: durable resumption protocol
    - ``ErrorCode`` + error classes: unified error taxonomy

Backward compatibility:
    ``from app.platform.agents.runtime import TeachingAgentRuntime`` continues to
    work because ``__init__`` re-exports it from ``.teaching_runtime``.
"""

from __future__ import annotations

from .base import AgentRunContext, LangGraphAgentRuntime, RunnableGraph
from .checkpoint import CheckpointPort, NullCheckpointPort
from .concurrency import AgentConcurrencyLimiter
from .context import ActorType, AgentActor
from .dispatcher import BaseAgentRuntime
from .errors import (
    AgentConfigurationError,
    AgentNotAvailableError,
    AgentRuntimeError,
    ErrorCode,
    HardGateError,
    RuntimeCancelledError,
    RuntimeInitializationError,
    RuntimeTimeoutError,
    SoftDependencyError,
)
from .events import (
    AgentRunEventPort,
    AgentRunStorePort,
    NullAgentRunEventPort,
    NullAgentRunStorePort,
    RunEventType,
    RunStatus,
)
from .profile import AgentProfile, AgentType, ExecutionMode, RuntimeKey
from .registry import AgentDefinitionKey, AgentRuntimeRegistry
from .teaching_runtime import TeachingAgentRuntime
from .validation import validate_agent_configuration, validate_platform_configuration

__all__ = [
    # Legacy runtime (compat)
    "TeachingAgentRuntime",
    # Generic runtime
    "LangGraphAgentRuntime",
    "BaseAgentRuntime",
    "RunnableGraph",
    # Profile & keys
    "AgentProfile",
    "AgentType",
    "ExecutionMode",
    "RuntimeKey",
    "AgentDefinitionKey",
    "AgentRuntimeRegistry",
    # Context & actor
    "AgentRunContext",
    "AgentActor",
    "ActorType",
    # Concurrency
    "AgentConcurrencyLimiter",
    # Events
    "AgentRunEventPort",
    "AgentRunStorePort",
    "NullAgentRunEventPort",
    "NullAgentRunStorePort",
    "RunStatus",
    "RunEventType",
    # Checkpoint
    "CheckpointPort",
    "NullCheckpointPort",
    # Errors
    "ErrorCode",
    "AgentRuntimeError",
    "RuntimeTimeoutError",
    "RuntimeCancelledError",
    "RuntimeInitializationError",
    "AgentNotAvailableError",
    "HardGateError",
    "SoftDependencyError",
    "AgentConfigurationError",
    # Validation
    "validate_agent_configuration",
    "validate_platform_configuration",
]
