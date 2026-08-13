"""Removable compatibility adapter for the Fanya/Chaoxing AI API example.

The source PDF is a reference example, not an assertion of an official
Chaoxing certification. This adapter is intentionally isolated from the
internal JWT routes: it translates only the external envelope and delegates to
existing Course Access and TeachingAgent services. Unsupported mappings fail
closed instead of inventing completion results.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.config import settings
from app.core.time_utils import to_aware, utcnow_aware
from app.models.course_model import Course, CourseScript, ScriptNode
from app.models.conversation_model import ConversationMessage
from app.models.database import get_session
from app.models.progress_model import LearningProgress, LearningStatus
from app.models.user_model import User
from app.services.course_access_service import require_course_permission
from app.services.learning_adjustment_service import learning_adjustment_service


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id") or f"req-{uuid.uuid4().hex}"


def _envelope(request: Request, code: int, msg: str, data: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={"code": code, "msg": msg, "data": data, "requestId": _request_id(request)},
    )


class CompatibilityRoute(APIRoute):
    """Keep validation and dependency failures inside the external envelope."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[JSONResponse]]:
        original_handler = super().get_route_handler()

        async def compat_handler(request: Request):
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                return _envelope(
                    request,
                    400,
                    "VALIDATION_FAILED",
                    {"code": "VALIDATION_FAILED", "errors": exc.errors()},
                )
            except HTTPException as exc:
                detail = exc.detail
                if isinstance(detail, dict):
                    message = str(detail.get("code") or detail.get("message") or "REQUEST_REJECTED")
                    data = detail
                else:
                    message = str(detail or "REQUEST_REJECTED")
                    data = {"code": message}
                return _envelope(request, exc.status_code, message, data)

        return compat_handler


router = APIRouter(
    tags=["泛雅·超星 AI 开放 API 参考兼容层"],
    route_class=CompatibilityRoute,
)


def _canonical_value(value: Any) -> str:
    """Produce a stable, documented representation for structured parameters."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return str(value)


def _compat_static_key() -> str:
    """Use a dedicated key when configured, with the legacy dev key as fallback.

    Keeping this lookup inside the optional package means deleting the package
    also removes its configuration behaviour. Deployments should set the
    dedicated variable rather than sharing the legacy internal signing key.
    """
    return os.getenv("FANYA_CHAOXING_AI_COMPAT_STATIC_KEY", "").strip() or settings.STATIC_KEY


def _parse_compat_time(value: str) -> datetime:
    formats = tuple(dict.fromkeys((settings.TIME_FORMAT, "%Y-%m-%d%H:%M:%S")))
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError("invalid time")


async def verify_compat_signature(request: Request) -> None:
    """Verify the reference MD5 ``time``/``enc`` request contract.

    The parent signature middleware deliberately whitelists this prefix so
    that this adapter owns both the exact canonicalisation and response shape.
    """
    static_key = _compat_static_key()
    if not static_key:
        raise HTTPException(status_code=503, detail={"code": "COMPAT_SIGNING_NOT_CONFIGURED"})

    params = dict(request.query_params)
    try:
        body = await request.json()
    except Exception:  # A schema error below gives the caller details.
        body = None
    if isinstance(body, dict):
        params.update(body)

    time_value = str(params.get("time") or "")
    provided = str(params.get("enc") or "")
    if not time_value or not provided:
        raise HTTPException(
            status_code=403,
            detail={"code": "SIGNATURE_INVALID", "message": "time and enc are required"},
        )
    try:
        request_time = _parse_compat_time(time_value)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail={"code": "SIGNATURE_INVALID"}) from exc
    if abs((utcnow_aware() - request_time).total_seconds()) > settings.SIGN_TIMEOUT_MINUTES * 60:
        raise HTTPException(status_code=403, detail={"code": "SIGNATURE_EXPIRED"})

    canonical = "".join(
        f"{key}{_canonical_value(params[key])}"
        for key in sorted(params)
        if key != "enc" and params[key] is not None and _canonical_value(params[key]).strip()
    )
    expected = hashlib.md5(f"{canonical}{static_key}{time_value}".encode("utf-8")).hexdigest().upper()
    if not hmac.compare_digest(expected, provided.upper()):
        raise HTTPException(status_code=403, detail={"code": "SIGNATURE_INVALID"})


class QAInteractRequest(BaseModel):
    schoolId: str = Field(min_length=1, max_length=128)
    userId: str = Field(min_length=1, max_length=128)
    courseId: str = Field(min_length=1, max_length=128)
    lessonId: str = Field(min_length=1, max_length=128)
    sessionId: str = Field(min_length=1, max_length=128)
    questionType: str = Field(default="text", pattern="^(text|voice)$")
    questionContent: str = Field(min_length=1, max_length=4000)
    currentSectionId: Optional[str] = Field(default=None, max_length=128)
    historyQa: list[dict[str, Any]] = Field(default_factory=list)
    time: Optional[str] = None
    enc: Optional[str] = None


class VoiceToTextRequest(BaseModel):
    voiceUrl: str = Field(min_length=1, max_length=2000)
    voiceDuration: Optional[int] = Field(default=None, ge=0, le=3600)
    language: str = Field(default="zh-CN", max_length=32)
    time: Optional[str] = None
    enc: Optional[str] = None


class ProgressTrackRequest(BaseModel):
    schoolId: str = Field(min_length=1, max_length=128)
    userId: str = Field(min_length=1, max_length=128)
    courseId: str = Field(min_length=1, max_length=128)
    lessonId: str = Field(min_length=1, max_length=128)
    currentSectionId: str = Field(min_length=1, max_length=128)
    progressPercent: float = Field(ge=0, le=100)
    lastOperateTime: str = Field(min_length=1, max_length=64)
    qaRecordId: Optional[str] = Field(default=None, max_length=128)
    time: Optional[str] = None
    enc: Optional[str] = None


class ProgressAdjustRequest(BaseModel):
    userId: str = Field(min_length=1, max_length=128)
    lessonId: str = Field(min_length=1, max_length=128)
    currentSectionId: str = Field(min_length=1, max_length=128)
    understandingLevel: str = Field(min_length=1, max_length=32)
    qaRecordId: str = Field(min_length=1, max_length=128)
    time: Optional[str] = None
    enc: Optional[str] = None


class UnsupportedRequest(BaseModel):
    time: Optional[str] = None
    enc: Optional[str] = None


def _resolve_user_and_course(
    session: Session,
    *,
    user_id: str,
    course_id: str,
    school_id: str | None = None,
) -> tuple[User, Course]:
    user = session.exec(
        select(User).where((User.fanya_account_id == user_id) | (User.username == user_id))
    ).first()
    course = session.exec(select(Course).where(Course.fanya_course_id == course_id)).first()
    if user is None or course is None or (school_id and user.school_id and user.school_id != school_id):
        raise HTTPException(status_code=404, detail={"code": "USER_OR_COURSE_NOT_FOUND"})
    return user, course


def _require_course_lesson(course: Course, external_lesson_id: str) -> None:
    """The current domain models one published lesson as its mapped course."""
    if external_lesson_id not in {course.fanya_course_id, str(course.id)}:
        raise HTTPException(status_code=404, detail={"code": "LESSON_MAPPING_UNAVAILABLE"})


def _resolve_section_id(session: Session, course: Course, external_section_id: str | None) -> str | None:
    if external_section_id is None:
        return None
    try:
        node_id = int(external_section_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "SECTION_MAPPING_UNAVAILABLE"}) from exc
    node = session.get(ScriptNode, node_id)
    script = session.get(CourseScript, node.script_id) if node else None
    if node is None or script is None or script.course_id != course.id:
        raise HTTPException(status_code=404, detail={"code": "SECTION_MAPPING_UNAVAILABLE"})
    return str(node.id)


def _parse_last_operate_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "VALIDATION_FAILED"}) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@router.post("/qa/interact", dependencies=[Depends(verify_compat_signature)])
async def compat_qa_interact(
    body: QAInteractRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    if body.questionType == "voice":
        return _envelope(request, 503, "ASR_UNAVAILABLE", {"code": "ASR_UNAVAILABLE"})
    user, course = _resolve_user_and_course(
        session, user_id=body.userId, course_id=body.courseId, school_id=body.schoolId
    )
    _require_course_lesson(course, body.lessonId)
    section_id = _resolve_section_id(session, course, body.currentSectionId)
    context = require_course_permission(
        session, {"user_id": str(user.id), "role": "user"}, int(course.id), "course.question.ask"
    )
    if not context.analytics_eligible:
        raise HTTPException(status_code=403, detail={"code": "COURSE_ACCESS_DENIED"})
    try:
        from app.api.v1.endpoints.teaching_agent import _respond_for_subject, get_runtime

        result = await _respond_for_subject(
            subject_user_id=int(user.id),
            course_id=int(course.id),
            session_id=body.sessionId,
            message=body.questionContent,
            resource_id=section_id,
            exercise_id=None,
            code_submission_id=None,
            question_observation=None,
            runtime_source=get_runtime(request),
            session=session,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return _envelope(request, exc.status_code, str(detail.get("code") or "TEACHING_AGENT_UNAVAILABLE"))

    concept = result.get("concept") or {}
    return _envelope(request, 200, "SUCCESS", {
        "answerId": result.get("trace_id"),
        "answerContent": result.get("answer") or "",
        "answerType": "text",
        "relatedKnowledge": {
            "knowledgeId": concept.get("concept_id"),
            "knowledgeName": concept.get("title") or concept.get("name"),
            "relatedSectionId": section_id,
        },
        "suggestions": [item.get("resource_id") for item in result.get("recommended_resources", [])],
        # This is a response-level interaction hint only. It is never written
        # as formal mastery evidence by this compatibility adapter.
        "understandingLevel": "partial" if result.get("status") == "ok" else "none",
    })


@router.post("/qa/voiceToText", dependencies=[Depends(verify_compat_signature)])
async def compat_voice_to_text(body: VoiceToTextRequest, request: Request):
    del body
    return _envelope(request, 503, "ASR_UNAVAILABLE", {"code": "ASR_UNAVAILABLE"})


@router.post("/progress/track", dependencies=[Depends(verify_compat_signature)])
async def compat_progress_track(
    body: ProgressTrackRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    user, course = _resolve_user_and_course(
        session, user_id=body.userId, course_id=body.courseId, school_id=body.schoolId
    )
    _require_course_lesson(course, body.lessonId)
    section_id = _resolve_section_id(session, course, body.currentSectionId)
    context = require_course_permission(
        session, {"user_id": str(user.id), "role": "user"}, int(course.id), "course.progress.read_self"
    )
    if not context.analytics_eligible:
        raise HTTPException(status_code=403, detail={"code": "COURSE_ACCESS_DENIED"})

    observed_at = _parse_last_operate_time(body.lastOperateTime)
    progress = session.exec(
        select(LearningProgress).where(
            LearningProgress.user_id == user.id,
            LearningProgress.course_id == course.id,
        )
    ).first()
    if progress is None:
        progress = LearningProgress(user_id=int(user.id), course_id=int(course.id))
    progress.completion_rate = max(float(progress.completion_rate or 0), body.progressPercent / 100)
    progress.current_node_id = int(section_id) if section_id else progress.current_node_id
    if section_id:
        node = session.get(ScriptNode, int(section_id))
        progress.script_id = node.script_id if node else progress.script_id
    if progress.completion_rate >= 1:
        progress.status = LearningStatus.COMPLETED
        progress.completed_at = progress.completed_at or observed_at
    elif progress.completion_rate > 0:
        progress.status = LearningStatus.IN_PROGRESS
        progress.started_at = progress.started_at or observed_at
    progress.last_accessed_at = max(to_aware(progress.last_accessed_at), observed_at)
    progress.updated_at = utcnow_aware()
    session.add(progress)
    session.commit()
    session.refresh(progress)
    return _envelope(request, 200, "SUCCESS", {
        "trackId": f"track-{progress.id}",
        "totalProgress": round(progress.completion_rate * 100, 2),
        "nextSectionSuggest": section_id,
    })


@router.post("/progress/adjust", dependencies=[Depends(verify_compat_signature)])
async def compat_progress_adjust(
    body: ProgressAdjustRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    user, course = _resolve_user_and_course(session, user_id=body.userId, course_id=body.lessonId)
    _require_course_lesson(course, body.lessonId)
    section_id = _resolve_section_id(session, course, body.currentSectionId)
    context = require_course_permission(
        session, {"user_id": str(user.id), "role": "user"}, int(course.id), "course.learn"
    )
    if not context.analytics_eligible:
        raise HTTPException(status_code=403, detail={"code": "COURSE_ACCESS_DENIED"})

    # ``understandingLevel`` is an external interaction hint, not a mastery
    # fact.  A supplement is available only when ``qaRecordId`` resolves to a
    # release-pinned proposal created by this learner's actual TeachingAgent
    # turn, and that same turn has a persisted assistant answer.
    proposal = learning_adjustment_service.find_compatibility_proposal(
        session,
        course_id=int(course.id),
        student_id=int(user.id),
        trace_id=body.qaRecordId,
    )
    answer = None
    if proposal is not None:
        answer = session.exec(
            select(ConversationMessage.content)
            .where(
                ConversationMessage.course_id == course.id,
                ConversationMessage.student_id == user.id,
                ConversationMessage.trace_id == body.qaRecordId,
                ConversationMessage.role == "assistant",
            )
            .order_by(ConversationMessage.created_at.desc())
        ).first()
    if not isinstance(answer, str) or not answer.strip():
        return _envelope(
            request,
            503,
            "LEARNING_ADJUSTMENT_CONTEXT_UNAVAILABLE",
            {"code": "LEARNING_ADJUSTMENT_CONTEXT_UNAVAILABLE"},
        )
    return _envelope(request, 200, "SUCCESS", {
        "adjustPlan": {
            "continueSectionId": section_id,
            "adjustType": "supplement",
            "supplementContent": answer,
            "nextSections": [],
        }
    })


@router.post("/lesson/parse", dependencies=[Depends(verify_compat_signature)])
async def compat_lesson_parse(body: UnsupportedRequest, request: Request):
    del body
    return _envelope(request, 503, "COMPAT_ADAPTER_UNAVAILABLE", {"code": "EXTERNAL_URL_IMPORT_UNAVAILABLE"})


@router.post("/lesson/generateScript", dependencies=[Depends(verify_compat_signature)])
async def compat_generate_script(body: UnsupportedRequest, request: Request):
    del body
    return _envelope(request, 503, "COMPAT_ADAPTER_UNAVAILABLE", {"code": "SCRIPT_MAPPING_UNAVAILABLE"})


@router.post("/lesson/generateAudio", dependencies=[Depends(verify_compat_signature)])
async def compat_generate_audio(body: UnsupportedRequest, request: Request):
    del body
    return _envelope(request, 503, "COMPAT_ADAPTER_UNAVAILABLE", {"code": "MEDIA_MAPPING_UNAVAILABLE"})
