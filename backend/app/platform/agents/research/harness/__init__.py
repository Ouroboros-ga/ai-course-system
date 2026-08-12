"""ResearchAgent harness primitives.

These modules are intentionally framework-light.  The LangGraph workflow
composes them, while their deterministic contracts remain independently
testable and reusable by API/background execution adapters.
"""

from .context import ContextItem, PreparedContext, ResearchContextManager
from .prompting import PromptBundle, PromptTemplateError, ResearchPromptAssembler
from .reliability import ReliableToolExecutor, ToolExecutionResult
from .tooling import (
    DynamicResearchToolSelector,
    ResearchToolRegistry,
    ResearchToolSelection,
    ResearchToolSpec,
)

__all__ = [
    "ContextItem",
    "DynamicResearchToolSelector",
    "PreparedContext",
    "PromptBundle",
    "PromptTemplateError",
    "ReliableToolExecutor",
    "ResearchContextManager",
    "ResearchPromptAssembler",
    "ResearchToolRegistry",
    "ResearchToolSelection",
    "ResearchToolSpec",
    "ToolExecutionResult",
]

