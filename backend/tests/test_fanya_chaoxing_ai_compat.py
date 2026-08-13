"""Contract tests for the removable Fanya/Chaoxing AI compatibility package."""
from __future__ import annotations

import hashlib
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.core.time_utils import utcnow_aware
from app.external_apis.fanya_chaoxing_ai.router import _canonical_value, _compat_static_key
from app.models.course_model import Course, CourseScript, CourseStatus, ScriptNode, ScriptNodeType
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_outline_model import CourseOutlineNode
from app.models.media_release_model import (
    MediaRelease,
    MediaReleaseCue,
    MediaReleaseItem,
    MediaReleaseStatus,
)
from app.models.progress_model import LearningProgress
from app.models.user_model import User, UserRole
from app.schemas.learning_adjustment import QuestionObservation
from app.services.conversation_service import persist_conversation_turn
from app.services.course_access_service import activate_student_membership, establish_course_access_baseline
from app.services.learning_adjustment_service import learning_adjustment_service


COMPAT_PREFIX = "/api/v1/compat"


def _signed(payload: dict) -> dict:
    body = dict(payload)
    time_value = utcnow_aware().strftime(settings.TIME_FORMAT)
    body["time"] = time_value
    canonical = "".join(
        f"{key}{_canonical_value(body[key])}"
        for key in sorted(body)
        if key != "enc" and body[key] is not None and _canonical_value(body[key]).strip()
    )
    body["enc"] = hashlib.md5(
        f"{canonical}{_compat_static_key()}{time_value}".encode("utf-8")
    ).hexdigest().upper()
    return body


def _make_course_context(session):
    tag = uuid.uuid4().hex[:12]
    owner = User(
        username=f"compat_owner_{tag}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.USER,
        school_id="school-compat",
        is_active=True,
    )
    student = User(
        username=f"compat_student_{tag}",
        fanya_account_id=f"fanya-student-compat-{tag}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.USER,
        school_id="school-compat",
        is_active=True,
    )
    session.add(owner)
    session.add(student)
    session.commit()
    session.refresh(owner)
    session.refresh(student)

    course = Course(
        fanya_course_id=f"fanya-course-compat-{tag}",
        fanya_course_name="Compat course",
        title="Compat course",
        teacher_id=owner.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, owner.id)
    activate_student_membership(session, course.id, student.id)

    script = CourseScript(
        course_id=course.id,
        script_content={"title": "Compat script"},
        created_by=owner.id,
    )
    session.add(script)
    session.commit()
    session.refresh(script)
    node = ScriptNode(
        script_id=script.id,
        node_index=1,
        node_type=ScriptNodeType.LECTURE,
        title="Compat section",
        content="Compat section content",
    )
    session.add(node)
    session.commit()
    session.refresh(node)
    return student, course, node


def test_compat_routes_are_registered_once(fastapi_app):
    paths = fastapi_app.openapi()["paths"]
    expected_paths = {
        f"{COMPAT_PREFIX}/qa/interact",
        f"{COMPAT_PREFIX}/qa/voiceToText",
        f"{COMPAT_PREFIX}/progress/track",
        f"{COMPAT_PREFIX}/progress/adjust",
        f"{COMPAT_PREFIX}/lesson/parse",
        f"{COMPAT_PREFIX}/lesson/generateScript",
        f"{COMPAT_PREFIX}/lesson/generateAudio",
    }
    assert expected_paths.issubset(paths)
    assert f"{COMPAT_PREFIX}/" in fastapi_app.state.signature_owned_path_prefixes


def test_compat_signature_failures_use_external_envelope(client):
    response = client.post(f"{COMPAT_PREFIX}/qa/voiceToText", json={"voiceUrl": "https://example.test/q.wav"})

    assert response.status_code == 403
    assert response.json()["code"] == 403
    assert response.json()["msg"] == "SIGNATURE_INVALID"
    assert response.json()["requestId"]
    assert "message" not in response.json()


def test_unsupported_asr_is_honest_and_uses_external_envelope(client):
    response = client.post(
        f"{COMPAT_PREFIX}/qa/voiceToText",
        json=_signed({"voiceUrl": "https://example.test/q.wav", "voiceDuration": 4}),
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": 503,
        "msg": "ASR_UNAVAILABLE",
        "data": {"code": "ASR_UNAVAILABLE"},
        "requestId": response.json()["requestId"],
    }


def test_compat_text_qa_marks_the_delegated_turn_as_a_learner_turn(
    client, session, monkeypatch
):
    student, course, node = _make_course_context(session)
    from app.api.v1.endpoints import teaching_agent

    async def fake_respond_for_subject(*, persist_learner_turn: bool, **_kwargs):
        assert persist_learner_turn is True
        return {"trace_id": "compat-trace", "answer": "Controlled answer", "concept": {}}

    monkeypatch.setattr(teaching_agent, "_respond_for_subject", fake_respond_for_subject)
    monkeypatch.setattr(teaching_agent, "get_runtime", lambda _request: object())

    response = client.post(
        f"{COMPAT_PREFIX}/qa/interact",
        json=_signed({
            "schoolId": "school-compat",
            "userId": student.fanya_account_id,
            "courseId": course.fanya_course_id,
            "lessonId": course.fanya_course_id,
            "sessionId": "compat-qa-session",
            "questionType": "text",
            "questionContent": "Explain this section.",
            "currentSectionId": str(node.id),
        }),
    )

    assert response.status_code == 200
    assert response.json()["data"]["answerContent"] == "Controlled answer"


def test_progress_track_requires_course_access_and_persists_progress(client, session):
    student, course, node = _make_course_context(session)
    response = client.post(
        f"{COMPAT_PREFIX}/progress/track",
        json=_signed({
            "schoolId": "school-compat",
            "userId": student.fanya_account_id,
            "courseId": course.fanya_course_id,
            "lessonId": course.fanya_course_id,
            "currentSectionId": str(node.id),
            "progressPercent": 35.5,
            "lastOperateTime": utcnow_aware().isoformat(),
        }),
    )

    assert response.status_code == 200
    assert response.json()["msg"] == "SUCCESS"
    assert response.json()["data"]["totalProgress"] == 35.5
    progress = session.exec(
        select(LearningProgress).where(
            LearningProgress.user_id == student.id,
            LearningProgress.course_id == course.id,
        )
    ).one()
    assert progress.current_node_id == node.id
    assert progress.completion_rate == 0.355


def test_progress_adjust_is_honest_when_release_pinned_context_is_unavailable(client, session):
    student, course, node = _make_course_context(session)

    response = client.post(
        f"{COMPAT_PREFIX}/progress/adjust",
        json=_signed({
            "userId": student.fanya_account_id,
            "lessonId": course.fanya_course_id,
            "currentSectionId": str(node.id),
            "understandingLevel": "partial",
            "qaRecordId": "qa-compat-adjust-1",
        }),
    )

    assert response.status_code == 503
    assert response.json()["msg"] == "LEARNING_ADJUSTMENT_CONTEXT_UNAVAILABLE"
    assert response.json()["data"] == {
        "code": "LEARNING_ADJUSTMENT_CONTEXT_UNAVAILABLE"
    }


def test_progress_adjust_returns_only_the_matching_validated_turn_supplement(client, session):
    """The compatibility adapter never derives a supplement from level alone."""
    student, course, node = _make_course_context(session)
    tag = uuid.uuid4().hex[:12]
    course_release_id = f"cr-compat-adjust-{tag}"
    media_release_id = f"mr-compat-adjust-{tag}"
    outline_version_id = f"ov-compat-adjust-{tag}"
    current_outline_id = f"on-compat-current-{tag}"
    prerequisite_outline_id = f"on-compat-prerequisite-{tag}"
    current_item_id = f"mi-compat-current-{tag}"
    prerequisite_item_id = f"mi-compat-prerequisite-{tag}"
    trace_id = f"trace-compat-adjust-{tag}"

    session.add(CourseRelease(
        release_id=course_release_id,
        course_id=course.id,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        outline_version_id=outline_version_id,
        media_snapshot={"media_release_id": media_release_id},
    ))
    session.add(CourseOutlineNode(
        outline_node_id=current_outline_id,
        outline_version_id=outline_version_id,
        course_id=course.id,
        knowledge_graph_node_id="compat-current-concept",
        title="Current concept",
    ))
    session.add(CourseOutlineNode(
        outline_node_id=prerequisite_outline_id,
        outline_version_id=outline_version_id,
        course_id=course.id,
        knowledge_graph_node_id="compat-prerequisite-concept",
        title="Prerequisite concept",
    ))
    session.add(MediaRelease(
        release_id=media_release_id,
        course_id=course.id,
        status=MediaReleaseStatus.ACTIVE,
        created_by=course.teacher_id,
        release_metadata={"audio_playlist_schema": "audio-playlist/v1"},
    ))
    session.flush()
    for item_id, outline_node_id, node_id in (
        (current_item_id, current_outline_id, 10_001),
        (prerequisite_item_id, prerequisite_outline_id, 10_002),
    ):
        session.add(MediaReleaseItem(
            item_id=item_id,
            release_id=media_release_id,
            course_id=course.id,
            node_id=node_id,
            outline_node_id=outline_node_id,
            duration_ms=120_000,
            audio_object_key=f"compat/{item_id}.mp3",
            status="ready",
        ))
    session.add(MediaReleaseCue(
        release_id=media_release_id,
        course_id=course.id,
        node_id=10_001,
        cue_index=0,
        start_time=8.2,
        end_time=18.0,
        ppt_page=4,
        audio_object_key=f"compat/{current_item_id}.mp3",
        cue_metadata={"time_basis": "item_local_v1", "outline_node_id": current_outline_id},
    ))
    session.add(MediaReleaseCue(
        release_id=media_release_id,
        course_id=course.id,
        node_id=10_002,
        cue_index=0,
        start_time=48.2,
        end_time=65.0,
        ppt_page=6,
        audio_object_key=f"compat/{prerequisite_item_id}.mp3",
        cue_metadata={"time_basis": "item_local_v1", "outline_node_id": prerequisite_outline_id},
    ))
    session.commit()

    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=student.id,
        observation=QuestionObservation(
            course_release_id=course_release_id,
            media_release_id=media_release_id,
            media_release_item_id=current_item_id,
            outline_node_id=current_outline_id,
            local_time_ms=8_200,
            page=4,
        ),
        teaching_action="prerequisite_review",
        current_concept_id="compat-current-concept",
        prerequisites=[{"concept_id": "compat-prerequisite-concept"}],
        weak_concepts=[{"concept_id": "compat-prerequisite-concept"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
        source_trace_id=trace_id,
    )
    assert proposal is not None
    persist_conversation_turn(
        session,
        student_id=student.id,
        course_id=course.id,
        session_id="compat-adjust-session",
        trace_id=trace_id,
        user_message="Why is the prerequisite needed?",
        assistant_answer="Use the prerequisite before continuing this section.",
    )

    response = client.post(
        f"{COMPAT_PREFIX}/progress/adjust",
        json=_signed({
            "userId": student.fanya_account_id,
            "lessonId": course.fanya_course_id,
            "currentSectionId": str(node.id),
            "understandingLevel": "full",
            "qaRecordId": trace_id,
        }),
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "adjustPlan": {
            "continueSectionId": str(node.id),
            "adjustType": "supplement",
            "supplementContent": "Use the prerequisite before continuing this section.",
            "nextSections": [],
        }
    }


def test_core_app_can_skip_missing_compatibility_package(monkeypatch):
    from app import main

    app = FastAPI()
    app.get("/internal-check")(lambda: {"ok": True})
    monkeypatch.setattr(main, "find_spec", lambda _name: None)
    main._mount_optional_fanya_chaoxing_ai_compat(app)

    assert not any(route.path.startswith(COMPAT_PREFIX) for route in app.routes)
    assert not hasattr(app.state, "signature_owned_path_prefixes")
    with TestClient(app) as client:
        assert client.get("/internal-check").json() == {"ok": True}
        assert client.post(f"{COMPAT_PREFIX}/qa/voiceToText").status_code == 404
