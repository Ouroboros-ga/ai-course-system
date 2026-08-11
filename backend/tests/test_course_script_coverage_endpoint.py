"""Teacher recovery path for initial-script coverage issues."""
from __future__ import annotations

from uuid import uuid4

from app.core.security import create_access_token, get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    CourseScriptCoverageIssue,
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
        'sub': str(user.id),
        'username': user.username,
        'role': user.role.value,
        'school_id': user.school_id or 'test-school',
    })
    return {"Authorization": f"Bearer {token}"}


def _course_owner(session) -> tuple[Course, User]:
    token = uuid4().hex[:10]
    owner = User(
        username=f"coverage_editor_{token}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(owner)
    session.flush()
    course = Course(
        fanya_course_id=f"coverage-editor-{token}",
        fanya_course_name="Coverage editor",
        title="Coverage editor",
        teacher_id=owner.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.flush()
    establish_course_access_baseline(session, course.id, owner.id)
    return course, owner


def _script_draft(session, *, course: Course, owner: User):
    outline = CourseOutlineVersion(
        course_id=course.id,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=owner.id,
    )
    session.add(outline)
    session.flush()
    script_version = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=owner.id,
    )
    session.add(script_version)
    session.flush()
    return outline, script_version


def test_teacher_can_fill_coverage_issue_and_close_it(client, session):
    course, owner = _course_owner(session)
    outline, script_version = _script_draft(session, course=course, owner=owner)
    filled = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="Already covered",
        order_index=0,
        source_block_refs=["block-covered"],
    )
    missing = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="Needs teacher script",
        order_index=1,
        source_block_refs=["block-a", "block-b"],
    )
    session.add(filled)
    session.add(missing)
    session.flush()
    session.add(TeachingScriptNode(
        course_id=course.id,
        script_version_id=script_version.script_version_id,
        outline_node_id=filled.outline_node_id,
        content="Existing valid script.",
        source_block_refs=["block-covered"],
    ))
    issue = CourseScriptCoverageIssue(
        course_id=course.id,
        build_task_id="cdbt_test",
        script_version_id=script_version.script_version_id,
        outline_node_id=missing.outline_node_id,
        issue_code="EVIDENCE_VERIFICATION_FAILED",
    )
    session.add(issue)
    session.commit()

    before = client.get(f"{EDITOR_BASE}/course/{course.id}/scripts", headers=_auth(owner))
    assert before.status_code == 200, before.text
    assert before.json()["data"]["coverage_issues"] == [{
        "issue_id": issue.issue_id,
        "outline_node_id": missing.outline_node_id,
        "code": "EVIDENCE_VERIFICATION_FAILED",
        "status": "open",
        "created_at": issue.created_at.isoformat(),
    }]

    created = client.post(
        f"{EDITOR_BASE}/course/{course.id}/scripts",
        headers=_auth(owner),
        json={
            "outline_node_id": missing.outline_node_id,
            "content": "Teacher-authored, evidence-grounded lecture script.",
            "style": "beginner",
        },
    )
    # ``unified_response`` preserves the product-level status in its envelope.
    # Existing course-editor callers consume that code while the HTTP transport
    # remains 200 for successful mutations.
    assert created.status_code == 200, created.text
    assert created.json()["code"] == 201
    assert created.json()["data"]["source_block_refs"] == ["block-a", "block-b"]
    session.refresh(issue)
    assert issue.status == "resolved"
    assert issue.resolved_by == owner.id
    assert issue.resolved_at is not None

    after = client.get(f"{EDITOR_BASE}/course/{course.id}/scripts", headers=_auth(owner))
    assert after.status_code == 200, after.text
    assert after.json()["data"]["coverage_issues"] == []
    duplicate = client.post(
        f"{EDITOR_BASE}/course/{course.id}/scripts",
        headers=_auth(owner),
        json={"outline_node_id": missing.outline_node_id, "content": "Duplicate."},
    )
    assert duplicate.status_code == 409


def test_script_coverage_creation_rejects_locked_foreign_and_unauthorized_nodes(client, session):
    course, owner = _course_owner(session)
    outline, script_version = _script_draft(session, course=course, owner=owner)
    locked = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="Locked knowledge point",
        order_index=0,
        locked_by=owner.id,
    )
    session.add(locked)
    other_course, _ = _course_owner(session)
    other_outline, _ = _script_draft(session, course=other_course, owner=owner)
    foreign = CourseOutlineNode(
        course_id=other_course.id,
        outline_version_id=other_outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="Foreign knowledge point",
        order_index=0,
    )
    outsider = User(
        username=f"coverage_outsider_{uuid4().hex[:10]}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(foreign)
    session.add(outsider)
    session.commit()

    locked_response = client.post(
        f"{EDITOR_BASE}/course/{course.id}/scripts",
        headers=_auth(owner),
        json={"outline_node_id": locked.outline_node_id, "content": "Not allowed."},
    )
    assert locked_response.status_code == 409
    foreign_response = client.post(
        f"{EDITOR_BASE}/course/{course.id}/scripts",
        headers=_auth(owner),
        json={"outline_node_id": foreign.outline_node_id, "content": "Not allowed."},
    )
    assert foreign_response.status_code == 422
    unauthorized = client.post(
        f"{EDITOR_BASE}/course/{course.id}/scripts",
        headers=_auth(outsider),
        json={"outline_node_id": locked.outline_node_id, "content": "Not allowed."},
    )
    assert unauthorized.status_code == 403
