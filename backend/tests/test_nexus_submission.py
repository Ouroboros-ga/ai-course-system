"""NX-CT1 代码伴学后端回归：本人提交快照端点 + chat run_ref OJ 路由。

- 内部端点 `/api/v1/nexus-internal/submission`：service token + 用户身份 +
  Course Access v1 + 归属三元组；404 不区分归属；test_summary 白名单重建；
  test_report 产物不投影；超限截断标记；
- proxy：`run_` 前缀 run_ref 走 OJ 投影（kind=oj_submission），上游收到的
  run_context 只含摘要，源码经内部端点按需拉取；非本人 run → 404。
全离线：Runtime 一律 MockTransport，不出网。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import httpx

from app.api.v1.endpoints import nexus_internal
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
)
from app.models.course_model import Course
from app.models.experiment_model import ExperimentRun, ExperimentRunArtifact

from tests.test_nexus_lb1_lb2 import (
    _auth,
    nexus_student_token,  # noqa: F401
    runtime_configured,  # noqa: F401
)

AUTH = {"Authorization": "Bearer internal-token-1"}

RUN_ID = "run_ct1_owner"


def _course(session, owner):
    course = Course(
        fanya_course_id=f"code-tutor-{uuid.uuid4().hex[:6]}",
        fanya_course_name="Code Tutor",
        title="Code Tutor",
        teacher_id=owner.id,
    )
    session.add(course)
    session.flush()
    session.add(CourseMembership(
        course_id=course.id, user_id=owner.id, role=CourseRole.STUDENT))
    session.add(CourseCapability(course_id=course.id, knowledge_graph=True))
    session.commit()
    session.refresh(course)
    return course


def _seed_run(session, course_id, student_id, run_id=RUN_ID):
    run = ExperimentRun(
        attempt_id=f"att-{run_id}",
        course_id=course_id,
        student_id=student_id,
        language="python",
        source_code="print('hello')",
        outcome="wrong_answer",
        compile_ok=True,
        compile_message="",
        runtime_message="",
        passed_count=1,
        total_count=3,
        score=0.33,
        error_code="WA",
        # 真实形状：判题写入器定的 {"cases": [...]}（experiment_attempt_service
        # 汇总段）；公开用例带 I/O，隐藏用例只有 passed/reason。
        test_summary={"cases": [
            {"case_name": "sample1", "passed": True, "reason": "passed",
             "hidden": False, "stdin": "1 2\n", "expected": "3\n",
             "actual": "3\n"},
            {"case_name": "hidden_a1b2c3", "passed": False,
             "reason": "wrong_answer", "hidden": True},
        ]},
    )
    session.add(run)
    session.flush()
    session.add(ExperimentRunArtifact(
        run_id=run.run_id, course_id=course_id,
        artifact_type="compile", content="ok"))
    session.add(ExperimentRunArtifact(
        run_id=run.run_id, course_id=course_id,
        artifact_type="stdout", content="hello\n"))
    session.add(ExperimentRunArtifact(
        run_id=run.run_id, course_id=course_id,
        artifact_type="test_report", content="hidden details here"))
    session.commit()
    session.refresh(run)
    return run


def _headers(user_id):
    return {**AUTH, "X-Nexus-User-Id": str(user_id)}


# ---------------------------------------------------------------------------
# 内部端点
# ---------------------------------------------------------------------------


def test_submission_owner_success(client, session, student_user, monkeypatch):
    monkeypatch.setattr(
        nexus_internal.settings, "NEXUS_INTERNAL_TOKEN", "internal-token-1")
    course = _course(session, student_user)
    _seed_run(session, course.id, student_user.id)
    response = client.get(
        "/api/v1/nexus-internal/submission",
        params={"course_id": course.id, "run_id": RUN_ID},
        headers=_headers(student_user.id),
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["authority"] == "oj_submission"
    assert body["is_supplementary"] is True
    sub = body["submission"]
    assert sub["run_id"] == RUN_ID
    assert sub["outcome"] == "wrong_answer"
    assert sub["source_code"] == "print('hello')"
    assert sub["source_truncated"] is False
    assert sub["passed_count"] == 1 and sub["total_count"] == 3
    # 白名单重建：公开用例 I/O 透传；隐藏用例仅四键、无 I/O。
    assert sub["test_summary"] == [
        {"case_name": "sample1", "passed": True, "reason": "passed",
         "hidden": False, "stdin": "1 2\n", "expected": "3\n",
         "actual": "3\n", "stdin_truncated": False,
         "expected_truncated": False, "actual_truncated": False},
        {"case_name": "hidden_a1b2c3", "passed": False,
         "reason": "wrong_answer", "hidden": True},
    ]
    # 产物：compile/stdout 在，test_report 不在。
    assert set(sub["artifacts"]) == {"compile", "stdout"}
    assert sub["artifacts"]["stdout"]["text"] == "hello\n"


def test_submission_truncation_flags(client, session, student_user, monkeypatch):
    monkeypatch.setattr(
        nexus_internal.settings, "NEXUS_INTERNAL_TOKEN", "internal-token-1")
    course = _course(session, student_user)
    run = _seed_run(session, course.id, student_user.id, run_id="run_ct1_big")
    run.source_code = "x" * 9000
    session.add(run)
    session.commit()
    response = client.get(
        "/api/v1/nexus-internal/submission",
        params={"course_id": course.id, "run_id": "run_ct1_big"},
        headers=_headers(student_user.id),
    )
    assert response.status_code == 200
    sub = response.json()["data"]["submission"]
    assert sub["source_truncated"] is True
    assert len(sub["source_code"]) == 8000


def test_submission_unknown_run_is_404(client, session, student_user, monkeypatch):
    monkeypatch.setattr(
        nexus_internal.settings, "NEXUS_INTERNAL_TOKEN", "internal-token-1")
    course = _course(session, student_user)
    response = client.get(
        "/api/v1/nexus-internal/submission",
        params={"course_id": course.id, "run_id": "run_no_such"},
        headers=_headers(student_user.id),
    )
    assert response.status_code == 404


def test_submission_cross_user_is_404(client, session, student_user, teacher_user,
                                      monkeypatch):
    """同课程陌生人（已入课）读他人提交 → 404，不区分归属。"""
    monkeypatch.setattr(
        nexus_internal.settings, "NEXUS_INTERNAL_TOKEN", "internal-token-1")
    course = _course(session, student_user)
    _seed_run(session, course.id, student_user.id)
    session.add(CourseMembership(
        course_id=course.id, user_id=teacher_user.id, role=CourseRole.STUDENT))
    session.commit()
    response = client.get(
        "/api/v1/nexus-internal/submission",
        params={"course_id": course.id, "run_id": RUN_ID},
        headers=_headers(teacher_user.id),
    )
    assert response.status_code == 404


def test_submission_unenrolled_is_403(client, session, student_user, teacher_user,
                                      monkeypatch):
    monkeypatch.setattr(
        nexus_internal.settings, "NEXUS_INTERNAL_TOKEN", "internal-token-1")
    course = Course(
        fanya_course_id=f"locked-{uuid.uuid4().hex[:6]}",
        fanya_course_name="Locked",
        title="Locked",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    response = client.get(
        "/api/v1/nexus-internal/submission",
        params={"course_id": course.id, "run_id": RUN_ID},
        headers=_headers(student_user.id),
    )
    assert response.status_code == 403


def test_submission_rejects_wrong_token(client, student_user):
    response = client.get(
        "/api/v1/nexus-internal/submission",
        params={"course_id": 1, "run_id": RUN_ID},
        headers={"Authorization": "Bearer wrong",
                 "X-Nexus-User-Id": str(student_user.id)},
    )
    assert response.status_code in (401, 503)


# ---------------------------------------------------------------------------
# proxy run_ref OJ 路由
# ---------------------------------------------------------------------------


def _mock_runtime(handler):
    from app.api.v1.endpoints import nexus_proxy

    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    return patch.object(nexus_proxy.httpx, "AsyncClient", factory)


def test_chat_oj_run_ref_projects_submission_context(
    client, session, nexus_student_token, student_user, runtime_configured
):
    """run_ 前缀 run_ref → kind=oj_submission 投影进上游 context。"""
    course = _course(session, student_user)
    _seed_run(session, course.id, student_user.id)
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"session_id": "code-tutor",
                                         "message": "ok"})

    with _mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "帮我看看", "session_id": "code-tutor",
                  "context": {"course_id": course.id,
                              "run_ref": {"run_id": RUN_ID}}},
            headers=_auth(nexus_student_token))
    assert response.status_code == 200
    ctx = captured["body"]["context"]
    assert "run_ref" not in ctx
    run_context = ctx["run_context"]
    assert run_context["kind"] == "oj_submission"
    assert run_context["run_id"] == RUN_ID
    assert run_context["status"] == "wrong_answer"
    assert run_context["submission_ref"] == {
        "course_id": course.id, "run_id": RUN_ID}
    assert "print('hello')" not in json.dumps(ctx)


def test_chat_oj_run_ref_missing_run_is_404_without_upstream(
    client, session, nexus_student_token, student_user, runtime_configured
):
    """不存在的 run_ id → 404，不触达上游 Runtime（不伪造上下文）。"""
    course = _course(session, student_user)
    _seed_run(session, course.id, student_user.id)
    called = []

    async def handler(request: httpx.Request) -> httpx.Response:
        called.append(True)
        return httpx.Response(200, json={"session_id": "x", "message": "ok"})

    with _mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "帮我看看", "session_id": "code-tutor",
                  "context": {"run_ref": {"run_id": "run_no_such"}}},
            headers=_auth(nexus_student_token))
    assert response.status_code == 404
    assert called == []
