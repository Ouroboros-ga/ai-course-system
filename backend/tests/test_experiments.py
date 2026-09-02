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

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session as SqlSession, select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseCapability
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.coding_diagnosis_model import CodingDiagnosisRecord
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.resource_model import LabRecord
from app.models.task_model import TaskRecord
from app.models.experiment_model import (
    AttemptStatus,
    CodingHintLevel,
    ExperimentDefinition,
    ExperimentAttempt,
    ExperimentPublishStatus,
    ExperimentRun,
    ExperimentTestCase,
    ExperimentVersion,
    RunOutcome,
    SandboxExecutionLease,
)
from app.models.graph_production_model import CourseKnowledgeNode
from app.models.knowledge_bundle_model import LearningProjectionOutbox
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
from app.services.task_service import task_service
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
    *, test_cases: list[dict] | None = None, passing_score: float = 1.0,
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
            {"case_name": "basic", "stdin": "1 2 3 4 5\n3\n", "expected_stdout": "2\n", "is_hidden": False, "weight": 0.5},
            {"case_name": "edge", "stdin": "1 2 3 4 5\n1\n", "expected_stdout": "0\n", "is_hidden": True, "weight": 0.5},
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


def _mark_version_publish_ready(session, version_id: str) -> None:
    """Seed only the durable result of a successful teacher preview for fixtures.

    Tests that exercise student permissions and run contracts do not need to
    execute a teacher reference solution.  They still need the same persisted
    lock and verified-preview state that the production publish validator
    requires after that preview has succeeded.
    """
    version = session.exec(
        select(ExperimentVersion).where(ExperimentVersion.version_id == version_id)
    ).one()
    version.is_locked = True
    version.is_active = True
    version.reference_preview_verified_at = datetime.now().astimezone()
    definition = session.exec(
        select(ExperimentDefinition).where(
            ExperimentDefinition.course_id == version.course_id,
            ExperimentDefinition.experiment_id == version.experiment_id,
        )
    ).one()
    definition.default_version_id = version.version_id
    session.add(version)
    session.add(definition)
    session.commit()


def _mark_definition_published_for_fixture(
    session, *, course_id: int, experiment_id: str,
) -> None:
    """Create the durable post-publication state for non-publish test fixtures."""
    definition = session.exec(
        select(ExperimentDefinition).where(
            ExperimentDefinition.course_id == course_id,
            ExperimentDefinition.experiment_id == experiment_id,
        )
    ).one()
    version = session.exec(
        select(ExperimentVersion).where(
            ExperimentVersion.course_id == course_id,
            ExperimentVersion.experiment_id == experiment_id,
        ).order_by(ExperimentVersion.version_number.desc())
    ).first()
    assert version is not None
    _mark_version_publish_ready(session, version.version_id)
    session.refresh(definition)
    definition.publish_status = ExperimentPublishStatus.PUBLISHED
    session.add(definition)
    session.commit()


def _map_experiment_to_knowledge_node(session, *, course_id: int, experiment_id: str) -> CourseKnowledgeNode:
    """Attach a verified course-owned node to a fixture experiment."""
    node = CourseKnowledgeNode(
        course_id=course_id,
        node_key=f"kn_experiment_{uuid.uuid4().hex}",
        title="Experiment concept",
    )
    definition = session.exec(
        select(ExperimentDefinition).where(
            ExperimentDefinition.course_id == course_id,
            ExperimentDefinition.experiment_id == experiment_id,
        )
    ).one()
    session.add(node)
    session.flush()
    definition.knowledge_node_ids = [node.id]
    session.add(definition)
    session.commit()
    return node


def _hold_formal_queue(monkeypatch) -> None:
    """Keep a durable formal task pending until the test runs the worker path."""
    from app.platform.tasks.worker import local_task_worker

    monkeypatch.setattr(local_task_worker, "submit", lambda *_args, **_kwargs: None)


def _run_formal_task_inline(
    *, task_id: str, course_id: int, attempt_id: str, run_id: str, student_id: int,
) -> None:
    """Exercise the registered production handler with the persisted task payload."""
    from app.models.database import engine
    from app.platform.tasks.handlers import register_business_handlers
    from app.platform.tasks.worker import LocalTaskWorker

    worker = LocalTaskWorker()
    register_business_handlers(worker)
    asyncio.run(worker.run_inline(
        lambda: SqlSession(engine),
        task_id,
        {
            "course_id": course_id,
            "attempt_id": attempt_id,
            "run_id": run_id,
            "student_id": student_id,
        },
    ))


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

    def test_publish_and_archive_lifecycle(self, client, session, teacher_user, monkeypatch):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        token = _token(teacher_user)

        d = _create_definition_via_api(client, token, course.id)
        # 必须先创建并激活版本，否则发布会被拒绝（缺少激活版本）
        version = _create_version_via_api(client, token, course.id, d["experiment_id"])
        _mark_version_publish_ready(session, version["version_id"])
        from app.services.experiment_service import sandbox_client as sandbox_singleton
        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
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
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d_published["experiment_id"],
        )

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

    def test_creating_version_keeps_it_inactive_until_preview_and_lock(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        token = _token(teacher_user)

        d = _create_definition_via_api(client, token, course.id)
        v = _create_version_via_api(client, token, course.id, d["experiment_id"])
        assert v["version_id"].startswith("expv_")
        assert v["is_active"] is False

        # 未经参考解预览和锁定的版本不得替换学生使用的默认版本。
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/definitions/{d['experiment_id']}",
            headers=_auth(token),
        )
        assert resp.json()["data"]["default_version_id"] is None

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
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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


class LegacySynchronousExperimentRunContract:
    """代码运行与沙箱降级"""

    def test_run_degrades_when_sandbox_unavailable(self, client, session, teacher_user, student_user, monkeypatch):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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
# 正式评测可信边界（0055）
# ---------------------------------------------------------------------------


class TestExperimentRun:
    """Formal assessment submits a durable task and only the worker terminates it."""

    def _published_attempt(self, client, session, teacher_user, student_user, *, test_cases=None):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        definition = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(
            client,
            _token(teacher_user),
            course.id,
            definition["experiment_id"],
            test_cases=test_cases,
        )
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=definition["experiment_id"],
        )
        response = client.post(
            f"{EXPERIMENTS}/{definition['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        assert response.status_code == 200, response.text
        return course, response.json()["data"]["attempt_id"]

    def _submit_pending_run(self, client, monkeypatch, *, course, attempt_id, student_user, source_code="print('x')"):
        _hold_formal_queue(monkeypatch)
        response = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "python3", "source_code": source_code},
            headers={**_auth(_token(student_user)), "Idempotency-Key": f"run-{uuid.uuid4().hex}"},
        )
        assert response.status_code == 202, response.text
        assert response.json()["code"] == 202
        return response.json()["data"]

    def test_worker_marks_sandbox_unavailable_retryable_without_finalizing_attempt(
        self, client, session, teacher_user, student_user, monkeypatch,
    ):
        course, attempt_id = self._published_attempt(client, session, teacher_user, student_user)
        submitted = self._submit_pending_run(
            client, monkeypatch, course=course, attempt_id=attempt_id, student_user=student_user,
        )
        from app.services.experiment_service import sandbox_client as sandbox_singleton

        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: False)
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id, attempt_id=attempt_id,
            run_id=submitted["run_id"], student_id=student_user.id,
        )
        session.expire_all()
        task = task_service.get_task(session, submitted["task_id"], owner_user_id=student_user.id)
        run = run_service.get_run(session, course_id=course.id, run_id=submitted["run_id"], student_id=student_user.id)
        attempt = attempt_service.get_attempt(session, course_id=course.id, attempt_id=attempt_id, student_id=student_user.id)

        assert task.status == "failed"
        assert task.error_code == "SANDBOX_UNAVAILABLE"
        assert task.retryable is True
        assert run.outcome == RunOutcome.SANDBOX_UNAVAILABLE
        assert attempt.status == AttemptStatus.SUBMITTED
        assert attempt.evidence_id is None

    def test_mid_run_sandbox_unavailable_is_retryable_without_finalizing_attempt(
        self, client, session, teacher_user, student_user, monkeypatch,
    ):
        course, attempt_id = self._published_attempt(client, session, teacher_user, student_user)
        submitted = self._submit_pending_run(
            client, monkeypatch, course=course, attempt_id=attempt_id, student_user=student_user,
        )
        from app.services.experiment_service import sandbox_client as sandbox_singleton

        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
        monkeypatch.setattr(
            sandbox_singleton,
            "submit_code",
            lambda **_kwargs: SandboxResult(status=SubmissionStatus.SANDBOX_UNAVAILABLE),
        )
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id, attempt_id=attempt_id,
            run_id=submitted["run_id"], student_id=student_user.id,
        )
        session.expire_all()
        task = task_service.get_task(session, submitted["task_id"], owner_user_id=student_user.id)
        run = run_service.get_run(session, course_id=course.id, run_id=submitted["run_id"], student_id=student_user.id)
        attempt = attempt_service.get_attempt(session, course_id=course.id, attempt_id=attempt_id, student_id=student_user.id)
        records = session.exec(select(LabRecord).where(LabRecord.attempt_id == attempt_id)).all()

        assert task.status == "failed"
        assert task.error_code == "SANDBOX_UNAVAILABLE"
        assert task.retryable is True
        assert run.outcome == RunOutcome.SANDBOX_UNAVAILABLE
        assert attempt.status == AttemptStatus.SUBMITTED
        assert attempt.evidence_id is None
        assert records == []
        assert session.exec(select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.student_id == student_user.id,
            LearningEvidenceRecord.course_id == course.id,
            LearningEvidenceRecord.source == "experiment_finalize_service",
        )).all() == []

    def test_accepted_worker_run_finalizes_attempt_and_writes_trusted_evidence(
        self, client, session, teacher_user, student_user, monkeypatch,
    ):
        course, attempt_id = self._published_attempt(client, session, teacher_user, student_user)
        attempt_before_run = attempt_service.get_attempt(
            session, course_id=course.id, attempt_id=attempt_id, student_id=student_user.id,
        )
        node = _map_experiment_to_knowledge_node(
            session,
            course_id=course.id,
            experiment_id=attempt_before_run.experiment_id,
        )
        submitted = self._submit_pending_run(
            client, monkeypatch, course=course, attempt_id=attempt_id, student_user=student_user,
        )
        from app.services.experiment_service import sandbox_client as sandbox_singleton

        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
        monkeypatch.setattr(
            sandbox_singleton,
            "submit_code",
            lambda **_kwargs: SandboxResult(status=SubmissionStatus.ACCEPTED, stdout="ok"),
        )
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id, attempt_id=attempt_id,
            run_id=submitted["run_id"], student_id=student_user.id,
        )
        session.expire_all()
        task = task_service.get_task(session, submitted["task_id"], owner_user_id=student_user.id)
        attempt = attempt_service.get_attempt(session, course_id=course.id, attempt_id=attempt_id, student_id=student_user.id)
        records = session.exec(select(LabRecord).where(LabRecord.attempt_id == attempt_id)).all()
        evidence = session.exec(select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.evidence_id == attempt.evidence_id,
        )).one()

        assert task.status == "succeeded"
        assert task.result_data["score"] == 1.0
        assert attempt.status == AttemptStatus.FINALIZED
        assert attempt.final_score == 1.0
        assert attempt.passed is True
        assert evidence.value == 1.0
        assert evidence.evidence_type == "coding_execution"
        assert evidence.node_id == node.id
        assert len(records) == 1
        assert records[0].trusted_source is True
        assert records[0].evidence_id == attempt.evidence_id

    def test_terminal_run_cannot_be_cancelled_or_rewrite_trusted_result(
        self, client, session, teacher_user, student_user, monkeypatch,
    ):
        """A late cancel must not turn a finalized score into a cancelled task."""
        course, attempt_id = self._published_attempt(client, session, teacher_user, student_user)
        submitted = self._submit_pending_run(
            client, monkeypatch, course=course, attempt_id=attempt_id, student_user=student_user,
        )
        from app.services.experiment_service import sandbox_client as sandbox_singleton

        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
        monkeypatch.setattr(
            sandbox_singleton,
            "submit_code",
            lambda **_kwargs: SandboxResult(status=SubmissionStatus.ACCEPTED, stdout="ok"),
        )
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id, attempt_id=attempt_id,
            run_id=submitted["run_id"], student_id=student_user.id,
        )
        # Reproduce the narrow worker window after durable finalization and
        # before its separate task-terminal write.
        task_record = session.exec(select(TaskRecord).where(
            TaskRecord.task_id == submitted["task_id"],
        )).one()
        task_record.status = "running"
        task_record.finished_at = None
        session.add(task_record)
        session.commit()

        response = client.post(
            f"{EXPERIMENTS}/runs/{submitted['run_id']}/cancel?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )

        assert response.status_code == 409, response.text
        assert response.json()["data"]["error_code"] == "STATE_CONFLICT"
        session.expire_all()
        task = task_service.get_task(session, submitted["task_id"], owner_user_id=student_user.id)
        attempt = attempt_service.get_attempt(
            session, course_id=course.id, attempt_id=attempt_id, student_id=student_user.id,
        )
        records = session.exec(select(LabRecord).where(LabRecord.attempt_id == attempt_id)).all()
        assert task.status == "running"
        assert attempt.status == AttemptStatus.FINALIZED
        assert attempt.final_score == 1.0
        assert len(records) == 1

    def test_formal_run_rejects_language_not_in_whitelist(self, client, session, teacher_user, student_user):
        course, attempt_id = self._published_attempt(client, session, teacher_user, student_user)

        response = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "java", "source_code": "public class A {}"},
            headers={**_auth(_token(student_user)), "Idempotency-Key": "wrong-language"},
        )

        assert response.status_code == 422
        assert response.json()["data"]["error_code"] == "VALIDATION_FAILED"

    def test_worker_result_does_not_leak_hidden_test_details(
        self, client, session, teacher_user, student_user, monkeypatch,
    ):
        course, attempt_id = self._published_attempt(
            client,
            session,
            teacher_user,
            student_user,
            test_cases=[
                {"case_name": "visible", "stdin": "visible_in\n", "expected_stdout": "visible_out\n", "is_hidden": False, "weight": 0.5},
                {"case_name": "secret", "stdin": "secret_in\n", "expected_stdout": "secret_out\n", "is_hidden": True, "weight": 0.5},
            ],
        )
        submitted = self._submit_pending_run(
            client, monkeypatch, course=course, attempt_id=attempt_id, student_user=student_user,
        )
        from app.services.experiment_service import sandbox_client as sandbox_singleton

        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
        monkeypatch.setattr(
            sandbox_singleton,
            "submit_code",
            lambda **kwargs: SandboxResult(
                status=SubmissionStatus.ACCEPTED,
                stdout=kwargs["expected_output"],
                time=0.01,
                memory=1024,
            ),
        )
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id, attempt_id=attempt_id,
            run_id=submitted["run_id"], student_id=student_user.id,
        )
        response = client.get(
            f"{EXPERIMENTS}/runs/{submitted['run_id']}?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )

        assert response.status_code == 200, response.text
        cases = response.json()["data"]["test_summary"]["cases"]
        hidden_cases = [case for case in cases if case["hidden"]]
        assert len(hidden_cases) == 1
        assert "secret_in" not in str(response.json())
        assert "secret_out" not in str(response.json())
        assert "stdin" not in hidden_cases[0]
        assert "expected" not in hidden_cases[0]
        assert "actual" not in hidden_cases[0]


class TestTrustedAssessedExecutionContract:
    """学生只能创建异步评测任务，不能伪造或手工终结正式成绩。"""

    def _published_attempt(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        teacher_token = _token(teacher_user)
        definition = _create_definition_via_api(client, teacher_token, course.id)
        version = _create_version_via_api(
            client,
            teacher_token,
            course.id,
            definition["experiment_id"],
            passing_score=1.0,
            test_cases=[
                {"case_name": "basic", "stdin": "", "expected_stdout": "", "is_hidden": False, "weight": 0.5},
                {"case_name": "hidden", "stdin": "", "expected_stdout": "", "is_hidden": True, "weight": 0.5},
            ],
        )
        # The contract tests do not exercise Judge0 preview.  Seed the state
        # produced by a successful preview so they can isolate request safety.
        stored_version = session.exec(
            select(ExperimentVersion).where(ExperimentVersion.version_id == version["version_id"])
        ).one()
        stored_version.is_locked = True
        stored_version.is_active = True
        stored_version.reference_preview_verified_at = datetime.now().astimezone()
        stored_definition = session.exec(
            select(ExperimentDefinition).where(ExperimentDefinition.experiment_id == definition["experiment_id"])
        ).one()
        stored_definition.default_version_id = stored_version.version_id
        stored_definition.publish_status = ExperimentPublishStatus.PUBLISHED
        session.add(stored_version)
        session.add(stored_definition)
        session.commit()
        response = client.post(
            f"{EXPERIMENTS}/{definition['experiment_id']}/attempts?course_id={course.id}",
            json={},
            headers=_auth(_token(student_user)),
        )
        assert response.status_code == 200
        return course, response.json()["data"]["attempt_id"]

    def test_formal_run_requires_idempotency_key(self, client, session, teacher_user, student_user):
        course, attempt_id = self._published_attempt(client, session, teacher_user, student_user)

        response = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "python3", "source_code": "print('x')"},
            headers=_auth(_token(student_user)),
        )

        assert response.status_code == 422
        assert response.json()["data"]["error_code"] == "VALIDATION_FAILED"

    def test_formal_run_is_always_async_and_idempotent(self, client, session, teacher_user, student_user):
        course, attempt_id = self._published_attempt(client, session, teacher_user, student_user)
        headers = {**_auth(_token(student_user)), "Idempotency-Key": "formal-run-001"}

        first = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "python3", "source_code": "print('x')"},
            headers=headers,
        )
        second = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
            json={"language": "python3", "source_code": "print('x')"},
            headers=headers,
        )

        assert first.status_code == 202
        assert first.json()["code"] == 202
        assert first.json()["data"]["status"] == "pending"
        assert second.status_code == 202
        assert second.json()["data"]["task_id"] == first.json()["data"]["task_id"]
        assert second.json()["data"]["run_id"] == first.json()["data"]["run_id"]

    def test_students_cannot_call_legacy_submit_or_finalize_routes(self, client, session, teacher_user, student_user):
        course, attempt_id = self._published_attempt(client, session, teacher_user, student_user)
        headers = _auth(_token(student_user))

        submit = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/submit?course_id={course.id}",
            headers=headers,
        )
        finalize = client.post(
            f"{EXPERIMENTS}/attempts/{attempt_id}/finalize?course_id={course.id}",
            headers=headers,
        )

        assert submit.status_code == 404
        assert finalize.status_code == 404
        assert submit.json()["code"] == 404
        assert finalize.json()["code"] == 404

    def test_formal_run_renews_its_lease_before_every_test_case(
        self, session, teacher_user, student_user, monkeypatch,
    ):
        """A multi-case Judge0 evaluation must refresh the durable lease per case."""
        course = _course(session, teacher_user.id)
        definition = ExperimentDefinition(
            course_id=course.id,
            title="Lease renewal",
            language_whitelist=["python3"],
            created_by=teacher_user.id,
        )
        version = ExperimentVersion(
            course_id=course.id,
            experiment_id=definition.experiment_id,
            version_number=1,
            created_by=teacher_user.id,
        )
        attempt = ExperimentAttempt(
            course_id=course.id,
            experiment_id=definition.experiment_id,
            version_id=version.version_id,
            student_id=student_user.id,
        )
        run = ExperimentRun(
            course_id=course.id,
            attempt_id=attempt.attempt_id,
            student_id=student_user.id,
            language="python3",
            source_code="print('ok')",
        )
        cases = [
            ExperimentTestCase(course_id=course.id, version_id=version.version_id, case_name="one"),
            ExperimentTestCase(course_id=course.id, version_id=version.version_id, case_name="two"),
        ]
        session.add(definition)
        session.add(version)
        session.add(attempt)
        session.add(run)
        session.add_all(cases)
        session.commit()

        renewals: list[str] = []
        from app.services.experiment_service import sandbox_client as sandbox_singleton
        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
        monkeypatch.setattr(
            sandbox_singleton,
            "submit_code",
            lambda **_: SandboxResult(status=SubmissionStatus.ACCEPTED),
        )

        async def renew_before_case() -> bool:
            renewals.append("renewed")
            return True

        asyncio.run(
            run_service._execute_run(
                session,
                run=run,
                attempt=attempt,
                version=version,
                before_case=renew_before_case,
            )
        )

        assert renewals == ["renewed", "renewed"]
        assert run.outcome == RunOutcome.ACCEPTED

    def test_formal_run_waits_for_database_slot_release(self, session, student_user):
        """A cross-process slot holder delays formal work without failing it."""
        from app.models.database import engine
        from app.platform.tasks.handlers import _wait_for_formal_sandbox_lease
        from app.platform.tasks.worker import TaskHandlerContext
        from app.services.experiment_service import FORMAL_LEASE_KEY, SandboxExecutionLeaseService
        from app.services.task_service import TaskCreateRequest, task_service

        holder = task_service.create_task(
            session,
            TaskCreateRequest(
                task_type="experiment_run",
                owner_user_id=student_user.id,
                course_id=1,
                input_summary="slot holder",
            ),
        )
        waiting = task_service.create_task(
            session,
            TaskCreateRequest(
                task_type="experiment_run",
                owner_user_id=student_user.id,
                course_id=1,
                input_summary="slot waiter",
            ),
        )
        lease = session.exec(select(SandboxExecutionLease).where(
            SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY,
        )).first()
        if lease is None:
            lease = SandboxExecutionLease(lease_key=FORMAL_LEASE_KEY)
        lease.holder_task_id = holder.task_id
        lease.lease_expires_at = datetime.now().astimezone() + timedelta(minutes=1)
        session.add(lease)
        session.commit()

        context = TaskHandlerContext(
            task_id=waiting.task_id,
            input_payload={},
            session_factory=lambda: SqlSession(engine),
            service=task_service,
        )

        async def wait_for_release() -> bool:
            waiter = asyncio.create_task(
                _wait_for_formal_sandbox_lease(context, poll_seconds=0.001)
            )
            await asyncio.sleep(0.01)
            assert not waiter.done()
            with SqlSession(engine) as release_session:
                SandboxExecutionLeaseService().release(
                    release_session, task_id=holder.task_id,
                )
                release_session.commit()
            return await asyncio.wait_for(waiter, timeout=0.5)

        assert asyncio.run(wait_for_release()) is True
        lease = session.exec(select(SandboxExecutionLease).where(
            SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY,
        )).one()
        assert lease.holder_task_id == waiting.task_id

    def test_formal_lease_create_race_has_one_holder_without_integrity_error(
        self, session,
    ):
        """Two worker processes racing an absent row produce one holder, not a task error."""
        import threading

        from sqlalchemy import delete, event
        from app.models.database import engine
        from app.services.experiment_service import FORMAL_LEASE_KEY, SandboxExecutionLeaseService

        session.exec(delete(SandboxExecutionLease).where(
            SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY,
        ))
        session.commit()

        select_barrier = threading.Barrier(2)
        observed_selects = 0
        observed_lock = threading.Lock()
        results: list[bool] = []
        errors: list[BaseException] = []

        def synchronize_absent_row_reads(conn, cursor, statement, parameters, context, executemany):
            nonlocal observed_selects
            if "FROM sandbox_execution_leases" not in statement or "SELECT" not in statement:
                return
            with observed_lock:
                observed_selects += 1
                should_wait = observed_selects <= 2
            if should_wait:
                select_barrier.wait(timeout=2)

        def acquire(task_id: str) -> None:
            try:
                with SqlSession(engine) as worker_session:
                    acquired = SandboxExecutionLeaseService().acquire(
                        worker_session, task_id=task_id,
                    )
                    worker_session.commit()
                    results.append(acquired)
            except BaseException as exc:
                errors.append(exc)

        event.listen(engine, "before_cursor_execute", synchronize_absent_row_reads)
        try:
            workers = [
                threading.Thread(target=acquire, args=("lease-race-a",)),
                threading.Thread(target=acquire, args=("lease-race-b",)),
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)
            assert not any(worker.is_alive() for worker in workers)
        finally:
            event.remove(engine, "before_cursor_execute", synchronize_absent_row_reads)
            with SqlSession(engine) as cleanup_session:
                cleanup_session.exec(delete(SandboxExecutionLease).where(
                    SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY,
                ))
                cleanup_session.commit()

        assert errors == []
        assert sorted(results) == [False, True]

    def test_formal_lease_reclaim_race_has_one_holder_without_integrity_error(
        self, session,
    ):
        """Only one worker can reclaim the same expired database lease."""
        import threading

        from sqlalchemy import delete, event
        from app.core.time_utils import utcnow_aware
        from app.models.database import engine
        from app.services.experiment_service import FORMAL_LEASE_KEY, SandboxExecutionLeaseService

        lease = session.exec(select(SandboxExecutionLease).where(
            SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY,
        )).first() or SandboxExecutionLease(lease_key=FORMAL_LEASE_KEY)
        lease.holder_task_id = "expired-holder"
        lease.lease_expires_at = utcnow_aware() - timedelta(seconds=1)
        session.add(lease)
        session.commit()

        select_barrier = threading.Barrier(2)
        observed_lock = threading.Lock()
        observed_selects = 0
        results: list[bool] = []
        errors: list[BaseException] = []

        def synchronize_expired_row_reads(conn, cursor, statement, parameters, context, executemany):
            nonlocal observed_selects
            if "FROM sandbox_execution_leases" not in statement or "SELECT" not in statement:
                return
            with observed_lock:
                observed_selects += 1
                should_wait = observed_selects <= 2
            if should_wait:
                select_barrier.wait(timeout=2)

        def acquire(task_id: str) -> None:
            try:
                with SqlSession(engine) as worker_session:
                    results.append(SandboxExecutionLeaseService().acquire(
                        worker_session, task_id=task_id,
                    ))
                    worker_session.commit()
            except BaseException as exc:
                errors.append(exc)

        event.listen(engine, "before_cursor_execute", synchronize_expired_row_reads)
        try:
            workers = [
                threading.Thread(target=acquire, args=("expired-race-a",)),
                threading.Thread(target=acquire, args=("expired-race-b",)),
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)
            assert not any(worker.is_alive() for worker in workers)
        finally:
            event.remove(engine, "before_cursor_execute", synchronize_expired_row_reads)
            with SqlSession(engine) as cleanup_session:
                cleanup_session.exec(delete(SandboxExecutionLease).where(
                    SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY,
                ))
                cleanup_session.commit()

        assert errors == []
        assert sorted(results) == [False, True]

    def test_formal_handler_releases_lease_when_run_validation_fails(
        self, session, student_user,
    ):
        """A malformed queued payload cannot strand the shared Judge0 slot."""
        from app.models.database import engine
        from app.platform.tasks.handlers import experiment_run_handler
        from app.platform.tasks.worker import TaskExecutionError, TaskHandlerContext
        from app.services.experiment_service import FORMAL_LEASE_KEY
        from app.services.task_service import TaskCreateRequest, task_service

        task = task_service.create_task(
            session,
            TaskCreateRequest(
                task_type="experiment_run",
                owner_user_id=student_user.id,
                course_id=1,
                input_summary="invalid formal run",
            ),
        )
        context = TaskHandlerContext(
            task_id=task.task_id,
            input_payload={
                "course_id": 1,
                "attempt_id": "attempt-missing",
                "run_id": "run-missing",
                "student_id": student_user.id,
            },
            session_factory=lambda: SqlSession(engine),
            service=task_service,
        )

        with pytest.raises(TaskExecutionError, match="不存在"):
            asyncio.run(experiment_run_handler(context))

        lease = session.exec(select(SandboxExecutionLease).where(
            SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY,
        )).one()
        assert lease.holder_task_id == ""


# ---------------------------------------------------------------------------
# Restart recovery
# ---------------------------------------------------------------------------


class TestExperimentRunRecovery:
    """Only unfinished, uncancelled formal runs may be requeued after restart."""

    def _create_recoverable_run(self, session, teacher_user, student_user, *, suffix: str):
        from app.services.task_service import TaskCreateRequest, task_service

        course = _course(session, teacher_user.id, title=f"Recovery {suffix}")
        definition = ExperimentDefinition(
            course_id=course.id,
            title="Restart recovery",
            language_whitelist=["python3"],
            created_by=teacher_user.id,
        )
        version = ExperimentVersion(
            course_id=course.id,
            experiment_id=definition.experiment_id,
            version_number=1,
            created_by=teacher_user.id,
        )
        attempt = ExperimentAttempt(
            course_id=course.id,
            experiment_id=definition.experiment_id,
            version_id=version.version_id,
            student_id=student_user.id,
            status=AttemptStatus.SUBMITTED,
        )
        run = ExperimentRun(
            course_id=course.id,
            attempt_id=attempt.attempt_id,
            student_id=student_user.id,
            language="python3",
            source_code="print('recovery')",
            outcome=RunOutcome.PENDING,
        )
        session.add(definition)
        session.add(version)
        session.add(attempt)
        session.add(run)
        session.commit()

        task = task_service.create_task(session, TaskCreateRequest(
            task_type="experiment_run",
            owner_user_id=student_user.id,
            course_id=course.id,
            input_summary="restart recovery test",
            input_payload={
                "course_id": course.id,
                "attempt_id": attempt.attempt_id,
                "run_id": run.run_id,
                "student_id": student_user.id,
            },
            idempotency_key=f"experiment-recovery-{suffix}",
        ))
        run.task_id = task.task_id
        session.add(run)
        task_service.mark_interrupted(session, task.task_id, reason="restart")
        session.commit()
        return course, attempt, run, task

    def test_restart_recovery_requeues_only_safe_formal_runs(
        self, session, teacher_user, student_user,
    ):
        """Cancellation and terminal outcomes cannot be replayed into a second grade."""
        safe_course, _, safe_run, safe_task = self._create_recoverable_run(
            session, teacher_user, student_user, suffix="safe",
        )
        _, _, cancelled_run, cancelled_task = self._create_recoverable_run(
            session, teacher_user, student_user, suffix="cancelled",
        )
        _, _, finished_run, finished_task = self._create_recoverable_run(
            session, teacher_user, student_user, suffix="finished",
        )
        cancelled_run.cancel_requested_at = datetime.now().astimezone()
        finished_run.outcome = RunOutcome.ACCEPTED
        finished_run.finished_at = datetime.now().astimezone()
        session.add(cancelled_run)
        session.add(finished_run)
        session.commit()

        class RecordingWorker:
            def __init__(self):
                self.submissions = []

            def submit(self, session_factory, task_id, payload):
                self.submissions.append((task_id, payload))

        from sqlmodel import Session as SqlSession
        from app.models.database import engine
        from app.models.task_model import TaskRecord
        from app.platform.tasks.experiment_run_queue import recover_experiment_run_tasks

        worker = RecordingWorker()
        recovered = asyncio.run(
            recover_experiment_run_tasks(lambda: SqlSession(engine), worker)
        )

        assert recovered == 1
        assert worker.submissions == [
            (
                safe_task.task_id,
                {
                    "course_id": safe_course.id,
                    "attempt_id": safe_run.attempt_id,
                    "run_id": safe_run.run_id,
                    "student_id": student_user.id,
                },
            ),
        ]
        safe_record = session.exec(select(TaskRecord).where(
            TaskRecord.task_id == safe_task.task_id,
        )).one()
        cancelled_record = session.exec(select(TaskRecord).where(
            TaskRecord.task_id == cancelled_task.task_id,
        )).one()
        finished_record = session.exec(select(TaskRecord).where(
            TaskRecord.task_id == finished_task.task_id,
        )).one()
        assert safe_record.status == "pending"
        assert cancelled_record.status == "cancelled"
        assert finished_record.status == "succeeded"


# ---------------------------------------------------------------------------
# 终结化与正式 LearningEvidence
# ---------------------------------------------------------------------------


class LegacyManualExperimentFinalizeContract:
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
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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


class TestExperimentFinalize:
    """The worker, rather than a student endpoint, owns terminal grades."""

    def test_non_accepted_worker_run_finalizes_zero_with_coding_evidence(
        self, client, session, teacher_user, student_user, monkeypatch,
    ):
        run_contract = TestExperimentRun()
        course, attempt_id = run_contract._published_attempt(
            client, session, teacher_user, student_user,
        )
        attempt_before_run = attempt_service.get_attempt(
            session, course_id=course.id, attempt_id=attempt_id, student_id=student_user.id,
        )
        node = _map_experiment_to_knowledge_node(
            session,
            course_id=course.id,
            experiment_id=attempt_before_run.experiment_id,
        )
        submitted = run_contract._submit_pending_run(
            client, monkeypatch, course=course, attempt_id=attempt_id, student_user=student_user,
        )
        from app.services.experiment_service import sandbox_client as sandbox_singleton

        monkeypatch.setattr(sandbox_singleton, "health_check", lambda: True)
        monkeypatch.setattr(
            sandbox_singleton,
            "submit_code",
            lambda **_kwargs: SandboxResult(status=SubmissionStatus.WRONG_ANSWER, stdout="wrong"),
        )
        dispatched_projection_events: list[str] = []
        monkeypatch.setattr(
            "app.services.learning_projection_outbox_service.dispatch_learning_projection",
            lambda event_id: dispatched_projection_events.append(event_id),
        )
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id, attempt_id=attempt_id,
            run_id=submitted["run_id"], student_id=student_user.id,
        )
        session.expire_all()
        task = task_service.get_task(session, submitted["task_id"], owner_user_id=student_user.id)
        attempt = attempt_service.get_attempt(session, course_id=course.id, attempt_id=attempt_id, student_id=student_user.id)
        records = session.exec(select(LabRecord).where(LabRecord.attempt_id == attempt_id)).all()
        evidence = session.exec(select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.course_id == course.id,
            LearningEvidenceRecord.student_id == student_user.id,
        )).all()

        assert task.status == "succeeded"
        assert task.result_data["score"] == 0.0
        assert attempt.status == AttemptStatus.FINALIZED
        assert attempt.final_score == 0.0
        assert attempt.passed is False
        assert attempt.evidence_id is not None
        assert len(evidence) == 1
        assert evidence[0].evidence_type == "coding_execution"
        assert evidence[0].node_id == node.id
        assert evidence[0].value == 0.0
        projection_events = session.exec(select(LearningProjectionOutbox).where(
            LearningProjectionOutbox.course_id == course.id,
            LearningProjectionOutbox.student_id == student_user.id,
        )).all()
        assert len(projection_events) == 1
        assert projection_events[0].attempt_id is None
        assert projection_events[0].source_type == "experiment_attempt"
        assert projection_events[0].source_ref == attempt_id
        assert dispatched_projection_events == [projection_events[0].event_id]
        assert len(records) == 1
        assert records[0].final_score == 0.0
        assert records[0].passed is False
        assert records[0].evidence_id == attempt.evidence_id


class TestCodingAgentHints:
    """CodingAgent 分层提示与教师审核"""

    def test_full_solution_forbidden_by_default(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        d = _create_definition_via_api(client, _token(teacher_user), course.id)
        _create_version_via_api(client, _token(teacher_user), course.id, d["experiment_id"])
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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
        _mark_definition_published_for_fixture(
            session, course_id=course.id, experiment_id=d["experiment_id"],
        )

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


# ---------------------------------------------------------------------------
# CodingAgent 运行讲解
# ---------------------------------------------------------------------------


class TestCodingAgentRunExplanation:
    """运行讲解只读取已保存的、归属受限的诊断记录。"""

    def _run_with_diagnosis(self, session, course_id: int, student_id: int) -> ExperimentRun:
        suffix = uuid.uuid4().hex
        run = ExperimentRun(
            run_id=f"run_explanation_{suffix}",
            attempt_id=f"attempt_explanation_{suffix}",
            course_id=course_id,
            student_id=student_id,
            language="python3",
            source_code="VERY_SECRET_STUDENT_SOURCE()",
            outcome=RunOutcome.WRONG_ANSWER,
        )
        diagnosis = CodingDiagnosisRecord(
            diagnosis_id=f"cd_explanation_{suffix}",
            run_id=run.run_id,
            course_id=course_id,
            student_id=student_id,
            outcome="wrong_answer",
            error_class="logic",
            summary="程序可以运行，但没有通过全部测试。",
            debug_steps=["找一个最小反例", "检查循环边界"],
            reason_codes=["WRONG_ANSWER", "CHECK_LOGIC"],
        )
        session.add(run)
        session.add(diagnosis)
        session.commit()
        return run

    def test_student_gets_rule_explanation_without_run_artifacts(
        self, client, session, teacher_user, student_user,
    ):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        run = self._run_with_diagnosis(session, course.id, student_user.id)

        response = client.post(
            f"{EXPERIMENTS}/runs/{run.run_id}/explanation?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["run_id"] == run.run_id
        assert data["source"] == "coding-rules"
        assert data["next_steps"] == ["找一个最小反例", "检查循环边界"]
        payload = str(data)
        assert "VERY_SECRET_STUDENT_SOURCE" not in payload
        assert "source_code" not in payload
        assert "artifact" not in payload
        assert "hidden" not in payload

    def test_student_explanation_invokes_scoped_coding_agent(
        self, client, fastapi_app, monkeypatch, session, teacher_user, student_user,
    ):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        run = self._run_with_diagnosis(session, course.id, student_user.id)

        class _CodingPlatform:
            def is_registered(self, agent_type):
                return getattr(agent_type, "value", agent_type) == "coding"

            async def respond(self, context):
                assert context.agent_type == "coding"
                assert context.scope == (str(student_user.id), str(course.id))
                assert context.student_id == str(student_user.id)
                assert context.course_id == str(course.id)
                assert context.code_submission_id == run.run_id
                return {
                    "status": "ok",
                    "final_answer": "先检查循环终止条件，再用最小输入复现。",
                    "warnings": [],
                    "degraded_services": [],
                }

        monkeypatch.setattr(fastapi_app.state, "agent_platform", _CodingPlatform())
        response = client.post(
            f"{EXPERIMENTS}/runs/{run.run_id}/explanation?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["source"] == "teaching-agent-coding-compat"
        assert data["summary"] == "先检查循环终止条件，再用最小输入复现。"
        assert "VERY_SECRET_STUDENT_SOURCE" not in str(data)

    def test_student_cannot_request_another_students_explanation(
        self, client, session, teacher_user, student_user,
    ):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        other_student = _user(session, "explanation-other", UserRole.STUDENT)
        _enroll_student(session, course.id, other_student.id)
        run = self._run_with_diagnosis(session, course.id, student_user.id)

        response = client.post(
            f"{EXPERIMENTS}/runs/{run.run_id}/explanation?course_id={course.id}",
            headers=_auth(_token(other_student)),
        )

        assert response.status_code == 403
        assert response.json()["data"]["error_code"] == "COURSE_ACCESS_DENIED"
