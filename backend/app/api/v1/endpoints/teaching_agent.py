"""Independent TeachingAgent API; it is unavailable until a runtime is injected."""

from __future__ import annotations

from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.security import get_current_user
from app.models.database import get_session
from app.platform.agents.registry import TeachingAgentRuntimeRegistry
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


def get_runtime(request: Request) -> Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry]:
    """Resolve the TeachingAgent runtime source for the request.

    批次4：优先返回 ``teaching_agent_runtime_registry``（按 student_id+course_id
    动态路由）；若 registry 缺失则回退到旧的单运行时注入（``teaching_agent_runtime``）。
    两者都缺失时返回 503（``TEACHING_AGENT_NOT_CONFIGURED``）。

    依赖顺序：本依赖在 ``get_current_user`` 之前解析，因此未注入运行时时
    503 优先于 401 返回（保持现有测试行为）。
    """
    registry = getattr(request.app.state, "teaching_agent_runtime_registry", None)
    if registry is not None:
        return registry
    runtime = getattr(request.app.state, "teaching_agent_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "TEACHING_AGENT_NOT_CONFIGURED", "message": "TeachingAgent runtime has not been injected."},
        )
    return runtime


def _resolve_runtime(
    runtime_source: Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry],
    student_id: str,
    course_id: str,
) -> TeachingAgentRuntime:
    """Resolve a concrete ``TeachingAgentRuntime`` for (student_id, course_id).

    When a registry is present, look up the runtime by (student_id, course_id);
    fail-closed 503 if no report is bound to that scope. When only the legacy
    single-runtime is injected, return it directly (preserves backward compat
    with the existing injected-runtime tests).
    """
    if isinstance(runtime_source, TeachingAgentRuntimeRegistry):
        runtime = runtime_source.get_or_create(student_id, course_id)
        if runtime is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "TEACHING_AGENT_SCOPE_NOT_CONFIGURED",
                    "message": "当前学生/课程没有可用的 KG-MEST Shadow 报告",
                },
            )
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
    """Run the agent only after the caller and the target learner are scoped.

    The request body is never an authorization source. A learner may only ask
    for their own state; staff may inspect another active learner only through
    the existing course analytics permission. This protects the ports even
    when an experimental runtime happens to be injected.

    批次4：移除原有的 ``teaching_agent_scope`` 单一作用域校验。运行时由
    ``teaching_agent_runtime_registry`` 按 (student_id, course_id) 动态解析；
    无对应报告时返回 503。权限校验仍要求 ``course.question.ask``。
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

    # 批次4：通过 registry 按 (student_id, course_id) 解析运行时。
    # 无对应报告时 fail-closed 503；不再做单一 scope 校验。
    runtime = _resolve_runtime(runtime_source, body.student_id, body.course_id)

    state = await runtime.respond(student_id=body.student_id, course_id=body.course_id, session_id=body.session_id, message=body.message, resource_id=body.resource_id, exercise_id=body.exercise_id, code_submission_id=body.code_submission_id)
    if state.get("status") == "rejected":
        raise HTTPException(status_code=403, detail={"code": state["errors"][-1], "trace_id": state["trace_id"]})
    if state.get("status") == "llm_unavailable":
        raise HTTPException(status_code=503, detail={"code": "TEACHING_LLM_UNAVAILABLE", "trace_id": state["trace_id"]})
    concept = next((item for item in state.get("concept_candidates", []) if item.get("concept_id") == state.get("current_concept_id")), None)
    return {"trace_id": state["trace_id"], "intent": state.get("intent"), "concept": concept, "teaching_action": state.get("teaching_action"), "answer": state.get("final_answer"), "citations": state.get("citations", []), "recommended_resources": [{"resource_id": resource_id} for resource_id in state.get("selected_resource_ids", [])], "warnings": state.get("warnings", []), "degraded_services": state.get("degraded_services", [])}
