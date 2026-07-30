"""Composition root for the Incremental draft modification pipeline.

Provides ``build_incremental_graph_factory`` which returns a ``RuntimeBuilder``
closure compatible with ``AgentPlatform.register_generic`` (or
``AgentRuntimeRegistry.register_factory``). The closure captures the
``IncrementalPrepDependencies``, compiles the Incremental workflow once,
and hands the same compiled graph to every scope.

The Incremental pipeline operates at course level: its ``scope`` is
``(course_id,)``. The same compiled graph serves all courses because the
course_id is carried in the state (set by the profile's initial-state
builder from ``AgentRunContext``), not in the graph compilation.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ...runtime.base import RunnableGraph
from .dependencies import IncrementalPrepDependencies
from .profile import build_incremental_profile
from .workflow import build_incremental_workflow

logger = logging.getLogger(__name__)


def build_incremental_graph_factory(
    deps: IncrementalPrepDependencies,
) -> Callable[[tuple[str, ...]], Optional[RunnableGraph]]:
    """Return a ``RuntimeBuilder`` closure for the Incremental pipeline.

    Args:
        deps: Frozen dependency container with the common Prep dependencies
            and the adapted ``IncrementalPrepPort``.

    Returns:
        A closure ``builder(scope) -> RunnableGraph | None``. The builder
        always returns the pre-compiled graph (the graph is course-agnostic;
        course_id is in the state). It returns ``None`` only if the workflow
        failed to compile at registration time.
    """
    try:
        compiled = build_incremental_workflow(deps)
    except Exception as error:  # noqa: BLE001 - fail-closed at registration
        logger.warning(
            "IncrementalPrep: workflow compilation failed: %s: %s",
            type(error).__name__, error,
        )
        return lambda scope: None

    def builder(scope: tuple[str, ...]) -> Optional[RunnableGraph]:
        # The Incremental graph is course-agnostic; course_id is in the state.
        # The scope is (course_id,) but is not needed at build time.
        return compiled

    return builder


__all__ = ["build_incremental_graph_factory", "build_incremental_profile"]
