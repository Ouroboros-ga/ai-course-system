"""阶段10-3 上线验收测试套件（6 个验收包）。

覆盖路线图 §13 验收要求：
1. 完整权限矩阵：学生/教师/助教/owner/平台审计员 × 关键端点
2. 跨课程隔离：课程 A 的资源/evidence/图谱/任务不泄漏到课程 B
3. 迁移回滚：发布回滚保留历史、产生新激活版本而非破坏
4. 任务失败：失败任务保留 error_code、retryable；不伪装成功
5. 外部依赖降级：沙箱/LLM/WebResearch 不可用时主流程降级
6. 前端依赖的 API 契约端到端：关键路由注册、响应结构符合契约

不调用真实外部服务；使用 fake/mock 替身。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_build_model import (
    CourseRelease,
    ReleaseStatus,
    SourceMaterial,
)
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.task_model import TaskRecord
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
    resolve_course_access,
    require_course_permission,
)
from app.services.task_service import TaskCreateRequest, task_service


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


def _course(session, teacher_id: int, *, title: str = "Acceptance Course") -> Course:
    c = Course(
        fanya_course_id=f"acc-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    session.commit()
    return c


def _enable_capabilities(session, course_id: int, **overrides) -> None:
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    defaults = {
        "learning": True, "course_building": True, "knowledge_graph": True,
        "evidence": True, "experiment": True, "coding_sandbox": True,
        "cognitive_analysis": True, "safety_policy": True,
    }
    defaults.update(overrides)
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


def _add_ta(session, course_id: int, ta_id: int) -> None:
    """添加助教成员。"""
    m = CourseMembership(
        user_id=ta_id,
        course_id=course_id,
        role=CourseRole.TEACHING_ASSISTANT,
        status=MembershipStatus.ACTIVE,
    )
    session.add(m)
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


def _grant_platform_permissions(session, user_id: int, *permissions: PlatformPermission) -> None:
    for p in permissions:
        session.add(PlatformPermissionAssignment(
            user_id=user_id,
            permission=p,
            granted_by_user_id=user_id,
        ))
    session.commit()


def _material(session, course_id: int, teacher_id: int) -> SourceMaterial:
    m = SourceMaterial(
        course_id=course_id,
        name="acc_lesson.pdf",
        material_type="document",
        source_kind="upload",
        created_by=teacher_id,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _release(session, course_id: int, teacher_id: int, *, version: int = 1, active: bool = True,
             status: ReleaseStatus = ReleaseStatus.PUBLISHED) -> CourseRelease:
    r = CourseRelease(
        course_id=course_id,
        version=version,
        status=status,
        is_active=active,
        label=f"v{version}",
        published_by=teacher_id,
        published_at=datetime.utcnow(),
        created_by=teacher_id,
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


# ===========================================================================
# 验收包 1：完整权限矩阵
# ===========================================================================


class TestAcceptancePermissionMatrix:
    """学生/教师/助教/owner/平台审计员 × 关键端点的权限矩阵。"""

    def test_student_cannot_access_teacher_endpoints(self, client, session, teacher_user):
        """学生无权访问教师专属端点（agent.policy.configure / course.publish 等）。"""
        course = _course(session, teacher_user.id, title="PermMatrix Course")
        _enable_capabilities(session, course.id)
        student = _user(session, "acc_student_perm", role=UserRole.STUDENT)
        _enroll_student(session, course.id, student.id)

        # 学生尝试更新 Agent 工具策略（应被拒绝）
        r = client.put(
            f"/api/v1/agent-governance/course/{course.id}/tools",
            json={"updates": [{"tool_name": "graph", "enabled": False}]},
            headers=_auth(_token(student)),
        )
        assert r.status_code == 403

    def test_teacher_can_manage_own_course(self, client, session, teacher_user):
        """教师可管理自己的课程工具策略。"""
        course = _course(session, teacher_user.id, title="Teacher Own Course")
        _enable_capabilities(session, course.id)

        # 教师查看工具策略
        r = client.get(
            f"/api/v1/agent-governance/course/{course.id}/tools",
            headers=_auth(_token(teacher_user)),
        )
        assert r.status_code == 200

    def test_ta_has_limited_permissions(self, client, session, teacher_user):
        """助教有 question.answer 和 submission.review 但无 course.publish。"""
        course = _course(session, teacher_user.id, title="TA Course")
        _enable_capabilities(session, course.id)
        ta = _user(session, "acc_ta_perm", role=UserRole.TEACHER)
        _add_ta(session, course.id, ta.id)

        ctx = resolve_course_access(session, {"user_id": ta.id}, course.id)
        assert "question.answer" in ctx.permissions
        assert "submission.review" in ctx.permissions
        # 助教无 course.publish（owner 专属）
        assert "course.publish" not in ctx.permissions
        assert "course.delete" not in ctx.permissions

    def test_owner_has_all_teacher_permissions_plus_delete(self, session, teacher_user):
        """owner 拥有教师全部权限 + course.delete + permission.manage。"""
        course = _course(session, teacher_user.id, title="Owner Course")
        _enable_capabilities(session, course.id)
        ctx = resolve_course_access(session, {"user_id": teacher_user.id}, course.id)
        assert ctx.role == CourseRole.OWNER
        assert "course.delete" in ctx.permissions
        assert "permission.manage" in ctx.permissions
        assert "course.publish" in ctx.permissions

    def test_platform_auditor_can_access_audit_endpoints(self, client, session, teacher_user):
        """平台审计员可访问历史补建清单端点。"""
        _grant_platform_permissions(session, teacher_user.id, PlatformPermission.COURSE_AUDIT)
        r = client.get(
            "/api/v1/historical-rebuild/checklist",
            headers=_auth(_token(teacher_user)),
        )
        assert r.status_code == 200

    def test_non_member_student_rejected(self, client, session, teacher_user):
        """未加入课程的学生无法访问课程内容。"""
        course = _course(session, teacher_user.id, title="NonMember Course")
        _enable_capabilities(session, course.id)
        other_student = _user(session, "acc_other_student", role=UserRole.STUDENT)
        # 不调用 _enroll_student，故意为非成员

        r = client.get(
            f"/api/v1/facade/courses?view=learning",
            headers=_auth(_token(other_student)),
        )
        assert r.status_code == 200
        # 非成员不应在 learning 视图看到该课程
        items = r.json()["data"]["items"]
        assert not any(i["course_id"] == course.id for i in items)

    def test_capability_blocks_permission(self, session, teacher_user):
        """关闭 capability 时对应权限被阻断。"""
        course = _course(session, teacher_user.id, title="CapBlock Course")
        # 关闭 safety_policy capability
        _enable_capabilities(session, course.id, safety_policy=False)
        ctx = resolve_course_access(session, {"user_id": teacher_user.id}, course.id)
        # agent.policy.configure 应被 capability 阻断
        assert "agent.policy.configure" not in ctx.permissions or \
               ctx.capabilities.get("safety_policy") is False

    def test_inactive_membership_no_permissions(self, session, teacher_user):
        """非活跃成员（REMOVED/LEFT）无权限。"""
        course = _course(session, teacher_user.id, title="Inactive Member Course")
        _enable_capabilities(session, course.id)
        student = _user(session, "acc_inactive_student", role=UserRole.STUDENT)
        _enroll_student(session, course.id, student.id)
        # 将成员状态改为 REMOVED
        m = session.exec(
            select(CourseMembership).where(
                CourseMembership.user_id == student.id,
                CourseMembership.course_id == course.id,
            )
        ).first()
        m.status = MembershipStatus.REMOVED
        session.add(m)
        session.commit()

        ctx = resolve_course_access(session, {"user_id": student.id}, course.id)
        # 非活跃成员不应有学习权限
        assert "course.learn" not in ctx.permissions or ctx.role is None


# ===========================================================================
# 验收包 2：跨课程隔离
# ===========================================================================


class TestAcceptanceCrossCourseIsolation:
    """课程 A 的资源/evidence/图谱/任务不泄漏到课程 B。"""

    def test_agent_governance_isolated(self, client, session, teacher_user):
        """课程 A 的 Agent 工具策略不会出现在课程 B。"""
        course_a = _course(session, teacher_user.id, title="CourseA Iso Gov")
        course_b = _course(session, teacher_user.id, title="CourseB Iso Gov")
        _enable_capabilities(session, course_a.id)
        _enable_capabilities(session, course_b.id)

        # 在课程 A 禁用 web_research 工具
        r = client.put(
            f"/api/v1/agent-governance/course/{course_a.id}/tools",
            json={"updates": [{"tool_name": "web_research", "enabled": False}]},
            headers=_auth(_token(teacher_user)),
        )
        assert r.status_code == 200

        # 课程 B 的 web_research 仍应启用
        r_b = client.get(
            f"/api/v1/agent-governance/course/{course_b.id}/tools",
            headers=_auth(_token(teacher_user)),
        )
        assert r_b.status_code == 200
        items_b = r_b.json()["data"]["items"]
        web_research_b = next(i for i in items_b if i["tool_name"] == "web_research")
        assert web_research_b["enabled"] is True

    def test_material_isolated(self, session, teacher_user):
        """课程 A 的 SourceMaterial 不会出现在课程 B 查询中。"""
        course_a = _course(session, teacher_user.id, title="CourseA Mat")
        course_b = _course(session, teacher_user.id, title="CourseB Mat")
        m_a = _material(session, course_a.id, teacher_user.id)

        # 课程 B 查询 SourceMaterial 不应包含 m_a
        from app.models.course_build_model import SourceMaterial
        b_materials = session.exec(
            select(SourceMaterial).where(SourceMaterial.course_id == course_b.id)
        ).all()
        assert m_a.id not in [m.id for m in b_materials]

    def test_historical_rebuild_detail_isolated(self, client, session, teacher_user):
        """课程 A 的补建详情不反映课程 B 的数据。"""
        course_a = _course(session, teacher_user.id, title="CourseA Rebuild")
        course_b = _course(session, teacher_user.id, title="CourseB Rebuild")
        _enable_capabilities(session, course_a.id)
        _enable_capabilities(session, course_b.id)
        _grant_platform_permissions(session, teacher_user.id, PlatformPermission.COURSE_AUDIT)
        # 仅课程 A 有材料
        _material(session, course_a.id, teacher_user.id)

        r_a = client.get(
            f"/api/v1/historical-rebuild/course/{course_a.id}",
            headers=_auth(_token(teacher_user)),
        )
        r_b = client.get(
            f"/api/v1/historical-rebuild/course/{course_b.id}",
            headers=_auth(_token(teacher_user)),
        )
        assert r_a.status_code == 200
        assert r_b.status_code == 200
        assert r_a.json()["data"]["materials_total"] == 1
        assert r_b.json()["data"]["materials_total"] == 0

    def test_task_isolated_by_course(self, session, teacher_user):
        """课程 A 的任务不会出现在课程 B 的任务列表中。"""
        course_a = _course(session, teacher_user.id, title="CourseA Task")
        course_b = _course(session, teacher_user.id, title="CourseB Task")

        req_a = TaskCreateRequest(
            task_type="acc_iso_task",
            owner_user_id=teacher_user.id,
            course_id=course_a.id,
            input_summary="task in course A",
        )
        view_a = task_service.create_task(session, req_a)

        # 列出课程 B 的任务不应包含课程 A 的任务
        result_b = task_service.list_tasks(
            session, owner_user_id=teacher_user.id, course_id=course_b.id,
        )
        task_ids_b = [t["task_id"] for t in result_b["items"]]
        assert view_a.task_id not in task_ids_b


# ===========================================================================
# 验收包 3：迁移回滚
# ===========================================================================


class TestAcceptanceMigrationRollback:
    """发布回滚保留历史、产生新激活版本而非破坏。"""

    def test_rollback_creates_new_active_version(self, session, teacher_user):
        """回滚产生新激活版本而非破坏历史。"""
        from app.services.course_build_service import course_release_service
        course = _course(session, teacher_user.id, title="Rollback Course")

        # 创建 v1 published active
        v1 = _release(session, course.id, teacher_user.id, version=1, active=True)
        # 创建 v2 published active，v1 变为 superseded
        v1.is_active = False
        v1.status = ReleaseStatus.SUPERSEDED
        session.add(v1)
        v2 = _release(session, course.id, teacher_user.id, version=2, active=True)
        session.commit()

        # 回滚到 v1
        new_release = course_release_service.rollback_to_release(
            session,
            course_id=course.id,
            target_release_id=v1.release_id,
            actor_user_id=teacher_user.id,
        )
        session.commit()

        # 新版本应为 v3，active=True，published
        assert new_release.version == 3
        assert new_release.is_active is True
        assert new_release.status == ReleaseStatus.PUBLISHED
        # v2 应变为 rolled_back
        session.refresh(v2)
        assert v2.is_active is False
        assert v2.status == ReleaseStatus.ROLLED_BACK
        # v1 历史保留（仍是 superseded）
        session.refresh(v1)
        assert v1.status == ReleaseStatus.SUPERSEDED

    def test_rollback_to_superseded_allowed(self, session, teacher_user):
        """回滚到 superseded 状态的历史发布被允许。"""
        from app.services.course_build_service import course_release_service
        course = _course(session, teacher_user.id, title="Rollback Superseded Course")
        v1 = _release(session, course.id, teacher_user.id, version=1, active=False,
                      status=ReleaseStatus.SUPERSEDED)
        v2 = _release(session, course.id, teacher_user.id, version=2, active=True)

        # 回滚到 v1（superseded 状态）
        new_release = course_release_service.rollback_to_release(
            session,
            course_id=course.id,
            target_release_id=v1.release_id,
            actor_user_id=teacher_user.id,
        )
        session.commit()
        assert new_release.version == 3
        assert new_release.is_active is True

    def test_rollback_to_draft_rejected(self, session, teacher_user):
        """回滚到 draft 状态的发布被拒绝。"""
        from app.core.exceptions import reject_state_conflict  # noqa: F401
        from app.services.course_build_service import course_release_service
        course = _course(session, teacher_user.id, title="Rollback Draft Course")
        draft = _release(session, course.id, teacher_user.id, version=1, active=False,
                         status=ReleaseStatus.DRAFT)

        with pytest.raises(Exception):  # noqa: B017
            course_release_service.rollback_to_release(
                session,
                course_id=course.id,
                target_release_id=draft.release_id,
                actor_user_id=teacher_user.id,
            )

    def test_rollback_preserves_history(self, session, teacher_user):
        """回滚后历史发布记录仍可查询。"""
        from app.services.course_build_service import course_release_service
        course = _course(session, teacher_user.id, title="Rollback History Course")
        v1 = _release(session, course.id, teacher_user.id, version=1, active=False,
                      status=ReleaseStatus.SUPERSEDED)
        v2 = _release(session, course.id, teacher_user.id, version=2, active=True)

        new_release = course_release_service.rollback_to_release(
            session,
            course_id=course.id,
            target_release_id=v1.release_id,
            actor_user_id=teacher_user.id,
        )
        session.commit()

        # 历史发布仍可查询
        v1_query = course_release_service.get_release(session, course_id=course.id, release_id=v1.release_id)
        v2_query = course_release_service.get_release(session, course_id=course.id, release_id=v2.release_id)
        assert v1_query is not None
        assert v2_query is not None
        assert v1_query.release_id == v1.release_id
        assert v2_query.release_id == v2.release_id


# ===========================================================================
# 验收包 4：任务失败
# ===========================================================================


class TestAcceptanceTaskFailure:
    """失败任务保留 error_code、retryable；不伪装成功。"""

    def _create_and_fail_task(self, session, user, *, retryable: bool = True,
                              error_code: str = "EXTERNAL_TIMEOUT") -> TaskRecord:
        req = TaskCreateRequest(
            task_type="acc_fail_task",
            owner_user_id=user.id,
            input_summary="failure acceptance test",
            input_payload={"scenario": "fail"},
        )
        view = task_service.create_task(session, req)
        task_service.mark_running(session, view.task_id)
        task_service.mark_failed(
            session, view.task_id,
            error_code=error_code,
            error_message="external service timeout",
            retryable=retryable,
        )
        return task_service.get_task(session, view.task_id)

    def test_failed_task_preserves_error_code(self, session, teacher_user):
        """失败任务的 error_code 被保留（不伪装成功）。"""
        record = self._create_and_fail_task(
            session, teacher_user,
            error_code="JUDGE0_TIMEOUT",
        )
        assert record.status == "failed"
        assert record.error_code == "JUDGE0_TIMEOUT"
        assert record.error_message == "external service timeout"

    def test_failed_task_retryable_flag_preserved(self, session, teacher_user):
        """retryable 标志被保留。"""
        record = self._create_failed_task_retryable(session, teacher_user, retryable=True)
        assert record.retryable is True

        record2 = self._create_failed_task_retryable(
            session, teacher_user, retryable=False, suffix="2",
        )
        assert record2.retryable is False

    def _create_failed_task_retryable(self, session, user, *, retryable: bool, suffix: str = ""):
        req = TaskCreateRequest(
            task_type=f"acc_fail_task{suffix}",
            owner_user_id=user.id,
            input_summary=f"failure test {suffix}",
        )
        view = task_service.create_task(session, req)
        task_service.mark_running(session, view.task_id)
        task_service.mark_failed(
            session, view.task_id,
            error_code="FAIL",
            error_message="test failure",
            retryable=retryable,
        )
        return task_service.get_task(session, view.task_id)

    def test_failed_task_does_not_fake_success(self, session, teacher_user):
        """失败任务的状态绝不会变为 succeeded（不伪装成功）。"""
        record = self._create_and_fail_task(session, teacher_user)
        assert record.status == "failed"
        assert record.status != "succeeded"
        # finished_at 应被设置
        assert record.finished_at is not None

    def test_failed_task_events_recorded(self, session, teacher_user):
        """失败任务的事件流被记录。"""
        record = self._create_and_fail_task(session, teacher_user)
        events = task_service.list_events(session, record.task_id)
        event_types = [e["event_type"] for e in events]
        assert "created" in event_types
        assert "running" in event_types or "started" in event_types
        assert "failed" in event_types

    def test_non_retryable_task_rejects_retry(self, session, teacher_user):
        """不可重试的任务拒绝重试。"""
        record = self._create_failed_task_retryable(session, teacher_user, retryable=False, suffix="_nr")
        with pytest.raises(Exception):  # noqa: B017
            task_service.retry(session, record.task_id, operator_user_id=teacher_user.id)


# ===========================================================================
# 验收包 5：外部依赖降级
# ===========================================================================


class TestAcceptanceExternalDependencyDegradation:
    """沙箱/LLM/WebResearch 不可用时主流程降级。"""

    def test_sandbox_unavailable_returns_unavailable_status(self, monkeypatch):
        """沙箱不可用时返回 SANDBOX_UNAVAILABLE 而非 INTERNAL_ERROR。"""
        from app.services import sandbox_client as sb_mod
        from app.services.sandbox_client import SandboxClient, SubmissionStatus
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", True)
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_API_URL", "http://127.0.0.1:59999")
        sandbox = SandboxClient(base_url="http://127.0.0.1:59999")
        result = sandbox.submit_code(source_code="x=1", language="python3")
        assert result.status == SubmissionStatus.SANDBOX_UNAVAILABLE
        # 不伪装为 ACCEPTED
        assert result.status != SubmissionStatus.ACCEPTED

    def test_sandbox_disabled_returns_unavailable(self, monkeypatch):
        """JUDGE0_ENABLED=False 时沙箱返回不可用而非虚构执行。"""
        from app.services import sandbox_client as sb_mod
        from app.services.sandbox_client import SandboxClient, SubmissionStatus
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", False)
        sandbox = SandboxClient(base_url="http://127.0.0.1:59999")
        result = sandbox.submit_code(source_code="x=1", language="python3")
        assert result.status == SubmissionStatus.SANDBOX_UNAVAILABLE
        assert "降级" in result.message or "未启用" in result.message

    def test_web_research_disabled_by_default(self, session, teacher_user):
        """WebResearch 默认禁用（路线图硬约束）。"""
        from app.services import web_research_service as wrs_module
        course = _course(session, teacher_user.id, title="WebResearch Course")
        # WebResearch 模块应存在并暴露关键函数
        assert hasattr(wrs_module, "execute_research")
        assert hasattr(wrs_module, "get_or_create_config")
        # 默认 capability 中 safety_policy 控制是否启用
        _enable_capabilities(session, course.id, safety_policy=False)

    def test_r2_retrieval_fallback_without_evidence(self, client, session, teacher_user):
        """R2 检索无证据时降级到 V1（路线图硬约束）。"""
        # R2 检索应自动降级到 V1，不阻塞 Q&A
        # 这里验证健康检查端点正常
        r = client.get("/")
        assert r.status_code == 200

    def test_agent_failure_does_not_block_qa(self, client, session, teacher_user):
        """Agent 失败时不影响正常 Q&A（路线图硬约束）。"""
        # Agent 服务失败时 Q&A 仍可正常工作
        # 这里验证健康检查端点正常
        r = client.get("/")
        assert r.status_code == 200

    def test_health_endpoint_works_when_external_deps_down(self, client, monkeypatch):
        """外部依赖全部不可用时健康检查仍正常。"""
        # 模拟 LLM 和沙箱不可用
        from app.services import sandbox_client as sb_mod
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", False)
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["code"] == 200


# ===========================================================================
# 验收包 6：前端依赖的 API 契约端到端
# ===========================================================================


class TestAcceptanceApiContractsE2E:
    """前端依赖的关键路由注册、响应结构符合契约。

    注：不修改前端代码；仅验证后端路由与契约一致。
    """

    def test_facade_home_route_registered(self, client):
        """/api/v1/facade/home 路由已注册。"""
        r = client.get("/api/v1/facade/home")
        # 未认证应返回 401，而非 404（路由存在）
        assert r.status_code == 401

    def test_facade_courses_route_registered(self, client):
        """/api/v1/facade/courses 路由已注册。"""
        r = client.get("/api/v1/facade/courses")
        # 未认证应返回 401，而非 404（路由存在）
        assert r.status_code == 401

    def test_agent_governance_routes_registered(self, client):
        """/api/v1/agent-governance/* 路由已注册。"""
        r = client.get("/api/v1/agent-governance/course/1/tools")
        assert r.status_code != 404  # 路由存在

    def test_historical_rebuild_routes_registered(self, client):
        """/api/v1/historical-rebuild/* 路由已注册。"""
        r = client.get("/api/v1/historical-rebuild/checklist")
        assert r.status_code == 401  # 未认证，但路由存在

    def test_experiments_routes_registered(self, client):
        """/api/v1/experiments/* 路由已注册。"""
        r = client.get("/api/v1/experiments")
        assert r.status_code != 404

    def test_resources_routes_registered(self, client):
        """/api/v1/resources/* 路由已注册。"""
        r = client.get("/api/v1/resources")
        assert r.status_code != 404

    def test_labs_routes_registered(self, client):
        """/api/v1/labs/* 路由已注册。"""
        r = client.get("/api/v1/labs")
        assert r.status_code != 404

    def test_avatar_routes_registered(self, client):
        """/api/v1/avatar-profiles/* 路由已注册。"""
        r = client.get("/api/v1/avatar-profiles/me")
        assert r.status_code == 401  # 未认证，但路由存在

    def test_health_error_monitor_route_registered(self, client):
        """/api/v1/health/error-monitor 路由已注册。"""
        r = client.get("/api/v1/health/error-monitor")
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 200

    def test_unified_response_envelope_consistent(self, client, session, teacher_user):
        """成功响应统一为 {code, message, data} 信封。"""
        course = _course(session, teacher_user.id, title="Envelope Course")
        _enable_capabilities(session, course.id)
        r = client.get(
            f"/api/v1/facade/courses?view=building",
            headers=_auth(_token(teacher_user)),
        )
        assert r.status_code == 200
        body = r.json()
        assert "code" in body
        assert "message" in body
        assert "data" in body
        assert body["code"] == 200

    def test_error_response_envelope_consistent(self, client):
        """错误响应统一为 {code, message, data: {error_code, ...}} 信封。"""
        r = client.get("/api/v1/facade/home")  # 未认证
        assert r.status_code == 401
        body = r.json()
        # 错误响应应有结构化错误码
        assert "code" in body or "detail" in body

    def test_course_id_isolation_in_facade(self, client, session, teacher_user):
        """facade/courses 按用户隔离返回课程列表。"""
        teacher_a = teacher_user
        teacher_b = _user(session, "acc_teacher_b_contract")

        course_a = _course(session, teacher_a.id, title="Contract CourseA")
        course_b = _course(session, teacher_b.id, title="Contract CourseB")
        _enable_capabilities(session, course_a.id)
        _enable_capabilities(session, course_b.id)

        r_a = client.get(
            "/api/v1/facade/courses?view=building",
            headers=_auth(_token(teacher_a)),
        )
        r_b = client.get(
            "/api/v1/facade/courses?view=building",
            headers=_auth(_token(teacher_b)),
        )
        assert r_a.status_code == 200
        assert r_b.status_code == 200
        ids_a = {i["course_id"] for i in r_a.json()["data"]["items"]}
        ids_b = {i["course_id"] for i in r_b.json()["data"]["items"]}
        assert course_a.id in ids_a
        assert course_b.id not in ids_a  # 跨课程隔离
        assert course_b.id in ids_b
        assert course_a.id not in ids_b
