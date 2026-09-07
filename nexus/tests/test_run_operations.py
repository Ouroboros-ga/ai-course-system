"""NX-LB3/LB4/LB5 Runtime 回归：会话并发/幂等、运行操作工具、提案工具。

全离线：LLM 用脚本化假模型，Backend 内部端点用 respx 拦截出站，不用 PG
（内存提案/审批存储）。验收映射（P2 计划 §9.4–§9.6）：
- 同会话单写者门：不同请求竞争 409 SESSION_BUSY；同键重试不重复执行；
- plan/tool/result/error/done 事件携带 session_id/request_id；
- get/cancel/note 工具：身份来自请求作用域，失败语义如实透传；
- 取消无授权 → confirmation_required（模型不可自授权）；
- 提案工具：创建/修改/请求审批走 LB2 同一域服务，模型不决定批准。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

import nexus.main as main_module
from nexus import approvals, proposals
from nexus.agent import RESEARCH_ONLY_TOOLS, _tools_for_mode
from nexus.config import get_settings
from nexus.main import app
from nexus.request_scope import (
    reset_execution_scope,
    reset_scope,
    set_execution_scope,
    set_scope,
)
from nexus.tools import NEXUS_TOOLS
from nexus.tools.reproduction import (
    _internal_ready,
    add_reproduction_note,
    cancel_reproduction_run,
    create_reproduction_proposal,
    get_reproduction_run,
    request_reproduction_approval,
    update_reproduction_proposal,
)

_INTERNAL = "http://backend-internal.test"


@pytest.fixture(autouse=True)
def _clean_stores():
    proposals.clear_memory_store()
    approvals.clear_memory_store()
    yield
    proposals.clear_memory_store()
    approvals.clear_memory_store()
    main_module._active_threads.clear()
    main_module._request_registry.clear()
    main_module._registry_order.clear()


@pytest.fixture
def internal_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", _INTERNAL)
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "tok")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 工具面：运行操作工具 Research-only（General 结构性不可见）
# ---------------------------------------------------------------------------

_NEW_TOOLS = {
    "get_reproduction_run", "cancel_reproduction_run", "add_reproduction_note",
    "create_reproduction_proposal", "update_reproduction_proposal",
    "request_reproduction_approval",
}


def test_run_operation_tools_are_research_only():
    names = {t.name for t in NEXUS_TOOLS}
    assert _NEW_TOOLS <= names
    assert _NEW_TOOLS <= RESEARCH_ONLY_TOOLS
    general_names = {t.name for t in _tools_for_mode("general")}
    research_names = {t.name for t in _tools_for_mode("research")}
    assert not (_NEW_TOOLS & general_names), "General 不得绑定运行操作工具"
    assert _NEW_TOOLS <= research_names


# ---------------------------------------------------------------------------
# 运行操作工具：身份来自作用域，失败语义如实透传（respx 拦截内部端点）
# ---------------------------------------------------------------------------


def _scope(user="7", session="s1"):
    scope_tokens = set_scope(user, None)
    exec_tokens = set_execution_scope(session, None)
    return scope_tokens, exec_tokens


def _unscope(tokens):
    reset_scope(tokens[0])
    reset_execution_scope(tokens[1])


async def test_get_run_tool_success_and_denials(internal_env):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{_INTERNAL}/api/v1/nexus-internal/runs/r1/status").respond(
            200, json={"code": 200, "message": "run status", "data": {
                "run_id": "r1", "status": "running", "steps": []}})
        mock.get(f"{_INTERNAL}/api/v1/nexus-internal/runs/r404/status").respond(
            404, json={"detail": "RUN_NOT_FOUND"})
        mock.get(f"{_INTERNAL}/api/v1/nexus-internal/runs/r403/status").respond(
            403, json={"detail": "RUN_SESSION_MISMATCH"})
        tokens = _scope()
        try:
            ok = await get_reproduction_run.ainvoke({"run_id": "r1"})
            assert ok["status"] == "success"
            assert ok["run"]["run_id"] == "r1"
            missing = await get_reproduction_run.ainvoke({"run_id": "r404"})
            assert missing["status"] == "not_found"
            assert missing["code"] == "RUN_NOT_FOUND"
            cross = await get_reproduction_run.ainvoke({"run_id": "r403"})
            assert cross["status"] == "rejected"
            assert cross["code"] == "RUN_SESSION_MISMATCH"
        finally:
            _unscope(tokens)


async def test_get_run_tool_without_scope_fails_closed(internal_env):
    result = await get_reproduction_run.ainvoke({"run_id": "r1"})
    assert result["status"] == "error"
    assert result["code"] == "SCOPE_MISSING"


async def test_get_run_tool_unconfigured_fails_closed(
    internal_env, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("NEXUS_BACKEND_INTERNAL_URL", raising=False)
    get_settings.cache_clear()
    assert _internal_ready() is None
    tokens = _scope()
    try:
        result = await get_reproduction_run.ainvoke({"run_id": "r1"})
    finally:
        _unscope(tokens)
    assert result["status"] == "unavailable"
    assert result["code"] == "BACKEND_INTERNAL_NOT_CONFIGURED"


async def test_cancel_tool_requires_user_confirmation_first(internal_env):
    """无授权 → confirmation_required（模型不可自授权）；有授权 → 成功。"""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{_INTERNAL}/api/v1/nexus-internal/runs/r9/cancel").mock(
            side_effect=[
                httpx.Response(200, json={"code": 200, "data": {
                    "run_id": "r9", "status": "confirmation_required",
                    "code": "CANCEL_CONFIRMATION_REQUIRED",
                    "detail": "需要用户确认"}}),
                httpx.Response(200, json={"code": 200, "data": {
                    "run_id": "r9", "job_id": "job-9", "status": "cancelling",
                    "already_terminal": False}}),
            ])
        tokens = _scope()
        try:
            first = await cancel_reproduction_run.ainvoke({"run_id": "r9"})
            assert first["status"] == "confirmation_required"
            assert first["code"] == "CANCEL_CONFIRMATION_REQUIRED"
            second = await cancel_reproduction_run.ainvoke({"run_id": "r9"})
            assert second["status"] == "success"
            assert second["run_status"] == "cancelling"
            assert second["job_id"] == "job-9"
        finally:
            _unscope(tokens)
        assert route.call_count == 2


async def test_note_tool_marks_agent_and_validates_length(internal_env):
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{_INTERNAL}/api/v1/nexus-internal/runs/r5/notes").respond(
            200, json={"code": 200, "data": {
                "note_id": "nt_1", "author_kind": "agent", "content": "解释"}})
        tokens = _scope()
        try:
            ok = await add_reproduction_note.ainvoke(
                {"run_id": "r5", "content": "解释"})
            assert ok["status"] == "success"
            assert ok["note"]["author_kind"] == "agent"
            too_long = await add_reproduction_note.ainvoke(
                {"run_id": "r5", "content": "x" * 4001})
            assert too_long["status"] == "rejected"
            assert too_long["code"] == "NOTE_CONTENT_INVALID"
            assert route.call_count == 1, "超长备注不得触达后端"
        finally:
            _unscope(tokens)


# ---------------------------------------------------------------------------
# 提案工具：与 LB2 域服务同一引擎；模型只准备材料，不决定批准
# ---------------------------------------------------------------------------


async def test_proposal_tools_create_patch_request_approval(internal_env):
    tokens = _scope(user="7", session="s1")
    try:
        created = await create_reproduction_proposal.ainvoke(
            {"preset_id": "nanogpt", "objective": "改小 batch",
             "parameters": {"batch_size": 8}})
        assert created["status"] == "success"
        proposal = created["proposal"]
        assert proposal["version"] == 1
        assert proposal["metric_policy"]["basis"] == "exploratory"

        bad_version = await update_reproduction_proposal.ainvoke(
            {"proposal_id": proposal["proposal_id"], "expected_version": 99,
             "parameters": {"max_iters": 500}})
        assert bad_version["status"] == "rejected"
        assert bad_version["code"] == "PROPOSAL_VERSION_CONFLICT"

        patched = await update_reproduction_proposal.ainvoke(
            {"proposal_id": proposal["proposal_id"], "expected_version": 1,
             "parameters": {"max_iters": 500}})
        assert patched["status"] == "success"
        assert patched["proposal"]["version"] == 2
        assert any(d["name"] == "max_iters"
                   for d in patched["diff"]["parameters_changed"])

        first = await request_reproduction_approval.ainvoke(
            {"proposal_id": proposal["proposal_id"], "expected_version": 2})
        assert first["status"] == "success"
        assert first["deduped"] is False
        again = await request_reproduction_approval.ainvoke(
            {"proposal_id": proposal["proposal_id"], "expected_version": 2})
        assert again["status"] == "success"
        assert again["deduped"] is True
        assert again["approval"]["approval_id"] == first["approval"]["approval_id"]

        # 请求审批后提案仍可修改（旧批准随版本自然失效）。
        patched2 = await update_reproduction_proposal.ainvoke(
            {"proposal_id": proposal["proposal_id"], "expected_version": 2,
             "parameters": {"max_iters": 600}})
        assert patched2["status"] == "success"
        assert patched2["proposal"]["version"] == 3
        # 旧版本的审批请求被版本门拒绝（不静默 pin 错版本）。
        stale = await request_reproduction_approval.ainvoke(
            {"proposal_id": proposal["proposal_id"], "expected_version": 2})
        assert stale["status"] == "rejected"
        assert stale["code"] == "PROPOSAL_VERSION_CONFLICT"
    finally:
        _unscope(tokens)


async def test_proposal_tools_reject_cross_user_and_unknown_preset(internal_env):
    tokens = _scope(user="7", session="s1")
    try:
        created = await create_reproduction_proposal.ainvoke(
            {"preset_id": "nanogpt", "parameters": {}})
        assert created["status"] == "success"
    finally:
        _unscope(tokens)
    tokens_other = _scope(user="99", session="s1")
    try:
        patched = await update_reproduction_proposal.ainvoke(
            {"proposal_id": created["proposal"]["proposal_id"],
             "expected_version": 1, "parameters": {}})
        assert patched["status"] == "rejected"
        assert patched["code"] == "PROPOSAL_FORBIDDEN"
    finally:
        _unscope(tokens_other)
    tokens = _scope()
    try:
        unknown = await create_reproduction_proposal.ainvoke(
            {"preset_id": "not-a-preset"})
        assert unknown["status"] == "rejected"
        assert unknown["code"] == "UNKNOWN_PRESET"
    finally:
        _unscope(tokens)


async def test_create_proposal_parent_must_be_owned(internal_env):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{_INTERNAL}/api/v1/nexus-internal/repro-runs/rX").respond(
            404, json={"detail": "RUN_NOT_FOUND"})
        tokens = _scope()
        try:
            result = await create_reproduction_proposal.ainvoke(
                {"preset_id": "nanogpt", "parent_run_id": "rX"})
            assert result["status"] == "not_found"
            assert result["code"] == "PROPOSAL_PARENT_NOT_FOUND"
        finally:
            _unscope(tokens)


# ---------------------------------------------------------------------------
# LB3：同会话单写者门 + 幂等重试（脚本化假模型驱动真实 deepagents graph）
# ---------------------------------------------------------------------------


class _Fake(BaseChatModel):
    """脚本化假模型（可延迟），并捕获最近一次用户消息内容。"""

    _delay: float = PrivateAttr(default=0.0)
    _calls: int = PrivateAttr(default=0)
    _last_content: str = PrivateAttr(default="")

    def __init__(self, delay: float = 0.0) -> None:
        super().__init__()
        self._delay = delay

    @property
    def _llm_type(self) -> str:
        return "nexus-fake"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        self._calls += 1
        self._last_content = str(messages[-1].content if messages else "")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="好的"))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        self._calls += 1
        self._last_content = str(messages[-1].content if messages else "")
        if self._delay:
            await asyncio.sleep(self._delay)
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="好的", id="fake-chunk"))


_FAKE_MODELS: list[_Fake] = []


def _agent_with(delay: float = 0.0):
    from deepagents import create_deep_agent
    from deepagents.middleware.filesystem import FilesystemMiddleware

    model = _Fake(delay=delay)
    _FAKE_MODELS.append(model)
    return create_deep_agent(
        model=model,
        tools=[],
        system_prompt="test",
        middleware=[FilesystemMiddleware(tools=["read_file"])],
        checkpointer=InMemorySaver(),
    )


def _calls() -> int:
    return _FAKE_MODELS[-1]._calls if _FAKE_MODELS else 0


def _last_content() -> str:
    return _FAKE_MODELS[-1]._last_content if _FAKE_MODELS else ""


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_API_KEY", "")
    get_settings.cache_clear()
    original_agents = main_module._agents
    yield main_module
    main_module._agents = original_agents
    get_settings.cache_clear()


def _install(agent) -> None:
    main_module._agents = {
        ("research", "deepseek-chat"): agent,
        ("general", "deepseek-chat"): agent,
    }
    main_module._pg_saver = None


async def _read_stream(client: AsyncClient, payload: dict) -> tuple[int, str]:
    async with client.stream("POST", "/api/v1/nexus/chat/stream", json=payload,
                             headers={"X-Nexus-User-Id": "42"}) as response:
        body = ""
        async for chunk in response.aiter_text():
            body += chunk
    return response.status_code, body


async def test_session_busy_and_idempotent_retry(fake_env):
    agent = _agent_with(delay=0.4)
    _install(agent)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        stream_task = asyncio.create_task(_read_stream(client, {
            "message": "跑实验", "session_id": "lb3", "mode": "research",
            "client_request_id": "r1"}))
        await asyncio.sleep(0.1)  # 让第一个请求进入执行态

        busy_other = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "另一条", "session_id": "lb3", "mode": "research",
                  "client_request_id": "r2"},
            headers={"X-Nexus-User-Id": "42"})
        assert busy_other.status_code == 409
        assert busy_other.json()["detail"]["code"] == "SESSION_BUSY"

        busy_same = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "跑实验", "session_id": "lb3", "mode": "research",
                  "client_request_id": "r1"},
            headers={"X-Nexus-User-Id": "42"})
        assert busy_same.status_code == 409

        status, body = await stream_task
        assert status == 200 and "event: done" in body

        # 流结束后同键重试（/chat）：不重复调用模型。
        calls_before = _calls()
        dedup = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "跑实验", "session_id": "lb3", "mode": "research",
                  "client_request_id": "r1"},
            headers={"X-Nexus-User-Id": "42"})
        assert dedup.status_code == 200
        assert dedup.json()["deduped"] is True
        assert _calls() == calls_before

        # 无幂等键的请求在空闲后照常执行（不误伤）。
        plain = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "你好", "session_id": "lb3", "mode": "research"},
            headers={"X-Nexus-User-Id": "42"})
        assert plain.status_code == 200
        assert _calls() == calls_before + 1


async def test_chat_idempotent_retry_returns_original_result(fake_env):
    _install(_agent_with(delay=0.0))
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        first = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "你好", "session_id": "lb3b", "mode": "research",
                  "client_request_id": "c1"},
            headers={"X-Nexus-User-Id": "42"})
        assert first.status_code == 200
        calls = _calls()
        retry = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "你好", "session_id": "lb3b", "mode": "research",
                  "client_request_id": "c1"},
            headers={"X-Nexus-User-Id": "42"})
        assert retry.status_code == 200
        body = retry.json()
        assert body["deduped"] is True
        assert body["message"] == first.json()["message"]
        assert _calls() == calls, "同键重试不得再次调用模型"


async def test_stream_events_carry_session_and_request_ids(fake_env):
    _install(_agent_with(delay=0.0))
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        status, body = await _read_stream(client, {
            "message": "你好", "session_id": "lb3c", "mode": "research",
            "client_request_id": "tag-1"})
    assert status == 200
    events = []
    for block in body.split("\n\n"):
        if block.startswith("event: "):
            event = block.split("\n", 1)[0].removeprefix("event: ")
            data = json.loads(block.split("data: ", 1)[1])
            events.append((event, data))
    assert events, "SSE 流不应为空"
    for event, data in events:
        assert data.get("session_id") == "lb3c", event
        assert data.get("request_id") == "tag-1", event


async def test_run_context_note_injected_into_message(fake_env):
    _install(_agent_with(delay=0.0))
    run_context = {
        "run_id": "run-1", "display_title": "nanoGPT #1", "run_number": 1,
        "preset_id": "nanogpt", "status": "failed", "stale": False,
        "detail": "step 4 failed (exit=1)",
        "steps": [{"index": 3, "command": "python train.py --max_iters=100",
                   "exit_code": 1, "timed_out": False, "duration_s": 24.0,
                   "log": {"text": "ZeroDivisionError\niter 100", "lines": 2,
                           "total_lines": 2, "truncated": False}}],
    }
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        response = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "为什么失败了？", "session_id": "lb3d",
                  "mode": "research",
                  "context": {"run_context": run_context}},
            headers={"X-Nexus-User-Id": "42"})
    assert response.status_code == 200
    content = _last_content()
    assert "[系统注记｜本次对话引用实验运行快照" in content
    assert "run_id=run-1" in content
    assert "状态=failed" in content
    assert "ZeroDivisionError" in content
    assert content.rstrip().endswith("为什么失败了？"), "原始用户消息必须在注记之后"
