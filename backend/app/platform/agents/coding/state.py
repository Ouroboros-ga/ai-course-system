"""CodingState: the state schema for the Coding Agent workflow.

Carries the student's code submission ID and the resulting diagnosis. The
state is intentionally minimal — the Coding Agent is a focused diagnostic
agent, not a full teaching workflow.
"""

from __future__ import annotations

from typing import Any

try:
    from typing import NotRequired, TypedDict
except ImportError:  # Python < 3.11
    from typing_extensions import NotRequired, TypedDict


class CodingState(TypedDict, total=False):
    """State for the Coding Agent workflow."""

    # Identity / tracing
    trace_id: str
    student_id: str
    course_id: str
    session_id: str

    # Input
    user_message: str
    code_submission_id: str
    exercise_id: str | None

    # Intermediate results
    sandbox_result: dict[str, Any] | None
    coding_diagnosis: dict[str, Any] | None

    # Output
    final_answer: str | None

    # Common fields (mirrors TeachingState / PrepState conventions)
    warnings: list[str]
    errors: list[str]
    degraded_services: list[str]
    trace: list[dict[str, Any]]
    status: NotRequired[str]
