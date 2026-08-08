"""Composition root for ResearchAgent."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from ..contracts.research import PaperSearchPort, ResearchScopePort
from ..runtime.base import RunnableGraph
from .workflow import ResearchTools, build_research_workflow

logger = logging.getLogger(__name__)


def build_research_graph_factory(
    *, scope_access: ResearchScopePort, paper_search: PaperSearchPort,
) -> Callable[[tuple[str, ...]], Optional[RunnableGraph]]:
    try:
        compiled = build_research_workflow(ResearchTools(
            scope_access=scope_access,
            paper_search=paper_search,
        ))
    except Exception as error:  # noqa: BLE001 - fail closed at registration
        logger.warning("ResearchAgent workflow compilation failed: %s", type(error).__name__)
        return lambda scope: None

    def builder(scope: tuple[str, ...]) -> Optional[RunnableGraph]:
        return compiled

    return builder


__all__ = ["build_research_graph_factory"]
