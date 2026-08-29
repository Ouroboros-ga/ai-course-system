"""State owned by the ResearchAgent Harness workflow."""
from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class ResearchState(TypedDict, total=False):
    run_id: str
    trace_id: str
    course_id: str
    actor_user_id: str
    session_id: str

    user_message: str
    query: str
    max_results: int
    cursor: str | None
    requested_action: str
    action_payload: dict[str, Any]
    context_budget_tokens: int
    allowed_tool_names: list[str]
    granted_permissions: list[str]

    workspace_id: str
    active_scope_id: str | None
    workspace_snapshot: dict[str, Any]
    context_items: list[dict[str, Any]]
    raw_context_tokens: int
    context_text: str
    context_meta: dict[str, Any]

    prompt_version: str
    prompt_hash: str
    prompt_role: str
    prompt_task: str
    planner_action: str
    planner_tool_hints: list[str]
    selected_tools: list[str]
    denied_tools: list[str]
    tool_scores: dict[str, float]
    tool_selection_reason: str
    graph_route: str
    tool_result: dict[str, Any] | list[dict[str, Any]] | None
    tool_error_code: str

    writing_result: dict[str, Any] | None
    trend_result: dict[str, Any] | None

    search_result: dict[str, Any] | None
    papers: list[dict[str, Any]]
    final_answer: str | None

    warnings: list[str]
    errors: list[str]
    degraded_services: list[str]
    trace: list[dict[str, Any]]
    status: NotRequired[str]
