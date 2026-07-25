"""Application-facing runtime for the controlled TeachingAgent workflow."""

from __future__ import annotations

import uuid
from typing import Any

from .contracts import TeachingTools
from .state import TeachingState
from .workflows.teaching import build_teaching_workflow


class TeachingAgentRuntime:
    def __init__(self, tools: TeachingTools) -> None:
        self._graph = build_teaching_workflow(tools)

    async def respond(self, *, student_id: str, course_id: str, session_id: str, message: str, resource_id: str | None = None, exercise_id: str | None = None, code_submission_id: str | None = None) -> TeachingState:
        initial: TeachingState = {
            "trace_id": str(uuid.uuid4()), "student_id": student_id, "course_id": course_id,
            "session_id": session_id, "user_message": message, "current_resource_id": resource_id,
            "current_exercise_id": exercise_id, "current_code_submission_id": code_submission_id,
            "warnings": [], "errors": [], "degraded_services": [], "trace": [], "citations": [],
            "retrieved_evidence": [], "selected_resource_ids": [],
            "session_context": None,
        }
        return await self._graph.ainvoke(initial)
