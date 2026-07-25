"""Independent TeachingAgent API; it is unavailable until a runtime is injected."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.security import get_current_user
from app.models.database import get_session
from app.platform.agents.runtime import TeachingAgentRuntime
from app.services.course_access_service import (
    require_course_permission,
    resolve_course_access,
)


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
async def respond(
    body: TeachingAgentRequest,
    request: Request,
    runtime: TeachingAgentRuntime = Depends(get_runtime),
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Run the agent only after the caller and the target learner are scoped.

    The request body is never an authorization source. A learner may only ask
    for their own state; staff may inspect another active learner only through
    the existing course analytics permission. This protects the ports even
    when an experimental runtime happens to be injected.
    """
    try:
        student_id = int(body.student_id)
        course_id = int(body.course_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "TEACHING_AGENT_SCOPE_INVALID", "message": "student_id 与 course_id 必须是数字 ID"},
        ) from exc

    caller_id = int(current_user["user_id"])
    if caller_id == student_id:
        caller_context = require_course_permission(
            session, current_user, course_id, "course.question.ask"
        )
        if not caller_context.analytics_eligible:
            raise HTTPException(
                status_code=403,
                detail={"code": "TEACHING_AGENT_LEARNER_REQUIRED", "message": "仅课程学习者可请求个人教学响应"},
            )
    else:
        require_course_permission(
            session, current_user, course_id, "analytics.view_member"
        )
        target_context = resolve_course_access(
            session, {"user_id": str(student_id)}, course_id
        )
        if not target_context.analytics_eligible:
            raise HTTPException(
                status_code=403,
                detail={"code": "TEACHING_AGENT_TARGET_NOT_LEARNER", "message": "目标不是本课程的有效学习者"},
            )

    # The current bootstrap deliberately injects one report-bound runtime.
    # Do not let a request body switch that runtime to another learner/course.
    runtime_scope = getattr(request.app.state, "teaching_agent_scope", None)
    if runtime_scope and (
        str(runtime_scope.get("student_id")) != body.student_id
        or str(runtime_scope.get("course_id")) != body.course_id
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TEACHING_AGENT_RUNTIME_SCOPE_MISMATCH",
                "message": "当前教学智能体运行时未绑定到该学生或课程",
            },
        )

    state = await runtime.respond(student_id=body.student_id, course_id=body.course_id, session_id=body.session_id, message=body.message, resource_id=body.resource_id, exercise_id=body.exercise_id, code_submission_id=body.code_submission_id)
    if state.get("status") == "rejected":
        raise HTTPException(status_code=403, detail={"code": state["errors"][-1], "trace_id": state["trace_id"]})
    if state.get("status") == "llm_unavailable":
        raise HTTPException(status_code=503, detail={"code": "TEACHING_LLM_UNAVAILABLE", "trace_id": state["trace_id"]})
    concept = next((item for item in state.get("concept_candidates", []) if item.get("concept_id") == state.get("current_concept_id")), None)
    return {"trace_id": state["trace_id"], "intent": state.get("intent"), "concept": concept, "teaching_action": state.get("teaching_action"), "answer": state.get("final_answer"), "citations": state.get("citations", []), "recommended_resources": [{"resource_id": resource_id} for resource_id in state.get("selected_resource_ids", [])], "warnings": state.get("warnings", []), "degraded_services": state.get("degraded_services", [])}
