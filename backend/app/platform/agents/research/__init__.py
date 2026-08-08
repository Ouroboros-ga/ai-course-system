"""ResearchAgent: course-bound, evidence-first scholarly research workflows."""

from .composition import build_research_graph_factory
from .profile import build_research_profile
from .workflow import ResearchTools, build_research_workflow

__all__ = [
    "ResearchTools",
    "build_research_graph_factory",
    "build_research_profile",
    "build_research_workflow",
]
