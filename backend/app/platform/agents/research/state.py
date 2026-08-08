"""State owned by the ResearchAgent literature-search workflow."""
from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class ResearchState(TypedDict, total=False):
    trace_id: str
    course_id: str
    actor_user_id: str
    session_id: str

    user_message: str
    query: str
    max_results: int
    cursor: str | None

    search_result: dict[str, Any] | None
    papers: list[dict[str, Any]]
    final_answer: str | None

    warnings: list[str]
    errors: list[str]
    degraded_services: list[str]
    trace: list[dict[str, Any]]
    status: NotRequired[str]
