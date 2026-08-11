from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.api.v1.endpoints import course_build_editor, course_outline
from app.core.security import get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_build_model import MaterialStatus, SourceMaterial, SourceMaterialVersion
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    CoursePptMapping,
    OutlineLifecycleStatus,
    OutlineNodeType,
    PatchOperation,
    PatchProposal,
    PatchProposalOperation,
    PatchProposalStatus,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.document_parse_model import DocumentBlock
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.platform.agents.prep.incremental.dependencies import IncrementalPrepResult
from app.platform.agents.prep.actions import PrepAction, PrepIntent


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


def _add_draft_script(session, course, outline_node, teacher):
    version = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=outline_node.outline_version_id,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=teacher.id,
    )
    session.add(version)
    session.flush()
    script = TeachingScriptNode(
        script_version_id=version.script_version_id,
        course_id=course.id,
        outline_node_id=outline_node.outline_node_id,
        content="原始讲稿内容",
        style="beginner",
    )
    session.add(script)
    session.commit()
    return script


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
    summary = response["data"]["change_summary"]
    assert summary["state"] == "applied"
    assert summary["count"] == 2
    assert {item["resource"] for item in summary["items"]} == {"outline"}
    assert all(item["node_title"].startswith("新标题") for item in summary["items"])
    assert "outline:" not in json.dumps(summary, ensure_ascii=False)
    assert not session.exec(select(PatchProposal).where(
        PatchProposal.course_id == course.id,
        PatchProposal.status == PatchProposalStatus.PENDING,
    )).all()


def test_single_node_title_command_stays_pending_until_accepted_and_exposes_safe_display(
    session,
    monkeypatch,
):
    teacher, course, first, _, _ = _setup_outline(session)

    async def fake_plan(**kwargs):
        assert kwargs["action"] == "optimize_node_title"
        return IncrementalPrepResult(
            summary="建议优化当前标题",
            operations=[{
                "target": f"outline:{first.outline_node_id}:title",
                "after": "优化后的标题",
                "reason": "标题更清晰",
                "evidence_refs": [],
            }],
            planner="llm_single_node",
        )

    monkeypatch.setattr(course_build_editor, "_plan_incremental_prep", fake_plan)
    response = asyncio.run(course_build_editor.run_prep_agent_command(
        course.id,
        course_build_editor.PrepAgentCommandRequest(
            instruction="请优化当前节点标题",
            outline_node_id=first.outline_node_id,
            action="optimize_node_title",
        ),
        _request(),
        session,
        _current_user(teacher),
    ))

    proposal_id = response["data"]["proposal_id"]
    summary = response["data"]["change_summary"]
    assert response["data"]["status"] == PatchProposalStatus.PENDING.value
    assert summary["state"] == "pending_review"
    assert summary["items"] == [{
        "resource": "outline",
        "resource_label": "课程节点",
        "field": "title",
        "field_label": "标题",
        "node_title": "旧标题一",
        "label": "课程节点《旧标题一》的标题",
    }]
    assert "outline:" not in json.dumps(summary, ensure_ascii=False)
    operation = session.exec(select(PatchProposalOperation).where(
        PatchProposalOperation.proposal_id == proposal_id,
    )).one()
    assert operation.target == f"outline:{first.outline_node_id}:title"
    session.expire_all()
    assert session.get(CourseOutlineNode, first.id).title == "旧标题一"

    listed = asyncio.run(course_build_editor.list_proposals(
        course.id,
        PatchProposalStatus.PENDING,
        session,
        _current_user(teacher),
    ))
    listed_operation = listed["data"]["items"][0]["operations"][0]
    assert listed_operation["target"] == operation.target
    assert listed_operation["display"]["label"] == "课程节点《旧标题一》的标题"
    assert "outline:" not in json.dumps(listed["data"]["items"][0]["change_summary"], ensure_ascii=False)

    decision = asyncio.run(course_build_editor.decide_proposal(
        course.id,
        proposal_id,
        course_build_editor.ProposalDecision(accepted=True),
        session,
        _current_user(teacher),
    ))
    assert decision["data"]["status"] == PatchProposalStatus.ACCEPTED.value
    assert decision["data"]["change_summary"]["state"] == "applied"
    session.expire_all()
    assert session.get(CourseOutlineNode, first.id).title == "优化后的标题"


def test_single_node_script_rejection_keeps_draft_unchanged(session, monkeypatch):
    teacher, course, first, _, _ = _setup_outline(session)
    script = _add_draft_script(session, course, first, teacher)

    async def fake_plan(**kwargs):
        assert kwargs["action"] == "optimize_node_script"
        return IncrementalPrepResult(
            summary="建议优化当前讲稿",
            operations=[{
                "target": f"script:{script.script_node_id}:content",
                "after": "优化后的讲稿内容",
                "reason": "表达更适合初学者",
                "evidence_refs": [],
            }],
            planner="llm_single_node",
        )

    monkeypatch.setattr(course_build_editor, "_plan_incremental_prep", fake_plan)
    response = asyncio.run(course_build_editor.run_prep_agent_command(
        course.id,
        course_build_editor.PrepAgentCommandRequest(
            instruction="请优化当前讲解脚本",
            outline_node_id=first.outline_node_id,
            action="optimize_node_script",
        ),
        _request(),
        session,
        _current_user(teacher),
    ))

    proposal_id = response["data"]["proposal_id"]
    summary = response["data"]["change_summary"]
    assert summary["state"] == "pending_review"
    assert summary["items"][0]["label"] == "讲解脚本《旧标题一》的讲稿内容"
    assert "script:" not in json.dumps(summary, ensure_ascii=False)
    session.expire_all()
    assert session.get(TeachingScriptNode, script.id).content == "原始讲稿内容"

    decision = asyncio.run(course_build_editor.decide_proposal(
        course.id,
        proposal_id,
        course_build_editor.ProposalDecision(accepted=False),
        session,
        _current_user(teacher),
    ))
    assert decision["data"]["status"] == PatchProposalStatus.REJECTED.value
    assert decision["data"]["change_summary"]["state"] == "rejected"
    session.expire_all()
    assert session.get(TeachingScriptNode, script.id).content == "原始讲稿内容"


def test_legacy_proposal_payload_also_uses_display_without_hiding_raw_audit_target(session):
    teacher, course, first, _, _ = _setup_outline(session)
    proposal = PatchProposal(
        course_id=course.id,
        tool_name="LegacyProposalTool",
        policy_version="legacy/1",
        reason="旧入口兼容测试",
        created_by=teacher.id,
    )
    session.add(proposal)
    session.flush()
    operation = PatchProposalOperation(
        proposal_id=proposal.proposal_id,
        course_id=course.id,
        operation=PatchOperation.REPLACE,
        target=f"outline:{first.outline_node_id}:title",
        before="旧标题一",
        after="新标题一",
        reason="统一标题",
        evidence_refs=[],
        policy_version="legacy/1",
    )
    session.add(operation)
    session.commit()

    payload = course_outline._proposal_payload(session, proposal, [operation])

    assert payload["change_summary"]["state"] == "pending_review"
    assert payload["operations"][0]["target"] == operation.target
    assert payload["operations"][0]["display"]["label"] == "课程节点《旧标题一》的标题"
    assert "outline:" not in json.dumps(payload["change_summary"], ensure_ascii=False)


def test_natural_language_one_click_command_reuses_the_atomic_batch_action(
    session,
    monkeypatch,
):
    teacher, course, first, second, _ = _setup_outline(session)

    async def fake_plan(**kwargs):
        assert kwargs["action"] == "organize_structure"
        assert "一键" in kwargs["instruction"]
        return _result(first, second)

    async def fake_classify(*args, **kwargs):
        assert kwargs["instruction"].startswith("请一键")
        return PrepIntent(
            action=PrepAction.ORGANIZE_STRUCTURE,
            instruction=kwargs["instruction"],
            apply_immediately=True,
        )

    monkeypatch.setattr(course_build_editor, "_plan_incremental_prep", fake_plan)
    from app.services.course_prep_agent_service import course_prep_agent_service
    monkeypatch.setattr(course_prep_agent_service, "classify_intent", fake_classify)

    response = asyncio.run(course_build_editor.run_prep_agent_command(
        course.id,
        course_build_editor.PrepAgentCommandRequest(
            instruction="请一键整理整个课程结构，并保留锁定节点。",
        ),
        _request(),
        session,
        _current_user(teacher),
    ))

    session.expire_all()
    assert response["data"]["action"] == "organize_structure"
    assert response["data"]["status"] == PatchProposalStatus.ACCEPTED.value
    assert session.get(CourseOutlineNode, first.id).title == "新标题一"
    assert session.get(CourseOutlineNode, second.id).title == "新标题二"
    assert not session.exec(select(PatchProposal).where(
        PatchProposal.course_id == course.id,
        PatchProposal.status == PatchProposalStatus.PENDING,
    )).all()


def test_explicit_button_action_bypasses_the_intent_classifier(session, monkeypatch):
    teacher, course, first, _, _ = _setup_outline(session)

    async def fail_classify(*args, **kwargs):
        raise AssertionError("explicit button action must not classify")

    async def fake_plan(**kwargs):
        assert kwargs["action"] == "optimize_node_title"
        return IncrementalPrepResult(
            summary="标题提案",
            operations=[{
                "target": f"outline:{first.outline_node_id}:title",
                "after": "按钮生成的新标题",
                "reason": "更清晰",
                "evidence_refs": [],
            }],
            planner="llm_single_node",
        )

    monkeypatch.setattr(course_build_editor, "_plan_incremental_prep", fake_plan)
    from app.services.course_prep_agent_service import course_prep_agent_service
    monkeypatch.setattr(course_prep_agent_service, "classify_intent", fail_classify)
    response = asyncio.run(course_build_editor.run_prep_agent_command(
        course.id,
        course_build_editor.PrepAgentCommandRequest(
            instruction="按钮发送的自然语言说明",
            outline_node_id=first.outline_node_id,
            action="optimize_node_title",
        ),
        _request(),
        session,
        _current_user(teacher),
    ))

    assert response["data"]["status"] == PatchProposalStatus.PENDING.value


def test_ambiguous_free_text_returns_clarification_without_planning(session, monkeypatch):
    teacher, course, _, _, _ = _setup_outline(session)

    async def fake_classify(*args, **kwargs):
        return PrepIntent(
            action=None,
            instruction=kwargs["instruction"],
            needs_clarification=True,
            clarification="请说明是整理结构还是优化讲解。",
        )

    async def fail_plan(**kwargs):
        raise AssertionError("ambiguous text must not enter planning")

    monkeypatch.setattr(course_build_editor, "_plan_incremental_prep", fail_plan)
    from app.services.course_prep_agent_service import course_prep_agent_service
    monkeypatch.setattr(course_prep_agent_service, "classify_intent", fake_classify)
    response = asyncio.run(course_build_editor.run_prep_agent_command(
        course.id,
        course_build_editor.PrepAgentCommandRequest(instruction="帮我处理一下"),
        _request(),
        session,
        _current_user(teacher),
    ))

    assert response["data"] == {
        "outcome": "needs_clarification",
        "clarification": "请说明是整理结构还是优化讲解。",
    }


def test_intent_router_unavailable_fails_closed_without_keyword_fallback(session, monkeypatch):
    teacher, course, _, _, _ = _setup_outline(session)

    async def unavailable(*args, **kwargs):
        from app.services.course_prep_agent_service import CoursePrepAgentIntentRoutingError
        raise CoursePrepAgentIntentRoutingError("router unavailable")

    async def fail_plan(**kwargs):
        raise AssertionError("unavailable router must not enter planning")

    monkeypatch.setattr(course_build_editor, "_plan_incremental_prep", fail_plan)
    from app.services.course_prep_agent_service import course_prep_agent_service
    monkeypatch.setattr(course_prep_agent_service, "classify_intent", unavailable)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(course_build_editor.run_prep_agent_command(
            course.id,
            course_build_editor.PrepAgentCommandRequest(
                instruction="请整理课程结构",
            ),
            _request(),
            session,
            _current_user(teacher),
        ))

    assert caught.value.status_code == 503
    assert caught.value.detail["error_code"] == "PREP_AGENT_INTENT_UNAVAILABLE"


def test_structure_batch_applies_move_and_remove_as_one_atomic_tree_change(session, monkeypatch):
    teacher, course, parent, child, _ = _setup_outline(session)
    child.parent_node_id = parent.outline_node_id
    child.order_index = 0
    draft_scripts = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=parent.outline_version_id,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=teacher.id,
    )
    historical_scripts = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=parent.outline_version_id,
        lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
        created_by=teacher.id,
    )
    session.add(draft_scripts)
    session.add(historical_scripts)
    session.flush()
    draft_script = TeachingScriptNode(
        script_version_id=draft_scripts.script_version_id,
        course_id=course.id,
        outline_node_id=parent.outline_node_id,
        content="current draft script",
    )
    historical_script = TeachingScriptNode(
        script_version_id=historical_scripts.script_version_id,
        course_id=course.id,
        outline_node_id=parent.outline_node_id,
        content="published historical script",
    )
    session.add(draft_script)
    session.add(historical_script)
    session.add(child)
    session.commit()

    async def fake_plan(**_kwargs):
        return IncrementalPrepResult(
            summary="移除冗余父节点",
            operations=[
                {
                    "operation": "move",
                    "target": f"outline:{child.outline_node_id}:structure",
                    "after": '{"parent_node_id": null, "order_index": 0}',
                    "reason": "子节点直接作为顶层知识点",
                    "evidence_refs": [],
                },
                {
                    "operation": "remove",
                    "target": f"outline:{parent.outline_node_id}:structure",
                    "after": "",
                    "reason": "父节点没有独立教学内容",
                    "evidence_refs": [],
                },
            ],
            planner="llm_structure",
        )

    monkeypatch.setattr(course_build_editor, "_plan_incremental_prep", fake_plan)
    response = asyncio.run(course_build_editor.run_prep_agent_batch_action(
        course.id,
        _payload(),
        _request(),
        session,
        _current_user(teacher),
    ))

    session.expire_all()
    assert session.get(CourseOutlineNode, parent.id) is None
    moved_child = session.get(CourseOutlineNode, child.id)
    assert moved_child is not None
    assert moved_child.parent_node_id is None
    assert moved_child.order_index == 0
    assert session.get(TeachingScriptNode, draft_script.id) is None
    assert session.get(TeachingScriptNode, historical_script.id) is not None
    assert response["data"]["updated_count"] == 2


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


def test_ppt_mapping_endpoint_allows_unprojected_version_for_manifest_ocr(session):
    """A pending material version may still be mapped through ppt-manifest/OCR."""
    teacher, course, _, _, _ = _setup_outline(session)
    material = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_manifest_ready",
        status=MaterialStatus.PARSING,
        name="courseware.pptx",
    )
    version = SourceMaterialVersion(
        version_id="smv_manifest_ready",
        course_id=course.id,
        material_id=material.material_id,
        parse_status=MaterialStatus.PARSING,
        is_current=True,
    )
    session.add(material)
    session.add(version)
    session.commit()

    class FakeGateway:
        async def start(self, **kwargs):
            assert kwargs["context"].extras["material_version_ids"] == [version.version_id]
            return SimpleNamespace(
                status="completed",
                result={"result": {
                    "total_mappings": 0,
                    "updated_count": 2,
                    "suggestions": [],
                    "material_version_ids": [version.version_id],
                }},
                error_code=None,
                error_message="",
            )

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            agent_platform=SimpleNamespace(gateway=FakeGateway()),
        )),
    )
    response = asyncio.run(course_build_editor.optimize_ppt_mapping(
        course.id,
        request,
        session,
        _current_user(teacher),
    ))

    assert response["data"]["updated_count"] == 2
    assert response["data"]["material_version_ids"] == [version.version_id]


def test_ppt_mapping_endpoint_returns_manual_recovery_for_zero_change_run(session):
    """No model match is actionable, but it is not a broken mapping workflow."""
    teacher, course, _, _, _ = _setup_outline(session)
    material = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_no_change",
        name="no-change.pptx",
    )
    version = SourceMaterialVersion(
        version_id="smv_no_change",
        course_id=course.id,
        material_id=material.material_id,
        parse_status=MaterialStatus.NEEDS_REVIEW,
        is_current=True,
    )
    session.add(material)
    session.add(version)
    session.commit()

    class FakeGateway:
        async def start(self, **_kwargs):
            return SimpleNamespace(
                status="completed",
                result={"result": {
                    "total_mappings": 0,
                    "updated_count": 0,
                    "suggestions": [],
                    "material_version_ids": [version.version_id],
                }},
                error_code=None,
                error_message="",
            )

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            agent_platform=SimpleNamespace(gateway=FakeGateway()),
        )),
    )

    response = asyncio.run(course_build_editor.optimize_ppt_mapping(
        course.id,
        request,
        session,
        _current_user(teacher),
    ))

    assert response["data"]["outcome"] == "no_change"
    assert response["data"]["reason"] == "NO_RELIABLE_MATCH"
    assert response["data"]["manual_next_steps"] == ["select_pages", "match_current_node"]
    assert response["data"]["material_version_ids"] == [version.version_id]


def test_ppt_mapping_workbench_bulk_save_preserves_non_contiguous_teacher_pages(session):
    """The visual editor saves one explicit teacher mapping, not blur events."""
    teacher, course, first_node, _, _ = _setup_outline(session)
    material = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_manual_pages",
        name="manual-pages.pptx",
    )
    version = SourceMaterialVersion(
        version_id="smv_manual_pages",
        course_id=course.id,
        material_id=material.material_id,
        parse_status=MaterialStatus.NEEDS_REVIEW,
        is_current=True,
    )
    session.add(material)
    session.add(version)
    for page in (1, 2, 3):
        session.add(DocumentBlock(
            course_id=course.id,
            material_version_id=version.version_id,
            run_id=f"run_manual_{page}",
            block_id=f"blk_manual_{page}",
            page_or_slide=page,
            text=f"PPT page {page}",
        ))
    session.commit()

    response = asyncio.run(course_build_editor.save_ppt_mappings(
        course.id,
        course_build_editor.PptMappingBulkUpdate(mappings=[
            course_build_editor.PptMappingBulkItem(
                outline_node_id=first_node.outline_node_id,
                material_version_id=version.version_id,
                page_refs=[3, 1],
                locked=True,
            ),
        ]),
        session,
        _current_user(teacher),
    ))

    mapping = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course.id,
        CoursePptMapping.outline_node_id == first_node.outline_node_id,
        CoursePptMapping.material_version_id == version.version_id,
    )).one()
    assert response["data"]["saved_count"] == 1
    assert mapping.page_refs == [1, 3]
    assert mapping.page_start == 1
    assert mapping.page_end == 3
    assert mapping.teacher_locked is True


def test_selected_page_matching_scopes_agent_to_visible_pages(session):
    teacher, course, first_node, _, _ = _setup_outline(session)
    material = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_selected_page",
        name="selected-page.pptx",
    )
    version = SourceMaterialVersion(
        version_id="smv_selected_page",
        course_id=course.id,
        material_id=material.material_id,
        parse_status=MaterialStatus.NEEDS_REVIEW,
        is_current=True,
    )
    session.add(material)
    session.add(version)
    session.add(DocumentBlock(
        course_id=course.id,
        material_version_id=version.version_id,
        run_id="run_selected_page",
        block_id="blk_selected_page",
        page_or_slide=3,
        text="selected page OCR",
    ))
    session.commit()

    class FakeGateway:
        async def start(self, **kwargs):
            extras = kwargs["context"].extras
            assert extras["material_version_ids"] == [version.version_id]
            assert extras["page_refs_by_material"] == {version.version_id: [3]}
            assert extras["seed_from_evidence"] is False
            return SimpleNamespace(
                status="completed",
                result={"result": {"updated_count": 0, "suggestions": []}},
                error_code=None,
                error_message="",
            )

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        agent_platform=SimpleNamespace(gateway=FakeGateway()),
    )))
    response = asyncio.run(course_build_editor.match_ppt_mapping_scope(
        course.id,
        course_build_editor.PptMappingMatchRequest(
            mode="selected_pages",
            material_version_id=version.version_id,
            page_refs=[3],
        ),
        request,
        session,
        _current_user(teacher),
    ))
    assert response["data"]["outcome"] == "no_reliable_match"


def test_ppt_mapping_endpoint_sends_all_current_ppt_versions_to_runtime(session):
    """One-click mapping must not select only the most recently uploaded deck."""
    teacher, course, _, _, _ = _setup_outline(session)
    first = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_deck_one",
        name="deck-one.pptx",
    )
    second = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_deck_two",
        name="deck-two.pptx",
    )
    session.add(first)
    session.add(second)
    session.add(SourceMaterialVersion(
        version_id="smv_deck_one",
        course_id=course.id,
        material_id=first.material_id,
        parse_status=MaterialStatus.NEEDS_REVIEW,
        is_current=True,
    ))
    session.add(SourceMaterialVersion(
        version_id="smv_deck_two",
        course_id=course.id,
        material_id=second.material_id,
        parse_status=MaterialStatus.NEEDS_REVIEW,
        is_current=True,
    ))
    session.commit()

    class FakeGateway:
        async def start(self, **kwargs):
            assert kwargs["context"].extras["material_version_ids"] == [
                "smv_deck_one",
                "smv_deck_two",
            ]
            return SimpleNamespace(
                status="completed",
                result={"result": {
                    "total_mappings": 0,
                    "updated_count": 4,
                    "suggestions": [],
                    "material_version_ids": ["smv_deck_one", "smv_deck_two"],
                }},
                error_code=None,
                error_message="",
            )

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            agent_platform=SimpleNamespace(gateway=FakeGateway()),
        )),
    )
    response = asyncio.run(course_build_editor.optimize_ppt_mapping(
        course.id,
        request,
        session,
        _current_user(teacher),
    ))

    assert response["data"]["updated_count"] == 4
    assert response["data"]["material_version_ids"] == ["smv_deck_one", "smv_deck_two"]


def test_ppt_mapping_state_keeps_page_ranges_bound_to_each_ppt_file(session):
    """The mapping screen receives one input per node per current deck."""
    teacher, course, first_node, _, _ = _setup_outline(session)
    first = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_display_one",
        name="deck-one.pptx",
    )
    second = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_display_two",
        name="deck-two.pptx",
    )
    session.add(first)
    session.add(second)
    session.add(SourceMaterialVersion(
        version_id="smv_display_one",
        course_id=course.id,
        material_id=first.material_id,
        parse_status=MaterialStatus.NEEDS_REVIEW,
        is_current=True,
    ))
    session.add(SourceMaterialVersion(
        version_id="smv_display_two",
        course_id=course.id,
        material_id=second.material_id,
        parse_status=MaterialStatus.NEEDS_REVIEW,
        is_current=True,
    ))
    session.add(DocumentBlock(
        course_id=course.id,
        material_version_id="smv_display_one",
        run_id="run_display_one",
        block_id="display_one_page_3",
        block_type="TEXT",
        page_or_slide=3,
        text="first deck",
    ))
    session.add(DocumentBlock(
        course_id=course.id,
        material_version_id="smv_display_two",
        run_id="run_display_two",
        block_id="display_two_page_8",
        block_type="TEXT",
        page_or_slide=8,
        text="second deck",
    ))
    session.add(CoursePptMapping(
        course_id=course.id,
        outline_node_id=first_node.outline_node_id,
        material_version_id="smv_display_one",
        page_start=2,
        page_end=3,
        page_refs=[2, 3],
        status="draft",
    ))
    session.add(CoursePptMapping(
        course_id=course.id,
        outline_node_id=first_node.outline_node_id,
        material_version_id="smv_display_two",
        page_start=8,
        page_end=8,
        page_refs=[8],
        status="draft",
    ))
    session.commit()

    response = asyncio.run(course_build_editor.get_ppt_mapping(
        course.id,
        session,
        _current_user(teacher),
    ))
    data = response["data"]
    assert data["mapping_contract_version"] == "ppt-mapping/v2"
    assert [item["material_version_id"] for item in data["ppt_materials"]] == [
        "smv_display_one",
        "smv_display_two",
    ]
    assert [item["page_count"] for item in data["ppt_materials"]] == [3, 8]
    node = next(item for item in data["nodes"] if item["outline_node_id"] == first_node.outline_node_id)
    assert {
        item["material_version_id"]: item["page_range"]
        for item in node["ppt_mappings"]
    } == {
        "smv_display_one": "2-3",
        "smv_display_two": "8",
    }


def test_ppt_mapping_state_collapses_legacy_duplicate_decks(session):
    """Same bytes uploaded before idempotency remain one logical PPT deck."""
    teacher, course, _first_node, _, _ = _setup_outline(session)
    original = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_original",
        name="engine.pptx",
    )
    duplicate = SourceMaterial(
        course_id=course.id,
        material_type="slide",
        current_version_id="smv_duplicate",
        name="engine-copy.pptx",
    )
    session.add(original)
    session.add(duplicate)
    session.add(SourceMaterialVersion(
        version_id="smv_original",
        course_id=course.id,
        material_id=original.material_id,
        file_hash="identical-ppt-bytes",
        parse_status=MaterialStatus.NEEDS_REVIEW,
        is_current=True,
    ))
    session.add(SourceMaterialVersion(
        version_id="smv_duplicate",
        course_id=course.id,
        material_id=duplicate.material_id,
        file_hash="identical-ppt-bytes",
        parse_status=MaterialStatus.NEEDS_REVIEW,
        is_current=True,
    ))
    session.commit()

    response = asyncio.run(course_build_editor.get_ppt_mapping(
        course.id,
        session,
        _current_user(teacher),
    ))

    assert [item["material_version_id"] for item in response["data"]["ppt_materials"]] == [
        "smv_original",
    ]
