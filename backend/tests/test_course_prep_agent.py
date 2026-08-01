"""P3: natural-language preparation proposals never include locked content."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.security import get_password_hash
from app.core.config import settings
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import CourseOutlineNode, CourseOutlineVersion, OutlineLifecycleStatus, OutlineNodeType, TeachingScriptNode, TeachingScriptVersion
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.course_prep_agent_service import AgentPlan, CoursePrepAgentPlanningError, CoursePrepAgentService, course_prep_agent_service
from app.platform.agents.prep.actions import PrepAction


def test_agent_instruction_excludes_locked_node_and_returns_proposal_data(session, monkeypatch):
    monkeypatch.setattr(course_prep_agent_service, "_llm_is_configured", lambda: False)
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


def test_flywheel_title_and_coverage_request_returns_canonical_title(session, monkeypatch):
    """The offline-safe path should preserve the requested flywheel title proposal."""
    monkeypatch.setattr(course_prep_agent_service, "_llm_is_configured", lambda: False)
    token = uuid4().hex[:10]
    teacher = User(
        username=f"p3_flywheel_{token}",
        hashed_password=get_password_hash("pw"),
        role=UserRole.TEACHER,
    )
    session.add(teacher)
    session.commit()
    session.refresh(teacher)
    course = Course(
        fanya_course_id=f"p3-flywheel-{token}",
        fanya_course_name="飞轮标题提案",
        title="飞轮标题提案",
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
    node = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="飞轮",
        order_index=0,
    )
    session.add(node)
    session.flush()
    script_version = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=teacher.id,
    )
    session.add(script_version)
    session.flush()
    session.add(TeachingScriptNode(
        course_id=course.id,
        script_version_id=script_version.script_version_id,
        outline_node_id=node.outline_node_id,
        content=(
            "飞轮是一个转动惯量很大的金属圆盘。其主要作用是贮存做功行程的一部分能量，保证发动机运转平稳；"
            "此外，飞轮又是传动系中摩擦离合器的主动盘，或自动变速器中液力变矩器的驱动盘。"
            "飞轮的形状见图2-43，其外缘上镶有齿圈。发动机起动时，起动机的小齿轮与飞轮的齿圈相啮合，"
            "保证发动机顺利起动。飞轮上通常刻有第一缸点火正时记号，以便调整和检查点火（喷油）正时和气门间隙。"
        ),
    ))
    session.commit()

    result = asyncio.run(course_prep_agent_service.plan(
        session,
        course_id=course.id,
        outline_node_id=node.outline_node_id,
        instruction=(
            "请针对课程节点飞轮，改进其标题表述和知识覆盖。"
        ),
    ))

    title_operation = next(item for item in result.operations if item["target"].endswith(":title"))
    assert title_operation["after"] == "发动机飞轮的作用、结构与正时标记"
    assert any(item["target"].endswith(":content") for item in result.operations)

    class WrongTitlePlanner:
        async def plan_incremental(self, payload):
            return AgentPlan.model_validate({
                "summary": "模型给出了一个过于笼统的标题",
                "operations": [{
                    "target_kind": "outline",
                    "target_id": payload["editable_outline"][0]["id"],
                    "field": "title",
                    "after": "飞轮优化建议",
                    "reason": "模型草拟标题",
                    "evidence_refs": [],
                }],
            })

    guarded_result = asyncio.run(CoursePrepAgentService(llm=WrongTitlePlanner()).plan(
        session,
        course_id=course.id,
        outline_node_id=node.outline_node_id,
        instruction="请针对课程节点飞轮，改进其标题表述和知识覆盖。",
    ))
    guarded_title = next(item for item in guarded_result.operations if item["target"].endswith(":title"))
    assert guarded_result.planner == "llm"
    assert guarded_title["after"] == "发动机飞轮的作用、结构与正时标记"

    class FailingPlanner:
        async def plan_incremental(self, payload):
            raise CoursePrepAgentPlanningError("模拟结构化输出失败")

    recovered_result = asyncio.run(CoursePrepAgentService(llm=FailingPlanner()).plan(
        session,
        course_id=course.id,
        outline_node_id=node.outline_node_id,
        instruction="请针对课程节点飞轮，改进其标题表述和知识覆盖。",
    ))
    recovered_title = next(item for item in recovered_result.operations if item["target"].endswith(":title"))
    assert recovered_result.planner == "deterministic_fallback"
    assert recovered_title["after"] == "发动机飞轮的作用、结构与正时标记"


def test_title_action_returns_the_flywheel_title_without_rule_based_rewrite(session):
    _, course, node, _ = _setup_course_with_script(session)
    node.title = "发动机飞轮"
    session.add(node)
    session.commit()

    class TitlePlanner:
        async def plan_incremental(self, payload):
            assert payload["batch_action"] == PrepAction.OPTIMIZE_NODE_TITLE.value
            assert [item["id"] for item in payload["editable_outline"]] == [node.outline_node_id]
            return AgentPlan.model_validate({
                "summary": "标题已概括飞轮的主要教学内容",
                "operations": [{
                    "target_kind": "outline",
                    "target_id": node.outline_node_id,
                    "operation": "replace",
                    "field": "title",
                    "after": "发动机飞轮的作用、结构与正时标记",
                    "reason": "概括飞轮的功能、结构和正时用途",
                    "downstream_impact": "讲解脚本和 PPT 映射可据此保持一致",
                    "evidence_refs": [],
                }],
            })

    result = asyncio.run(CoursePrepAgentService(llm=TitlePlanner()).plan_action(
        session,
        course_id=course.id,
        action=PrepAction.OPTIMIZE_NODE_TITLE,
        outline_node_id=node.outline_node_id,
    ))

    assert result.planner == "llm_node_title"
    assert result.operations == [{
        "target": f"outline:{node.outline_node_id}:title",
        "after": "发动机飞轮的作用、结构与正时标记",
        "reason": "概括飞轮的功能、结构和正时用途。下游影响：讲解脚本和 PPT 映射可据此保持一致",
        "evidence_refs": [],
    }]


def test_agent_only_plans_against_latest_draft_versions(session, monkeypatch):
    monkeypatch.setattr(course_prep_agent_service, "_llm_is_configured", lambda: False)
    token = uuid4().hex[:10]
    teacher = User(username=f"p3_agent_versions_{token}", hashed_password=get_password_hash("pw"), role=UserRole.TEACHER)
    session.add(teacher); session.commit(); session.refresh(teacher)
    course = Course(fanya_course_id=f"p3-versions-{token}", fanya_course_name="P3 versions", title="P3 versions", teacher_id=teacher.id, status=CourseStatus.DRAFT)
    session.add(course); session.commit(); session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher.id)

    archived = CourseOutlineVersion(
        course_id=course.id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.ARCHIVED,
        created_by=teacher.id,
    )
    current = CourseOutlineVersion(
        course_id=course.id,
        version=2,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=teacher.id,
    )
    session.add(archived); session.add(current); session.flush()
    historical_node = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=archived.outline_version_id,
        node_type=OutlineNodeType.CHAPTER,
        title="历史第一章",
        order_index=0,
    )
    current_node = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=current.outline_version_id,
        node_type=OutlineNodeType.CHAPTER,
        title="当前第一章",
        order_index=0,
    )
    session.add(historical_node); session.add(current_node); session.flush()
    historical_script = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=archived.outline_version_id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.ARCHIVED,
        created_by=teacher.id,
    )
    current_script = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=current.outline_version_id,
        version=2,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=teacher.id,
    )
    session.add(historical_script); session.add(current_script); session.flush()
    historical_script_node = TeachingScriptNode(
        course_id=course.id,
        script_version_id=historical_script.script_version_id,
        outline_node_id=historical_node.outline_node_id,
        content="历史讲稿",
    )
    current_script_node = TeachingScriptNode(
        course_id=course.id,
        script_version_id=current_script.script_version_id,
        outline_node_id=current_node.outline_node_id,
        content="当前讲稿",
    )
    session.add(historical_script_node)
    session.add(current_script_node)
    session.commit()

    result = asyncio.run(course_prep_agent_service.plan(
        session,
        course_id=course.id,
        instruction="请把第一章讲稿表达得更通俗",
        outline_node_id=current_node.outline_node_id,
    ))

    assert result.planner == "deterministic_fallback"
    assert result.operations
    assert all(
        historical_node.outline_node_id not in item["target"]
        and historical_script_node.script_node_id not in item["target"]
        for item in result.operations
    )
    assert any(
        current_node.outline_node_id in item["target"]
        or current_script_node.script_node_id in item["target"]
        for item in result.operations
    )

    with pytest.raises(ValueError, match="最新草稿"):
        asyncio.run(course_prep_agent_service.plan(
            session,
            course_id=course.id,
            instruction="调整历史版本",
            outline_node_id=historical_node.outline_node_id,
        ))


class _FakeLLMResponse:
    def __init__(self, content: str, model: str = "fake", latency_ms: float = 10.0, usage: dict | None = None):
        self.content = content
        self.model = model
        self.latency_ms = latency_ms
        self.usage = usage or {}


class _FakeLLMClient:
    """Fake LLM client that returns a sequence of canned responses.

    Used to verify the structured-repair retry logic in
    ``CoursePrepAgentService._call_llm_with_retry``.
    """

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.call_count = 0
        self.received_messages: list[list] = []

    async def chat(self, messages, **kwargs):
        self.received_messages.append(messages)
        if self.call_count >= len(self._responses):
            raise RuntimeError("no more fake responses")
        content = self._responses[self.call_count]
        self.call_count += 1
        return _FakeLLMResponse(content=content)


def _setup_course_with_script(session, *, instruction_keyword: str = "内容和风格"):
    token = uuid4().hex[:10]
    teacher = User(
        username=f"p3_retry_{token}",
        hashed_password=get_password_hash("pw"),
        role=UserRole.TEACHER,
    )
    session.add(teacher)
    session.commit()
    session.refresh(teacher)
    course = Course(
        fanya_course_id=f"p3-retry-{token}",
        fanya_course_name="P3 retry",
        title="P3 retry",
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
    node = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="16.1 活塞销内孔形状",
        order_index=0,
    )
    session.add(node)
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
        outline_node_id=node.outline_node_id,
        content="活塞销内孔形状有圆柱形孔、锥形扩展、中间封闭式等多种形式。",
        style="academic",
    )
    session.add(script_node)
    session.commit()
    session.refresh(script_node)
    return teacher, course, node, script_node


def test_llm_retry_repairs_invalid_plan_and_includes_style_field(session, monkeypatch):
    """Regression: LLM 首次返回不合规 JSON 时，重试机制应修复并返回有效提案。

    场景：教师针对单个讲稿节点要求"内容和风格"润色。
    首次 LLM 返回空 operations 数组（违反 min_length=1）；
    修复重试后返回包含 content + style 两项操作的合法 JSON。

    同时验证 payload 中 editable_scripts 包含 style 字段。
    """
    monkeypatch.setattr(course_prep_agent_service, "_llm_is_configured", lambda: True)

    teacher, course, node, script_node = _setup_course_with_script(session)

    # 首次返回空 operations（触发 ValidationError），二次返回合法 plan
    invalid_response = json.dumps({"summary": "空提案", "operations": []})
    valid_response = json.dumps({
        "summary": "针对活塞销内孔形状讲稿的内容与风格润色建议",
        "operations": [
            {
                "target_kind": "script",
                "target_id": script_node.script_node_id,
                "field": "content",
                "after": "活塞销内孔形状多样：a）圆柱形孔；b）端部呈锥形扩展；c）中间封闭式；d）单侧封闭式；e）内有塑料芯的钢套销；f）成形销。",
                "reason": "按教学表达规范重组内容，保留原事实",
                "downstream_impact": "可能影响音频与数字人媒体，需在接受后重新生成",
                "evidence_refs": [],
            },
            {
                "target_kind": "script",
                "target_id": script_node.script_node_id,
                "field": "style",
                "after": "beginner",
                "reason": "教师要求风格调整，从 academic 改为 beginner 以贴合教学对象",
                "downstream_impact": "仅影响讲解风格标签",
                "evidence_refs": [],
            },
        ],
    })
    fake_client = _FakeLLMClient([invalid_response, valid_response])
    monkeypatch.setattr(course_prep_agent_service, "_llm", fake_client)

    result = asyncio.run(course_prep_agent_service.plan(
        session,
        course_id=course.id,
        instruction="请针对讲稿节点的内容和风格提出润色建议，使其更符合教学表达规范。",
        outline_node_id=node.outline_node_id,
    ))

    # 重试后应成功，planner 为 llm
    assert result.planner == "llm"
    # 应包含两项操作（content + style）
    assert len(result.operations) == 2
    fields = {op["target"].split(":")[-1] for op in result.operations}
    assert fields == {"content", "style"}
    # 验证 style 操作的 after 值
    style_op = next(op for op in result.operations if op["target"].endswith(":style"))
    assert style_op["after"] == "beginner"
    # 验证 LLM 被调用 2 次（首次失败 + 重试成功）
    assert fake_client.call_count == 2
    # 验证 payload 中 editable_scripts 包含 style 字段
    user_msg = fake_client.received_messages[0][1].content
    payload = json.loads(user_msg)
    assert "style" in payload["editable_scripts"][0]
    assert payload["editable_scripts"][0]["style"] == "academic"


def test_llm_retry_exhausted_falls_back_to_deterministic_plan(session, monkeypatch):
    """连续两次返回不合规 JSON 时，单节点增量流程应回退到本地计划。"""
    monkeypatch.setattr(course_prep_agent_service, "_llm_is_configured", lambda: True)

    teacher, course, node, script_node = _setup_course_with_script(session)

    # 两次都返回空 operations
    invalid_response = json.dumps({"summary": "空提案", "operations": []})
    fake_client = _FakeLLMClient([invalid_response, invalid_response])
    monkeypatch.setattr(course_prep_agent_service, "_llm", fake_client)

    result = asyncio.run(course_prep_agent_service.plan(
        session,
        course_id=course.id,
        instruction="请针对讲稿节点的内容和风格提出润色建议。",
        outline_node_id=node.outline_node_id,
    ))
    assert result.planner == "deterministic_fallback"
    assert any(item["target"].endswith(":content") for item in result.operations)
    # 验证 LLM 被调用 2 次（首次 + 1 次重试）
    assert fake_client.call_count == 2


class _BatchPlanner:
    def __init__(self):
        self.payloads: list[dict] = []

    async def plan_incremental(self, payload):
        self.payloads.append(payload)
        action = payload["batch_action"]
        if action == "organize_structure":
            operations = [{
                "target_kind": "outline",
                "target_id": item["id"],
                "field": "title",
                "after": f"{item['title']}（优化）",
                "reason": "统一标题表达",
                "downstream_impact": "检查关联讲稿",
                "evidence_refs": [],
            } for item in payload["editable_outline"]]
        else:
            scripts_by_id = {
                item["id"]: item
                for item in payload["course_context"]["scripts"]
            }
            operations = [{
                "target_kind": "script",
                "target_id": item["id"],
                "field": "content",
                "after": f"{scripts_by_id[item['id']]['content']}\n\n优化后的教学总结。",
                "reason": "改善教学表达",
                "downstream_impact": "媒体需要重新生成",
                "evidence_refs": [],
            } for item in payload["editable_scripts"]]
        from app.services.course_prep_agent_service import AgentPlan
        return AgentPlan.model_validate({"summary": "批量完成", "operations": operations})


def test_batch_structure_planning_covers_every_unlocked_node(session):
    teacher, course, node, _ = _setup_course_with_script(session)
    second = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=node.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="第二知识点",
        order_index=1,
    )
    locked = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=node.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="锁定知识点",
        order_index=2,
        locked_by=teacher.id,
    )
    session.add(second)
    session.add(locked)
    session.commit()
    planner = _BatchPlanner()
    service = CoursePrepAgentService(llm=planner)

    result = asyncio.run(service.plan_batch(
        session,
        course_id=course.id,
        action="organize_structure",
    ))

    targets = {item["target"] for item in result.operations}
    assert targets == {
        f"outline:{node.outline_node_id}:title",
        f"outline:{second.outline_node_id}:title",
    }
    assert f"outline:{locked.outline_node_id}" in result.excluded_locked_targets
    assert len(planner.payloads) == 1
    payload = planner.payloads[0]
    hierarchy = payload["course_context"]["hierarchy"]
    assert {item["id"] for item in hierarchy} == {
        node.outline_node_id,
        second.outline_node_id,
    }


def test_structure_action_can_move_children_then_remove_an_unlocked_parent(session):
    _, course, parent, _ = _setup_course_with_script(session)
    child = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=parent.outline_version_id,
        parent_node_id=parent.outline_node_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="子知识点",
        order_index=0,
    )
    session.add(child)
    session.commit()

    class StructurePlanner:
        async def plan_incremental(self, payload):
            assert payload["batch_action"] == PrepAction.ORGANIZE_STRUCTURE.value
            return AgentPlan.model_validate({
                "summary": "移除冗余父节点并保留子知识点",
                "operations": [
                    {
                        "target_kind": "outline", "target_id": child.outline_node_id,
                        "operation": "move", "field": "structure", "parent_node_id": None,
                        "order_index": 0, "reason": "子知识点可直接作为顶层教学节点",
                        "downstream_impact": "保留原有知识内容", "evidence_refs": [],
                    },
                    {
                        "target_kind": "outline", "target_id": parent.outline_node_id,
                        "operation": "remove", "field": "structure",
                        "reason": "父节点没有独立教学内容", "downstream_impact": "移除冗余层级",
                        "evidence_refs": [],
                    },
                ],
            })

    result = asyncio.run(CoursePrepAgentService(llm=StructurePlanner()).plan_action(
        session,
        course_id=course.id,
        action=PrepAction.ORGANIZE_STRUCTURE,
    ))

    assert [(item["operation"], item["target"]) for item in result.operations] == [
        ("move", f"outline:{child.outline_node_id}:structure"),
        ("remove", f"outline:{parent.outline_node_id}:structure"),
    ]


def test_batch_script_planning_uses_five_script_groups_with_full_outline_context(session):
    _, course, node, first_script = _setup_course_with_script(session)
    outline_version_id = node.outline_version_id
    script_version_id = first_script.script_version_id
    long_content = "原始讲稿，包含完整教学事实。"
    first_script.content = long_content
    session.add(first_script)
    for index in range(1, 25):
        outline_node = CourseOutlineNode(
            course_id=course.id,
            outline_version_id=outline_version_id,
            node_type=OutlineNodeType.KNOWLEDGE_POINT,
            title=f"知识点 {index}",
            order_index=index,
        )
        session.add(outline_node)
        session.flush()
        session.add(TeachingScriptNode(
            course_id=course.id,
            script_version_id=script_version_id,
            outline_node_id=outline_node.outline_node_id,
            content=f"讲稿 {index}" + long_content,
            style="academic",
        ))
    session.commit()
    planner = _BatchPlanner()
    service = CoursePrepAgentService(llm=planner)

    result = asyncio.run(service.plan_batch(
        session,
        course_id=course.id,
        action="optimize_scripts",
    ))

    assert len(result.operations) == 25
    assert len(planner.payloads) == 5
    assert all(1 <= len(payload["editable_scripts"]) <= 5 for payload in planner.payloads)
    assert all(len(payload["course_context"]["hierarchy"]) == 25 for payload in planner.payloads)
    assert all(len(payload["course_context"]["scripts"]) <= 5 for payload in planner.payloads)
    first_payload = next(
        payload for payload in planner.payloads
        if any(item["id"] == first_script.script_node_id for item in payload["editable_scripts"])
    )
    target_script = next(item for item in first_payload["editable_scripts"] if item["id"] == first_script.script_node_id)
    context_script = next(item for item in first_payload["course_context"]["scripts"] if item["id"] == first_script.script_node_id)
    assert "content" not in target_script
    assert context_script["content"] == long_content


def test_batch_capacity_accepts_normal_full_course_context(monkeypatch):
    """53 outline nodes + 27 short scripts must not fail before LLM planning."""
    monkeypatch.setattr(settings, "LLM_MAX_TOKENS", 8192)
    outline = [
        SimpleNamespace(title=f"第 {index} 个知识点", parent_node_id="")
        for index in range(53)
    ]
    scripts = [
        SimpleNamespace(content="这是用于验证完整课程讲稿容量的教学说明。" * 8, style="academic")
        for _index in range(27)
    ]

    CoursePrepAgentService._validate_batch_capacity(
        action="organize_structure",
        outline=outline,
        scripts=scripts,
        target_count=len(outline),
    )
    CoursePrepAgentService._validate_batch_capacity(
        action="optimize_scripts",
        outline=outline,
        scripts=scripts,
        target_count=len(scripts),
    )


def test_batch_capacity_still_rejects_genuinely_oversized_course(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_TOKENS", 8192)
    scripts = [SimpleNamespace(content="讲稿" * 20_000, style="academic")]

    with pytest.raises(CoursePrepAgentPlanningError, match="超过单次模型容量"):
        CoursePrepAgentService._validate_batch_capacity(
            action="optimize_scripts",
            outline=[],
            scripts=scripts,
            target_count=1,
        )
