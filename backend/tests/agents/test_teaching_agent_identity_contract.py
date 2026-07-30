"""Identity-boundary tests for TeachingAgent HTTP contracts."""
from __future__ import annotations

from types import SimpleNamespace

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
