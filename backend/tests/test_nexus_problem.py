"""NX-CT1-R5 题目关联后端回归：problem_ref 投影 + 快照有界透传。

- problem_ref 只传引用声明；题干公开面（标题/描述/公开样例）由服务端投影，
  未发布/无权/不存在 → 404/403（与 run_ref 同严格）；
- 客户端自带的 problem_context 一律剥离；code_snapshot 只做有界透传。
全离线：Runtime 一律 MockTransport，不出网。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import httpx

from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
)
from app.models.course_model import Course
from app.models.experiment_model import (
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentTestCase,
    ExperimentVersion,
)

from tests.test_nexus_lb1_lb2 import (
    _auth,
    nexus_student_token,  # noqa: F401
    runtime_configured,  # noqa: F401
)


def _course(session, owner):
    course = Course(
        fanya_course_id=f"code-tutor-prob-{uuid.uuid4().hex[:6]}",
        fanya_course_name="Code Tutor Problem",
        title="Code Tutor Problem",
        teacher_id=owner.id,
    )
    session.add(course)
    session.flush()
    session.add(CourseMembership(
        course_id=course.id, user_id=owner.id, role=CourseRole.STUDENT))
    capability = CourseCapability(course_id=course.id, knowledge_graph=True)
    capability.experiment = True
    session.add(capability)
    session.commit()
    session.refresh(course)
    return course


def _seed_problem(session, course_id, creator_id, published=True):
    definition = ExperimentDefinition(
        course_id=course_id,
        title="两数之和",
        description="给定 n 个整数，求和为 target 的下标。" + "x" * 5000,
        publish_status=ExperimentPublishStatus.PUBLISHED if published else ExperimentPublishStatus.DRAFT,
        created_by=creator_id,
    )
    session.add(definition)
    session.flush()
    version = ExperimentVersion(
        course_id=course_id,
        experiment_id=definition.experiment_id,
        version_number=1,
        created_by=creator_id,
    )
    session.add(version)
    session.flush()
    definition.default_version_id = version.version_id
    session.add(definition)
    session.add(ExperimentTestCase(
        version_id=version.version_id, course_id=course_id,
        case_name="sample1", stdin="4\n2 7 11 15\n9\n",
        expected_stdout="0 1\n", is_hidden=False,
    ))
    session.add(ExperimentTestCase(
        version_id=version.version_id, course_id=course_id,
        case_name="hidden1", stdin="SECRET-IN", expected_stdout="SECRET-OUT",
        is_hidden=True,
    ))
    session.commit()
    session.refresh(definition)
    return definition


def _mock_runtime(handler):
    from app.api.v1.endpoints import nexus_proxy

    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    return patch.object(nexus_proxy.httpx, "AsyncClient", factory)


def test_chat_problem_ref_projects_public_surface(
    client, session, nexus_student_token, student_user, runtime_configured
):
    """problem_ref → kind=oj_problem：标题/描述截断+仅公开样例+快照截断。"""
    course = _course(session, student_user)
    definition = _seed_problem(session, course.id, student_user.id)
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"session_id": "code-tutor", "message": "ok"})

    with _mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "这题怎么做", "session_id": "code-tutor",
                  "context": {"course_id": course.id,
                              "problem_ref": {"experiment_id": definition.experiment_id},
                              "problem_context": {"kind": "forged"},
                              "code_snapshot": "y" * 9000}},
            headers=_auth(nexus_student_token))
    assert response.status_code == 200
    ctx = captured["body"]["context"]
    assert "problem_ref" not in ctx
    prob = ctx["problem_context"]
    assert prob["kind"] == "oj_problem"
    assert prob["title"] == "两数之和"
    assert prob["description_truncated"] is True
    assert len(prob["description"]) == 4000
    # 仅公开样例；隐藏用例的输入输出永不过线。
    assert [s["case_name"] for s in prob["samples"]] == ["sample1"]
    assert "SECRET" not in json.dumps(ctx)
    # 快照有界透传（讨论材料，非投影）。
    assert len(ctx["code_snapshot"]) == 8000
    assert ctx["code_snapshot_truncated"] is True


def test_chat_problem_ref_unpublished_is_404_without_upstream(
    client, session, nexus_student_token, student_user, runtime_configured
):
    """未发布题目 → 404，不触达上游（不泄露草稿存在性之外的任何事）。"""
    course = _course(session, student_user)
    definition = _seed_problem(session, course.id, student_user.id, published=False)
    called = []

    async def handler(request: httpx.Request) -> httpx.Response:
        called.append(True)
        return httpx.Response(200, json={"session_id": "x", "message": "ok"})

    with _mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "这题怎么做", "session_id": "code-tutor",
                  "context": {"course_id": course.id,
                              "problem_ref": {"experiment_id": definition.experiment_id}}},
            headers=_auth(nexus_student_token))
    assert response.status_code == 404
    assert called == []


def test_chat_without_problem_ref_has_no_problem_context(
    client, session, nexus_student_token, student_user, runtime_configured
):
    """无 problem_ref 时不注入题目上下文（普通对话零影响）。"""
    course = _course(session, student_user)
    _seed_problem(session, course.id, student_user.id)
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"session_id": "code-tutor", "message": "ok"})

    with _mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "你好", "session_id": "code-tutor",
                  "context": {"course_id": course.id}},
            headers=_auth(nexus_student_token))
    assert response.status_code == 200
    assert "problem_context" not in captured["body"]["context"]
