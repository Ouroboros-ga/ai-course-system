"""Agent profiles and runtime cache keys.

An ``AgentProfile`` declaratively describes an agent's:
    - ``agent_type`` (``AgentType`` enum)
    - ``build_initial_state``: how to map an ``AgentRunContext`` to the agent's
      state schema (the agent keeps its own State TypedDict; the runtime does
      not impose a unified state)
    - ``default_timeout_seconds``: optional per-agent timeout

``RuntimeKey`` is the cache key for runtime instances. Per the adopted plan,
the key need NOT permanently carry ``actor_id``. Agents that need per-actor
isolation (e.g. TeachingAgent) include ``(student_id, course_id)`` in
``scope``; agents that operate at course level (e.g. 备课 agent) use a
coarser ``scope`` like ``(course_id,)`` or ``(draft_id,)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping


class AgentType(str, Enum):
    """Stable identifiers for the three integrated agents."""

    EDU = "edu"        # TeachingAgent: per-(student, course) Q&A
    PREP = "prep"      # 备课 Agent: per-draft/outline-node planning
    CODING = "coding"  # Coding Agent: per-(student, course) code diagnosis


# Initial-state builder signature: (ctx, trace_id) -> dict
InitialStateBuilder = Callable[["AgentRunContext", str], Mapping[str, Any]]


@dataclass(frozen=True)
class AgentProfile:
    """Declarative description of how to run one agent type.

    The profile is the only place that knows the agent's state schema. The
    generic runtime uses ``build_initial_state`` to translate a context into
    that schema without coupling itself to any specific TypedDict.
    """

    agent_type: AgentType
    build_initial_state: InitialStateBuilder
    default_timeout_seconds: float | None = None
    # Human-readable description for tracing/observability only.
    description: str = ""

    def runtime_key(self, scope: tuple[str, ...], config_version: str = "v1") -> "RuntimeKey":
        return RuntimeKey(
            agent_type=self.agent_type,
            scope=scope,
            config_version=config_version,
        )


@dataclass(frozen=True)
class RuntimeKey:
    """Cache key for runtime instances.

    Equality and hashability are derived from ``(agent_type, scope,
    config_version)``. The key is intentionally a value object so caches can
    use it directly without deep comparisons of dependency graphs.
    """

    agent_type: AgentType
    scope: tuple[str, ...]
    config_version: str = "v1"

    def __post_init__(self) -> None:
        # Defensive normalization: scope must be a tuple of strings.
        if not isinstance(self.scope, tuple):
            raise TypeError(f"RuntimeKey.scope must be tuple, got {type(self.scope).__name__}")
        for item in self.scope:
            if not isinstance(item, str):
                raise TypeError("RuntimeKey.scope must contain only strings")

    def __str__(self) -> str:
        scope_repr = "/".join(self.scope) if self.scope else "_"
        return f"{self.agent_type.value}:{scope_repr}:{self.config_version}"
