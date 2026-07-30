"""AgentPlatform: unified platform for all agent runtimes.

The platform is the single entry point for agent-runtime resolution across
the three integrated agents (EDU, PREP, CODING). It assembles:

    - ``AgentRuntimeRegistry``: definition-keyed cache of stateless runtimes.
    - ``AgentGateway``: unified run lifecycle entry point.
    - ``ProviderContainer``: process-level provider assembly.
    - ``ToolCatalog``: tool description and assembly metadata.
    - Legacy resolver: for EDU agent until Phase 2b/3 migration.

Design rules (per adopted migration plan + Phase 1 infrastructure):
    - The platform does NOT replace ``TeachingAgentRuntimeRegistry``; it
      wraps it. Existing endpoint code that calls ``registry.get_or_create``
      continues to work unchanged.
    - The platform does NOT own tool instances; builders are responsible
      for wiring tools into the compiled graph.
    - Cache keys (``RuntimeKey``) need not permanently carry ``actor_id``;
      agents that do not need per-actor isolation use a coarser scope.
    - The platform is fail-closed: unavailable agents return ``None``,
      never raise.
    - New components (Gateway, RuntimeRegistry, ProviderContainer) are
      optional and nullable so the platform can be built incrementally.

Registration is done at bootstrap time (see ``bootstrap.py``). The platform
is stored on ``app.state.agent_platform`` and is optional — endpoints that
have not been migrated to the platform continue to use the legacy registry
directly.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional, Protocol, runtime_checkable

from .gateway import AgentGateway
from .runtime.base import AgentRunContext, LangGraphAgentRuntime, RunnableGraph
from .runtime.concurrency import AgentConcurrencyLimiter
from .runtime.dispatcher import BaseAgentRuntime
from .runtime.events import AgentRunEventPort, NullAgentRunEventPort
from .runtime.profile import AgentProfile, AgentType, RuntimeKey
from .runtime.registry import AgentDefinitionKey, AgentRuntimeRegistry

logger = logging.getLogger(__name__)

# A legacy resolver takes (student_id, course_id) and returns a runtime or None.
# This matches TeachingAgentRuntimeRegistry.get_or_create's signature.
LegacyResolver = Callable[[str, str], Optional[Any]]

# A generic builder takes a scope tuple and returns a compiled graph or None.
# The builder is responsible for wiring tools, compiling the LangGraph workflow,
# and returning a RunnableGraph. Returning None means the agent is unavailable
# for the given scope (e.g. course not configured).
RuntimeBuilder = Callable[[tuple[str, ...]], Optional[RunnableGraph]]


@runtime_checkable
class AgentRuntimeProtocol(Protocol):
    """Minimal protocol satisfied by both legacy and generic runtimes."""

    async def respond(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]: ...


class AgentPlatform:
    """Unified registry for all agent runtimes.

    The platform is the single entry point for agent-runtime resolution.
    It supports two registration modes:

    - ``register_legacy``: for agents backed by an existing registry
      (currently EDU / TeachingAgent). The platform delegates to the
      legacy resolver and never caches beyond what the legacy registry
      already caches.

    - ``register_generic``: for agents backed by ``AgentProfile`` +
      ``LangGraphAgentRuntime`` (PREP, CODING). The platform caches
      runtimes per ``RuntimeKey`` with simple dict-based caching.

    The platform is fail-closed: unregistered agents or unavailable scopes
    return ``None``, never raise.
    """

    def __init__(
        self,
        *,
        runtime_registry: AgentRuntimeRegistry | None = None,
        gateway: AgentGateway | None = None,
        provider_container: Any | None = None,  # ProviderContainer
        concurrency_limiter: AgentConcurrencyLimiter | None = None,
        event_port: AgentRunEventPort | None = None,
    ) -> None:
        self._legacy_resolvers: dict[AgentType, LegacyResolver] = {}
        self._profiles: dict[AgentType, AgentProfile] = {}
        self._builders: dict[AgentType, RuntimeBuilder] = {}
        self._cache: dict[RuntimeKey, LangGraphAgentRuntime] = {}
        # Phase 1 infrastructure (nullable for incremental adoption).
        self._runtime_registry = runtime_registry or AgentRuntimeRegistry()
        self._concurrency_limiter = concurrency_limiter or AgentConcurrencyLimiter()
        self._event_port: AgentRunEventPort = event_port or NullAgentRunEventPort()
        self._provider_container = provider_container
        self._gateway = gateway

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def register_legacy(
        self,
        agent_type: AgentType,
        resolver: LegacyResolver,
    ) -> None:
        """Register a legacy agent backed by an existing registry.

        The ``resolver`` is called with ``(student_id, course_id)`` and must
        return a runtime instance or ``None``. This matches the signature of
        ``TeachingAgentRuntimeRegistry.get_or_create``.
        """
        if agent_type in self._legacy_resolvers:
            logger.warning("AgentPlatform: re-registering legacy agent %s", agent_type.value)
        self._legacy_resolvers[agent_type] = resolver
        logger.info("AgentPlatform: registered legacy agent %s", agent_type.value)

    def register_generic(
        self,
        profile: AgentProfile,
        builder: RuntimeBuilder,
    ) -> None:
        """Register a generic agent backed by ``LangGraphAgentRuntime``.

        The ``builder`` receives a scope tuple and returns a compiled
        ``RunnableGraph`` (or ``None`` if unavailable). The platform wraps
        the graph in a ``LangGraphAgentRuntime`` and caches it per
        ``RuntimeKey``.
        """
        if profile.agent_type in self._profiles:
            logger.warning("AgentPlatform: re-registering generic agent %s", profile.agent_type.value)
        self._profiles[profile.agent_type] = profile
        self._builders[profile.agent_type] = builder
        logger.info("AgentPlatform: registered generic agent %s", profile.agent_type.value)

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    def is_registered(self, agent_type: AgentType) -> bool:
        """Check if an agent type is registered (legacy or generic)."""
        return agent_type in self._legacy_resolvers or agent_type in self._profiles

    def is_legacy(self, agent_type: AgentType) -> bool:
        """Check if an agent type is registered as legacy (e.g. EDU)."""
        return agent_type in self._legacy_resolvers

    def list_registered(self) -> list[AgentType]:
        """List all registered agent types."""
        registered = set(self._legacy_resolvers.keys()) | set(self._profiles.keys())
        return sorted(registered, key=lambda t: t.value)

    # ------------------------------------------------------------------ #
    # Runtime resolution
    # ------------------------------------------------------------------ #

    def get_legacy_runtime(
        self,
        agent_type: AgentType,
        student_id: str,
        course_id: str,
    ) -> Optional[Any]:
        """Resolve a legacy runtime (e.g. TeachingAgentRuntime).

        Returns the runtime instance or ``None`` if the agent is not
        registered as legacy or the resolver returns ``None``.
        """
        resolver = self._legacy_resolvers.get(agent_type)
        if resolver is None:
            return None
        try:
            return resolver(student_id, course_id)
        except Exception as error:  # noqa: BLE001 - fail-closed
            logger.warning(
                "AgentPlatform: legacy resolver for %s raised: %s: %s",
                agent_type.value, type(error).__name__, error,
            )
            return None

    def get_runtime(
        self,
        agent_type: AgentType,
        scope: tuple[str, ...],
        config_version: str = "v1",
    ) -> Optional[LangGraphAgentRuntime]:
        """Get or build a generic runtime (PREP, CODING).

        Returns a cached ``LangGraphAgentRuntime`` if available, or builds
        one via the registered builder. Returns ``None`` if the agent is
        not registered as generic or the builder returns ``None``.
        """
        profile = self._profiles.get(agent_type)
        builder = self._builders.get(agent_type)
        if profile is None or builder is None:
            return None

        key = RuntimeKey(
            agent_type=agent_type,
            scope=scope,
            config_version=config_version,
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        try:
            graph = builder(scope)
        except Exception as error:  # noqa: BLE001 - fail-closed
            logger.warning(
                "AgentPlatform: builder for %s raised: %s: %s",
                agent_type.value, type(error).__name__, error,
            )
            return None
        if graph is None:
            return None

        runtime = LangGraphAgentRuntime(
            graph=graph,
            profile=profile,
            timeout_seconds=profile.default_timeout_seconds,
        )
        self._cache[key] = runtime
        return runtime

    async def respond(
        self,
        ctx: AgentRunContext,
    ) -> Mapping[str, Any]:
        """Convenience: resolve a generic runtime and invoke it.

        For legacy agents (EDU), use ``get_legacy_runtime`` and call the
        runtime's own ``respond`` method directly — the legacy runtime has
        a different signature (keyword args, not ``AgentRunContext``).

        Returns a fail-closed error dict if the agent is unavailable.
        """
        agent_type = AgentType(ctx.agent_type) if isinstance(ctx.agent_type, str) else ctx.agent_type
        runtime = self.get_runtime(agent_type, ctx.scope)
        if runtime is None:
            trace_id = ctx.trace_id
            return {
                "trace_id": trace_id,
                "errors": ["AGENT_NOT_AVAILABLE"],
                "status": "unavailable",
                "trace": [{"node": "platform", "error": "AgentNotRegistered"}],
            }
        return await runtime.respond(ctx)

    # ------------------------------------------------------------------ #
    # Cache management
    # ------------------------------------------------------------------ #

    def invalidate(
        self,
        agent_type: AgentType,
        scope: tuple[str, ...],
        config_version: str = "v1",
    ) -> None:
        """Drop a cached generic runtime so the next call rebuilds it."""
        key = RuntimeKey(
            agent_type=agent_type,
            scope=scope,
            config_version=config_version,
        )
        self._cache.pop(key, None)

    def clear_cache(self) -> None:
        """Drop all cached generic runtimes."""
        self._cache.clear()

    # ------------------------------------------------------------------ #
    # Phase 1 infrastructure accessors
    # ------------------------------------------------------------------ #

    @property
    def runtime_registry(self) -> AgentRuntimeRegistry:
        """The definition-keyed runtime registry (Phase 1)."""
        return self._runtime_registry

    @property
    def concurrency_limiter(self) -> AgentConcurrencyLimiter:
        """The shared concurrency limiter (Phase 1)."""
        return self._concurrency_limiter

    @property
    def event_port(self) -> AgentRunEventPort:
        """The shared event port (Phase 1)."""
        return self._event_port

    @property
    def gateway(self) -> AgentGateway | None:
        """The agent gateway, if configured. None until bootstrap wires it."""
        return self._gateway

    def set_gateway(self, gateway: AgentGateway) -> None:
        """Set the gateway after construction (for deferred bootstrap)."""
        self._gateway = gateway

    @property
    def provider_container(self) -> Any | None:
        """The provider container, if configured. None until bootstrap wires it."""
        return self._provider_container

    def set_provider_container(self, container: Any) -> None:
        """Set the provider container after construction."""
        self._provider_container = container

    async def close(self) -> None:
        """Release process-level resources.

        Closes the provider container and clears all caches. Called
        during application shutdown.
        """
        if self._provider_container is not None:
            close_fn = getattr(self._provider_container, "close", None)
            if close_fn is not None:
                result = close_fn()
                if hasattr(result, "__await__"):
                    await result
        self._cache.clear()
        self._runtime_registry.clear()


class LegacyAgentPlatform(AgentPlatform):
    """Compatibility alias for the transitional platform.

    During the migration, bootstrap builds a ``LegacyAgentPlatform`` that
    allows all Phase 1 infrastructure components to be ``None``. This is
    the only configuration in which ``gateway``, ``provider_container``,
    etc. may be absent.

    The formal ``AgentPlatform`` (target) will eventually require these
    components, but that enforcement is deferred until Phase 3 completes
    EDU migration. Until then, ``LegacyAgentPlatform`` is the safe default.

    Usage::

        # Transitional (Phase 1-2): all components optional
        platform = LegacyAgentPlatform()

        # Target (Phase 3+): core components required
        platform = AgentPlatform(
            runtime_registry=...,
            gateway=...,
            provider_container=...,
        )
    """

    pass


__all__ = [
    "AgentPlatform",
    "LegacyAgentPlatform",
    "AgentRuntimeProtocol",
    "LegacyResolver",
    "RuntimeBuilder",
]
