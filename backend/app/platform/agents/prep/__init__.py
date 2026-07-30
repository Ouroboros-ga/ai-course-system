"""Prep Agent (备课 Agent) subpackage.

Houses the agent-specific artifacts for the teacher-facing course-preparation
agent. The Prep Agent is a proposal-only planner: it never directly mutates
outline/script rows — every change is returned as a reviewable plan that the
endpoint persists as a ``PatchProposal``.

The existing ``CoursePrepAgentService`` (in ``app.services``) remains the
business-logic source of truth. This subpackage wraps it in the new agent
runtime skeleton (``AgentProfile`` + ``LangGraphAgentRuntime``) so that the
unified ``AgentPlatform`` can serve Prep agent runtimes alongside EDU and
CODING.

Layout:
    - ``state``: the ``PrepState`` TypedDict
    - ``workflow``: a thin LangGraph workflow that calls the service
    - ``profile``: the ``AgentProfile`` for the Prep agent
    - ``composition``: the composition root (build_prep_graph_factory)
"""

from __future__ import annotations

__all__: list[str] = []
