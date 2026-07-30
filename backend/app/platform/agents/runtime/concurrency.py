"""Concurrency limiter for agent runtimes.

Provides a per-agent-type semaphore-based limiter that bounds the number
of concurrent runs. The limiter is intentionally simple: it does NOT queue
calls — when the semaphore is exhausted, ``acquire`` raises
``RuntimeInitializationError`` rather than blocking indefinitely.

Design rationale:
    - Phase 1 introduces the framework with *loose* defaults so existing
      TeachingAgent behavior is unchanged (high limit, no real contention).
    - The limiter is per agent-type, not global, so a slow Prep run does
      not block Edu Q&A.
    - The limiter is async-context-manager based; ``asyncio.CancelledError``
      propagates naturally through the ``acquire`` call.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

from .errors import RuntimeInitializationError

logger = logging.getLogger(__name__)


@dataclass
class AgentConcurrencyLimiter:
    """Per-agent-type concurrency limiter using semaphores.

    The limiter maintains one ``asyncio.Semaphore`` per agent type. Semaphores
    are created lazily on first ``acquire`` for a given agent type and limit.

    Usage::

        limiter = AgentConcurrencyLimiter()
        async with limiter.acquire("edu", limit=100):
            await runtime.run(...)
    """

    _semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    _limits: dict[str, int] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def _get_semaphore(self, agent_type: str, limit: int) -> asyncio.Semaphore:
        """Get or create the semaphore for ``agent_type``.

        If the limit changes between calls for the same agent type, the
        existing semaphore is reused (the new limit is logged but not applied
        until the process restarts). This avoids race conditions during
        reconfiguration.
        """
        existing = self._semaphores.get(agent_type)
        if existing is not None:
            if limit != self._limits.get(agent_type):
                logger.warning(
                    "AgentConcurrencyLimiter: limit changed for %s (%d -> %d); "
                    "existing semaphore retained until process restart.",
                    agent_type, self._limits.get(agent_type, 0), limit,
                )
            return existing

        async with self._lock:
            # Double-check after acquiring the lock.
            existing = self._semaphores.get(agent_type)
            if existing is not None:
                return existing
            semaphore = asyncio.Semaphore(limit)
            self._semaphores[agent_type] = semaphore
            self._limits[agent_type] = limit
            return semaphore

    @asynccontextmanager
    async def acquire(self, agent_type: str, *, limit: int | None) -> AsyncIterator[None]:
        """Acquire a concurrency slot for ``agent_type``.

        When ``limit`` is ``None``, no limit is imposed (passthrough). This
        is the safe default that preserves existing behavior: the runtime
        does not introduce its own semaphore. Real limits are set at
        bootstrap per agent.

        When ``limit`` is set, raises ``RuntimeInitializationError`` if the
        semaphore cannot be acquired within a short grace window (1s). This
        prevents silent indefinite blocking when the limit is misconfigured.
        """
        if limit is None:
            # No limit: passthrough without semaphore.
            yield
            return

        semaphore = await self._get_semaphore(agent_type, limit)
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=1.0)
        except asyncio.TimeoutError:
            raise RuntimeInitializationError(
                f"Concurrency limit exhausted for agent {agent_type} (limit={limit})",
            ) from None
        try:
            yield
        finally:
            semaphore.release()

    def active_count(self, agent_type: str) -> int:
        """Return the number of currently held slots for ``agent_type``."""
        limit = self._limits.get(agent_type, 0)
        semaphore = self._semaphores.get(agent_type)
        if semaphore is None or limit == 0:
            return 0
        return limit - semaphore._value  # type: ignore[attr-defined]


__all__ = ["AgentConcurrencyLimiter"]
