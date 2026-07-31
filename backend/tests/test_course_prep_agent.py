"""P3: natural-language preparation proposals never include locked content."""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from app.core.security import get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import CourseOutlineNode, CourseOutlineVersion, OutlineLifecycleStatus, OutlineNodeType, TeachingScriptNode, TeachingScriptVersion
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.course_prep_agent_service import CoursePrepAgentPlanningError, CoursePrepAgentService, course_prep_agent_service


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


def test_llm_retry_exhausted_raises_planning_error(session, monkeypatch):
    """连续两次返回不合规 JSON 时，应抛出 CoursePrepAgentPlanningError。"""
    monkeypatch.setattr(course_prep_agent_service, "_llm_is_configured", lambda: True)

    teacher, course, node, script_node = _setup_course_with_script(session)

    # 两次都返回空 operations
    invalid_response = json.dumps({"summary": "空提案", "operations": []})
    fake_client = _FakeLLMClient([invalid_response, invalid_response])
    monkeypatch.setattr(course_prep_agent_service, "_llm", fake_client)

    with pytest.raises(CoursePrepAgentPlanningError, match="格式不符合安全协议"):
        asyncio.run(course_prep_agent_service.plan(
            session,
            course_id=course.id,
            instruction="请针对讲稿节点的内容和风格提出润色建议。",
            outline_node_id=node.outline_node_id,
        ))
    # 验证 LLM 被调用 2 次（首次 + 1 次重试）
    assert fake_client.call_count == 2
