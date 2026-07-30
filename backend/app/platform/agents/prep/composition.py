"""Composition root for the Prep Agent.

Provides ``build_prep_graph_factory`` which returns a ``RuntimeBuilder``
closure compatible with ``AgentPlatform.register_generic``. The closure
captures the session factory and the existing ``CoursePrepAgentService``
singleton, compiles the Prep workflow, and returns a ``RunnableGraph``.

The Prep Agent operates at course level: its ``scope`` is
``(course_id,)``. The same compiled graph can serve all courses because
the course_id is carried in the state (not in the graph compilation).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ..runtime.base import RunnableGraph
from .profile import build_prep_profile
from .workflow import PrepTools, build_prep_workflow

logger = logging.getLogger(__name__)


def build_prep_graph_factory(
    *,
    session_factory: Callable,
    service=None,
) -> Callable[[tuple[str, ...]], Optional[RunnableGraph]]:
    """Return a ``RuntimeBuilder`` closure for the Prep Agent.

    Args:
        session_factory: A callable that returns a SQLModel ``Session``.
        service: Optional ``CoursePrepAgentService`` instance. Defaults to
            the module-level singleton ``course_prep_agent_service``.

    Returns:
        A closure ``builder(scope) -> RunnableGraph | None``. The builder
        always returns a compiled graph (the same graph serves all courses
        because course_id is in the state). It returns ``None`` only if
        the workflow fails to compile.
    """
    if service is None:
        from app.services.course_prep_agent_service import course_prep_agent_service as service

    tools = PrepTools(service=service, session_factory=session_factory)

    # Compile the graph once; the same graph serves all course scopes.
    try:
        compiled = build_prep_workflow(tools)
    except Exception as error:  # noqa: BLE001 - fail-closed at registration
        logger.warning("PrepAgent: workflow compilation failed: %s: %s", type(error).__name__, error)
        return lambda scope: None

    def builder(scope: tuple[str, ...]) -> Optional[RunnableGraph]:
        # The Prep graph is course-agnostic; course_id is in the state.
        # The scope is (course_id,) but we don't need it at build time.
        return compiled

    return builder


__all__ = ["build_prep_graph_factory", "build_prep_profile"]
