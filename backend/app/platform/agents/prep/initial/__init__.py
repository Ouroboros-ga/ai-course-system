"""Initial course build subpackage for the Prep Agent.

This is one of the three Prep Agent pipelines (Initial, Incremental, PPT
mapping). The Initial pipeline wraps ``InitialCoursePrepService.build()`` —
the first-time course generation flow — in the generic LangGraph agent
runtime so the unified ``AgentPlatform`` can dispatch it as a queued run.

Layout:
    - ``state``: the ``InitialPrepState`` TypedDict (request / progress / result)
    - ``dependencies``: the ``InitialPrepDependencies`` container and the
      ``InitialCoursePrepPort`` protocol adapted to the service
    - ``workflow``: a single-node LangGraph workflow that calls the port
    - ``profile``: the ``AgentProfile`` for the Initial pipeline
    - ``composition``: the composition root (``build_initial_graph_factory``)
"""

from __future__ import annotations

__all__: list[str] = []
