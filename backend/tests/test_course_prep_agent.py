"""P3: natural-language preparation proposals never include locked content."""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.core.security import get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import CourseOutlineNode, CourseOutlineVersion, OutlineLifecycleStatus, OutlineNodeType, TeachingScriptNode, TeachingScriptVersion
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.course_prep_agent_service import course_prep_agent_service


def test_agent_instruction_excludes_locked_node_and_returns_proposal_data(session):
    token = uuid4().hex[:10]
    teacher = User(username=f"p3_agent_{token}", hashed_password=get_password_hash("pw"), role=UserRole.TEACHER)
    session.add(teacher); session.commit(); session.refresh(teacher)
    course = Course(fanya_course_id=f"p3-{token}", fanya_course_name="P3", title="P3", teacher_id=teacher.id, status=CourseStatus.DRAFT)
    session.add(course); session.commit(); session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher.id)
    outline = CourseOutlineVersion(course_id=course.id, lifecycle_status=OutlineLifecycleStatus.DRAFT, created_by=teacher.id)
    session.add(outline); session.flush()
    locked = CourseOutlineNode(course_id=course.id, outline_version_id=outline.outline_version_id, node_type=OutlineNodeType.CHAPTER, title="第一章", order_index=0, locked_by=teacher.id)
    editable = CourseOutlineNode(course_id=course.id, outline_version_id=outline.outline_version_id, node_type=OutlineNodeType.CHAPTER, title="第二章", order_index=1)
    session.add(locked); session.add(editable); session.flush()
    script = TeachingScriptVersion(course_id=course.id, outline_version_id=outline.outline_version_id, lifecycle_status=OutlineLifecycleStatus.DRAFT, created_by=teacher.id)
    session.add(script); session.flush()
    session.add(TeachingScriptNode(course_id=course.id, script_version_id=script.script_version_id, outline_node_id=locked.outline_node_id, content="锁定讲稿", locked_by=teacher.id))
    session.add(TeachingScriptNode(course_id=course.id, script_version_id=script.script_version_id, outline_node_id=editable.outline_node_id, content="第二章讲稿"))
    session.commit()

    result = asyncio.run(course_prep_agent_service.plan(session, course_id=course.id, instruction="调整第二章的教学节奏"))

    assert result.planner == "deterministic_fallback"
    assert result.operations
    assert all(locked.outline_node_id not in item["target"] for item in result.operations)
    assert any(editable.outline_node_id in item["target"] for item in result.operations)
