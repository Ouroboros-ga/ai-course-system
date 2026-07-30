"""Tracing helpers shared across agent runtimes.

These helpers normalize trace entries so that all three agents produce
the same ``node_trace`` shape. They are intentionally side-effect-free;
agents call them to build trace fragments and merge them into state.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from .state import NodeTraceEntry


def trace_entry(
    node: str,
    *,
    duration_ms: float | None = None,
    skipped: bool = False,
    error: str | None = None,
    **detail: Any,
) -> NodeTraceEntry:
    """Build a single ``NodeTraceEntry``.

    Extra keyword arguments are collected into ``detail`` so agent nodes
    can attach domain-specific fields without changing the signature.
    """
    entry: NodeTraceEntry = {"node": node}
    if duration_ms is not None:
        entry["duration_ms"] = duration_ms
    if skipped:
        entry["skipped"] = True
    if error is not None:
        entry["error"] = error
    if detail:
        entry["detail"] = dict(detail)
    return entry


def append_trace(state: Mapping[str, Any], entry: NodeTraceEntry) -> list[NodeTraceEntry]:
    """Return a new ``node_trace`` list with ``entry`` appended.

    This is a pure helper; the caller assigns the result back to state.
    """
    existing = list(state.get("node_trace") or state.get("trace") or [])
    existing.append(entry)
    return existing


class NodeTimer:
    """Context manager for measuring node execution time.

    Usage::

        with NodeTimer() as timer:
            await do_work()
        entry = trace_entry("my_node", duration_ms=timer.elapsed_ms)
    """

    __slots__ = ("_start", "_end")

    def __init__(self) -> None:
        self._start: float = 0.0
        self._end: float = 0.0

    def __enter__(self) -> "NodeTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._end = time.monotonic()

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds (0 if not yet exited)."""
        end = self._end or time.monotonic()
        return (end - self._start) * 1000.0


__all__ = [
    "trace_entry",
    "append_trace",
    "NodeTimer",
]
