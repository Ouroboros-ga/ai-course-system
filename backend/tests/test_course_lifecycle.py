"""阶段2 成员、设置、加入申请与课程生命周期 端到端测试。

覆盖路线图 §5 验收与 PageDesign前端API契约规划.md §3.8：
- 加入申请状态机：pending → approved | rejected | info_requested | cancelled
- 课程分组 CRUD 与成员分配（不改角色、删组不删成员）
- 课程设置版本化与回滚、乐观锁冲突
- 泛雅同步预览-确认两阶段
- 成员/设置 facade 聚合读模型
- 跨课程/跨用户严格隔离
- 审计事件可追溯

四类必备测试：成功、权限拒绝、跨课程拒绝、降级。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseMembership, CourseRole, MembershipStatus
from app.models.course_lifecycle_model import (
    CourseGroup,
    CourseGroupMember,
    CourseJoinRequest,
    CourseSettingVersion,
    IntegrationSyncRun,
    JoinRequestStatus,
    SyncRunStatus,
)
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)


COURSE_ACCESS = "/api/v1/course-access"
COURSE_GROUPS = "/api/v1/course-groups"
COURSE_SETTINGS = "/api/v1/course-settings"
INTEGRATIONS = "/api/v1/integrations"
AUDIT = "/api/v1/audit"
FACADE = "/api/v1/facade"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name: str, role: UserRole = UserRole.STUDENT) -> User:
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
    title: str = "Lifecycle Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"lc-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=status,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    session.commit()  # baseline add 后必须 commit 才能对请求 session 可见
    return c


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. 加入申请：成功路径
# ---------------------------------------------------------------------------


def test_join_request_create_approve_activates_membership(client, session):
    """学生提交申请 -> 教师通过 -> 学生 membership 被激活， enrollment 创建。"""
    teacher = _user(session, "lc_join_teacher", UserRole.TEACHER)
    student = _user(session, "lc_join_student", UserRole.STUDENT)
    course = _course(session, teacher.id, title="加入申请课程")

    # 学生提交申请
    resp = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "希望加入学习"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201
    req_data = body["data"]
    assert req_data["status"] == "pending"
    assert req_data["applicant_user_id"] == student.id
    request_id = req_data["request_id"]

    # 教师通过
    resp_appr = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/approve",
        json={"review_comment": "同意加入"},
        headers=_auth(_token(teacher)),
    )
    assert resp_appr.status_code == 200, resp_appr.text
    assert resp_appr.json()["data"]["status"] == "approved"
    assert resp_appr.json()["data"]["reviewer_user_id"] == teacher.id

    # 验证 membership 已激活
    membership = session.exec(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.user_id == student.id,
        )
    ).first()
    assert membership is not None
    assert membership.status == MembershipStatus.ACTIVE
    assert membership.role == CourseRole.STUDENT

    # 验证 enrollment 已创建
    enr = session.exec(
        select(StudentEnrollment).where(
            StudentEnrollment.student_id == student.id,
            StudentEnrollment.course_id == course.id,
        )
    ).first()
    assert enr is not None


def test_join_request_reject_does_not_activate(client, session):
    """教师拒绝 -> 状态 rejected，不激活 membership。"""
    teacher = _user(session, "lc_reject_teacher", UserRole.TEACHER)
    student = _user(session, "lc_reject_student", UserRole.STUDENT)
    course = _course(session, teacher.id)

    resp = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "请拒绝我"},
        headers=_auth(_token(student)),
    )
    request_id = resp.json()["data"]["request_id"]

    resp_rej = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/reject",
        json={"review_comment": "不符合条件"},
        headers=_auth(_token(teacher)),
    )
    assert resp_rej.status_code == 200
    assert resp_rej.json()["data"]["status"] == "rejected"

    # membership 不应存在
    membership = session.exec(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.user_id == student.id,
        )
    ).first()
    assert membership is None


def test_join_request_info_requested_then_supplement(client, session):
    """教师请求补充信息 -> 学生补充 -> 重新 pending -> 教师通过。"""
    teacher = _user(session, "lc_info_teacher", UserRole.TEACHER)
    student = _user(session, "lc_info_student", UserRole.STUDENT)
    course = _course(session, teacher.id)

    r1 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "想加入"},
        headers=_auth(_token(student)),
    )
    request_id = r1.json()["data"]["request_id"]

    r2 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/request-info",
        json={"review_comment": "请补充学号"},
        headers=_auth(_token(teacher)),
    )
    assert r2.json()["data"]["status"] == "info_requested"

    r3 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/supplement",
        json={"supplement_info": "学号 2026001"},
        headers=_auth(_token(student)),
    )
    assert r3.json()["data"]["status"] == "pending"
    assert r3.json()["data"]["supplement_info"] == "学号 2026001"

    r4 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/approve",
        json={"review_comment": "已确认"},
        headers=_auth(_token(teacher)),
    )
    assert r4.json()["data"]["status"] == "approved"


def test_join_request_cancel_by_applicant(client, session):
    """学生撤销自己的申请 -> status cancelled。"""
    teacher = _user(session, "lc_cancel_teacher", UserRole.TEACHER)
    student = _user(session, "lc_cancel_student", UserRole.STUDENT)
    course = _course(session, teacher.id)

    r1 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "想加入"},
        headers=_auth(_token(student)),
    )
    request_id = r1.json()["data"]["request_id"]

    r2 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/cancel",
        headers=_auth(_token(student)),
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "cancelled"


def test_join_request_idempotent_pending_returns_same(client, session):
    """已有 pending 申请时再次创建 -> 返回同一申请。"""
    teacher = _user(session, "lc_idem_teacher", UserRole.TEACHER)
    student = _user(session, "lc_idem_student", UserRole.STUDENT)
    course = _course(session, teacher.id)

    r1 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "第一次"},
        headers=_auth(_token(student)),
    )
    r2 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "第二次"},
        headers=_auth(_token(student)),
    )
    assert r1.json()["data"]["request_id"] == r2.json()["data"]["request_id"]


# ---------------------------------------------------------------------------
# 2. 权限拒绝
# ---------------------------------------------------------------------------


def test_join_request_list_requires_membership_view(client, session):
    """学生调用教师查看申请列表接口 -> 403。"""
    teacher = _user(session, "lc_perm_teacher", UserRole.TEACHER)
    student = _user(session, "lc_perm_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()

    resp = client.get(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


def test_join_request_approve_requires_teacher(client, session):
    """学生调用 approve 接口 -> 403。"""
    teacher = _user(session, "lc_approve_perm_teacher", UserRole.TEACHER)
    student_a = _user(session, "lc_approve_perm_a", UserRole.STUDENT)
    student_b = _user(session, "lc_approve_perm_b", UserRole.STUDENT)
    course = _course(session, teacher.id)

    r1 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "申请"},
        headers=_auth(_token(student_a)),
    )
    request_id = r1.json()["data"]["request_id"]

    # 学生 B 尝试审批 -> 403
    resp = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/approve",
        json={"review_comment": "我无权"},
        headers=_auth(_token(student_b)),
    )
    assert resp.status_code == 403


def test_join_request_state_conflict_on_double_approve(client, session):
    """已 approved 的申请再次 approve -> 409 STATE_CONFLICT。"""
    teacher = _user(session, "lc_conflict_teacher", UserRole.TEACHER)
    student = _user(session, "lc_conflict_student", UserRole.STUDENT)
    course = _course(session, teacher.id)

    r1 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "申请"},
        headers=_auth(_token(student)),
    )
    request_id = r1.json()["data"]["request_id"]

    client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/approve",
        json={"review_comment": "通过"},
        headers=_auth(_token(teacher)),
    )
    resp = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/approve",
        json={"review_comment": "再次通过"},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_code"] == "STATE_CONFLICT"


# ---------------------------------------------------------------------------
# 3. 跨课程隔离
# ---------------------------------------------------------------------------


def test_join_request_cross_course_access_denied(client, session):
    """课程 A 的教师不能审批课程 B 的申请。"""
    teacher_a = _user(session, "lc_cross_teacher_a", UserRole.TEACHER)
    teacher_b = _user(session, "lc_cross_teacher_b", UserRole.TEACHER)
    student = _user(session, "lc_cross_student", UserRole.STUDENT)
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")

    # 学生申请课程 A
    r1 = client.post(
        f"{COURSE_ACCESS}/courses/{course_a.id}/join-requests",
        json={"apply_reason": "申请 A"},
        headers=_auth(_token(student)),
    )
    request_id_a = r1.json()["data"]["request_id"]

    # 教师 B 尝试审批课程 A 的申请 -> 403
    resp = client.post(
        f"{COURSE_ACCESS}/courses/{course_a.id}/join-requests/{request_id_a}/approve",
        json={"review_comment": "越权"},
        headers=_auth(_token(teacher_b)),
    )
    assert resp.status_code == 403


def test_join_request_not_found_in_wrong_course(client, session):
    """课程 A 的申请在课程 B 查询 -> 404 RESOURCE_NOT_FOUND。"""
    teacher_a = _user(session, "lc_nf_teacher_a", UserRole.TEACHER)
    teacher_b = _user(session, "lc_nf_teacher_b", UserRole.TEACHER)
    student = _user(session, "lc_nf_student", UserRole.STUDENT)
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")

    r1 = client.post(
        f"{COURSE_ACCESS}/courses/{course_a.id}/join-requests",
        json={"apply_reason": "申请 A"},
        headers=_auth(_token(student)),
    )
    request_id_a = r1.json()["data"]["request_id"]

    # 教师 B 在课程 B 中查询课程 A 的申请 ID -> 404
    resp = client.post(
        f"{COURSE_ACCESS}/courses/{course_b.id}/join-requests/{request_id_a}/approve",
        json={"review_comment": "试图审批"},
        headers=_auth(_token(teacher_b)),
    )
    assert resp.status_code == 404
    assert resp.json()["data"]["error_code"] == "RESOURCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 4. 降级：草稿/已关闭课程不接受加入申请
# ---------------------------------------------------------------------------


def test_join_request_draft_course_rejected(client, session):
    """草稿课程不接受加入申请 -> 422 VALIDATION_FAILED。"""
    teacher = _user(session, "lc_draft_teacher", UserRole.TEACHER)
    student = _user(session, "lc_draft_student", UserRole.STUDENT)
    course = _course(session, teacher.id, status=CourseStatus.DRAFT)

    resp = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "想加入草稿"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 422
    assert resp.json()["data"]["error_code"] == "VALIDATION_FAILED"


def test_join_request_closed_course_rejected(client, session):
    """已关闭课程不接受加入申请 -> 422。"""
    teacher = _user(session, "lc_closed_teacher", UserRole.TEACHER)
    student = _user(session, "lc_closed_student", UserRole.STUDENT)
    course = _course(session, teacher.id, status=CourseStatus.CLOSED)

    resp = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "想加入"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 5. 课程分组
# ---------------------------------------------------------------------------


def test_group_crud_and_member_assignment(client, session):
    """分组 CRUD + 成员分配 + 删除分组不删除成员。"""
    teacher = _user(session, "lc_group_teacher", UserRole.TEACHER)
    student = _user(session, "lc_group_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()

    # 创建分组
    r_create = client.post(
        f"{COURSE_GROUPS}/course/{course.id}/groups",
        json={"name": "实验一组", "description": "A 班", "group_type": "experiment"},
        headers=_auth(_token(teacher)),
    )
    assert r_create.status_code == 200
    assert r_create.json()["code"] == 201
    group_id = r_create.json()["data"]["group_id"]

    # 添加成员
    r_add = client.post(
        f"{COURSE_GROUPS}/course/{course.id}/groups/{group_id}/members",
        json={"user_id": student.id},
        headers=_auth(_token(teacher)),
    )
    assert r_add.status_code == 200
    assert r_add.json()["code"] == 201

    # 列出成员
    r_list = client.get(
        f"{COURSE_GROUPS}/course/{course.id}/groups/{group_id}/members",
        headers=_auth(_token(teacher)),
    )
    assert r_list.status_code == 200
    assert any(m["user_id"] == student.id for m in r_list.json()["data"]["items"])

    # 删除分组
    r_del = client.delete(
        f"{COURSE_GROUPS}/course/{course.id}/groups/{group_id}",
        headers=_auth(_token(teacher)),
    )
    assert r_del.status_code == 200

    # 成员本身仍然存在（CourseMembership 没被删除）
    membership = session.exec(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.user_id == student.id,
        )
    ).first()
    assert membership is not None
    assert membership.status == MembershipStatus.ACTIVE


def test_group_cross_course_access_denied(client, session):
    """教师 B 不能操作课程 A 的分组。"""
    teacher_a = _user(session, "lc_group_ta", UserRole.TEACHER)
    teacher_b = _user(session, "lc_group_tb", UserRole.TEACHER)
    course_a = _course(session, teacher_a.id, title="分组课程 A")

    resp = client.post(
        f"{COURSE_GROUPS}/course/{course_a.id}/groups",
        json={"name": "B 试图创建"},
        headers=_auth(_token(teacher_b)),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 6. 课程设置版本化
# ---------------------------------------------------------------------------


def test_settings_update_creates_new_version(client, session):
    """更新设置生成新版本；旧版本 is_current=False。"""
    teacher = _user(session, "lc_set_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    r1 = client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/profile",
        json={"patch": {"title": "新标题", "description": "新简介"}, "expected_version": None},
        headers=_auth(_token(teacher)),
    )
    assert r1.status_code == 200, r1.text
    v1 = r1.json()["data"]
    assert v1["version"] == 1
    assert v1["profile"]["title"] == "新标题"

    r2 = client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/profile",
        json={"patch": {"title": "更新标题"}, "expected_version": 1},
        headers=_auth(_token(teacher)),
    )
    v2 = r2.json()["data"]
    assert v2["version"] == 2
    assert v2["profile"]["title"] == "更新标题"
    assert v2["is_current"] is True

    # 旧版本仍可查询，且 is_current=False
    versions = client.get(
        f"{COURSE_SETTINGS}/course/{course.id}/settings/versions",
        headers=_auth(_token(teacher)),
    ).json()["data"]["items"]
    assert len(versions) >= 2
    assert versions[0]["is_current"] is True  # 最新版
    assert versions[1]["is_current"] is False


def test_settings_optimistic_lock_conflict(client, session):
    """expected_version 不匹配 -> 409 VERSION_CONFLICT。"""
    teacher = _user(session, "lc_lock_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/profile",
        json={"patch": {"title": "v1"}, "expected_version": None},
        headers=_auth(_token(teacher)),
    )
    client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/profile",
        json={"patch": {"title": "v2"}, "expected_version": 1},
        headers=_auth(_token(teacher)),
    )
    # 用过期的 expected_version=1
    resp = client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/profile",
        json={"patch": {"title": "stale"}, "expected_version": 1},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_code"] == "VERSION_CONFLICT"


def test_settings_rollback_creates_new_version(client, session):
    """回滚到旧版本生成新版本（不破坏历史）。"""
    teacher = _user(session, "lc_rollback_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/profile",
        json={"patch": {"title": "v1"}, "expected_version": None},
        headers=_auth(_token(teacher)),
    )
    client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/profile",
        json={"patch": {"title": "v2"}, "expected_version": 1},
        headers=_auth(_token(teacher)),
    )
    resp = client.post(
        f"{COURSE_SETTINGS}/course/{course.id}/settings/rollback",
        json={"target_version": 1},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    rolled = resp.json()["data"]
    assert rolled["version"] == 3  # 新版本号
    assert rolled["profile"]["title"] == "v1"  # 内容回滚到 v1


def test_settings_unauthorized_for_student(client, session):
    """学生不能修改设置 -> 403。"""
    teacher = _user(session, "lc_set_perm_teacher", UserRole.TEACHER)
    student = _user(session, "lc_set_perm_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()

    resp = client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/profile",
        json={"patch": {"title": "学生篡改"}, "expected_version": None},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


def test_settings_agent_policy_field_whitelist(client, session):
    """agent_policy 仅接受白名单字段（前端 SettingsAgentPage 契约字段）；非法字段被忽略。"""
    teacher = _user(session, "lc_ap_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    resp = client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/agent-policy",
        json={
            "patch": {
                "enabled": False,
                "enabled_tools": ["graph_read", "question_bank"],
                "require_teacher_confirmation": True,
                "web_research_enabled": False,
                "agent_name": "课程助手",  # 历史占位字段，不在白名单内
                "malicious_field": "hack",
            },
            "expected_version": None,
        },
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    ap = resp.json()["data"]["agent_policy"]
    assert ap["enabled"] is False
    assert ap["enabled_tools"] == ["graph_read", "question_bank"]
    assert ap["require_teacher_confirmation"] is True
    assert ap["web_research_enabled"] is False
    assert "agent_name" not in ap
    assert "malicious_field" not in ap


# ---------------------------------------------------------------------------
# 7. 泛雅同步
# ---------------------------------------------------------------------------


def test_fanya_sync_preview_then_confirm(client, session):
    """预览差异 -> 教师确认 -> 应用 added/removed。"""
    teacher = _user(session, "lc_sync_teacher", UserRole.TEACHER)
    student_to_add = _user(session, "lc_sync_student_add", UserRole.STUDENT)
    student_to_remove = _user(session, "lc_sync_student_remove", UserRole.STUDENT)
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student_to_remove.id)
    session.commit()

    # 创建同步运行
    r1 = client.post(
        f"{INTEGRATIONS}/fanya/course/{course.id}/sync",
        json={"source_course_id": "fanya-123"},
        headers=_auth(_token(teacher)),
    )
    assert r1.status_code == 200
    assert r1.json()["code"] == 201
    sync_run_id = r1.json()["data"]["sync_run_id"]
    assert r1.json()["data"]["status"] == "previewing"

    # 保存预览
    r2 = client.put(
        f"{INTEGRATIONS}/fanya/course/{course.id}/sync/{sync_run_id}/preview",
        json={
            "added": [{"user_id": student_to_add.id, "name": "新增学生"}],
            "removed": [{"user_id": student_to_remove.id, "name": "已退学"}],
            "conflicts": [],
        },
        headers=_auth(_token(teacher)),
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["preview_summary"]["added"] == 1
    assert r2.json()["data"]["preview_summary"]["removed"] == 1

    # 确认执行
    r3 = client.post(
        f"{INTEGRATIONS}/fanya/course/{course.id}/sync/{sync_run_id}/confirm",
        headers=_auth(_token(teacher)),
    )
    assert r3.status_code == 200, r3.text
    data = r3.json()["data"]
    assert data["status"] == "succeeded"
    assert data["applied_added"] == 1
    assert data["applied_removed"] == 1

    # 验证 membership 变更
    add_membership = session.exec(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.user_id == student_to_add.id,
        )
    ).first()
    assert add_membership is not None
    assert add_membership.status == MembershipStatus.ACTIVE

    remove_membership = session.exec(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.user_id == student_to_remove.id,
        )
    ).first()
    assert remove_membership is not None
    assert remove_membership.status == MembershipStatus.REMOVED


def test_fanya_sync_confirm_without_preview_conflict(client, session):
    """未保存预览就 confirm -> 409 STATE_CONFLICT（空差异直接成功，不冲突）。

    实际上空差异会直接成功；本测试验证有 preview 但状态不对的场景：
    重复 confirm 第二次 -> STATE_CONFLICT。
    """
    teacher = _user(session, "lc_sync_conflict_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    r1 = client.post(
        f"{INTEGRATIONS}/fanya/course/{course.id}/sync",
        json={"source_course_id": "fanya-456"},
        headers=_auth(_token(teacher)),
    )
    sync_run_id = r1.json()["data"]["sync_run_id"]

    # 空预览直接 confirm -> succeeded
    r2 = client.post(
        f"{INTEGRATIONS}/fanya/course/{course.id}/sync/{sync_run_id}/confirm",
        headers=_auth(_token(teacher)),
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "succeeded"

    # 再次 confirm -> STATE_CONFLICT
    r3 = client.post(
        f"{INTEGRATIONS}/fanya/course/{course.id}/sync/{sync_run_id}/confirm",
        headers=_auth(_token(teacher)),
    )
    assert r3.status_code == 409
    assert r3.json()["data"]["error_code"] == "STATE_CONFLICT"


def test_fanya_sync_cross_course_denied(client, session):
    """教师 B 不能在课程 A 创建同步运行。"""
    teacher_a = _user(session, "lc_sync_ta", UserRole.TEACHER)
    teacher_b = _user(session, "lc_sync_tb", UserRole.TEACHER)
    course_a = _course(session, teacher_a.id, title="同步课程 A")

    resp = client.post(
        f"{INTEGRATIONS}/fanya/course/{course_a.id}/sync",
        json={"source_course_id": "fanya-789"},
        headers=_auth(_token(teacher_b)),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 8. facade members/settings 聚合读模型
# ---------------------------------------------------------------------------


def test_facade_members_view_aggregates(client, session):
    """facade /course/{id}/members 返回 members/groups/pending_requests/sync_runs。"""
    teacher = _user(session, "lc_facade_members_teacher", UserRole.TEACHER)
    student = _user(session, "lc_facade_members_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()

    resp = client.get(
        f"{FACADE}/course/{course.id}/members",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert any(m["user_id"] == student.id for m in data["members"])
    assert data["can_review_join_requests"] is True
    assert data["viewer_role"] == "owner"
    assert data["groups"] == []
    assert data["pending_join_requests"] == []
    assert data["recent_sync_runs"] == []


def test_facade_members_student_cannot_see_pending(client, session):
    """学生调用 facade members 看不到 pending_join_requests。"""
    teacher = _user(session, "lc_facade_stu_teacher", UserRole.TEACHER)
    student = _user(session, "lc_facade_stu_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()

    resp = client.get(
        f"{FACADE}/course/{course.id}/members",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["can_review_join_requests"] is False
    assert data["pending_join_requests"] == []


def test_facade_settings_view(client, session):
    """facade /course/{id}/settings 返回当前设置 + can_edit/can_publish。"""
    teacher = _user(session, "lc_facade_set_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # 先更新一次设置
    client.put(
        f"{COURSE_SETTINGS}/course/{course.id}/profile",
        json={"patch": {"title": "facade 课程"}, "expected_version": None},
        headers=_auth(_token(teacher)),
    )

    resp = client.get(
        f"{FACADE}/course/{course.id}/settings",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["can_edit"] is True
    assert data["can_publish"] is True
    assert data["current_setting"] is not None
    assert data["current_setting"]["profile"]["title"] == "facade 课程"
    assert data["course_profile"]["title"] == "facade 课程"


# ---------------------------------------------------------------------------
# 9. 审计事件
# ---------------------------------------------------------------------------


def test_audit_events_recorded_for_join_request_approve(client, session):
    """通过加入申请后审计事件被记录。"""
    teacher = _user(session, "lc_audit_teacher", UserRole.TEACHER)
    student = _user(session, "lc_audit_student", UserRole.STUDENT)
    course = _course(session, teacher.id)

    r1 = client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests",
        json={"apply_reason": "审计测试"},
        headers=_auth(_token(student)),
    )
    request_id = r1.json()["data"]["request_id"]

    client.post(
        f"{COURSE_ACCESS}/courses/{course.id}/join-requests/{request_id}/approve",
        json={"review_comment": "通过"},
        headers=_auth(_token(teacher)),
    )

    resp = client.get(
        f"{AUDIT}/course/{course.id}/audit-events",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    events = resp.json()["data"]["items"]
    assert any(e["event_type"] == "course.join_request.approve" for e in events)


def test_audit_events_cross_course_isolated(client, session):
    """课程 A 的审计事件不出现在课程 B 的列表中。"""
    teacher_a = _user(session, "lc_audit_ta", UserRole.TEACHER)
    teacher_b = _user(session, "lc_audit_tb", UserRole.TEACHER)
    course_a = _course(session, teacher_a.id, title="审计课程 A")
    course_b = _course(session, teacher_b.id, title="审计课程 B")

    # 在课程 A 触发审计事件
    client.put(
        f"{COURSE_SETTINGS}/course/{course_a.id}/profile",
        json={"patch": {"title": "A 标题"}, "expected_version": None},
        headers=_auth(_token(teacher_a)),
    )

    # 课程 B 的审计事件列表不应包含课程 A 的事件
    resp = client.get(
        f"{AUDIT}/course/{course_b.id}/audit-events",
        headers=_auth(_token(teacher_b)),
    )
    events_b = resp.json()["data"]["items"]
    for e in events_b:
        assert e["course_id"] == course_b.id
