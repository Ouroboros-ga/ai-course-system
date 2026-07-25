"""Integration tests for the authenticated prerequisite-jump workflow.

The previous suite constructed unrelated in-memory rows and called protected
routes without a token.  It therefore exercised neither Course Access v1 nor
the course/node isolation required by the learner workflow.
"""
from __future__ import annotations

import uuid

import pytest
from sqlmodel import select

from app.models.course_model import Course, CourseScript, CourseStatus, ScriptNode, ScriptNodeType
from app.models.progress_model import LearningJumpHistory
from app.services.course_access_service import establish_course_access_baseline


@pytest.fixture
def jump_course(session, teacher_user):
    course = Course(
        fanya_course_id=f"jump-{uuid.uuid4().hex}",
        fanya_course_name="Jump test course",
        title="Jump test course",
        teacher_id=teacher_user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_user.id)

    script = CourseScript(course_id=course.id, script_content={"nodes": []}, created_by=teacher_user.id)
    session.add(script)
    session.commit()
    session.refresh(script)
    nodes = [
        ScriptNode(script_id=script.id, node_index=0, node_type=ScriptNodeType.LECTURE, title="Foundation", content="Foundation"),
        ScriptNode(script_id=script.id, node_index=1, node_type=ScriptNodeType.LECTURE, title="Application", content="Application"),
        ScriptNode(script_id=script.id, node_index=2, node_type=ScriptNodeType.LECTURE, title="Extension", content="Extension"),
    ]
    session.add_all(nodes)
    session.commit()
    for node in nodes:
        session.refresh(node)
    return course, nodes


@pytest.fixture
def enrolled_jump_course(client, student_token, jump_course):
    course, nodes = jump_course
    response = client.post(
        f"/api/v1/document/course/{course.id}/enroll",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert response.status_code == 200
    return course, nodes


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _jump_payload(course_id: int, source_id: int, target_id: int, **overrides):
    payload = {
        "courseId": course_id,
        "fromNodeId": source_id,
        "fromNodeTitle": "Application",
        "fromNodeIndex": 1,
        "toPrerequisiteId": target_id,
        "toNodeTitle": "Foundation",
        "toNodeIndex": 0,
        "triggerQuestion": "Why does this work?",
        "gapDescription": "Needs the foundation first.",
        "confidenceScore": 0.8,
        "urgencyLevel": "medium",
    }
    payload.update(overrides)
    return payload


def test_jump_requires_an_active_learner_membership(client, student_token, jump_course):
    course, nodes = jump_course
    response = client.post(
        "/api/v1/prerequisite/jump",
        headers=_headers(student_token),
        json=_jump_payload(course.id, nodes[1].id, nodes[0].id),
    )
    assert response.status_code == 403


def test_jump_and_return_are_scoped_to_the_current_learner(client, session, student_token, enrolled_jump_course):
    course, nodes = enrolled_jump_course
    created = client.post(
        "/api/v1/prerequisite/jump",
        headers=_headers(student_token),
        json=_jump_payload(course.id, nodes[1].id, nodes[0].id),
    )
    assert created.status_code == 200
    body = created.json()["data"]
    assert body["success"] is True
    assert body["jumpDepth"] == 1

    jump = session.get(LearningJumpHistory, body["jumpId"])
    assert jump is not None
    assert jump.course_id == course.id
    assert jump.session_id

    returned = client.post(
        "/api/v1/prerequisite/return",
        headers=_headers(student_token),
        json={"jumpId": jump.id, "reviewDurationSeconds": 120},
    )
    assert returned.status_code == 200
    assert returned.json()["data"]["originalNode"]["nodeId"] == nodes[1].id

    stack = client.get(
        f"/api/v1/prerequisite/jump-stack?courseId={course.id}",
        headers=_headers(student_token),
    )
    assert stack.status_code == 200
    assert stack.json()["data"]["unresolvedCount"] == 0


def test_nested_jump_rejects_foreign_parent_and_keeps_course_scope(client, student_token, enrolled_jump_course):
    course, nodes = enrolled_jump_course
    headers = _headers(student_token)
    first = client.post(
        "/api/v1/prerequisite/jump",
        headers=headers,
        json=_jump_payload(course.id, nodes[2].id, nodes[1].id),
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/prerequisite/jump",
        headers=headers,
        json=_jump_payload(
            course.id,
            nodes[1].id,
            nodes[0].id,
            parentJumpId=first.json()["data"]["jumpId"],
        ),
    )
    assert second.status_code == 200
    assert second.json()["data"]["jumpDepth"] == 2

    invalid_parent = client.post(
        "/api/v1/prerequisite/jump",
        headers=headers,
        json=_jump_payload(course.id, nodes[1].id, nodes[0].id, parentJumpId=999999),
    )
    assert invalid_parent.status_code == 404


def test_jump_rejects_a_node_from_another_course(client, session, student_token, enrolled_jump_course, teacher_user):
    course, nodes = enrolled_jump_course
    other_course = Course(
        fanya_course_id=f"foreign-node-{uuid.uuid4().hex}",
        fanya_course_name="Foreign course",
        title="Foreign course",
        teacher_id=teacher_user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(other_course)
    session.commit()
    session.refresh(other_course)
    establish_course_access_baseline(session, other_course.id, teacher_user.id)
    other_script = CourseScript(course_id=other_course.id, script_content={"nodes": []}, created_by=teacher_user.id)
    session.add(other_script)
    session.commit()
    session.refresh(other_script)
    foreign_node = ScriptNode(script_id=other_script.id, node_index=0, node_type=ScriptNodeType.LECTURE, title="Foreign", content="Foreign")
    session.add(foreign_node)
    session.commit()
    session.refresh(foreign_node)

    response = client.post(
        "/api/v1/prerequisite/jump",
        headers=_headers(student_token),
        json=_jump_payload(course.id, nodes[1].id, foreign_node.id),
    )
    assert response.status_code == 404


def test_direct_history_rows_receive_a_safe_session_identifier(session):
    record = LearningJumpHistory(user_id=1, course_id=1, from_node_id=2, to_node_id=1)
    session.add(record)
    session.commit()
    assert record.session_id.startswith("jump-")
