"""Shared utilities reusable across agent workflows.

This package contains:
    - ``workflow_utils``: trace/degrade/governance/invocation helpers
      extracted from the TeachingAgent workflow (Commit 1).
    - ``state``: ``RuntimeMeta`` TypedDict and ``empty_meta`` builder
      (Phase 1). The unified metadata block embedded in every agent state.
    - ``tracing``: ``trace_entry``, ``append_trace``, ``NodeTimer``
      (Phase 1). Normalized trace entry builders shared by all agents.

The TeachingAgent workflow continues to import helpers from its own private
locations for now; future phases will switch it to import from here.
"""

from __future__ import annotations

from .state import ErrorEntry, NodeTraceEntry, RuntimeMeta, empty_meta
from .tracing import NodeTimer, append_trace, trace_entry
from .workflow_utils import (
    degrade,
    governance_check,
    record_invocation,
    trace,
)

__all__ = [
    # workflow_utils (Commit 1)
    "trace",
    "degrade",
    "governance_check",
    "record_invocation",
    # state (Phase 1)
    "RuntimeMeta",
    "NodeTraceEntry",
    "ErrorEntry",
    "empty_meta",
    # tracing (Phase 1)
    "trace_entry",
    "append_trace",
    "NodeTimer",
]
