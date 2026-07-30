"""Coding Agent (代码诊断 Agent) subpackage.

Houses the agent-specific artifacts for the student-facing code-diagnosis
agent. The Coding Agent focuses on interpreting sandbox execution results
and producing student-friendly code feedback.

Unlike the TeachingAgent (which has 18 nodes) or the Prep Agent (which wraps
an existing service), the Coding Agent is a new skeleton with a minimal
3-node workflow:
    1. ``load_sandbox_result`` — read execution result via ``SandboxPort``
    2. ``load_coding_diagnosis`` — read server-side diagnosis via
       ``CodingDiagnosisPort``
    3. ``generate_diagnosis_response`` — produce a student-friendly response
       (LLM-based when configured, rule-based fallback otherwise)

Governance: per the adopted migration plan, the Coding Agent uses
prompt-level governance rather than teacher approval for every action.
Only high-risk actions (e.g. triggering a new sandbox run) go through the
teacher safety valve.

Layout:
    - ``state``: the ``CodingState`` TypedDict
    - ``workflow``: the 3-node LangGraph workflow
    - ``profile``: the ``AgentProfile`` for the Coding agent
    - ``composition``: the composition root (build_coding_graph_factory)
"""

from __future__ import annotations

__all__: list[str] = []
