"""Shared workflow utilities reusable across agent workflows.

Commit 1 extracts the four small helpers used by the TeachingAgent workflow
(``_trace``, ``_degrade``, ``_governance_check``, ``_record_invocation``)
into a shared module so that subsequent agents (Prep, Coding) can reuse the
same trace/degradation/governance shape without duplicating code.

The TeachingAgent workflow continues to import these from its own private
locations for now; Commit 2 will switch it to import from here. The shared
helpers accept a generic governance port (``ToolGovernancePort``) so they are
not coupled to ``TeachingTools``.
"""

from __future__ import annotations

from .workflow_utils import (
    degrade,
    governance_check,
    record_invocation,
    trace,
)

__all__ = [
    "trace",
    "degrade",
    "governance_check",
    "record_invocation",
]
