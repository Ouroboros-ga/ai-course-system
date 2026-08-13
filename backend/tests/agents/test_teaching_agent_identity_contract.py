"""Identity-boundary tests for TeachingAgent HTTP contracts."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import teaching_agent as endpoint


class CapturingRuntime:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def respond(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "trace_id": "trace-identity",
            "status": "ok",
            "intent": "concept_question",
            "concept_candidates": [],
            "current_concept_id": None,
            "teaching_action": "normal_answer",
            "final_answer": "answer",
            "citations": [],
            "selected_resource_ids": [],
            "warnings": [],
            "degraded_services": [],
        }


def _client(runtime: CapturingRuntime, *, caller_id: int) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1/teaching-agent")
    app.dependency_overrides[endpoint.get_runtime] = lambda: runtime
    app.dependency_overrides[endpoint.get_session] = lambda: object()
    app.dependency_overrides[endpoint.get_current_user] = lambda: {
        "user_id": str(caller_id),
        "username": f"user-{caller_id}",
    }
    return TestClient(app)


def test_self_service_derives_learner_from_authenticated_user(monkeypatch):
    runtime = CapturingRuntime()
    client = _client(runtime, caller_id=7)
    permission_calls: list[tuple[int, str]] = []

    def require_self_permission(_session, _principal, course_id, permission):
        permission_calls.append((course_id, permission))
        return SimpleNamespace(analytics_eligible=True)

    monkeypatch.setattr(endpoint, "require_course_permission", require_self_permission)
    response = client.post("/api/v1/teaching-agent/respond", json={
        "course_id": "84", "session_id": "session-1",
        "message": "Explain binary search.",
    })

    assert response.status_code == 200
    assert permission_calls == [(84, "course.question.ask")]
    assert runtime.calls[0]["student_id"] == "7"
    assert runtime.calls[0]["course_id"] == "84"


def test_self_service_rejects_legacy_impersonation_field(monkeypatch):
    runtime = CapturingRuntime()
    client = _client(runtime, caller_id=7)
    monkeypatch.setattr(
        endpoint, "require_course_permission",
        lambda *_args, **_kwargs: SimpleNamespace(analytics_eligible=True),
    )
    response = client.post("/api/v1/teaching-agent/respond", json={
        "student_id": "8", "course_id": "84", "session_id": "session-1",
        "message": "Read another learner.",
    })

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TEACHING_AGENT_SELF_ID_MISMATCH"
    assert runtime.calls == []


def test_teacher_target_contract_requires_member_analytics_permission(monkeypatch):
    runtime = CapturingRuntime()
    client = _client(runtime, caller_id=2)
    permission_calls: list[tuple[int, str]] = []
    target_principals: list[dict] = []

    def require_teacher_permission(_session, _principal, course_id, permission):
        permission_calls.append((course_id, permission))
        return SimpleNamespace(analytics_eligible=False)

    def resolve_target(_session, principal, course_id):
        target_principals.append({"principal": principal, "course_id": course_id})
        return SimpleNamespace(analytics_eligible=True)

    monkeypatch.setattr(endpoint, "require_course_permission", require_teacher_permission)
    monkeypatch.setattr(endpoint, "resolve_course_access", resolve_target)
    response = client.post("/api/v1/teaching-agent/respond-for-learner", json={
        "learner_user_id": "7", "course_id": "84",
        "session_id": "teacher-session",
        "message": "Prepare a learner-specific explanation.",
    })

    assert response.status_code == 200
    assert permission_calls == [(84, "analytics.view_member")]
    assert target_principals == [{"principal": {"user_id": "7"}, "course_id": 84}]
    assert runtime.calls[0]["student_id"] == "7"


def test_teacher_response_rejects_student_playback_observation(monkeypatch):
    """Only the learner client can describe the moment a question was asked."""
    runtime = CapturingRuntime()
    client = _client(runtime, caller_id=2)
    monkeypatch.setattr(
        endpoint,
        "require_course_permission",
        lambda *_args, **_kwargs: SimpleNamespace(analytics_eligible=False),
    )
    monkeypatch.setattr(
        endpoint,
        "resolve_course_access",
        lambda *_args, **_kwargs: SimpleNamespace(analytics_eligible=True),
    )

    response = client.post("/api/v1/teaching-agent/respond-for-learner", json={
        "learner_user_id": "7", "course_id": "84",
        "session_id": "teacher-session", "message": "Prepare an explanation.",
        "question_observation": {
            "course_release_id": "cr_1", "media_release_id": "mr_1",
            "media_release_item_id": "item_1", "outline_node_id": "node_1",
            "local_time_ms": 8200, "page": 4,
        },
    })

    assert response.status_code == 422
    assert runtime.calls == []


def test_teacher_response_does_not_write_a_learner_turn_or_signal(monkeypatch):
    """Teacher previews must not become student chat, cognition or review state."""
    runtime = CapturingRuntime()
    client = _client(runtime, caller_id=2)
    monkeypatch.setattr(
        endpoint,
        "require_course_permission",
        lambda *_args, **_kwargs: SimpleNamespace(analytics_eligible=False),
    )
    monkeypatch.setattr(
        endpoint,
        "resolve_course_access",
        lambda *_args, **_kwargs: SimpleNamespace(analytics_eligible=True),
    )
    monkeypatch.setattr(
        endpoint,
        "persist_conversation_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not persist")),
    )
    monkeypatch.setattr(
        endpoint,
        "record_question_depth",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not record")),
    )

    response = client.post("/api/v1/teaching-agent/respond-for-learner", json={
        "learner_user_id": "7", "course_id": "84",
        "session_id": "teacher-session", "message": "Prepare an explanation.",
    })

    assert response.status_code == 200
    assert runtime.calls[0]["question_observation"] is None


def test_teacher_target_contract_rejects_non_learner(monkeypatch):
    runtime = CapturingRuntime()
    client = _client(runtime, caller_id=2)
    monkeypatch.setattr(
        endpoint, "require_course_permission",
        lambda *_args, **_kwargs: SimpleNamespace(analytics_eligible=False),
    )
    monkeypatch.setattr(
        endpoint, "resolve_course_access",
        lambda *_args, **_kwargs: SimpleNamespace(analytics_eligible=False),
    )
    response = client.post("/api/v1/teaching-agent/respond-for-learner", json={
        "learner_user_id": "9", "course_id": "84",
        "session_id": "teacher-session", "message": "Read a non-learner.",
    })

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TEACHING_AGENT_TARGET_NOT_LEARNER"
    assert runtime.calls == []


@pytest.mark.parametrize("field", ["hardness", "constraint_level", "allowed_tools"])
@pytest.mark.parametrize(
    ("path", "identity_field"),
    [
        ("/api/v1/teaching-agent/respond", None),
        ("/api/v1/teaching-agent/respond-for-learner", "learner_user_id"),
    ],
)
def test_http_contract_rejects_client_supplied_governance_fields(path, identity_field, field):
    runtime = CapturingRuntime()
    client = _client(runtime, caller_id=7)
    payload = {
        "course_id": "84",
        "session_id": "session-1",
        "message": "Attempt to override policy.",
        field: ["retrieval"] if field == "allowed_tools" else "locked",
    }
    if identity_field:
        payload[identity_field] = "7"

    response = client.post(path, json=payload)

    assert response.status_code == 422
    assert runtime.calls == []
