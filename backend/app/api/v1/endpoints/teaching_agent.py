"""Controlled TeachingAgent endpoint with Course Access v1 enforcement."""
from __future__ import annotations

from typing import Any, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
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
from app.services.coding_challenge_service import coding_challenge_service
from app.schemas.learning_adjustment import QuestionObservation
from app.core.exceptions import unified_response

router = APIRouter()


@router.get(
    "/coding-challenges/active",
    summary="Restore the learner's active conversational coding challenge",
)
async def get_active_coding_challenge(
    course_id: int,
    session_id: str = Query(min_length=1, max_length=128),
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Restore only the authenticated learner's offer for this conversation."""
    context = require_course_permission(
        session, current_user, course_id, "experiment.run",
    )
    if not (
        context.analytics_eligible
        and context.capabilities.get("experiment", False)
        and context.capabilities.get("coding_sandbox", False)
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CODING_CHALLENGE_UNAVAILABLE",
                "message": "The course has not enabled conversational coding challenges.",
            },
        )
    state = coding_challenge_service.get_active_state(
        session,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
        conversation_session_id=session_id,
    )
    return unified_response(code=200, message="Coding challenge state", data=state)


def _require_coding_challenge_access(
    session: Session,
    current_user: dict[str, Any],
    course_id: int,
) -> None:
    context = require_course_permission(
        session, current_user, course_id, "experiment.run",
    )
    if not (
        context.analytics_eligible
        and context.capabilities.get("experiment", False)
        and context.capabilities.get("coding_sandbox", False)
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CODING_CHALLENGE_UNAVAILABLE",
                "message": "The course has not enabled conversational coding challenges.",
            },
        )


@router.get("/coding-challenges/offers/{offer_id}")
async def get_coding_challenge_offer(
    offer_id: str,
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _require_coding_challenge_access(session, current_user, course_id)
    offer = coding_challenge_service.get_offer_view(
        session,
        offer_id=offer_id,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
    )
    return unified_response(code=200, message="Coding challenge offer", data=offer)


@router.post("/coding-challenges/offers/{offer_id}/dismiss")
async def dismiss_coding_challenge_offer(
    offer_id: str,
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _require_coding_challenge_access(session, current_user, course_id)
    offer = coding_challenge_service.dismiss_offer(
        session,
        offer_id=offer_id,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
    )
    return unified_response(code=200, message="Coding challenge dismissed", data=offer)


@router.post("/coding-challenges/offers/{offer_id}/replace")
async def replace_coding_challenge_offer(
    offer_id: str,
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _require_coding_challenge_access(session, current_user, course_id)
    offer = coding_challenge_service.replace_offer(
        session,
        offer_id=offer_id,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
    )
    return unified_response(code=200, message="Coding challenge replaced", data=offer)


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


class CodingChallengeStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_anchor: dict[str, Any] = Field(default_factory=dict)


class CodingChallengeRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(min_length=1, max_length=50)
    source_code: str = Field(min_length=1, max_length=100_000)


class CodingChallengeCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="returned_to_course", pattern="^(accepted|returned_to_course|student_exit|inactive_timeout)$")


@router.post(
    "/coding-challenges/offers/{offer_id}/start",
    summary="Start one verified guided-practice coding challenge",
)
async def start_coding_challenge(
    offer_id: str,
    payload: CodingChallengeStartRequest,
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    context = require_course_permission(
        session, current_user, course_id, "experiment.run",
    )
    if not (
        context.analytics_eligible
        and context.capabilities.get("experiment", False)
        and context.capabilities.get("coding_sandbox", False)
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CODING_CHALLENGE_UNAVAILABLE",
                "message": "The course has not enabled conversational coding challenges.",
            },
        )
    state = coding_challenge_service.start_offer(
        session,
        offer_id=offer_id,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
        return_anchor=payload.return_anchor,
    )
    return unified_response(code=200, message="Coding challenge started", data=state)


@router.post(
    "/coding-challenges/sessions/{challenge_session_id}/runs",
    status_code=202,
    summary="Run code and request TeachingAgent feedback",
)
async def create_coding_challenge_run(
    challenge_session_id: str,
    payload: CodingChallengeRunRequest,
    course_id: int,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=128,
    ),
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> JSONResponse:
    context = require_course_permission(
        session, current_user, course_id, "experiment.run",
    )
    if not (
        context.analytics_eligible
        and context.capabilities.get("experiment", False)
        and context.capabilities.get("coding_sandbox", False)
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CODING_CHALLENGE_UNAVAILABLE",
                "message": "The course has not enabled conversational coding challenges.",
            },
        )
    if not idempotency_key:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "Idempotency-Key is required for code runs.",
            },
        )

    user_id = int(current_user["user_id"])
    coding_challenge_service.require_open_guided_session(
        session,
        attempt_id=challenge_session_id,
        course_id=course_id,
        student_id=user_id,
    )
    from app.services.experiment_service import run_service
    from app.services.task_service import TaskCreateRequest, task_service

    run = await run_service.create_run(
        session,
        course_id=course_id,
        attempt_id=challenge_session_id,
        language=payload.language,
        source_code=payload.source_code,
        student_id=user_id,
        idempotency_key=idempotency_key,
    )
    if not run.task_id:
        task_view = task_service.create_task(session, TaskCreateRequest(
            task_type="experiment_run",
            owner_user_id=user_id,
            course_id=course_id,
            input_summary=f"课程 {course_id} 引导练习 {challenge_session_id} 代码运行",
            # Source is already stored in the access-controlled run record;
            # duplicating it into a task payload would contaminate task audit.
            input_payload={
                "course_id": course_id,
                "run_id": run.run_id,
                "attempt_id": challenge_session_id,
                "language": payload.language,
                "student_id": user_id,
                "interaction_mode": "guided_practice",
            },
            idempotency_key=(
                f"guided-experiment-run:{course_id}:{challenge_session_id}:{idempotency_key}"
            ),
            resource_links=[
                {"resource_kind": "course", "resource_id": str(course_id), "relation": "input"},
                {
                    "resource_kind": "experiment_attempt",
                    "resource_id": challenge_session_id,
                    "relation": "input",
                },
                {"resource_kind": "experiment_run", "resource_id": run.run_id, "relation": "output"},
            ],
        ), commit=False)
        run.task_id = task_view.task_id
        session.add(run)
        coding_challenge_service.touch_session(
            session,
            attempt_id=challenge_session_id,
            course_id=course_id,
            student_id=user_id,
        )
        session.commit()
        session.refresh(run)
        try:
            from app.models.database import session_factory as _session_factory
            from app.platform.tasks.worker import local_task_worker

            if local_task_worker.has_handler("experiment_run"):
                local_task_worker.submit(
                    _session_factory,
                    task_view.task_id,
                    {
                        "course_id": course_id,
                        "run_id": run.run_id,
                        "attempt_id": challenge_session_id,
                        "student_id": user_id,
                    },
                )
        except Exception:
            # The durable task remains pending and can be recovered by the
            # normal startup task scan.
            pass

    return JSONResponse(
        status_code=202,
        content=unified_response(
            code=202,
            message="Code run queued",
            data={"run_id": run.run_id, "task_id": run.task_id, "status": run.outcome.value},
        ),
    )


@router.post(
    "/coding-challenges/sessions/{challenge_session_id}/close",
    summary="Close and aggregate one guided-practice evidence episode",
)
async def close_coding_challenge(
    challenge_session_id: str,
    payload: CodingChallengeCloseRequest,
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    context = require_course_permission(
        session, current_user, course_id, "experiment.run",
    )
    if not (
        context.analytics_eligible
        and context.capabilities.get("experiment", False)
        and context.capabilities.get("coding_sandbox", False)
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CODING_CHALLENGE_UNAVAILABLE",
                "message": "The course has not enabled conversational coding challenges.",
            },
        )
    result = coding_challenge_service.close_session(
        session,
        attempt_id=challenge_session_id,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
        reason=payload.reason,
    )
    return unified_response(code=200, message="Coding challenge closed", data=result)


@router.get(
    "/coding-challenges/runs/{run_id}",
    summary="Read a bounded run result and TeachingAgent feedback",
)
async def get_coding_challenge_run(
    run_id: str,
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    context = require_course_permission(
        session, current_user, course_id, "experiment.run",
    )
    if not (
        context.analytics_eligible
        and context.capabilities.get("experiment", False)
        and context.capabilities.get("coding_sandbox", False)
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CODING_CHALLENGE_UNAVAILABLE",
                "message": "The course has not enabled conversational coding challenges.",
            },
        )
    data = coding_challenge_service.get_run_view(
        session,
        run_id=run_id,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
    )
    return unified_response(code=200, message="Coding challenge run", data=data)


@router.post(
    "/coding-challenges/runs/{run_id}/hint",
    summary="Reveal and record use of the optional TeachingAgent hint",
)
async def reveal_coding_challenge_hint(
    run_id: str,
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _require_coding_challenge_access(session, current_user, course_id)
    data = coding_challenge_service.reveal_run_hint(
        session,
        run_id=run_id,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
    )
    return unified_response(code=200, message="Optional hint revealed", data=data)


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
    sandbox_available: bool | None = None,
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
    # R14：学科参考（is_supplementary）随回答透出，供前端展示"学科参考"区块；
    # 与 citations（课程证据闭包）严格分离。2026-09-01 起兼容两级来源：
    # discipline_kb（概念层）与 discipline_corpus（语料段落层，RAG 白名单）。
    discipline_references = [
        {
            "node_id": ref.get("node_id"),
            "name": ref.get("name"),
            "course": ref.get("course"),
            "node_type": ref.get("node_type", "concept"),
            "definition": ref.get("definition"),
            "key_points": ref.get("key_points", []),
            "doc_id": ref.get("doc_id"),
            "chunk_no": ref.get("chunk_no"),
            "matched_by": ref.get("matched_by", []),
            "source_title": ref.get("source_title"),
            "source_authors": ref.get("source_authors"),
            "source_chapter": ref.get("source_chapter"),
            "source_license": ref.get("source_license"),
            "retrieval_source": ref.get("retrieval_source", "discipline_kb"),
            "is_supplementary": True,
        }
        for ref in state.get("discipline_kb_results", [])
        if ref.get("name")
    ]
    response = {
        "trace_id": state["trace_id"], "status": "ok", "intent": state.get("intent"), "concept": concept,
        "teaching_action": state.get("teaching_action"), "answer": state.get("final_answer"),
        "citations": state.get("citations", []),
        "discipline_references": discipline_references,
        "recommended_resources": [{"resource_id": resource_id} for resource_id in state.get("selected_resource_ids", [])],
        "warnings": state.get("warnings", []), "degraded_services": state.get("degraded_services", []),
        "learning_adjustment": state.get("learning_adjustment"),
    }

    # Challenge preparation never delays or replaces the teaching answer.
    # The decision receives only this turn plus structured runtime fields; all
    # authorization, release identity, frequency and sandbox gates are applied
    # again by the server-owned service before an offer can be returned.
    if persist_learner_turn:
        try:
            offer = await coding_challenge_service.maybe_create_offer(
                session,
                course_id=course_id,
                student_id=subject_user_id,
                conversation_session_id=session_id,
                trace_id=str(state.get("trace_id", "")),
                message=message,
                concept_id=state.get("current_concept_id"),
                teaching_action=state.get("teaching_action"),
                sandbox_available=sandbox_available,
            )
            if offer is not None:
                response["coding_challenge_offer"] = offer
        except Exception:
            # An unavailable generator or stale release identity is a local
            # offer failure, never a reason to suppress the completed answer.
            pass

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
    request: Request,
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
        sandbox_available=(
            bool(getattr(request.app.state.coding_agent_sandbox_port, "is_healthy", False))
            if getattr(request.app.state, "coding_agent_sandbox_port", None) is not None
            else None
        ),
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
