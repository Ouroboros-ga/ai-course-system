"""Controlled TeachingAgent endpoint with Course Access v1 enforcement."""
from __future__ import annotations

from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.security import get_current_user
from app.models.database import get_session
from app.platform.agents.platform import AgentPlatform
from app.platform.agents.registry import TeachingAgentRuntimeRegistry
from app.platform.agents.runtime import TeachingAgentRuntime
from app.platform.agents.runtime.profile import AgentType
from app.services.cognitive_service import compute_cognitive_state, record_question_depth
from app.services.conversation_service import (
    derive_question_inference_signals,
    list_conversation_messages,
    persist_conversation_turn,
)
from app.services.course_access_service import require_course_permission, resolve_course_access
from app.schemas.learning_adjustment import QuestionObservation

router = APIRouter()


def _course_agent_enabled(session: Session, course_id: int) -> bool:
    """课程级智能体启动开关（settings.agent_policy.enabled）。

    未显式配置（enabled 为 None）视为开启——本地 Demo 底层开关全开的
    默认语义；教师可在设置页「智能体」显式关闭后，教学问答端点拒绝请求。
    会话对象不完整（如单元测试的 mock session）时同样默认开启。
    """
    if not hasattr(session, "exec"):
        return True
    from app.services.course_lifecycle_service import course_settings_service

    current = course_settings_service.get_current(session, course_id=course_id)
    if current is None or not current.agent_policy:
        return True
    enabled = current.agent_policy.get("enabled")
    return enabled is None or enabled is True


class TeachingAgentRequest(BaseModel):
    """Self-service request.

    ``student_id`` is retained as a deprecated compatibility field.  The
    endpoint never trusts it; the authenticated user is always the learner
    subject.  Teacher/admin impersonation uses the separate
    ``/respond-for-learner`` contract.
    """

    model_config = ConfigDict(extra="forbid")

    student_id: str | None = Field(default=None, min_length=1, max_length=128)
    course_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    resource_id: str | None = Field(default=None, max_length=128)
    exercise_id: str | None = Field(default=None, max_length=128)
    code_submission_id: str | None = Field(default=None, max_length=128)
    question_observation: QuestionObservation | None = None


def get_runtime(request: Request) -> Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry, AgentPlatform]:
    # 统一入口：优先经 AgentPlatform 解析（Prep/Coding/EDU 同一入口）。
    # 向后兼容：仅注入 legacy registry 的环境（如部分测试）回退到 registry。
    platform = getattr(request.app.state, "agent_platform", None)
    if platform is not None and getattr(platform, "is_legacy", lambda _t: False)(AgentType.EDU):
        return platform
    registry = getattr(request.app.state, "teaching_agent_runtime_registry", None)
    if registry is not None:
        return registry
    runtime = getattr(request.app.state, "teaching_agent_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail={"code": "TEACHING_AGENT_NOT_CONFIGURED", "message": "TeachingAgent runtime has not been injected."})
    return runtime


class TeachingAgentLearnerRequest(BaseModel):
    """Teacher-side request for a specific learner in the course."""

    model_config = ConfigDict(extra="forbid")

    learner_user_id: str = Field(min_length=1, max_length=128)
    course_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    resource_id: str | None = Field(default=None, max_length=128)
    exercise_id: str | None = Field(default=None, max_length=128)
    code_submission_id: str | None = Field(default=None, max_length=128)


def _resolve_runtime(runtime_source: Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry, AgentPlatform], student_id: str, course_id: str) -> TeachingAgentRuntime:
    """Resolve a runtime; KG-MEST is optional enrichment, not an availability gate."""
    if isinstance(runtime_source, AgentPlatform):
        runtime = runtime_source.get_legacy_runtime(AgentType.EDU, student_id, course_id)
        if runtime is None:
            raise HTTPException(status_code=503, detail={"code": "TEACHING_AGENT_RUNTIME_UNAVAILABLE", "message": "TeachingAgent runtime could not be built."})
        return runtime
    if isinstance(runtime_source, TeachingAgentRuntimeRegistry):
        runtime = runtime_source.get_or_create(student_id, course_id)
        if runtime is None:
            raise HTTPException(status_code=503, detail={"code": "TEACHING_AGENT_RUNTIME_UNAVAILABLE", "message": "TeachingAgent runtime could not be built."})
        return runtime
    return runtime_source


async def _respond_for_subject(
    *,
    subject_user_id: int,
    course_id: int,
    session_id: str,
    message: str,
    resource_id: str | None,
    exercise_id: str | None,
    code_submission_id: str | None,
    question_observation: QuestionObservation | None,
    persist_learner_turn: bool,
    runtime_source: Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry, AgentPlatform],
    session: Session,
) -> dict[str, Any]:
    runtime = _resolve_runtime(runtime_source, str(subject_user_id), str(course_id))
    state = await runtime.respond(
        student_id=str(subject_user_id), course_id=str(course_id), session_id=session_id,
        message=message, resource_id=resource_id, exercise_id=exercise_id,
        code_submission_id=code_submission_id,
        question_observation=question_observation,
    )
    if state.get("status") == "rejected":
        raise HTTPException(status_code=403, detail={"code": state["errors"][-1], "trace_id": state["trace_id"]})
    if state.get("status") == "llm_unavailable":
        raise HTTPException(status_code=503, detail={"code": "TEACHING_LLM_UNAVAILABLE", "trace_id": state["trace_id"]})

    # 认知采集：LLM 已在意图解析时实时标定提问深度，随本次回答落库（追加型）。
    # 记录失败不影响回答本身（数据最小化，只存深度分数与标签）。
    depth = state.get("inquiry_depth")
    if persist_learner_turn and depth is not None:
        try:
            node_id = _safe_node_id(session, course_id, state.get("current_concept_id"))
            record_question_depth(
                session,
                student_id=subject_user_id,
                course_id=course_id,
                node_id=node_id,
                depth_score=float(depth),
                trace_id=str(state.get("trace_id", "")),
            )
            # 提问本身就是认知证据：深度记录落库后立即重算六维认知，
            # 让 inquiry_depth 随提问及时更新，而不是只等答题触发。
            compute_cognitive_state(
                session,
                student_id=subject_user_id,
                course_id=course_id,
                node_id=node_id,
            )
        except Exception:  # noqa: BLE001 - 认知采集失败不阻断回答
            pass

    degraded = set(state.get("degraded_services", []))
    if {"knowledge_graph", "retrieval"} & degraded:
        return {
            "trace_id": state["trace_id"], "status": "fallback_required",
            "fallback_reason": "COURSE_KNOWLEDGE_GRAPH_PENDING",
            "warnings": [*state.get("warnings", []), "COURSE_KNOWLEDGE_GRAPH_PENDING"],
            "degraded_services": sorted(degraded),
        }

    concept = next((item for item in state.get("concept_candidates", []) if item.get("concept_id") == state.get("current_concept_id")), None)
    response = {
        "trace_id": state["trace_id"], "status": "ok", "intent": state.get("intent"), "concept": concept,
        "teaching_action": state.get("teaching_action"), "answer": state.get("final_answer"),
        "citations": state.get("citations", []),
        "recommended_resources": [{"resource_id": resource_id} for resource_id in state.get("selected_resource_ids", [])],
        "warnings": state.get("warnings", []), "degraded_services": state.get("degraded_services", []),
        "learning_adjustment": state.get("learning_adjustment"),
    }

    # Conversation Domain (AGENTS.md §5.1): persist the question/answer turn so
    # the learner can resume the conversation. This is the product-experience
    # domain, independent from the data-minimized Agent Runtime Context / Audit
    # tables. Only persisted when a final answer exists (atomic Q/A turn).
    # Non-blocking: a persistence failure must never break the teaching response.
    final_answer = state.get("final_answer")
    if persist_learner_turn and final_answer:
        persist_conversation_turn(
            session,
            student_id=subject_user_id,
            course_id=course_id,
            session_id=session_id,
            trace_id=str(state.get("trace_id", "")),
            user_message=message,
            assistant_answer=final_answer,
            concept_id=state.get("current_concept_id"),
            resource_id=resource_id,
            citations=state.get("citations", []),
        )
    return response


@router.post("/respond", summary="Controlled LangGraph self-service teaching response")
async def respond(
    body: TeachingAgentRequest,
    runtime_source: Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry] = Depends(get_runtime),
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        course_id = int(body.course_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "TEACHING_AGENT_SCOPE_INVALID", "message": "course_id must be a numeric ID"}) from exc

    caller_id = int(current_user["user_id"])
    if body.student_id is not None and str(body.student_id) != str(caller_id):
        raise HTTPException(status_code=403, detail={"code": "TEACHING_AGENT_SELF_ID_MISMATCH", "message": "Self-service requests cannot select another learner."})
    context = require_course_permission(session, current_user, course_id, "course.question.ask")
    if not _course_agent_enabled(session, course_id):
        raise HTTPException(status_code=403, detail={"code": "TEACHING_AGENT_DISABLED", "message": "课程智能体未启用，请联系课程教师在设置中开启。"})
    if not context.analytics_eligible:
        raise HTTPException(status_code=403, detail={"code": "TEACHING_AGENT_LEARNER_REQUIRED", "message": "Only an active course learner may request an individualized teaching response."})
    return await _respond_for_subject(
        subject_user_id=caller_id, course_id=course_id, session_id=body.session_id,
        message=body.message, resource_id=body.resource_id, exercise_id=body.exercise_id,
        code_submission_id=body.code_submission_id, runtime_source=runtime_source,
        question_observation=body.question_observation,
        persist_learner_turn=True,
        session=session,
    )


@router.post("/respond-for-learner", summary="Controlled teaching response for a selected learner")
async def respond_for_learner(
    body: TeachingAgentLearnerRequest,
    runtime_source: Union[TeachingAgentRuntime, TeachingAgentRuntimeRegistry] = Depends(get_runtime),
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        learner_user_id = int(body.learner_user_id)
        course_id = int(body.course_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "TEACHING_AGENT_SCOPE_INVALID", "message": "learner_user_id and course_id must be numeric IDs"}) from exc

    require_course_permission(session, current_user, course_id, "analytics.view_member")
    if not _course_agent_enabled(session, course_id):
        raise HTTPException(status_code=403, detail={"code": "TEACHING_AGENT_DISABLED", "message": "课程智能体未启用，请联系课程教师在设置中开启。"})
    target_context = resolve_course_access(session, {"user_id": str(learner_user_id)}, course_id)
    if not target_context.analytics_eligible:
        raise HTTPException(status_code=403, detail={"code": "TEACHING_AGENT_TARGET_NOT_LEARNER", "message": "Target is not an active learner in this course."})
    return await _respond_for_subject(
        subject_user_id=learner_user_id, course_id=course_id, session_id=body.session_id,
        message=body.message, resource_id=body.resource_id, exercise_id=body.exercise_id,
        code_submission_id=body.code_submission_id, runtime_source=runtime_source,
        question_observation=None,
        persist_learner_turn=False,
        session=session,
    )


def _safe_node_id(session: Session, course_id: int, value: Any) -> int | None:
    """把概念/节点 ID（数字或 ``kn_*`` node_key）解析为课程内数字节点 ID。

    教学工作流中的 ``current_concept_id`` 是知识图谱的稳定公开 node_key
    （如 ``kn_xxx``），而提问深度/认知表使用 ``CourseKnowledgeNode.id``。
    解析必须课程隔离；缺失、非法或跨课程时返回 None（对应课程级），
    绝不静默把别的课程节点当作本课程节点。
    """
    if value is None or value == "":
        return None
    try:
        from app.services.knowledge_node_identity_service import resolve_node_id

        return resolve_node_id(session, course_id, value)
    except Exception:  # noqa: BLE001 - 身份解析失败退化为课程级，不阻断回答
        return None


@router.get("/conversations/{course_id}", summary="Resume a learner's teaching-agent conversation")
async def list_conversation_history(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
    session_id: str | None = Query(default=None, description="可选：限定某个学习会话"),
    limit: int = Query(default=200, ge=1, le=500, description="返回消息上限"),
) -> dict[str, Any]:
    """Conversation Domain: return the calling learner's conversation history.

    Scoped to the authenticated learner via ``course.question.ask``. Returns
    messages oldest-first so the workspace can rebuild the chat panel after a
    refresh / re-entry. Expired rows (past retention) are excluded server-side.
    This is the product-experience domain; the Agent Runtime Context / Audit
    tables remain data-minimized and never expose raw messages.
    """
    context = require_course_permission(session, current_user, course_id, "course.question.ask")
    if not context.analytics_eligible:
        raise HTTPException(status_code=403, detail={"code": "TEACHING_AGENT_LEARNER_REQUIRED", "message": "Only an active course learner may read their own conversation history."})
    messages = list_conversation_messages(
        session,
        student_id=int(current_user["user_id"]),
        course_id=course_id,
        session_id=session_id,
        limit=limit,
    )
    return {
        "course_id": course_id,
        "session_id": session_id,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "concept_id": msg.concept_id,
                "resource_id": msg.resource_id,
                "trace_id": msg.trace_id,
                "citations": msg.citations,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ],
    }


@router.get("/conversations/{course_id}/inference", summary="Question-derived learning signals (提问反推)")
async def get_question_inference_signals(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
    concept_id: str | None = Query(default=None, description="可选：限定某个知识点概念 ID"),
    lookback_days: int = Query(default=14, ge=1, le=90, description="回看窗口天数"),
) -> dict[str, Any]:
    """提问反推：把学生近期提问聚合成结构化学习证据信号。

    学习分析不得直接依赖完整 Conversation（AGENTS.md §5.1）；本接口返回的是
    结构化投影（计数、平均提问深度、薄弱标记、trace 引用），不返回原始问题
    全文。学习者读取自己的信号；教师读取需走 analytics.view_member 的受控路径。
    """
    context = require_course_permission(session, current_user, course_id, "course.question.ask")
    if not context.analytics_eligible:
        raise HTTPException(status_code=403, detail={"code": "TEACHING_AGENT_LEARNER_REQUIRED", "message": "Only an active course learner may read their own inference signals."})
    return derive_question_inference_signals(
        session,
        student_id=int(current_user["user_id"]),
        course_id=course_id,
        concept_id=concept_id,
        lookback_days=lookback_days,
    )
