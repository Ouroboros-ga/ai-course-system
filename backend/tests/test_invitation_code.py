"""Tests for invitation-code enrollment and course close/reopen semantics (批次1)."""
from __future__ import annotations

from app.models.course_model import Course, CourseStatus
from app.services.course_access_service import establish_course_access_baseline


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_course(session, teacher, *, status=CourseStatus.PUBLISHED, invite_code=None):
    course = Course(
        fanya_course_id=f"invite-{status.value}-{id(teacher)}",
        fanya_course_name="t",
        title="邀请码测试课程",
        teacher_id=teacher.id,
        status=status,
        invite_code=invite_code,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course_id=course.id, owner_user_id=teacher.id)
    session.commit()
    return course


def test_teacher_sets_invite_code(client, session, teacher_user, teacher_token):
    course = _make_course(session, teacher_user)
    r = client.post(
        f"/api/v1/course-access/courses/{course.id}/invite-code",
        json={},
        headers=_headers(teacher_token),
    )
    assert r.status_code == 200
    code = r.json()["data"]["invite_code"]
    assert len(code) == 8
    session.refresh(course)
    assert course.invite_code == code


def test_student_joins_by_code(client, session, teacher_user, student_user, student_token):
    course = _make_course(session, teacher_user, invite_code="ABCD1234")
    r = client.post(
        "/api/v1/course-access/courses/join-by-code",
        json={"invite_code": "ABCD1234"},
        headers=_headers(student_token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["enrolled"] is True
    assert r.json()["data"]["course_id"] == course.id


def test_invalid_code_rejected(client, session, teacher_user, student_token):
    _make_course(session, teacher_user, invite_code="VALIDCODE")
    r = client.post(
        "/api/v1/course-access/courses/join-by-code",
        json={"invite_code": "WRONGCODE"},
        headers=_headers(student_token),
    )
    assert r.status_code == 404


def test_closed_course_rejects_join(client, session, teacher_user, student_token):
    _make_course(session, teacher_user, status=CourseStatus.CLOSED, invite_code="CLOSEDC1")
    r = client.post(
        "/api/v1/course-access/courses/join-by-code",
        json={"invite_code": "CLOSEDC1"},
        headers=_headers(student_token),
    )
    assert r.status_code == 400


def test_rejoin_after_withdraw_returns_reactivated(client, session, teacher_user, student_user, student_token):
    course = _make_course(session, teacher_user, invite_code="REJOIN01")
    r1 = client.post(
        "/api/v1/course-access/courses/join-by-code",
        json={"invite_code": "REJOIN01"},
        headers=_headers(student_token),
    )
    assert r1.json()["data"]["enrolled"] is True
    r2 = client.post(
        f"/api/v1/document/course/{course.id}/unenroll",
        headers=_headers(student_token),
    )
    assert r2.status_code == 200
    r3 = client.post(
        "/api/v1/course-access/courses/join-by-code",
        json={"invite_code": "REJOIN01"},
        headers=_headers(student_token),
    )
    assert r3.status_code == 200
    assert r3.json()["data"]["reactivated"] is True


def test_duplicate_join_returns_already_enrolled(client, session, teacher_user, student_token):
    _make_course(session, teacher_user, invite_code="DUPCODE1")
    r1 = client.post(
        "/api/v1/course-access/courses/join-by-code",
        json={"invite_code": "DUPCODE1"},
        headers=_headers(student_token),
    )
    assert r1.json()["data"]["enrolled"] is True
    r2 = client.post(
        "/api/v1/course-access/courses/join-by-code",
        json={"invite_code": "DUPCODE1"},
        headers=_headers(student_token),
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["already_enrolled"] is True


def test_teacher_close_and_reopen_course(client, session, teacher_user, teacher_token):
    course = _make_course(session, teacher_user)
    r = client.post(
        f"/api/v1/course-access/courses/{course.id}/close",
        headers=_headers(teacher_token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "closed"
    session.refresh(course)
    assert course.status == CourseStatus.CLOSED
    r2 = client.post(
        f"/api/v1/course-access/courses/{course.id}/reopen",
        headers=_headers(teacher_token),
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "published"
    session.refresh(course)
    assert course.status == CourseStatus.PUBLISHED


def test_clear_invite_code(client, session, teacher_user, teacher_token):
    course = _make_course(session, teacher_user, invite_code="CLEARME1")
    r = client.delete(
        f"/api/v1/course-access/courses/{course.id}/invite-code",
        headers=_headers(teacher_token),
    )
    assert r.status_code == 200
    session.refresh(course)
    assert course.invite_code is None


def test_active_teacher_can_join_by_code(client, session, teacher_user, teacher_token):
    """2026-08-17 修复：任何活跃平台用户（含教师/管理员）可经邀请码加入课程
    （ff46fc75f 身份模型收敛）；教师入课返回 200 + enrolled: true。"""
    _make_course(session, teacher_user, invite_code="TEACHER1")
    r = client.post(
        "/api/v1/course-access/courses/join-by-code",
        json={"invite_code": "TEACHER1"},
        headers=_headers(teacher_token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["enrolled"] is True
