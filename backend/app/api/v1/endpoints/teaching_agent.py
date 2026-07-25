"""Controlled TeachingAgent endpoint with Course Access v1 enforcement."""
from __future__ import annotations

from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.security import get_current_user
from app.models.database import get_session
from app.platform.agents.registry import TeachingAgentRuntimeRegistry
from app.platform.agents.runtime import TeachingAgentRuntime
from app.services.course_access_service import require_course_permission, resolve_course_access

router = APIRouter()


class TeachingAgentRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    course_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    resource_id: str | None = Field(default=None, max_length=128)
    exercise_id: str | None = Field(default=None, max_length=128)
    code_submission_id: str | None = Field(default=None, max_length=128)


def get_runtime(request: Request) -> Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry]:
    registry = getattr(request.app.state, "teaching_agent_runtime_registry", None)
    if registry is not None:
        return registry
    runtime = getattr(request.app.state, "teaching_agent_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail={"code": "TEACHING_AGENT_NOT_CONFIGURED", "message": "TeachingAgent runtime has not been injected."})
    return runtime


def _resolve_runtime(runtime_source: Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry], student_id: str, course_id: str) -> TeachingAgentRuntime:
    """Resolve a runtime; KG-MEST is optional enrichment, not an availability gate."""
    if isinstance(runtime_source, TeachingAgentRuntimeRegistry):
        runtime = runtime_source.get_or_create(student_id, course_id)
        if runtime is None:
            raise HTTPException(status_code=503, detail={"code": "TEACHING_AGENT_RUNTIME_UNAVAILABLE", "message": "TeachingAgent runtime could not be built."})
        return runtime
    return runtime_source


@router.post("/respond", summary="Controlled LangGraph teaching response")
async def respond(
    body: TeachingAgentRequest,
    request: Request,
    runtime_source: Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry] = Depends(get_runtime),
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        student_id = int(body.student_id)
        course_id = int(body.course_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "TEACHING_AGENT_SCOPE_INVALID", "message": "student_id and course_id must be numeric IDs"}) from exc

    caller_id = int(current_user["user_id"])
    if caller_id == student_id:
        context = require_course_permission(session, current_user, course_id, "course.question.ask")
        if not context.analytics_eligible:
            raise HTTPException(status_code=403, detail={"code": "TEACHING_AGENT_LEARNER_REQUIRED", "message": "Only an active course learner may request an individualized teaching response."})
    else:
        require_course_permission(session, current_user, course_id, "analytics.view_member")
        target_context = resolve_course_access(session, {"user_id": str(student_id)}, course_id)
        if not target_context.analytics_eligible:
            raise HTTPException(status_code=403, detail={"code": "TEACHING_AGENT_TARGET_NOT_LEARNER", "message": "Target is not an active learner in this course."})

    runtime = _resolve_runtime(runtime_source, body.student_id, body.course_id)
    state = await runtime.respond(
        student_id=body.student_id, course_id=body.course_id, session_id=body.session_id,
        message=body.message, resource_id=body.resource_id, exercise_id=body.exercise_id,
        code_submission_id=body.code_submission_id,
    )
    if state.get("status") == "rejected":
        raise HTTPException(status_code=403, detail={"code": state["errors"][-1], "trace_id": state["trace_id"]})
    if state.get("status") == "llm_unavailable":
        raise HTTPException(status_code=503, detail={"code": "TEACHING_LLM_UNAVAILABLE", "trace_id": state["trace_id"]})

    degraded = set(state.get("degraded_services", []))
    if {"knowledge_graph", "retrieval"} & degraded:
        # The frontend calls V1 /chat/ask and shows this human-readable state.
        return {
            "trace_id": state["trace_id"], "status": "fallback_required",
            "fallback_reason": "COURSE_KNOWLEDGE_GRAPH_PENDING",
            "warnings": [*state.get("warnings", []), "COURSE_KNOWLEDGE_GRAPH_PENDING"],
            "degraded_services": sorted(degraded),
        }

    concept = next((item for item in state.get("concept_candidates", []) if item.get("concept_id") == state.get("current_concept_id")), None)
    return {
        "trace_id": state["trace_id"], "status": "ok", "intent": state.get("intent"), "concept": concept,
        "teaching_action": state.get("teaching_action"), "answer": state.get("final_answer"),
        "citations": state.get("citations", []),
        "recommended_resources": [{"resource_id": resource_id} for resource_id in state.get("selected_resource_ids", [])],
        "warnings": state.get("warnings", []), "degraded_services": state.get("degraded_services", []),
    }
