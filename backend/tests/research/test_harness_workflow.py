"""Executable graph contracts for the ResearchAgent Harness workflow."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.platform.agents.providers.research.workspace import (
    SqlResearchWorkspaceProvider,
)
from app.platform.agents.research.workflow import ResearchTools, build_research_workflow


def _workspace_provider():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return SqlResearchWorkspaceProvider(session_factory=lambda: Session(engine))


def _initial(**overrides):
    state = {
        "run_id": "run_harness_test",
        "trace_id": "trace-harness-test",
        "course_id": "7",
        "actor_user_id": "11",
        "session_id": "session-harness-test",
        "user_message": "创建待办：核验 RAG 论文",
        "query": "创建待办：核验 RAG 论文",
        "requested_action": "todo_create",
        "action_payload": {"title": "核验 RAG 论文", "priority": 3},
        "max_results": 8,
        "context_budget_tokens": 256,
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }
    state.update(overrides)
    return state


def _tools(workspace=None):
    scope_access = AsyncMock()
    scope_access.authorize.return_value = {
        "allowed": True,
        "permission": "course.question.ask",
    }
    paper_search = AsyncMock()
    paper_search.search.return_value = {
        "status": "success",
        "provider": "arxiv",
        "items": [],
        "retrieved_at": "2026-08-11T12:00:00+08:00",
    }
    return ResearchTools(
        scope_access=scope_access,
        paper_search=paper_search,
        workspace=workspace or _workspace_provider(),
    )


def test_harness_graph_has_real_conditional_nodes_for_context_and_tools():
    graph = build_research_workflow(_tools())
    node_names = set(graph.get_graph().nodes)

    assert {
        "scope_validator",
        "workspace_hydrate",
        "context_assess",
        "context_select",
        "context_compress",
        "prompt_assemble",
        "intent_planner",
        "tool_selector",
        "route_tools",
        "literature_search",
        "todo_action",
        "notepad_action",
        "memory_action",
        "scope_action",
        "evidence_gate",
        "workspace_refresh",
        "response",
    }.issubset(node_names)


def test_todo_route_persists_result_and_rechecks_tool_permission():
    tools = _tools()
    graph = build_research_workflow(tools)

    result = asyncio.run(graph.ainvoke(_initial()))

    assert result["status"] == "success"
    assert result["graph_route"] == "todo"
    assert result["selected_tools"] == ["todo_manager"]
    assert result["tool_result"]["title"] == "核验 RAG 论文"
    assert result["workspace_snapshot"]["todos"][0]["priority"] == 3
    assert tools.scope_access.authorize.await_count == 2
    assert any(entry["node"] == "todo_action" for entry in result["trace"])
    assert "assembled_prompt" not in result


def test_oversized_workspace_context_takes_compression_branch():
    workspace = _workspace_provider()
    created = asyncio.run(workspace.get_or_create_workspace(
        course_id=7,
        actor_user_id="11",
        title="RAG",
    ))
    asyncio.run(workspace.save_note(
        workspace_id=created["workspace_id"],
        course_id=7,
        actor_user_id="11",
        scope_id=created["active_scope_id"],
        title="长笔记",
        content="RAG 教育实验指标与证据核验。" * 200,
    ))
    tools = _tools(workspace)
    graph = build_research_workflow(tools)

    result = asyncio.run(graph.ainvoke(_initial(
        workspace_id=created["workspace_id"],
        context_budget_tokens=64,
    )))

    assert result["context_meta"]["compressed"] is True
    assert result["context_meta"]["estimated_tokens"] <= 64
    assert any(entry["node"] == "context_compress" for entry in result["trace"])


def test_scope_interrupt_and_resume_are_real_graph_actions():
    tools = _tools()
    graph = build_research_workflow(tools)
    created = asyncio.run(graph.ainvoke(_initial(
        user_message="创建子任务",
        query="创建子任务",
        requested_action="scope_create",
        action_payload={"title": "指标复核", "objective": "复核实验指标"},
    )))
    scope_id = created["tool_result"]["scope_id"]
    workspace_id = created["workspace_snapshot"]["workspace_id"]

    interrupted = asyncio.run(graph.ainvoke(_initial(
        workspace_id=workspace_id,
        user_message="中断子任务",
        query="中断子任务",
        requested_action="scope_interrupt",
        action_payload={"scope_id": scope_id, "context_summary": "已完成指标定义核验"},
    )))
    resumed = asyncio.run(graph.ainvoke(_initial(
        workspace_id=workspace_id,
        user_message="恢复子任务",
        query="恢复子任务",
        requested_action="scope_resume",
        action_payload={"scope_id": scope_id},
    )))

    assert interrupted["tool_result"]["status"] == "interrupted"
    assert resumed["tool_result"]["status"] == "active"
    assert resumed["tool_result"]["context_summary"] == "已完成指标定义核验"
    assert resumed["workspace_snapshot"]["active_scope_id"] == scope_id

