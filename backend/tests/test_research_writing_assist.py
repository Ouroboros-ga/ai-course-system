"""ResearchAgent 学术写作辅助（writing_assist）契约与 fail-closed 行为。

覆盖：工具选择、prompt 任务与变量装配、结构化 LLM 成功路径、LLM 不可用时的
fail-closed 降级、API 动作枚举注册。全部使用 Fake/Mock，不调用真实付费服务。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.platform.agents.research.harness.tooling import DynamicResearchToolSelector, ResearchToolRegistry
from app.platform.agents.research.workflow import (
    ResearchTools,
    WritingAssistResult,
    _prompt_task,
    _prompt_variables,
    build_research_workflow,
)


def _base_state(**overrides):
    state = {
        "course_id": "1",
        "actor_user_id": "7",
        "query": "帮我写一篇关于检索增强生成（RAG）的综述",
        "requested_action": "writing_assist",
        "action_payload": {"task": "draft"},
        "granted_permissions": ["course.question.ask"],
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }
    state.update(overrides)
    return state


class _Parsed:
    def __init__(self, parsed):
        self.parsed = parsed


class _FakeStructuredLLM:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        return _Parsed(self.result)


def _fakes(structured_llm):
    scope_access = AsyncMock()
    scope_access.authorize.return_value = {"allowed": True}
    workspace = AsyncMock()
    workspace.get_or_create_workspace.return_value = {"workspace_id": "w1"}
    workspace.get_workspace_snapshot.return_value = {}
    return ResearchTools(
        scope_access=scope_access,
        paper_search=AsyncMock(),
        workspace=workspace,
        structured_llm=structured_llm,
    )


# ---------------------------------------------------------------------------
# 工具选择与 prompt 装配
# ---------------------------------------------------------------------------


def test_selector_picks_writing_assist_for_review_request():
    registry = ResearchToolRegistry.default()
    selector = DynamicResearchToolSelector(registry)
    selection = selector.select(
        message="帮我写一篇综述，并把结论润色一下",
        requested_action="auto",
        allowed_tool_names={spec.name for spec in registry.list()},
        granted_permissions={"course.question.ask"},
    )
    assert "writing_assist" in selection.selected_tool_names


def test_prompt_task_and_variables_for_writing():
    assert _prompt_task("writing_assist") == "writing_assist"
    variables = _prompt_variables(
        {"query": "q", "context_text": "ctx", "papers": []},
        "scope",
        "manifest",
        "writing_assist",
    )
    assert set(variables) == {"scope_title", "research_question", "context", "papers_summary"}
    assert "无已核验论文结果" in variables["papers_summary"]

    generic = _prompt_variables({"query": "q", "context_text": "ctx"}, "scope", "manifest", "research_request")
    assert set(generic) == {"scope_title", "research_question", "context", "tool_manifest"}


def test_api_action_enum_includes_writing_assist():
    from app.api.v1.endpoints import research_agent

    assert "writing_assist" in research_agent.ResearchAction.__args__


# ---------------------------------------------------------------------------
# 工作流行为
# ---------------------------------------------------------------------------


def test_writing_action_generates_draft_with_structured_llm():
    llm = _FakeStructuredLLM(
        WritingAssistResult(
            draft="本综述梳理了 RAG 的核心组件：检索器、生成器与融合策略。",
            headings=["引言", "方法", "展望"],
        )
    )
    graph = build_research_workflow(_fakes(structured_llm=llm))

    state = asyncio.run(graph.ainvoke(_base_state()))

    assert state["graph_route"] == "writing"
    assert state["status"] == "success"
    assert state["writing_result"]["ai_generated"] is True
    assert state["writing_result"]["task"] == "draft"
    assert "RAG" in state["writing_result"]["draft"]
    assert len(state["writing_result"]["headings"]) == 3
    assert "草稿" in state["final_answer"]
    assert state["tool_result"]["heading_count"] == 3
    assert "writing_assist" in state["selected_tools"]


def test_writing_action_respects_payload_task_kind():
    llm = _FakeStructuredLLM(WritingAssistResult(draft="润色后的段落。", headings=[]))
    graph = build_research_workflow(_fakes(structured_llm=llm))

    state = asyncio.run(graph.ainvoke(_base_state(action_payload={"task": "polish"})))

    assert state["writing_result"]["task"] == "polish"


def test_writing_action_fails_closed_without_llm():
    graph = build_research_workflow(_fakes(structured_llm=None))

    state = asyncio.run(graph.ainvoke(_base_state()))

    assert state["status"] == "degraded"
    assert state["tool_error_code"] == "RESEARCH_WRITING_LLM_UNAVAILABLE"
    assert state["writing_result"] is None
    assert "research_writing_llm" in state["degraded_services"]
    assert "未生成或伪造任何草稿" in state["final_answer"]


def test_writing_action_denied_without_permission():
    # 第一次调用（scope_validator）放行；第二次调用（工具执行前 reauthorize）拒绝
    scope_access = AsyncMock()
    scope_access.authorize.side_effect = [
        {"allowed": True},
        {"allowed": False, "reason_code": "DENIED"},
    ]
    workspace = AsyncMock()
    workspace.get_or_create_workspace.return_value = {"workspace_id": "w1"}
    workspace.get_workspace_snapshot.return_value = {}
    graph = build_research_workflow(ResearchTools(
        scope_access=scope_access,
        paper_search=AsyncMock(),
        workspace=workspace,
        structured_llm=_FakeStructuredLLM(WritingAssistResult(draft="x", headings=[])),
    ))

    state = asyncio.run(graph.ainvoke(_base_state()))

    assert state["tool_error_code"] == "RESEARCH_TOOL_PERMISSION_DENIED"
    assert state.get("writing_result") is None
