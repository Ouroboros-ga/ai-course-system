"""Incremental draft modification subpackage for the Prep Agent.

This is one of the three Prep Agent pipelines (Initial, Incremental, PPT
mapping). The Incremental pipeline wraps ``CoursePrepAgentService.plan()``
— the per-draft proposal planning flow — in the generic LangGraph agent
runtime so the unified ``AgentPlatform`` can dispatch it as an inline run.

The pipeline is proposal-only: it never directly mutates outline/script
rows. Every change is returned as a reviewable plan that the endpoint
persists as a ``PatchProposal``.

Layout:
    - ``state``: the ``IncrementalPrepState`` TypedDict (request / context / result)
    - ``dependencies``: the ``IncrementalPrepDependencies`` container and the
      ``IncrementalPrepPort`` protocol adapted to the service
    - ``workflow``: a single-node LangGraph workflow that calls the port
    - ``profile``: the ``AgentProfile`` for the Incremental pipeline
    - ``composition``: the composition root (``build_incremental_graph_factory``)
"""

from __future__ import annotations

__all__: list[str] = []
