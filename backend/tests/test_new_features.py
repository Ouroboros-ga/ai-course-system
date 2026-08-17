"""Regression coverage for course enrolment and learner progress APIs.

These tests use Course Access v1 records instead of the historical fake
``course_id=999`` fixture.  Public responses use the stable ``data`` envelope.
"""
from __future__ import annotations

import uuid

import pytest
from sqlmodel import select

from app.models.course_model import (
    Course,
    CourseScript,
    CourseStatus,
    ScriptNode,
    ScriptNodeType,
)
from app.models.progress_model import LearningProgress
from app.services.course_access_service import establish_course_access_baseline


@pytest.fixture
def published_course(session, teacher_user):
    course = Course(
        fanya_course_id=f"enrol-{uuid.uuid4().hex}",
        fanya_course_name="Enrollment regression course",
        title="Enrollment regression course",
        teacher_id=teacher_user.id,
        status=CourseStatus.PUBLISHED,
        total_nodes=1,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_user.id)

    script = CourseScript(
        course_id=course.id,
        script_content={"nodes": []},
        created_by=teacher_user.id,
    )
    session.add(script)
    session.commit()
    session.refresh(script)
    session.add(ScriptNode(
        script_id=script.id,
        node_index=0,
        node_type=ScriptNodeType.LECTURE,
        title="Introduction",
        content="Course introduction",
    ))
    session.commit()
    return course


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_course_list_reports_student_count(client, teacher_token, published_course):
    response = client.get("/api/v1/document/courses", headers=_headers(teacher_token))
    assert response.status_code == 200
    courses = response.json()["data"]["courses"]
    course = next(item for item in courses if item["id"] == published_course.id)
    assert course["student_count"] == 0


def test_active_teacher_can_enroll_as_learner(client, teacher_token, published_course):
    """2026-08-17 修复：身份模型已收敛（ff46fc75f），任何活跃用户（含教师/管理员）
    都可作为学习者加入课程；教师选课返回 200 + enrollment_id。"""
    response = client.post(
        f"/api/v1/document/course/{published_course.id}/enroll",
        headers=_headers(teacher_token),
    )
    assert response.status_code == 200
    assert response.json()["data"]["enrollment_id"]


def test_enroll_progress_and_teacher_stats(client, session, teacher_token, student_token, published_course):
    enroll = client.post(
        f"/api/v1/document/course/{published_course.id}/enroll",
        headers=_headers(student_token),
    )
    assert enroll.status_code == 200
    assert enroll.json()["data"]["enrollment_id"]

    mine = client.get("/api/v1/document/my-courses", headers=_headers(student_token))
    assert mine.status_code == 200
    assert [item["course_id"] for item in mine.json()["data"]["courses"]] == [published_course.id]

    script = session.exec(
        select(CourseScript).where(CourseScript.course_id == published_course.id)
    ).one()
    node = session.exec(
        select(ScriptNode).where(ScriptNode.script_id == script.id)
    ).one()

    sync = client.post(
        "/api/v1/progress/sync",
        headers=_headers(student_token),
        json={"courseId": published_course.id, "nodeId": node.id, "timestamp": 60.0, "isCompleted": True, "timeSpent": 120},
    )
    assert sync.status_code == 200
    assert sync.json()["data"]["isCompleted"] is True

    session.expire_all()
    progress = session.exec(select(LearningProgress).where(
        LearningProgress.course_id == published_course.id
    )).one()
    assert progress.completion_rate == 1.0

    stats = client.get(
        f"/api/v1/document/course/{published_course.id}/stats",
        headers=_headers(teacher_token),
    )
    assert stats.status_code == 200
    assert stats.json()["data"]["total_students"] == 1


def test_unenroll_withdraws_membership_then_allows_reenrol(client, student_token, published_course):
    headers = _headers(student_token)
    assert client.post(f"/api/v1/document/course/{published_course.id}/enroll", headers=headers).status_code == 200
    assert client.post(f"/api/v1/document/course/{published_course.id}/unenroll", headers=headers).status_code == 200
    assert client.get("/api/v1/document/my-courses", headers=headers).json()["data"]["total"] == 0

    reenrol = client.post(f"/api/v1/document/course/{published_course.id}/enroll", headers=headers)
    assert reenrol.status_code == 200
    assert reenrol.json()["data"]["reactivated"] is True
