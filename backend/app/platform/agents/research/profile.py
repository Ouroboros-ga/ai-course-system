"""Runtime profile for a course-bound ResearchAgent."""
from __future__ import annotations

from typing import Any, Mapping

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
            "trace_id": trace_id,
            "course_id": ctx.course_id or "",
            "actor_user_id": str(ctx.extras.get("actor_user_id") or ctx.student_id or ctx.teacher_id or ""),
            "session_id": ctx.session_id or "",
            "user_message": ctx.user_message or "",
            "query": ctx.user_message or "",
            "max_results": max_results,
            "cursor": ctx.extras.get("cursor"),
            "warnings": [],
            "errors": [],
            "degraded_services": [],
            "trace": [],
        }

    return AgentProfile(
        agent_type=AgentType.RESEARCH,
        build_initial_state=build_initial_state,
        default_timeout_seconds=25.0,
        description="ResearchAgent: course-bound scholarly search with auditable source boundaries",
        max_concurrency=4,
        execution_mode=ExecutionMode.HYBRID,
        share_runtime_across_actors=True,
        allowed_tool_names=frozenset({"paper_search"}),
    )
