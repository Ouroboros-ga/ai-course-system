"""Lecture-script lock/unlock endpoint regression coverage."""
from __future__ import annotations

from uuid import uuid4

from app.core.security import create_access_token, get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    OutlineNodeType,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline


EDITOR_BASE = "/api/v1/course-editor"


def _auth(user: User) -> dict[str, str]:
    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })
    return {"Authorization": f"Bearer {token}"}


def test_teacher_can_unlock_a_locked_draft_script_node(client, session):
    teacher = User(
        username=f"script_unlock_{uuid4().hex[:10]}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(teacher)
    session.commit()
    session.refresh(teacher)

    course = Course(
        fanya_course_id=f"script-unlock-{uuid4().hex}",
        fanya_course_name="讲稿解锁回归课",
        title="讲稿解锁回归课",
        teacher_id=teacher.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher.id)

    outline = CourseOutlineVersion(
        course_id=course.id,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=teacher.id,
    )
    session.add(outline)
    session.flush()
    outline_node = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="可恢复编辑的讲稿",
        order_index=0,
    )
    session.add(outline_node)
    session.flush()
    script = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=teacher.id,
    )
    session.add(script)
    session.flush()
    script_node = TeachingScriptNode(
        course_id=course.id,
        script_version_id=script.script_version_id,
        outline_node_id=outline_node.outline_node_id,
        content="已锁定讲稿",
        locked_by=teacher.id,
    )
    session.add(script_node)
    session.commit()
    session.refresh(script_node)

    response = client.post(
        f"{EDITOR_BASE}/course/{course.id}/scripts/{script_node.script_node_id}/unlock",
        headers=_auth(teacher),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["locked"] is False
    assert response.json()["data"]["locked_by"] is None
    session.refresh(script_node)
    assert script_node.locked_by is None
    assert script_node.locked_at is None
