"""Independent TeachingAgent API; it is unavailable until a runtime is injected."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.platform.agents.runtime import TeachingAgentRuntime


router = APIRouter()


class TeachingAgentRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    course_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    resource_id: str | None = Field(default=None, max_length=128)
    exercise_id: str | None = Field(default=None, max_length=128)
    code_submission_id: str | None = Field(default=None, max_length=128)


def get_runtime(request: Request) -> TeachingAgentRuntime:
    runtime = getattr(request.app.state, "teaching_agent_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail={"code": "TEACHING_AGENT_NOT_CONFIGURED", "message": "TeachingAgent runtime has not been injected."})
    return runtime


@router.post("/respond", summary="Controlled LangGraph teaching response")
async def respond(body: TeachingAgentRequest, request: Request) -> dict[str, Any]:
    state = await get_runtime(request).respond(student_id=body.student_id, course_id=body.course_id, session_id=body.session_id, message=body.message, resource_id=body.resource_id, exercise_id=body.exercise_id, code_submission_id=body.code_submission_id)
    if state.get("status") == "rejected":
        raise HTTPException(status_code=403, detail={"code": state["errors"][-1], "trace_id": state["trace_id"]})
    if state.get("status") == "llm_unavailable":
        raise HTTPException(status_code=503, detail={"code": "TEACHING_LLM_UNAVAILABLE", "trace_id": state["trace_id"]})
    concept = next((item for item in state.get("concept_candidates", []) if item.get("concept_id") == state.get("current_concept_id")), None)
    return {"trace_id": state["trace_id"], "intent": state.get("intent"), "concept": concept, "teaching_action": state.get("teaching_action"), "answer": state.get("final_answer"), "citations": state.get("citations", []), "recommended_resources": [{"resource_id": resource_id} for resource_id in state.get("selected_resource_ids", [])], "warnings": state.get("warnings", []), "degraded_services": state.get("degraded_services", [])}
