"""Definition-keyed agent runtime registry.

This is the Phase 1 ``AgentRuntimeRegistry`` described in the migration
design. It caches compiled, stateless, concurrently-shareable runtimes
keyed by ``AgentDefinitionKey`` — NOT by student or course.

Design rationale:
    - The legacy ``TeachingAgentRuntimeRegistry`` (in ``edu/registry.py``)
      caches per-``(student_id, course_id)`` because KG-MEST reports are
      bound at construction time. This coupling is scheduled for removal
      in Phase 2b.
    - This new registry caches per ``AgentDefinitionKey``: agent_type +
      agent_version + model_profile + feature_flags_hash. The cached
      runtime has NO request-level state; it is safe to share across
      concurrent requests.
    - Course-specific differences are loaded at call time via State,
      CoursePolicyPort, Prompt configuration, and FeatureFlagPort — not
      by building a different runtime per course.

Backward compatibility:
    - This registry does NOT replace ``TeachingAgentRuntimeRegistry``.
    - ``AgentPlatform`` delegates to whichever registry is appropriate:
      legacy for EDU (until Phase 2b), this new registry for PREP/CODING.
    - Existing endpoints that call ``registry.get_or_create(student_id,
      course_id)`` continue to work against the legacy registry.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from .dispatcher import BaseAgentRuntime
from .errors import AgentNotAvailableError
from .profile import AgentProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentDefinitionKey:
    """Cache key for stateless, shareable runtimes.

    Fields:
        agent_type: ``edu`` / ``prep`` / ``coding``.
        agent_version: profile version (e.g. ``"v1"``).
        model_profile: LLM model identifier hash (e.g. ``"qwen-72b"``).
        feature_flags_hash: hash of relevant feature flags that affect
            graph topology (e.g. ``"kg_mest_enabled|web_research_disabled"``).

    The key deliberately excludes ``student_id``, ``course_id``, and
    ``actor_id``. Per-actor and per-course differences are loaded at call
    time, not baked into the runtime.
    """

    agent_type: str
    agent_version: str = "v1"
    model_profile: str = "default"
    feature_flags_hash: str = ""

    def __str__(self) -> str:
        return f"{self.agent_type}:{self.agent_version}:{self.model_profile}:{self.feature_flags_hash or '_'}"


# Factory signature: () -> BaseAgentRuntime (called once per key, under lock)
RuntimeFactory = Callable[[], BaseAgentRuntime]


class AgentRuntimeRegistry:
    """Definition-keyed runtime cache with lazy, lock-protected construction.

    The registry holds at most one ``BaseAgentRuntime`` per
    ``AgentDefinitionKey``. Construction is delegated to a registered
    factory callable and protected by an ``asyncio.Lock`` per key to
    avoid duplicate builds under concurrency.

    The registry is process-level and thread-safe within a single asyncio
    event loop. For multi-process deployments, each process maintains its
    own registry; runtimes are stateless so this is safe.
    """

    def __init__(self) -> None:
        self._factories: dict[AgentDefinitionKey, RuntimeFactory] = {}
        self._runtimes: dict[AgentDefinitionKey, BaseAgentRuntime] = {}
        self._locks: dict[AgentDefinitionKey, asyncio.Lock] = {}

    def register_factory(
        self,
        key: AgentDefinitionKey,
        factory: RuntimeFactory,
    ) -> None:
        """Register a factory for a definition key.

        If a factory is already registered for the same key, the new one
        replaces it and any cached runtime for that key is invalidated.
        """
        if key in self._factories:
            logger.info("AgentRuntimeRegistry: replacing factory for %s", key)
            self._runtimes.pop(key, None)
        self._factories[key] = factory
        self._locks.setdefault(key, asyncio.Lock())

    def is_registered(self, key: AgentDefinitionKey) -> bool:
        return key in self._factories

    async def get_or_create(self, key: AgentDefinitionKey) -> BaseAgentRuntime:
        """Get the cached runtime for ``key``, or build it via the factory.

        Raises ``AgentNotAvailableError`` if no factory is registered for
        the key.
        """
        cached = self._runtimes.get(key)
        if cached is not None:
            return cached

        factory = self._factories.get(key)
        if factory is None:
            raise AgentNotAvailableError(
                f"No runtime factory registered for {key}",
            )

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Double-check after acquiring the lock.
            cached = self._runtimes.get(key)
            if cached is not None:
                return cached

            try:
                runtime = factory()
            except Exception as error:  # noqa: BLE001 - fail-closed
                logger.warning(
                    "AgentRuntimeRegistry: factory for %s raised: %s: %s",
                    key, type(error).__name__, error,
                )
                raise AgentNotAvailableError(
                    f"Runtime construction failed for {key}: {error}",
                ) from error

            self._runtimes[key] = runtime
            logger.info("AgentRuntimeRegistry: built runtime for %s", key)
            return runtime

    def invalidate(self, key: AgentDefinitionKey) -> None:
        """Drop the cached runtime for ``key`` so the next call rebuilds it."""
        self._runtimes.pop(key, None)

    def clear(self) -> None:
        """Drop all cached runtimes."""
        self._runtimes.clear()

    def list_keys(self) -> list[AgentDefinitionKey]:
        """List all registered definition keys."""
        return list(self._factories.keys())


__all__ = [
    "AgentDefinitionKey",
    "AgentRuntimeRegistry",
    "RuntimeFactory",
]
