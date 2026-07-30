"""PPT mapping optimization subpackage for the Prep Agent.

This is one of the three Prep Agent pipelines (Initial, Incremental, PPT
mapping). The PPT mapping pipeline wraps ``PptMappingOptimizationService``
— the per-material mapping optimization flow — in the generic LangGraph
agent runtime so the unified ``AgentPlatform`` can dispatch it as an
inline run.

The pipeline reads OCR text blocks from a PPT material version, matches
them against the course outline's knowledge-point nodes, and updates
``CoursePptMapping`` rows in place. Mappings flagged ``teacher_locked``
are never modified.

Layout:
    - ``state``: the ``PptMappingState`` TypedDict (request / result)
    - ``dependencies``: the ``PptMappingDependencies`` container and the
      ``PptMappingOptimizationPort`` protocol adapted to the service
    - ``workflow``: a single-node LangGraph workflow that calls the port
    - ``profile``: the ``AgentProfile`` for the PPT mapping pipeline
    - ``composition``: the composition root (``build_ppt_mapping_graph_factory``)
"""

from __future__ import annotations

__all__: list[str] = []
