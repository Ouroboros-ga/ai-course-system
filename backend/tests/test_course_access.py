"""Permission-matrix tests for the course access-control cutover."""
from __future__ import annotations

from datetime import datetime
import sqlite3

import pytest
from sqlmodel import select

from app.core.security import get_password_hash
from app.core.security import create_access_token
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    DEFAULT_NEW_COURSE_CAPABILITIES,
    activate_student_membership,
    establish_course_access_baseline,
    resolve_course_access,
)
from app.common.db_migrator import (
    ACCESS_CONTROL_MIGRATION_BATCH,
    access_control_preflight,
    rollback_access_control_backfill,
)


def _user(session, name: str, role: UserRole = UserRole.STUDENT) -> User:
    user = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id=f"permission-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="Permission Course",
        title="Permission Course",
        teacher_id=teacher_id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _principal(user: User) -> dict:
    return {"user_id": str(user.id), "role": user.role.value, "username": user.username}


def _member(session, user: User, course: Course, role: CourseRole, **kwargs) -> CourseMembership:
    membership = CourseMembership(user_id=user.id, course_id=course.id, role=role, **kwargs)
    session.add(membership)
    session.commit()
    session.refresh(membership)
    return membership


def _capability(session, course: Course, **values) -> CourseCapability:
    capability = CourseCapability(course_id=course.id, **values)
    session.add(capability)
    session.commit()
    return capability


def test_legacy_teacher_id_is_not_a_runtime_authorization_source(session):
    owner = _user(session, "permission_legacy_owner")
    course = _course(session, owner.id)
    _capability(session, course)

    context = resolve_course_access(session, _principal(owner), course.id)

    assert context.role is None
    assert not context.allows("course.view")


def test_active_explicit_owner_gets_course_permissions(session):
    owner = _user(session, "permission_explicit_owner", UserRole.TEACHER)
    course = _course(session, owner.id)
    _capability(session, course, course_building=True)
    _member(session, owner, course, CourseRole.OWNER, analytics_excluded=True)

    context = resolve_course_access(session, _principal(owner), course.id)

    assert context.allows("course.view")
    assert context.allows("course.edit")
    assert context.participation_mode.value == "teacher_preview"
    assert context.analytics_eligible is False


def test_membership_must_be_active(session):
    student = _user(session, "permission_invited_student")
    course = _course(session, student.id)
    _capability(session, course, learning=True)
    _member(session, student, course, CourseRole.STUDENT, status=MembershipStatus.INVITED)

    context = resolve_course_access(session, _principal(student), course.id)

    assert context.role is None
    assert context.membership_status == MembershipStatus.INVITED
    assert not context.allows("course.learn")


def test_explicit_deny_overrides_role_default(session):
    owner = _user(session, "permission_denied_owner", UserRole.TEACHER)
    course = _course(session, owner.id)
    _capability(session, course, course_building=True)
    _member(
        session,
        owner,
        course,
        CourseRole.OWNER,
        permission_overrides={"deny": ["course.publish"]},
    )

    context = resolve_course_access(session, _principal(owner), course.id)

    assert context.allows("course.edit")
    assert not context.allows("course.publish")


def test_disabled_course_capability_blocks_even_authorized_teacher(session):
    teacher = _user(session, "permission_capability_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    _capability(session, course, course_building=False)
    _member(session, teacher, course, CourseRole.TEACHER)

    context = resolve_course_access(session, _principal(teacher), course.id)

    assert "course.edit" in context.permissions
    assert not context.allows("course.edit")


def test_legacy_admin_role_is_not_a_runtime_authorization_source(session):
    admin = _user(session, "permission_legacy_admin", UserRole.ADMIN)
    course_owner = _user(session, "permission_course_owner")
    course = _course(session, course_owner.id)
    _capability(session, course)

    context = resolve_course_access(session, _principal(admin), course.id)

    assert not context.allows("course.view")


def test_explicit_platform_admin_is_cross_course_authorized(session):
    admin = _user(session, "permission_platform_admin", UserRole.STUDENT)
    course_owner = _user(session, "permission_platform_course_owner")
    course = _course(session, course_owner.id)
    _capability(session, course)
    session.add(PlatformPermissionAssignment(user_id=admin.id, permission=PlatformPermission.ADMIN))
    session.commit()

    context = resolve_course_access(session, _principal(admin), course.id)

    assert context.allows("course.view")
    assert context.allows("course.delete")
    assert context.analytics_eligible is False
    # 隐藏课程所有者身份：无成员关系也呈现为 OWNER（成员列表不可见）。
    assert context.role == CourseRole.OWNER
    assert context.membership_status is None


def test_safety_manage_platform_permission_grants_agent_policy_across_courses(session):
    """PlatformPermission.SAFETY_MANAGE 跨课程授予 agent.policy/sandbox.policy 权限子集。

    验收包1 P0-3：覆盖 SAFETY_MANAGE 平台权限，断言权限子集边界。
    """
    safety_mgr = _user(session, "permission_safety_mgr", UserRole.TEACHER)
    course_owner = _user(session, "permission_safety_owner", UserRole.TEACHER)
    course = _course(session, course_owner.id)
    # 全 capability 开启，确保权限边界仅由 platform permission 决定
    _capability(
        session, course,
        learning=True, course_building=True, knowledge_graph=True,
        evidence=True, experiment=True, coding_sandbox=True,
        cognitive_analysis=True, safety_policy=True,
    )
    session.add(PlatformPermissionAssignment(
        user_id=safety_mgr.id, permission=PlatformPermission.SAFETY_MANAGE,
    ))
    session.commit()

    ctx = resolve_course_access(session, _principal(safety_mgr), course.id)

    # SAFETY_MANAGE 应授予 agent.policy 与 sandbox.policy 子集
    assert ctx.allows("agent.policy.view")
    assert ctx.allows("agent.policy.configure")
    assert ctx.allows("sandbox.policy.view")
    assert ctx.allows("sandbox.policy.configure")
    # 不应越权获得课程删除/权限管理/发布等敏感权限
    assert not ctx.allows("course.delete")
    assert not ctx.allows("permission.manage")
    assert not ctx.allows("course.publish")
    # 也不应获得非安全相关的审计权限
    assert not ctx.allows("analytics.export")


def test_capability_manage_platform_permission_grants_permission_manage(session):
    """PlatformPermission.CAPABILITY_MANAGE 跨课程仅授予 permission.manage。

    验收包1 P0-3：覆盖 CAPABILITY_MANAGE 平台权限，断言权限子集边界。
    """
    cap_mgr = _user(session, "permission_cap_mgr", UserRole.TEACHER)
    course_owner = _user(session, "permission_cap_owner", UserRole.TEACHER)
    course = _course(session, course_owner.id)
    _capability(
        session, course,
        learning=True, course_building=True, knowledge_graph=True,
        evidence=True, experiment=True, coding_sandbox=True,
        cognitive_analysis=True, safety_policy=True,
    )
    session.add(PlatformPermissionAssignment(
        user_id=cap_mgr.id, permission=PlatformPermission.CAPABILITY_MANAGE,
    ))
    session.commit()

    ctx = resolve_course_access(session, _principal(cap_mgr), course.id)

    # CAPABILITY_MANAGE 仅授予 permission.manage
    assert ctx.allows("permission.manage")
    # 不应越权获得 agent.policy 配置、沙箱配置、课程删除等
    assert not ctx.allows("agent.policy.configure")
    assert not ctx.allows("sandbox.policy.configure")
    assert not ctx.allows("course.delete")
    assert not ctx.allows("course.publish")
    # SAFETY_MANAGE 才有的权限不应泄漏到 CAPABILITY_MANAGE
    assert not ctx.allows("agent.policy.view")


def test_course_bootstrap_and_student_activation_create_authoritative_records(session):
    owner = _user(session, "permission_bootstrap_owner", UserRole.TEACHER)
    student = _user(session, "permission_bootstrap_student")
    course = _course(session, owner.id)

    establish_course_access_baseline(session, course.id, owner.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()

    owner_context = resolve_course_access(session, _principal(owner), course.id)
    student_context = resolve_course_access(session, _principal(student), course.id)
    assert owner_context.allows("course.edit")
    assert student_context.allows("course.learn")
    assert student_context.analytics_eligible is True


def test_access_endpoint_exposes_only_explicit_course_access(client, session):
    owner = _user(session, "permission_endpoint_owner", UserRole.TEACHER)
    course = _course(session, owner.id)
    _capability(session, course, learning=True, course_building=True)
    _member(session, owner, course, CourseRole.OWNER, analytics_excluded=True)
    token = create_access_token({"sub": str(owner.id), "username": owner.username, "role": "teacher"})

    response = client.get(
        f"/api/v1/course-access/courses/{course.id}/access",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["course_role"] == "owner"
    assert data["allowed"]["course.edit"] is True


def test_access_endpoint_rejects_legacy_owner_without_membership(client, session):
    owner = _user(session, "permission_endpoint_legacy", UserRole.TEACHER)
    course = _course(session, owner.id)
    _capability(session, course, learning=True, course_building=True)
    token = create_access_token({"sub": str(owner.id), "username": owner.username, "role": "teacher"})

    response = client.get(
        f"/api/v1/course-access/courses/{course.id}/access",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_new_courses_require_explicit_code_sandbox_opt_in():
    assert DEFAULT_NEW_COURSE_CAPABILITIES["experiment"] is False
    assert DEFAULT_NEW_COURSE_CAPABILITIES["coding_sandbox"] is False


def test_disabling_code_sandbox_also_disables_current_experiment_platform(client, session):
    """The current experiment UI is code-sandbox-only, so it cannot remain exposed alone."""
    owner = _user(session, "permission_platform_gate_owner", UserRole.TEACHER)
    course = _course(session, owner.id)
    establish_course_access_baseline(session, course.id, owner.id)
    session.commit()
    token = create_access_token({"sub": str(owner.id), "username": owner.username, "role": "teacher"})

    response = client.put(
        f"/api/v1/course-access/courses/{course.id}/capabilities",
        json={
            "learning": True,
            "course_building": True,
            "knowledge_graph": True,
            "evidence": True,
            "experiment": True,
            "coding_sandbox": False,
            "cognitive_analysis": True,
            "safety_policy": False,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    capabilities = response.json()["data"]["capabilities"]
    assert capabilities["experiment"] is False
    assert capabilities["coding_sandbox"] is False
    stored = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    assert stored.experiment is False
    assert stored.coding_sandbox is False


def test_course_teacher_can_enable_current_code_sandbox_platform(client, session):
    owner = _user(session, "permission_platform_gate_course_owner", UserRole.TEACHER)
    teacher = _user(session, "permission_platform_gate_teacher", UserRole.TEACHER)
    course = _course(session, owner.id)
    establish_course_access_baseline(session, course.id, owner.id)
    _member(session, teacher, course, CourseRole.TEACHER, analytics_excluded=True)
    session.commit()
    token = create_access_token({"sub": str(teacher.id), "username": teacher.username, "role": "teacher"})

    response = client.put(
        f"/api/v1/course-access/courses/{course.id}/experiment-platform",
        json={"enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    capabilities = response.json()["data"]["capabilities"]
    assert capabilities["experiment"] is True
    assert capabilities["coding_sandbox"] is True
    stored = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    assert stored.experiment is True
    assert stored.coding_sandbox is True


def test_student_cannot_change_current_code_sandbox_platform(client, session):
    owner = _user(session, "permission_platform_gate_student_owner", UserRole.TEACHER)
    student = _user(session, "permission_platform_gate_student", UserRole.STUDENT)
    course = _course(session, owner.id)
    establish_course_access_baseline(session, course.id, owner.id)
    _member(session, student, course, CourseRole.STUDENT, analytics_excluded=False)
    session.commit()
    token = create_access_token({"sub": str(student.id), "username": student.username, "role": "student"})

    response = client.put(
        f"/api/v1/course-access/courses/{course.id}/experiment-platform",
        json={"enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_draft_course_cannot_issue_invite_code(client, session):
    """A course must be explicitly published before it can be discoverable/joinable."""
    owner = _user(session, "permission_draft_invite_owner", UserRole.TEACHER)
    course = _course(session, owner.id)
    establish_course_access_baseline(session, course.id, owner.id)
    session.commit()
    token = create_access_token({"sub": str(owner.id), "username": owner.username, "role": "teacher"})

    response = client.post(
        f"/api/v1/course-access/courses/{course.id}/invite-code",
        json={"invite_code": "DRAFT-ONLY"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    body = response.json()
    assert body.get("code") == 409
    assert "发布" in str(body)
    session.refresh(course)
    assert course.invite_code is None


def test_citation_endpoint_uses_course_membership_not_legacy_owner(client, session):
    owner = _user(session, "permission_citation_owner", UserRole.TEACHER)
    course = _course(session, owner.id)
    _capability(session, course, learning=True)
    token = create_access_token({"sub": str(owner.id), "username": owner.username, "role": "teacher"})

    denied = client.get(
        f"/api/v1/citations/locate?course_id={course.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 403

    _member(session, owner, course, CourseRole.OWNER, analytics_excluded=True)
    allowed = client.get(
        f"/api/v1/citations/locate?course_id={course.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["data"]["match_type"] == "none"


def _legacy_access_db(path, *, orphan_owner: bool = False):
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, is_active INTEGER NOT NULL, role VARCHAR NOT NULL);
        CREATE TABLE courses (id INTEGER PRIMARY KEY, teacher_id INTEGER, created_at TIMESTAMP);
        CREATE TABLE student_enrollments (course_id INTEGER, student_id INTEGER, is_active INTEGER, enrolled_at TIMESTAMP);
        CREATE TABLE course_capabilities (
          course_id INTEGER UNIQUE, learning INTEGER, course_building INTEGER, knowledge_graph INTEGER,
          evidence INTEGER, experiment INTEGER, coding_sandbox INTEGER, cognitive_analysis INTEGER,
          safety_policy INTEGER, updated_at TIMESTAMP, migration_batch_id VARCHAR
        );
        CREATE TABLE course_memberships (
          user_id INTEGER, course_id INTEGER, role VARCHAR, status VARCHAR, permission_overrides VARCHAR,
          analytics_excluded INTEGER, joined_at TIMESTAMP, updated_at TIMESTAMP, migration_batch_id VARCHAR,
          UNIQUE(user_id, course_id)
        );
        CREATE TABLE platform_permission_assignments (
          user_id INTEGER, permission VARCHAR, granted_by_user_id INTEGER, granted_at TIMESTAMP,
          migration_batch_id VARCHAR, UNIQUE(user_id, permission)
        );
    """)
    cursor.execute("INSERT INTO users VALUES (1, 1, 'teacher')")
    cursor.execute("INSERT INTO users VALUES (2, 1, 'student')")
    cursor.execute("INSERT INTO courses VALUES (10, ?, CURRENT_TIMESTAMP)", (999 if orphan_owner else 1,))
    cursor.execute("INSERT INTO student_enrollments VALUES (10, 2, 1, CURRENT_TIMESTAMP)")
    conn.commit()
    return conn


def test_access_control_preflight_fails_before_backfill_for_orphan_legacy_owner(tmp_path):
    path = tmp_path / "orphan.sqlite"
    conn = _legacy_access_db(path, orphan_owner=True)
    conn.close()

    report = access_control_preflight(str(path))

    assert report["ok"] is False
    assert report["counts"]["orphan_course_owners"] == 1


def test_access_control_backfill_is_idempotent_and_rollback_is_batch_scoped(
    tmp_path, run_alembic
):
    """alembic revision 0002 回填幂等，且 rollback_access_control_backfill 按批次隔离回滚。

    验证：
    - alembic stamp 0001 + upgrade 0002 后，legacy 数据被回填到目标表（带 batch_id）。
    - 再次 stamp 0001 + upgrade 0002 时，逐行 NOT EXISTS 检查确保无重复行。
    - rollback_access_control_backfill 仅删除本批次记录，回滚边界为 batch_id。
    """
    path = tmp_path / "legacy.sqlite"
    conn = _legacy_access_db(str(path))
    conn.close()

    assert access_control_preflight(str(path))["ok"] is True

    # 1. 通过 alembic stamp 0001 + upgrade 0002 完成回填。
    run_alembic(str(path), "stamp", "0001")
    run_alembic(str(path), "upgrade", "0002")

    # 2. 验证回填结果：1 capability + 2 memberships + 1 permission。
    conn = sqlite3.connect(str(path))
    caps = conn.execute(
        "SELECT COUNT(*) FROM course_capabilities WHERE migration_batch_id = ?",
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    ).fetchone()[0]
    memberships = conn.execute(
        "SELECT COUNT(*) FROM course_memberships WHERE migration_batch_id = ?",
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    ).fetchone()[0]
    perms = conn.execute(
        "SELECT COUNT(*) FROM platform_permission_assignments WHERE migration_batch_id = ?",
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    ).fetchone()[0]
    conn.close()
    assert caps == 1
    assert memberships == 2  # owner + student
    assert perms == 1  # teacher -> platform.course.create

    # 3. 幂等性：重新 stamp 0001 + upgrade 0002。
    #    逐行幂等检查应保留现有记录且不产生重复。
    run_alembic(str(path), "stamp", "0001")
    run_alembic(str(path), "upgrade", "0002")

    conn = sqlite3.connect(str(path))
    memberships_after = conn.execute(
        "SELECT COUNT(*) FROM course_memberships WHERE migration_batch_id = ?",
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    ).fetchone()[0]
    conn.close()
    assert memberships_after == 2  # 无重复

    # 4. rollback_access_control_backfill 按批次删除记录（回滚边界为 batch_id）。
    deleted = rollback_access_control_backfill(str(path))

    assert deleted == {
        "platform_permission_assignments": 1,
        "course_memberships": 2,
        "course_capabilities": 1,
    }
    conn = sqlite3.connect(str(path))
    remaining = conn.execute(
        "SELECT COUNT(*) FROM course_memberships WHERE migration_batch_id = ?",
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    ).fetchone()[0]
    conn.close()
    assert remaining == 0


def test_access_control_backfill_repairs_a_partially_applied_batch(
    tmp_path, run_alembic
):
    """An existing batch row must not suppress unrelated missing grants."""
    path = tmp_path / "partial_legacy.sqlite"
    conn = _legacy_access_db(str(path))
    conn.execute(
        """
        INSERT INTO course_memberships
            (user_id, course_id, role, status, permission_overrides,
             analytics_excluded, joined_at, updated_at, migration_batch_id)
        VALUES (1, 10, 'OWNER', 'ACTIVE', '{}', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
        """,
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    )
    conn.commit()
    conn.close()

    run_alembic(str(path), "stamp", "0001")
    run_alembic(str(path), "upgrade", "0002")

    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM course_memberships"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM course_capabilities"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM platform_permission_assignments "
            "WHERE permission = 'COURSE_CREATE'"
        ).fetchone()[0] == 1
    finally:
        conn.close()
