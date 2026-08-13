"""API contract tests for course-scoped TeachingAgent constraint governance."""
from __future__ import annotations

import uuid

from sqlmodel import select

from app.models.access_control_model import CourseCapability
from app.models.course_lifecycle_model import CourseGroup
from app.models.course_model import Course, CourseStatus
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)


BASE = "/api/v1/agent-governance"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _course(session, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id=f"constraint-{uuid.uuid4().hex}",
        fanya_course_name="Constraint API course",
        title="Constraint API course",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_id)
    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).first()
    capability.safety_policy = True
    session.add(capability)
    session.commit()
    return course


def _enroll(session, course_id: int, student_id: int) -> None:
    activate_student_membership(session, course_id, student_id)
    session.commit()


def _policy(level: str = "balanced", *, rules: list[dict] | None = None) -> dict:
    return {
        "level": level,
        "scopes": ["evidence", "response", "context", "tools", "actions"],
        "rules": rules or [],
    }


def _save_payload(policy: dict, expected_version: int = 0) -> dict:
    return {
        "expected_version": expected_version,
        "change_reason": "Course teaching policy",
        "policy": policy,
    }


def test_student_cannot_update_teaching_constraints(
    client,
    session,
    teacher_user,
    student_user,
    student_token,
    teacher_token,
):
    course = _course(session, teacher_user.id)
    _enroll(session, course.id, student_user.id)

    response = client.put(
        f"{BASE}/course/{course.id}/teaching-constraints",
        headers=_auth(student_token),
        json=_save_payload(_policy()),
    )

    assert response.status_code == 403
    current = client.get(
        f"{BASE}/course/{course.id}/teaching-constraints",
        headers=_auth(teacher_token),
    )
    assert current.status_code == 200, current.text
    assert current.json()["data"]["active_version"]["version"] == 0


def test_teacher_can_save_read_and_preview_student_specific_policy(
    client,
    session,
    teacher_user,
    student_user,
    teacher_token,
):
    course = _course(session, teacher_user.id)
    _enroll(session, course.id, student_user.id)
    policy = _policy(
        rules=[
            {
                "rule_id": "student_lock",
                "priority": 100,
                "target_type": "student",
                "target_id": str(student_user.id),
                "level": "locked",
                "reason": "Temporary assessment lock",
            }
        ]
    )

    saved = client.put(
        f"{BASE}/course/{course.id}/teaching-constraints",
        headers=_auth(teacher_token),
        json=_save_payload(policy),
    )
    read = client.get(
        f"{BASE}/course/{course.id}/teaching-constraints",
        headers=_auth(teacher_token),
    )
    preview = client.post(
        f"{BASE}/course/{course.id}/teaching-constraints/preview",
        headers=_auth(teacher_token),
        json={"student_id": student_user.id, "intent": "concept_question"},
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["active_version"]["version"] == 1
    assert read.status_code == 200, read.text
    assert read.json()["data"]["active_version"]["policy"]["baseline"]["level"] == "balanced"
    assert preview.status_code == 200, preview.text
    effective = preview.json()["data"]["effective"]
    assert effective["level"] == "locked"
    assert effective["matched_rule_ids"] == ["student_lock"]
    assert "question_generation" in effective["disabled_tools"]


def test_cross_course_group_rule_is_rejected(
    client,
    session,
    teacher_user,
    teacher_token,
):
    course = _course(session, teacher_user.id)
    other_course = _course(session, teacher_user.id)
    foreign_group = CourseGroup(
        course_id=other_course.id,
        name="Foreign group",
        created_by=teacher_user.id,
    )
    session.add(foreign_group)
    session.commit()
    session.refresh(foreign_group)
    policy = _policy(
        rules=[
            {
                "rule_id": "foreign_group",
                "priority": 10,
                "target_type": "group",
                "target_id": foreign_group.group_id,
                "level": "strict",
                "reason": "Must stay course scoped",
            }
        ]
    )

    response = client.put(
        f"{BASE}/course/{course.id}/teaching-constraints",
        headers=_auth(teacher_token),
        json=_save_payload(policy),
    )

    assert response.status_code == 422, response.text
    details = response.json()["data"]["details"]
    assert details["reason_code"] == "CONSTRAINT_GROUP_OUT_OF_SCOPE"


def test_stale_api_writer_gets_conflict_and_versions_remain_minimal(
    client,
    session,
    teacher_user,
    teacher_token,
):
    course = _course(session, teacher_user.id)
    url = f"{BASE}/course/{course.id}/teaching-constraints"
    first = client.put(
        url,
        headers=_auth(teacher_token),
        json=_save_payload(_policy("balanced")),
    )
    stale = client.put(
        url,
        headers=_auth(teacher_token),
        json=_save_payload(_policy("locked"), expected_version=0),
    )
    versions = client.get(
        f"{url}/versions",
        headers=_auth(teacher_token),
    )

    assert first.status_code == 200, first.text
    assert stale.status_code == 409, stale.text
    assert stale.json()["data"]["details"]["reason_code"] == "CONSTRAINT_VERSION_CONFLICT"
    assert versions.status_code == 200, versions.text
    item = versions.json()["data"]["items"][0]
    assert "policy" not in item
    assert not set(item).intersection({"prompt", "raw_message", "answer"})
