"""Contract tests for the removable Fanya/Chaoxing AI compatibility package."""
from __future__ import annotations

import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.core.time_utils import utcnow_aware
from app.external_apis.fanya_chaoxing_ai.router import _canonical_value, _compat_static_key
from app.models.course_model import Course, CourseScript, CourseStatus, ScriptNode, ScriptNodeType
from app.models.progress_model import LearningProgress
from app.models.user_model import User, UserRole
from app.services.course_access_service import activate_student_membership, establish_course_access_baseline


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
    owner = User(
        username="compat_owner",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.USER,
        school_id="school-compat",
        is_active=True,
    )
    student = User(
        username="compat_student",
        fanya_account_id="fanya-student-compat",
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
        fanya_course_id="fanya-course-compat",
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
