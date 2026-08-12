"""Bounded retry, timeout and circuit breaking for ResearchAgent tools."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .tooling import ResearchToolRegistry


@dataclass(frozen=True)
class ToolExecutionResult:
    status: str
    value: Any = None
    attempts: int = 0
    error_code: str = ""
    error_type: str = ""
    latency_ms: float = 0.0


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None


class ReliableToolExecutor:
    """Execute only registered tools with bounded failure amplification."""

    def __init__(
        self,
        *,
        registry: ResearchToolRegistry,
        failure_threshold: int = 3,
        reset_timeout_seconds: float = 30.0,
        base_backoff_seconds: float = 0.15,
    ) -> None:
        self._registry = registry
        self._failure_threshold = max(1, failure_threshold)
        self._reset_timeout = max(0.0, reset_timeout_seconds)
        self._base_backoff = max(0.0, base_backoff_seconds)
        self._circuits: dict[str, _CircuitState] = {}

    async def execute(
        self,
        tool_name: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> ToolExecutionResult:
        spec = self._registry.get(tool_name)
        if spec is None:
            return ToolExecutionResult(
                status="denied",
                error_code="RESEARCH_TOOL_NOT_ALLOWLISTED",
            )

        circuit = self._circuits.setdefault(tool_name, _CircuitState())
        now = time.monotonic()
        if circuit.opened_at is not None:
            if now - circuit.opened_at < self._reset_timeout:
                return ToolExecutionResult(
                    status="circuit_open",
                    error_code="RESEARCH_TOOL_CIRCUIT_OPEN",
                )
            circuit.opened_at = None
            circuit.failures = max(0, self._failure_threshold - 1)

        started = time.monotonic()
        attempts = 0
        last_error: BaseException | None = None
        for attempt in range(spec.max_retries + 1):
            attempts = attempt + 1
            try:
                value = await asyncio.wait_for(
                    operation(),
                    timeout=max(0.05, spec.timeout_seconds),
                )
                circuit.failures = 0
                circuit.opened_at = None
                return ToolExecutionResult(
                    status="success",
                    value=value,
                    attempts=attempts,
                    latency_ms=(time.monotonic() - started) * 1000,
                )
            except Exception as error:  # noqa: BLE001 - mapped to stable tool status
                last_error = error
                circuit.failures += 1
                if circuit.failures >= self._failure_threshold:
                    circuit.opened_at = time.monotonic()
                    break
                if attempt < spec.max_retries and self._base_backoff:
                    await asyncio.sleep(self._base_backoff * (2 ** attempt))

        return ToolExecutionResult(
            status="failed",
            attempts=attempts,
            error_code=(
                "RESEARCH_TOOL_TIMEOUT"
                if isinstance(last_error, asyncio.TimeoutError)
                else "RESEARCH_TOOL_FAILED"
            ),
            error_type=type(last_error).__name__ if last_error else "UnknownError",
            latency_ms=(time.monotonic() - started) * 1000,
        )


__all__ = ["ReliableToolExecutor", "ToolExecutionResult"]
