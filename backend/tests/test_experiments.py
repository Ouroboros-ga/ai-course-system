"""阶段6 课程实验、Judge0 与 CodingAgent 端到端测试。

覆盖路线图 §9 验收与 PageDesign前端API契约规划.md §3.7：
- 实验定义：教师创建/列表/详情/更新/发布/归档；跨课程隔离
- 实验版本与测试用例：版本创建/激活/锁定；隐藏测试学生视图不可见
- 学生尝试：创建/详情/提交；学生只能看自己的尝试；未发布实验不可创建尝试
- 代码运行：沙箱不可用时降级；语言白名单校验；隐藏测试不泄露详情
- 终结化：通过评分规则形成正式 LearningEvidence；失败不写掌握结论
- CodingAgent 分层提示：full_solution 默认禁止；教师审核
- 权限拒绝：学生不能 configure；非课程成员不能 run
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseCapability
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.experiment_model import (
    AttemptStatus,
    CodingHintLevel,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentRun,
    ExperimentTestCase,
    ExperimentVersion,
    RunOutcome,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from app.services.experiment_service import (
    attempt_service,
    coding_hint_service,
    definition_service,
    finalize_service,
    run_service,
    version_service,
)
from app.services.sandbox_client import (
    SandboxClient,
    SandboxResourceLimits,
    SandboxResult,
    SubmissionStatus,
)


EXPERIMENTS = "/api/v1/experiments"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name: str, role: UserRole = UserRole.TEACHER) -> User:
    u = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _course(
    session,
    teacher_id: int,
    *,
    title: str = "Stage6 Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"s6-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=status,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    session.commit()
    return c


def _enable_experiment_capabilities(session, course_id: int) -> None:
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    defaults = {
        "learning": True,
        "course_building": True,
        "knowledge_graph": True,
        "evidence": True,
        "experiment": True,
        "coding_sandbox": True,
        "cognitive_analysis": True,
        "safety_policy": False,
    }
    if cap is None:
        cap = CourseCapability(course_id=course_id, **defaults)
    else:
        for k, v in defaults.items():
            setattr(cap, k, v)
    session.add(cap)
    session.commit()


def _enroll_student(session, course_id: int, student_id: int) -> None:
    enr = StudentEnrollment(
        student_id=student_id,
        course_id=course_id,
        overall_progress=0.0,
        last_study_time=datetime.utcnow(),
        is_active=True,
    )
    session.add(enr)
    activate_student_membership(session, course_id, student_id)
    session.commit()


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_definition_via_api(
    client, teacher_token: str, course_id: int, *, title: str = "二分查找实验",
    language_whitelist: list[str] | None = None, max_attempts: int = 3,
) -> dict:
    """教师通过 API 创建实验定义"""
    resp = client.post(
        f"{EXPERIMENTS}/course/{course_id}/definitions",
        json={
            "title": title,
            "description": "实现二分查找",
            "language_whitelist": language_whitelist or ["python3"],
            "knowledge_node_ids": [],
            "max_attempts": max_attempts,
            "cooldown_minutes": 0,
        },
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201, body
    return body["data"]


def _create_version_via_api(
    client, teacher_token: str, course_id: int, experiment_id: str,
    *, test_cases: list[dict] | None = None, passing_score: float = 0.6,
    activate: bool = True,
) -> dict:
    """教师通过 API 创建实验版本（含测试用例）"""
    payload = {
        "label": "v1",
        "cpu_time_limit": 5,
        "memory_limit": 128_000,
        "wall_time_limit": 10,
        "max_processes": 30,
        "max_file_size": 1024,
        "passing_score": passing_score,
        "writes_formal_evidence": True,
        "test_cases": test_cases or [
            {"case_name": "basic", "stdin": "1 2 3 4 5\n3\n", "expected_stdout": "2\n", "is_hidden": False, "weight": 1.0},
            {"case_name": "edge", "stdin": "1 2 3 4 5\n1\n", "expected_stdout": "0\n", "is_hidden": True, "weight": 1.0},
        ],
        "activate": activate,
    }
    resp = client.post(
        f"{EXPERIMENTS}/{experiment_id}/versions?course_id={course_id}",
        json=payload,
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201, body
    return body["data"]


def _publish_definition_via_api(
    client, teacher_token: str, course_id: int, experiment_id: str,
) -> dict:
    resp = client.post(
        f"{EXPERIMENTS}/course/{course_id}/definitions/{experiment_id}/publish",
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# 实验定义 CRUD
# ---------------------------------------------------------------------------


class TestExperimentDefinition:
    """实验定义管理"""

    def test_teacher_creates_definition_with_language_whitelist(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        token = _token(teacher_user)

        data = _create_definition_via_api(client, token, course.id)
        assert data["experiment_id"].startswith("exp_")
        assert data["course_id"] == course.id
        assert data["publish_status"] == "draft"
        assert data["language_whitelist"] == ["python3"]
        assert data["max_attempts"] == 3

    def test_student_cannot_configure_experiment(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(student_user)

        resp = client.post(
            f"{EXPERIMENTS}/course/{course.id}/definitions",
            json={"title": "x", "language_whitelist": ["python3"]},
            headers=_auth(token),
        )
        # 学生无 experiment.configure 权限 → 403
        assert resp.status_code == 403

    def test_cross_course_definition_invisible(self, client, session):
        t1 = _user(session, "t1_def_x", UserRole.TEACHER)
        t2 = _user(session, "t2_def_x", UserRole.TEACHER)
        c1 = _course(session, t1.id, title="C1")
        c2 = _course(session, t2.id, title="C2")
        _enable_experiment_capabilities(session, c1.id)
        _enable_experiment_capabilities(session, c2.id)

        d1 = _create_definition_via_api(client, _token(t1), c1.id, title="C1实验")
        # t2 不应在 c2 看到 c1 的实验
        resp = client.get(
            f"{EXPERIMENTS}/course/{c2.id}/definitions",
            headers=_auth(_token(t2)),
        )
        assert resp.status_code == 200
        body = resp.json()
        ids = [item["experiment_id"] for item in body["data"]["items"]]
        assert d1["experiment_id"] not in ids

    def test_publish_and_archive_lifecycle(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        token = _token(teacher_user)

        d = _create_definition_via_api(client, token, course.id)
        # 必须先创建并激活版本，否则发布会被拒绝（缺少激活版本）
        _create_version_via_api(client, token, course.id, d["experiment_id"])
        # 发布
        published = _publish_definition_via_api(client, token, course.id, d["experiment_id"])
        assert published["publish_status"] == "published"
        # 归档
        resp = client.post(
            f"{EXPERIMENTS}/course/{course.id}/definitions/{d['experiment_id']}/archive",
            headers=_auth(token),
        )
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["publish_status"] == "archived"

    def test_student_only_sees_published_definitions(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d_draft = _create_definition_via_api(client, _token(teacher_user), course.id, title="draft")
        d_published = _create_definition_via_api(client, _token(teacher_user), course.id, title="pub")
        _create_version_via_api(client, _token(teacher_user), course.id, d_published["experiment_id"])
        _publish_definition_via_api(client, _token(teacher_user), course.id, d_published["experiment_id"])

        # 学生视角：只看到 published
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/definitions",
            headers=_auth(_token(student_user)),
        )
        assert resp.status_code == 200
        body = resp.json()
        ids = [item["experiment_id"] for item in body["data"]["items"]]
        assert d_published["experiment_id"] in ids
        assert d_draft["experiment_id"] not in ids


# ---------------------------------------------------------------------------
# 实验版本与测试用例
# ---------------------------------------------------------------------------


class TestExperimentVersion:
    """实验版本与测试用例管理"""

    def test_create_version_with_test_cases_and_activate(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        token = _token(teacher_user)

        d = _create_definition_via_api(client, token, course.id)
        v = _create_version_via_api(client, token, course.id, d["experiment_id"])
        assert v["version_id"].startswith("expv_")
        assert v["is_active"] is True

        # 定义应记录 default_version_id
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/definitions/{d['experiment_id']}",
            headers=_auth(token),
        )
        assert resp.json()["data"]["default_version_id"] == v["version_id"]

    def test_hidden_test_cases_invisible_to_student(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        d = _create_definition_via_api(client, token, course.id)
        v = _create_version_via_api(client, token, course.id, d["experiment_id"])

        # 教师视图：可见隐藏测试
        resp_t = client.get(
            f"{EXPERIMENTS}/versions/{v['version_id']}?course_id={course.id}",
            headers=_auth(token),
        )
        cases_t = resp_t.json()["data"]["test_cases"]
        hidden_t = [c for c in cases_t if c["is_hidden"]]
        assert len(hidden_t) == 1
        assert "stdin" in hidden_t[0]  # 教师可见 stdin

        # 学生视图：隐藏测试不暴露 stdin/expected
        resp_s = client.get(
            f"{EXPERIMENTS}/versions/{v['version_id']}?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )
        cases_s = resp_s.json()["data"]["test_cases"]
        hidden_s = [c for c in cases_s if c["is_hidden"]]
        assert len(hidden_s) == 1
        assert "stdin" not in hidden_s[0]
        assert "expected_stdout" not in hidden_s[0]


# ---------------------------------------------------------------------------
# 学生尝试
# ---------------------------------------------------------------------------


class TestExperimentAttempt:
    """学生尝试创建与提交"""

    def test_student_creates_attempt_for_published_experiment(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={"return_anchor": {"node_id": 1}},
            headers=_auth(_token(student_user)),
        )
        body = resp.json()
        assert body["code"] == 201, body
        assert body["data"]["status"] == "in_progress"
        assert body["data"]["student_id"] == student_user.id

    def test_cannot_create_attempt_for_draft_experiment(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        # 未发布

        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        body = resp.json()
        assert body["code"] != 201  # 状态冲突

    def test_student_cannot_view_others_attempt(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        s1 = _user(session, "s1_att_x", UserRole.STUDENT)
        s2 = _user(session, "s2_att_x", UserRole.STUDENT)
        _enroll_student(session, course.id, s1.id)
        _enroll_student(session, course.id, s2.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        # s1 创建尝试
        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(s1)),
        )
        attempt_id = resp.json()["data"]["attempt_id"]

        # s2 不可访问 s1 的尝试
        resp2 = client.get(
            f"{EXPERIMENTS}/attempts/{attempt_id}?course_id={course.id}",
            headers=_auth(_token(s2)),
        )
        body = resp2.json()
        assert body["code"] != 200  # 拒绝访问


# ---------------------------------------------------------------------------
# 代码运行与沙箱降级
# ---------------------------------------------------------------------------


class TestExperimentRun:
    """代码运行与沙箱降级"""

    def test_run_degrades_when_sandbox_unavailable(self, client, session, teacher_user, student_user, monkeypatch):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        # 创建尝试
        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        attempt_id = resp.json()["data"]["attempt_id"]

        # 强制沙箱不可用
        from app.services.experiment_service import sandbox_client as sandbox_singleton
        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: False)

        resp_run = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "python3", "source_code": "print('hello')"},
            headers=_auth(_token(student_user)),
        )
        body = resp_run.json()
        assert body["code"] == 201, body
        assert body["data"]["outcome"] == "sandbox_unavailable"
        assert body["data"]["error_code"] == "SANDBOX_UNAVAILABLE"

    def test_run_does_not_write_formal_evidence(self, client, session, teacher_user, student_user, monkeypatch):
        """run 阶段不写正式学习证据（仅 finalize-passed 才写）。

        验收包3 P1-7：显式查询 LearningEvidenceRecord 表断言为空。
        """
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        # 记录 run 前的 evidence 数量
        evidence_before = session.exec(
            select(LearningEvidenceRecord).where(
                LearningEvidenceRecord.course_id == course.id,
                LearningEvidenceRecord.student_id == student_user.id,
            )
        ).all()
        assert len(evidence_before) == 0

        # 创建尝试
        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        attempt_id = resp.json()["data"]["attempt_id"]

        # 强制沙箱可用并执行 run（即使 run 成功也不应写证据）
        from app.services.experiment_service import sandbox_client as sandbox_singleton
        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
        # mock submit_code 返回 ACCEPTED，让 run "成功"
        from app.services.sandbox_client import SandboxResult, SubmissionStatus
        monkeypatch.setattr(
            sandbox_singleton,
            "submit_code",
            lambda *a, **kw: SandboxResult(
                status=SubmissionStatus.ACCEPTED,
                stdout="hello",
                message="ok",
            ),
        )

        resp_run = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "python3", "source_code": "print('hello')"},
            headers=_auth(_token(student_user)),
        )
        # run 端点返回 HTTP 200 + body.code=201（与项目统一响应规范一致）
        assert resp_run.status_code == 200
        assert resp_run.json()["code"] == 201

        # 查询 run 后的 evidence 表，应为空（finalize 才写证据）
        evidence_after = session.exec(
            select(LearningEvidenceRecord).where(
                LearningEvidenceRecord.course_id == course.id,
                LearningEvidenceRecord.student_id == student_user.id,
            )
        ).all()
        assert len(evidence_after) == 0, \
            f"run 阶段不应写正式证据，但发现 {len(evidence_after)} 条记录"

    def test_run_rejects_language_not_in_whitelist(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(
            client, _token(teacher_user), course.id, language_whitelist=["python3"],
        )
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        attempt_id = resp.json()["data"]["attempt_id"]

        # 使用未在白名单的语言
        resp_run = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "java", "source_code": "public class A {}"},
            headers=_auth(_token(student_user)),
        )
        body = resp_run.json()
        assert body["code"] != 201  # 校验失败

    def test_run_does_not_leak_hidden_test_details(self, client, session, teacher_user, student_user, monkeypatch):
        """即使沙箱返回结果，隐藏测试也不向前端泄露 stdin/expected"""
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(
            client, _token(teacher_user), course.id, d["experiment_id"],
            test_cases=[
                {"case_name": "visible", "stdin": "in1\n", "expected_stdout": "out1\n", "is_hidden": False, "weight": 1.0},
                {"case_name": "secret", "stdin": "secret_in\n", "expected_stdout": "secret_out\n", "is_hidden": True, "weight": 1.0},
            ],
        )
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        attempt_id = resp.json()["data"]["attempt_id"]

        # Mock 沙箱为 ACCEPTED
        from app.services.experiment_service import sandbox_client as sandbox_singleton
        def _fake_submit(source_code, language, stdin="", expected_output="", limits=None):
            return SandboxResult(
                status=SubmissionStatus.ACCEPTED,
                stdout=expected_output,
                time=0.01,
                memory=1024,
            )
        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
        monkeypatch.setattr(sandbox_singleton, "submit_code", _fake_submit)

        resp_run = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "python3", "source_code": "print('x')"},
            headers=_auth(_token(student_user)),
        )
        body = resp_run.json()
        cases = body["data"]["test_summary"]["cases"]
        hidden_cases = [c for c in cases if c["hidden"]]
        assert len(hidden_cases) == 1
        # 隐藏测试不暴露 stdin/expected/actual
        assert "stdin" not in hidden_cases[0]
        assert "expected" not in hidden_cases[0]
        assert "actual" not in hidden_cases[0]


# ---------------------------------------------------------------------------
# 终结化与正式 LearningEvidence
# ---------------------------------------------------------------------------


class TestExperimentFinalize:
    """实验终结化与正式学习证据"""

    def test_finalize_writes_formal_evidence_when_passed(self, client, session, teacher_user, student_user, monkeypatch):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(
            client, _token(teacher_user), course.id, d["experiment_id"],
            passing_score=0.6,
        )
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        # 学生尝试
        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        attempt_id = resp.json()["data"]["attempt_id"]

        # Mock 沙箱为 ACCEPTED
        from app.services.experiment_service import sandbox_client as sandbox_singleton
        def _fake_submit(source_code, language, stdin="", expected_output="", limits=None):
            return SandboxResult(
                status=SubmissionStatus.ACCEPTED,
                stdout=expected_output,
                time=0.01,
                memory=1024,
            )
        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
        monkeypatch.setattr(sandbox_singleton, "submit_code", _fake_submit)

        # 提交运行
        client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "python3", "source_code": "print('x')"},
            headers=_auth(_token(student_user)),
        )
        # 提交尝试
        client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/submit?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )
        # 终结化
        resp_f = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/finalize?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )
        body = resp_f.json()
        assert body["code"] == 200, body
        assert body["data"]["status"] == "finalized"
        assert body["data"]["passed"] is True
        assert body["data"]["evidence_id"]  # 已写入正式证据

        # 验证 LearningEvidenceRecord 已创建
        ev_records = session.exec(
            select(LearningEvidenceRecord).where(
                LearningEvidenceRecord.course_id == course.id,
                LearningEvidenceRecord.student_id == student_user.id,
            )
        ).all()
        assert any(r.evidence_id == body["data"]["evidence_id"] for r in ev_records)

    def test_finalize_failed_when_sandbox_unavailable(self, client, session, teacher_user, student_user, monkeypatch):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        attempt_id = resp.json()["data"]["attempt_id"]

        from app.services.experiment_service import sandbox_client as sandbox_singleton
        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: False)

        client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "python3", "source_code": "print('x')"},
            headers=_auth(_token(student_user)),
        )
        client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/submit?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )
        resp_f = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/finalize?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )
        body = resp_f.json()
        # 沙箱不可用 → 未通过 → FAILED，不写掌握结论
        assert body["data"]["status"] == "failed"
        assert body["data"]["passed"] is False
        assert body["data"]["evidence_id"] is None


# ---------------------------------------------------------------------------
# CodingAgent 分层提示
# ---------------------------------------------------------------------------


class TestCodingAgentHints:
    """CodingAgent 分层提示与教师审核"""

    def test_full_solution_forbidden_by_default(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        attempt_id = resp.json()["data"]["attempt_id"]

        # 学生请求 full_solution，默认禁止
        resp_hint = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/agent-hints?course_id={course.id}",
            json={"hint_level": "full_solution", "reason_codes": ["stuck"]},
            headers=_auth(_token(student_user)),
        )
        body = resp_hint.json()
        assert body["code"] != 201  # 拒绝

    def test_concept_hint_allowed_and_teacher_can_review(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _publish_definition_via_api(client, _token(teacher_user), course.id, d["experiment_id"])

        resp = client.post(
            f"{EXPERIMENTS}/{d['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        attempt_id = resp.json()["data"]["attempt_id"]

        # 学生请求 concept 提示
        resp_hint = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/agent-hints?course_id={course.id}",
            json={"hint_level": "concept", "reason_codes": ["stuck"]},
            headers=_auth(_token(student_user)),
        )
        body = resp_hint.json()
        assert body["code"] == 201, body
        hint_id = body["data"]["hint_id"]

        # 教师审核
        resp_review = client.post(
            f"{EXPERIMENTS}/agent-hints/{hint_id}/review?course_id={course.id}",
            json={"decision": "approved", "note": "good"},
            headers=_auth(_token(teacher_user)),
        )
        body_r = resp_review.json()
        assert body_r["code"] == 200, body_r
        assert body_r["data"]["teacher_reviewed"] is True
        assert body_r["data"]["teacher_decision"] == "approved"
