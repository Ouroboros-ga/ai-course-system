"""PrepState: the state schema for the Prep Agent workflow.

The state carries the teacher's instruction and the planning result. It is
intentionally minimal: the existing ``CoursePrepAgentService`` handles all
business logic (draft loading, evidence retrieval, LLM planning, locked-node
filtering, evidence_refs hard gate). The workflow wraps that service call.

The ``plan_result`` field holds a serialized ``CoursePrepAgentResult``:
    - ``summary``: str
    - ``operations``: list[dict] — each with target, after, reason, evidence_refs
    - ``evidence``: list[dict] — retrieved course evidence
    - ``excluded_locked_targets``: list[str]
    - ``planner``: str — "llm" or "deterministic_fallback"
"""

from __future__ import annotations

from typing import Any

try:
    from typing import NotRequired, TypedDict
except ImportError:  # Python < 3.11
    from typing_extensions import NotRequired, TypedDict


class PrepState(TypedDict, total=False):
    """State for the Prep Agent workflow."""

    # Identity / tracing
    trace_id: str
    course_id: str
    teacher_id: str
    session_id: str

    # Input
    instruction: str
    outline_node_id: str | None

    # Output
    plan_result: dict[str, Any] | None

    # Common fields (mirrors TeachingState conventions)
    warnings: list[str]
    errors: list[str]
    degraded_services: list[str]
    trace: list[dict[str, Any]]
    status: NotRequired[str]
