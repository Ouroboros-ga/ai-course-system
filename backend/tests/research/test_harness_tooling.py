"""Security and reliability contracts for dynamic ResearchAgent tools."""
from __future__ import annotations

import asyncio

from app.platform.agents.research.harness.reliability import ReliableToolExecutor
from app.platform.agents.research.harness.tooling import (
    DynamicResearchToolSelector,
    ResearchToolRegistry,
)


def test_dynamic_tool_selector_intersects_intent_whitelist_and_permissions():
    registry = ResearchToolRegistry.default()
    selector = DynamicResearchToolSelector(registry)

    selection = selector.select(
        message="检索 RAG 论文并把后续阅读加入待办",
        requested_action="auto",
        context_kinds={"todo", "paper"},
        allowed_tool_names={"paper_search", "todo_manager", "notepad"},
        granted_permissions={"course.question.ask"},
    )

    assert selection.primary_intent == "literature_search"
    assert selection.selected_tool_names == ["paper_search", "todo_manager"]
    assert "notepad" not in selection.selected_tool_names


def test_dynamic_tool_selector_reports_permission_denial_without_injecting_tool():
    registry = ResearchToolRegistry.default()
    selector = DynamicResearchToolSelector(registry)

    selection = selector.select(
        message="检索论文",
        requested_action="literature_search",
        context_kinds=set(),
        allowed_tool_names={"paper_search"},
        granted_permissions=set(),
    )

    assert selection.selected_tool_names == []
    assert selection.denied_tool_names == ["paper_search"]
    assert selection.reason_code == "RESEARCH_TOOL_PERMISSION_DENIED"


def test_reliable_tool_executor_retries_then_returns_success():
    registry = ResearchToolRegistry.default()
    executor = ReliableToolExecutor(
        registry=registry,
        failure_threshold=2,
        reset_timeout_seconds=60,
        base_backoff_seconds=0,
    )
    calls = 0

    async def flaky_call():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        return {"items": ["ok"]}

    result = asyncio.run(executor.execute("paper_search", flaky_call))

    assert result.status == "success"
    assert result.attempts == 2
    assert result.value == {"items": ["ok"]}
    assert calls == 2


def test_reliable_tool_executor_opens_circuit_and_never_runs_unlisted_tool():
    registry = ResearchToolRegistry.default()
    executor = ReliableToolExecutor(
        registry=registry,
        failure_threshold=1,
        reset_timeout_seconds=60,
        base_backoff_seconds=0,
    )
    calls = 0

    async def failing_call():
        nonlocal calls
        calls += 1
        raise RuntimeError("upstream down")

    first = asyncio.run(executor.execute("paper_search", failing_call))
    second = asyncio.run(executor.execute("paper_search", failing_call))
    unknown = asyncio.run(executor.execute("host_shell", failing_call))

    assert first.status == "failed"
    assert first.error_code == "RESEARCH_TOOL_FAILED"
    assert second.status == "circuit_open"
    assert second.error_code == "RESEARCH_TOOL_CIRCUIT_OPEN"
    assert unknown.status == "denied"
    assert unknown.error_code == "RESEARCH_TOOL_NOT_ALLOWLISTED"
    assert calls == 1

