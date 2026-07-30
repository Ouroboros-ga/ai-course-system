"""Shared state types for agent runs.

``RuntimeMeta`` is the unified metadata block embedded in every agent
state. It carries run identity, timing, trace, and degradation flags that
the runtime layer owns. Agent-specific state (EduState, PrepState,
CodingState) nests ``meta`` rather than flattening thirty fields at the
top level.

Design rules:
    - The runtime initializes ``meta`` fields; agent nodes may read and
      append to ``warnings``, ``errors``, ``degraded_services``, and
      ``node_trace`` but must not overwrite run identity fields.
    - ``RuntimeMeta`` is a ``TypedDict(total=False)`` so partial updates
      from LangGraph nodes are valid.
"""

from __future__ import annotations

from typing import Any, TypedDict


class NodeTraceEntry(TypedDict, total=False):
    """One entry in the ``node_trace`` list.

    The ``node`` field is the only required key. Other fields are optional
    and agent-specific (e.g. ``skipped``, ``available``, ``error``).
    """

    node: str
    duration_ms: float
    skipped: bool
    error: str
    detail: dict[str, Any]


class ErrorEntry(TypedDict, total=False):
    """Structured error entry for the ``errors`` list.

    Agents may append plain strings (legacy convention) or structured
    dicts. The runtime normalizes to ``ErrorEntry`` when building the
    final response.
    """

    code: str
    message: str
    node: str


class RuntimeMeta(TypedDict, total=False):
    """Unified runtime metadata embedded in every agent state.

    Fields:
        run_id: Stable identifier for this run (used in audit and metrics).
        trace_id: Per-run trace identifier for log correlation.
        agent_type: ``edu`` / ``prep`` / ``coding``.
        config_version: Configuration version that built this runtime.
        started_at: ISO-8601 UTC timestamp when the run started.
        warnings: Non-fatal warnings accumulated during the run.
        errors: Fatal errors accumulated during the run.
        degraded_services: Services that fell back during the run.
        node_trace: Per-node timing and detail entries.
        status: Terminal status of the run (``ok``, ``timeout``, etc.).
    """

    run_id: str
    trace_id: str
    agent_type: str
    config_version: str
    started_at: str
    warnings: list[str]
    errors: list[Any]  # str | ErrorEntry
    degraded_services: list[str]
    node_trace: list[NodeTraceEntry]
    status: str


def empty_meta(*, run_id: str, trace_id: str, agent_type: str, config_version: str = "v1") -> RuntimeMeta:
    """Build an empty ``RuntimeMeta`` with identity fields pre-filled."""
    return RuntimeMeta(
        run_id=run_id,
        trace_id=trace_id,
        agent_type=agent_type,
        config_version=config_version,
        warnings=[],
        errors=[],
        degraded_services=[],
        node_trace=[],
    )


__all__ = [
    "RuntimeMeta",
    "NodeTraceEntry",
    "ErrorEntry",
    "empty_meta",
]
