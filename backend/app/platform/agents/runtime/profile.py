"""Agent profiles and runtime cache keys.

An ``AgentProfile`` declaratively describes an agent's:
    - ``agent_type`` (``AgentType`` enum)
    - ``build_initial_state``: how to map an ``AgentRunContext`` to the
      agent's state schema (the agent keeps its own State TypedDict; the runtime
      does not impose a unified state)
    - ``default_timeout_seconds``: optional per-agent timeout
    - ``max_concurrency``: max concurrent runs for this agent type
    - ``execution_mode``: inline / queued / hybrid
    - ``supports_*``: capability flags for streaming, checkpoint, interrupt
    - ``allowed_tool_names``: frozenset of tool names the agent may call

``RuntimeKey`` is the cache key for runtime instances. Per the adopted plan,
the key need NOT permanently carry ``actor_id``. Agents that need per-actor
isolation (e.g. TeachingAgent) include ``(student_id, course_id)`` in
``scope``; agents that operate at course level (e.g. 备课 agent) use a
coarser ``scope`` like ``(course_id,)`` or ``(draft_id,)``.

Phase 1 backward compatibility:
    The new fields (``max_concurrency``, ``execution_mode``, ``supports_*``,
    ``allowed_tool_names``) all have *loose* defaults so existing profile
    constructors (edu/prep/coding) continue to work without changes. The
    defaults are intentionally permissive to preserve existing behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping


class AgentType(str, Enum):
    """Stable identifiers for the three integrated agents."""

    EDU = "edu"        # TeachingAgent: per-(student, course) Q&A
    PREP = "prep"      # 备课 Agent: per-draft/outline-node planning
    CODING = "coding"  # Coding Agent: per-(student, course) code diagnosis


class ExecutionMode(str, Enum):
    """How an agent run is dispatched.

    - ``INLINE``: synchronous within the HTTP request (Edu Q&A).
    - ``QUEUED``: dispatched to a durable worker (initial Prep build).
    - ``HYBRID``: inline by default, queued for long operations.
    """

    INLINE = "inline"
    QUEUED = "queued"
    HYBRID = "hybrid"


# Initial-state builder signature: (ctx, trace_id) -> dict
InitialStateBuilder = Callable[["AgentRunContext", str], Mapping[str, Any]]


@dataclass(frozen=True)
class AgentProfile:
    """Declarative description of how to run one agent type.

    The profile is the only place that knows the agent's state schema. The
    generic runtime uses ``build_initial_state`` to translate a context into
    that schema without coupling itself to any specific TypedDict.

    New fields (Phase 1) have loose defaults:
        - ``max_concurrency`` defaults to 256 (effectively unlimited).
        - ``execution_mode`` defaults to ``INLINE``.
        - ``supports_streaming`` / ``supports_checkpoint`` / ``supports_interrupt``
          default to ``False``.
        - ``allowed_tool_names`` defaults to empty (no restriction enforced
          by the runtime; governance is delegated to ToolGovernancePort).

    These defaults ensure existing profile constructors in edu/prep/coding
    continue to work without modification.
    """

    agent_type: AgentType
    build_initial_state: InitialStateBuilder
    default_timeout_seconds: float | None = None
    # Human-readable description for tracing/observability only.
    description: str = ""

    # --- Phase 1 extensions ---
    # ``max_concurrency`` defaults to None: the runtime does NOT impose its
    # own limit. This preserves existing behavior (no limit) rather than
    # silently introducing a 256-wide semaphore that could allow 256
    # concurrent LLM calls. Real limits are set per-agent at bootstrap:
    #   - Edu Q&A: ~20
    #   - Prep inline: ~3
    #   - Coding explain: ~10
    # Provider-level bulkheads (LLM pool, DB pool, Judge0) are separate.
    max_concurrency: int | None = None
    execution_mode: ExecutionMode = ExecutionMode.INLINE
    supports_streaming: bool = False
    supports_checkpoint: bool = False
    supports_interrupt: bool = False
    allowed_tool_names: frozenset[str] = field(default_factory=frozenset)

    # ``share_runtime_across_actors``: whether the runtime built from this
    # profile is safe to share across different actors (students/teachers).
    #
    # THIS IS A HARD GATE against state cross-contamination. The EDU agent
    # currently binds KG-MEST student reports at runtime construction time,
    # so sharing its runtime across students would mix their cognitive state.
    # Until Phase 2b moves KG-MEST reads to call time, EDU MUST keep this
    # set to ``False``.
    #
    # Prep and Coding agents that do not bind per-actor state at construction
    # may set this to ``True`` to enable definition-keyed caching.
    share_runtime_across_actors: bool = False

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
