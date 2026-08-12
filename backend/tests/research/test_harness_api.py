"""Public API contracts for the persisted ResearchAgent workspace."""
from __future__ import annotations

import uuid

from app.core.security import create_access_token, get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)


def _user(session, prefix: str, role: UserRole) -> User:
    user = User(
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        hashed_password=get_password_hash("test"),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, owner: User, member: User) -> Course:
    course = Course(
        fanya_course_id=f"harness-{uuid.uuid4().hex}",
        fanya_course_name="Research Harness",
        title="Research Harness",
        teacher_id=owner.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, owner.id)
    activate_student_membership(session, course.id, member.id)
    session.commit()
    return course


def _headers(user: User) -> dict[str, str]:
    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
    })
    return {"Authorization": f"Bearer {token}"}


def test_workspace_snapshot_and_todo_run_are_visible_without_prompt_leak(client, session):
    owner = _user(session, "harness_owner", UserRole.TEACHER)
    member = _user(session, "harness_member", UserRole.STUDENT)
    course = _course(session, owner, member)

    snapshot_response = client.get(
        f"/api/v1/research-agent/courses/{course.id}/workspace",
        headers=_headers(member),
    )
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()["data"]
    assert snapshot["workspace_id"].startswith("rws_")
    assert snapshot["active_scope_id"].startswith("rscope_")

    run_response = client.post(
        f"/api/v1/research-agent/courses/{course.id}/workspace/runs",
        json={
            "message": "创建待办：核验 RAG 论文",
            "action": "todo_create",
            "workspace_id": snapshot["workspace_id"],
            "payload": {"title": "核验 RAG 论文", "priority": 3},
        },
        headers=_headers(member),
    )

    assert run_response.status_code == 200
    data = run_response.json()["data"]
    assert data["status"] == "success"
    assert data["graph_route"] == "todo"
    assert data["selected_tools"] == ["todo_manager"]
    assert data["workspace"]["todos"][0]["title"] == "核验 RAG 论文"
    serialized = run_response.text
    assert "assembled_prompt" not in serialized
    assert '"trace"' not in serialized


def test_workspace_run_rejects_an_outsider_before_graph_execution(client, session):
    owner = _user(session, "harness_owner_denied", UserRole.TEACHER)
    member = _user(session, "harness_member_denied", UserRole.STUDENT)
    outsider = _user(session, "harness_outsider", UserRole.STUDENT)
    course = _course(session, owner, member)

    response = client.post(
        f"/api/v1/research-agent/courses/{course.id}/workspace/runs",
        json={"message": "创建待办", "action": "todo_create", "payload": {"title": "不应创建"}},
        headers=_headers(outsider),
    )

    assert response.status_code == 403


def test_capabilities_expose_harness_without_claiming_reproduction(client, session):
    owner = _user(session, "harness_cap_owner", UserRole.TEACHER)
    member = _user(session, "harness_cap_member", UserRole.STUDENT)
    course = _course(session, owner, member)

    response = client.get(
        f"/api/v1/research-agent/courses/{course.id}/capabilities",
        headers=_headers(member),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    stages = {item["key"]: item["status"] for item in data["stages"]}
    assert stages["research_harness"] == "available"
    assert stages["code_reproduction"] != "available"

