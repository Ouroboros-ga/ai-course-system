from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.api.v1.endpoints import course_build_editor
from app.core.security import get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    OutlineNodeType,
    PatchProposal,
    PatchProposalOperation,
    PatchProposalStatus,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.platform.agents.prep.incremental.dependencies import IncrementalPrepResult


def _setup_outline(session):
    token = uuid4().hex[:10]
    teacher = User(
        username=f"prep_batch_{token}",
        hashed_password=get_password_hash("pw"),
        role=UserRole.TEACHER,
    )
    session.add(teacher)
    session.commit()
    session.refresh(teacher)
    course = Course(
        fanya_course_id=f"prep-batch-{token}",
        fanya_course_name="Prep batch",
        title="Prep batch",
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
    first = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="旧标题一",
        order_index=0,
    )
    second = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="旧标题二",
        order_index=1,
    )
    locked = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="锁定标题",
        order_index=2,
        locked_by=teacher.id,
    )
    session.add(first)
    session.add(second)
    session.add(locked)
    session.commit()
    return teacher, course, first, second, locked


def _request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent_platform=None)))


def _payload():
    return course_build_editor.PrepAgentBatchRequest(action="organize_structure")


def _current_user(teacher):
    return {"user_id": teacher.id, "username": teacher.username, "role": "teacher"}


def _result(first, second):
    return IncrementalPrepResult(
        summary="批量完成",
        operations=[
            {
                "target": f"outline:{first.outline_node_id}:title",
                "after": "新标题一",
                "reason": "统一标题",
                "evidence_refs": [],
            },
            {
                "target": f"outline:{second.outline_node_id}:title",
                "after": "新标题二",
                "reason": "统一标题",
                "evidence_refs": [],
            },
        ],
        excluded_locked_targets=[],
        planner="llm_batched",
    )


def test_batch_endpoint_applies_every_planned_node_without_pending_approval(
    session,
    monkeypatch,
):
    teacher, course, first, second, locked = _setup_outline(session)

    async def fake_plan(**kwargs):
        return _result(first, second)

    monkeypatch.setattr(course_build_editor, "_plan_incremental_prep", fake_plan)

    response = asyncio.run(
        course_build_editor.run_prep_agent_batch_action(
            course.id,
            _payload(),
            _request(),
            session,
            _current_user(teacher),
        )
    )

    session.expire_all()
    assert session.get(CourseOutlineNode, first.id).title == "新标题一"
    assert session.get(CourseOutlineNode, second.id).title == "新标题二"
    assert session.get(CourseOutlineNode, locked.id).title == "锁定标题"
    proposal = session.exec(select(PatchProposal).where(
        PatchProposal.course_id == course.id
    )).one()
    operations = session.exec(select(PatchProposalOperation).where(
        PatchProposalOperation.proposal_id == proposal.proposal_id
    )).all()
    assert proposal.status == PatchProposalStatus.ACCEPTED
    assert all(operation.accepted is True for operation in operations)
    assert len(operations) == 2
    assert response["data"]["updated_count"] == 2
    assert not session.exec(select(PatchProposal).where(
        PatchProposal.course_id == course.id,
        PatchProposal.status == PatchProposalStatus.PENDING,
    )).all()


def test_batch_endpoint_rolls_back_when_one_planned_target_changed(
    session,
    monkeypatch,
):
    teacher, course, first, second, _ = _setup_outline(session)

    async def fake_plan(**kwargs):
        result = _result(first, second)
        second.locked_by = teacher.id
        session.add(second)
        session.flush()
        return result

    monkeypatch.setattr(course_build_editor, "_plan_incremental_prep", fake_plan)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            course_build_editor.run_prep_agent_batch_action(
                course.id,
                _payload(),
                _request(),
                session,
                _current_user(teacher),
            )
        )

    assert caught.value.status_code == 409
    session.expire_all()
    assert session.get(CourseOutlineNode, first.id).title == "旧标题一"
    assert session.get(CourseOutlineNode, second.id).title == "旧标题二"
    assert not session.exec(select(PatchProposal).where(
        PatchProposal.course_id == course.id
    )).all()


def test_batch_endpoint_rejects_overlapping_course_optimization(session):
    teacher, course, _, _, _ = _setup_outline(session)

    async def run():
        lock = await course_build_editor._try_acquire_prep_batch_lock(course.id)
        assert lock is not None
        try:
            with pytest.raises(HTTPException) as caught:
                await course_build_editor.run_prep_agent_batch_action(
                    course.id,
                    _payload(),
                    _request(),
                    session,
                    _current_user(teacher),
                )
        finally:
            lock.release()
        return caught.value

    error = asyncio.run(run())
    assert error.status_code == 409
    assert error.detail["error_code"] == "PREP_AGENT_BUSY"
