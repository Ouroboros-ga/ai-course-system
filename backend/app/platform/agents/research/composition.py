"""Composition root for ResearchAgent."""
from __future__ import annotations

import logging
from collections.abc import Callable

from ..contracts.llm import StructuredLLMPort
from ..contracts.research import PaperSearchPort, ResearchScopePort
from ..contracts.research_workspace import ResearchWorkspacePort
from ..runtime.base import RunnableGraph
from .workflow import ResearchTools, build_research_workflow

logger = logging.getLogger(__name__)


def build_research_graph_factory(
    *,
    scope_access: ResearchScopePort,
    paper_search: PaperSearchPort,
    workspace: ResearchWorkspacePort,
    structured_llm: StructuredLLMPort | None = None,
) -> Callable[[tuple[str, ...]], RunnableGraph | None]:
    try:
        compiled = build_research_workflow(ResearchTools(
            scope_access=scope_access,
            paper_search=paper_search,
            workspace=workspace,
            structured_llm=structured_llm,
        ))
    except Exception as error:  # noqa: BLE001 - fail closed at registration
        logger.warning("ResearchAgent workflow compilation failed: %s", type(error).__name__)
        return lambda scope: None

    def builder(scope: tuple[str, ...]) -> RunnableGraph | None:
        return compiled

    return builder


__all__ = ["build_research_graph_factory"]
