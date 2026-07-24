"""Permission-matrix tests for the course access-control cutover."""
from __future__ import annotations

from datetime import datetime
import sqlite3

import pytest

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
    activate_student_membership,
    establish_course_access_baseline,
    resolve_course_access,
)
from app.common.db_migrator import (
    ACCESS_CONTROL_MIGRATION_BATCH,
    _backfill_access_control,
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


def test_access_control_backfill_is_idempotent_and_rollback_is_batch_scoped(tmp_path):
    path = tmp_path / "legacy.sqlite"
    conn = _legacy_access_db(path)
    cursor = conn.cursor()

    assert access_control_preflight(str(path))["ok"] is True
    assert _backfill_access_control(cursor) == 4
    assert _backfill_access_control(cursor) == 0
    conn.commit()
    conn.close()

    deleted = rollback_access_control_backfill(str(path))

    assert deleted == {
        "platform_permission_assignments": 1,
        "course_memberships": 2,
        "course_capabilities": 1,
    }
    conn = sqlite3.connect(path)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM course_memberships WHERE migration_batch_id = ?",
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    ).fetchone()[0]
    conn.close()
    assert remaining == 0
