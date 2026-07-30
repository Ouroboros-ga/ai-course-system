"""Agent Runtime package.

Provides a generic LangGraph-based runtime that can host any agent workflow,
alongside the legacy ``TeachingAgentRuntime`` for backward compatibility.

Public API (stable):
    - ``TeachingAgentRuntime``: legacy per-course/student runtime (Commit 1 keeps it)
    - ``LangGraphAgentRuntime``: generic runtime wrapping a compiled LangGraph
    - ``AgentProfile``, ``AgentType``: declarative description of an agent
    - ``RuntimeKey``: cache key for runtime instances
    - ``AgentRunContext``: request-scoped execution context

Backward compatibility:
    ``from app.platform.agents.runtime import TeachingAgentRuntime`` continues to
    work because ``__init__`` re-exports it from ``.teaching_runtime``.
"""

from __future__ import annotations

from .base import AgentRunContext, LangGraphAgentRuntime, RunnableGraph
from .profile import AgentProfile, AgentType, RuntimeKey
from .teaching_runtime import TeachingAgentRuntime

__all__ = [
    "TeachingAgentRuntime",
    "LangGraphAgentRuntime",
    "RunnableGraph",
    "AgentRunContext",
    "AgentProfile",
    "AgentType",
    "RuntimeKey",
]
