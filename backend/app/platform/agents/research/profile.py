"""Runtime profile for a course-bound ResearchAgent."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..runtime.base import AgentRunContext
from ..runtime.profile import AgentProfile, AgentType, ExecutionMode


def build_research_profile() -> AgentProfile:
    def build_initial_state(ctx: AgentRunContext, *, trace_id: str) -> Mapping[str, Any]:
        raw_limit = ctx.extras.get("max_results", 8)
        try:
            max_results = min(max(int(raw_limit), 1), 20)
        except (TypeError, ValueError):
            max_results = 8
        return {
            "run_id": ctx.run_id,
            "trace_id": trace_id,
            "course_id": ctx.course_id or "",
            "actor_user_id": str(ctx.extras.get("actor_user_id") or ctx.student_id or ctx.teacher_id or ""),
            "session_id": ctx.session_id or "",
            "user_message": ctx.user_message or "",
            "query": ctx.user_message or "",
            "max_results": max_results,
            "cursor": ctx.extras.get("cursor"),
            "requested_action": str(ctx.extras.get("action") or "literature_search"),
            "action_payload": dict(ctx.extras.get("payload") or {}),
            "workspace_id": str(ctx.extras.get("workspace_id") or ""),
            "active_scope_id": ctx.extras.get("scope_id"),
            "context_budget_tokens": min(
                64_000,
                max(32, int(ctx.extras.get("context_budget_tokens") or 4_000)),
            ),
            "allowed_tool_names": [
                "paper_search", "todo_manager", "notepad", "memory", "scope_manager",
            ],
            "warnings": [],
            "errors": [],
            "degraded_services": [],
            "trace": [],
        }

    return AgentProfile(
        agent_type=AgentType.RESEARCH,
        build_initial_state=build_initial_state,
        default_timeout_seconds=25.0,
        description="ResearchAgent Harness: course-bound research workspace with auditable tools and memory",
        max_concurrency=8,
        # Every currently exposed Harness action completes inline. Long-running
        # synthesis/reproduction must move to a durable queue before this can
        # truthfully change to HYBRID.
        execution_mode=ExecutionMode.INLINE,
        share_runtime_across_actors=True,
        allowed_tool_names=frozenset({
            "paper_search", "todo_manager", "notepad", "memory", "scope_manager",
        }),
    )
