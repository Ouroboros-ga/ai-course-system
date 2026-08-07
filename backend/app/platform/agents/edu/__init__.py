"""TeachingAgent (Edu Agent) subpackage.

Houses the agent-specific artifacts for the student-facing teaching agent:
    - ``state``: the ``TeachingState`` TypedDict
    - ``workflow``: the 19-node LangGraph workflow
    - ``policy``: deterministic teaching-action policy
    - ``prompts``: versioned LLM prompts
    - ``kg_mest_report_store``: isolated KG-MEST Shadow report store
    - ``composition``: explicit composition roots (build_teaching_runtime, ...)
    - ``registry``: per-(student, course) runtime registry with LRU+TTL cache
    - ``runtime``: the ``TeachingAgentRuntime`` application-facing runtime

Backward compatibility:
    The old top-level modules (``app.platform.agents.state``,
    ``app.platform.agents.composition``, ``app.platform.agents.registry``,
    ``app.platform.agents.runtime``) continue to import by re-exporting from
    this subpackage. The ``policies/`` and ``prompts/`` packages and
    ``workflows/`` package are kept as compat shims too.
"""

from __future__ import annotations

from .runtime import TeachingAgentRuntime

__all__ = ["TeachingAgentRuntime"]
