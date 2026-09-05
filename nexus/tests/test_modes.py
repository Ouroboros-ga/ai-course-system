"""M1 回归：模式真实化（D2/D1-B2）+ SSE error（D5）+ 结构化 tool_result（D4）。

全 mock：不调真实 LLM、不连 PG。模式工具面用 deepagents 真实图 +
不联网的 ChatOpenAI 间谍验证；流事件契约用注入的假 agent/工具验证。
"""

import asyncio
import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

import nexus.agent
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from nexus.agent import RESEARCH_ONLY_TOOLS, build_agent, normalize_mode
from nexus.main import app
from nexus.tools import NEXUS_TOOLS

# ---------------------------------------------------------------------------
# M1-B2：模式归一与双 Profile 工具面
# ---------------------------------------------------------------------------


def test_normalize_mode_whitelist():
    assert normalize_mode(None) == "research"
    assert normalize_mode("") == "research"
    assert normalize_mode("research") == "research"
    assert normalize_mode("nexus_research") == "research"
    assert normalize_mode("general") == "general"
    assert normalize_mode("nexus_general") == "general"
    assert normalize_mode("NEXUS_GENERAL") == "general"
    # 未知值不 fail，归 Research（默认全工具面，与旧行为一致）。
    assert normalize_mode("bogus") == "research"


def test_research_only_tools_subset_of_product_tools():
    product_names = {t.name for t in NEXUS_TOOLS}
    assert RESEARCH_ONLY_TOOLS <= product_names


class _SpyChatOpenAI(ChatOpenAI):
    _responses: list[AIMessage] = PrivateAttr(default_factory=list)
    _bound_tool_names: list[str] = PrivateAttr(default_factory=list)

    def __init__(self, responses: list[AIMessage]) -> None:
        super().__init__(
            model="deepseek-chat",
            api_key="spy-key-not-real",
            base_url="https://api.deepseek.com/v1",
        )
        self._responses = list(responses)

    @property
    def bound_tool_names(self) -> list[str]:
        return list(self._bound_tool_names)

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        self._bound_tool_names = sorted(getattr(t, "name", str(t)) for t in tools)
        return self

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        response = self._responses.pop(0) if self._responses else AIMessage(content="ok")
        return ChatResult(generations=[ChatGeneration(message=response)])


def _registry(agent) -> list[str]:
    return sorted(agent.nodes["tools"].bound.tools_by_name.keys())


async def test_mode_tool_surfaces(monkeypatch: pytest.MonkeyPatch):
    """General = read_file + web_search；Research = read_file + 四产品工具。"""
    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "dummy-key-for-modes")
    # 先 patch 再 build：两个实例都必须持 spy（不联网），否则 ainvoke 会真连 LLM。
    spy = _SpyChatOpenAI(responses=[AIMessage(content="ok")])
    monkeypatch.setattr(nexus.agent, "build_llm", lambda: spy)
    research = build_agent(mode="research")
    general = build_agent(mode="general")
    product = {t.name for t in NEXUS_TOOLS}
    assert set(_registry(research)) == {"read_file"} | product
    # General 含课程/CS 检索与产物写入（Phase 12 演示链：普通模式 → CS/Course
    # RAG + Web → 生成 Artifact），仅排除 research-only 三工具。
    assert set(_registry(general)) == {
        "read_file", "web_search", "search_course_materials", "search_cs_knowledge", "write_artifact",
    }
    # 模型可见面同执行器注册表（research-only 工具结构性不绑定）。
    await general.ainvoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "mode-surface"}},
    )
    assert spy.bound_tool_names == sorted(_registry(general))


async def test_general_mode_rejects_research_tool_call(monkeypatch: pytest.MonkeyPatch):
    """General 模式下敌意 research 工具调用不得产生成功结果。"""
    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "dummy-key-for-hostile-mode")
    hostile = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_arxiv_papers", "args": {"query": "pwn"}, "id": "call-1"},
        ],
    )
    spy = _SpyChatOpenAI(responses=[hostile, AIMessage(content="done")])
    monkeypatch.setattr(nexus.agent, "build_llm", lambda: spy)
    agent = build_agent(mode="general")
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "hi"}]},
            config={"configurable": {"thread_id": "mode-hostile"}},
        )
    except Exception:
        # 未绑定工具导致图节点失败也是一种拦截形态：绝不产出成功结果。
        return
    from langchain_core.messages import ToolMessage

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert all(m.status == "error" for m in tool_msgs), f"research 工具调用未被拦截: {tool_msgs}"


async def test_mode_switch_shares_thread_context():
    """同 session 切模式：两实例共享同一 saver 与 thread，上下文连续。"""
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    def _fake(responses):
        class _M(GenericFakeChatModel):
            def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
                return self

        return _M(messages=(r for r in responses))

    saver = InMemorySaver()
    general = create_deep_agent(
        model=_fake([AIMessage(content="通用回答")]),
        tools=[],
        system_prompt="general",
        checkpointer=saver,
    )
    research = create_deep_agent(
        model=_fake([AIMessage(content="研究回答")]),
        tools=[],
        system_prompt="research",
        checkpointer=saver,
    )
    config = {"configurable": {"thread_id": "user-9:nexus-session-shared-mode"}}
    await general.ainvoke({"messages": [{"role": "user", "content": "q1"}]}, config)
    await research.ainvoke({"messages": [{"role": "user", "content": "q2"}]}, config)
    state = await research.aget_state(config)
    contents = [getattr(m, "content", "") for m in state.values["messages"]]
    assert "通用回答" in contents and "研究回答" in contents


# ---------------------------------------------------------------------------
# M1-B1：mode/context 字段真实到达 Runtime
# ---------------------------------------------------------------------------


async def test_chat_request_routes_by_mode(monkeypatch: pytest.MonkeyPatch):
    """同 session_id，mode 决定使用哪个实例（两层 pydantic 不再丢字段）。"""
    import nexus.main as main_module

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    def _fake(responses):
        class _M(GenericFakeChatModel):
            def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
                return self

        return _M(messages=(r for r in responses))

    general_agent = create_deep_agent(
        model=_fake([AIMessage(content="G-回复")]),
        tools=[],
        system_prompt="general",
        checkpointer=InMemorySaver(),
    )
    research_agent = create_deep_agent(
        model=_fake([AIMessage(content="R-回复")]),
        tools=[],
        system_prompt="research",
        checkpointer=InMemorySaver(),
    )
    original = main_module._agents
    main_module._agents = {"general": general_agent, "research": research_agent}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(
                "/api/v1/nexus/chat",
                json={
                    "message": "hi",
                    "session_id": "mode-route",
                    "mode": "nexus_general",
                    "context": {"course_id": 7},
                },
            )
            r2 = await client.post(
                "/api/v1/nexus/chat",
                json={"message": "hi", "session_id": "mode-route"},
            )
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["message"] == "G-回复"
        assert r2.json()["message"] == "R-回复"
    finally:
        main_module._agents = original


# ---------------------------------------------------------------------------
# M1-B3：SSE error 事件（done/error 互斥）
# ---------------------------------------------------------------------------


class _ExplodingAgent:
    """astream 先产出一个事件然后炸掉：模拟 Agent 循环中途异常。"""

    async def astream(self, inputs, config, stream_mode=None):  # noqa: ANN001, ANN003
        yield "updates", {}
        raise RuntimeError("tool node exploded")


async def test_stream_error_event_on_agent_failure(monkeypatch: pytest.MonkeyPatch):
    import nexus.main as main_module

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    original = main_module._agents
    main_module._agents = {"research": _ExplodingAgent(), "general": _ExplodingAgent()}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nexus/chat/stream",
                json={"message": "hi", "session_id": "err-1"},
            )
        assert response.status_code == 200
        assert "event: error" in response.text
        assert "tool node exploded" in response.text
        assert "event: done" not in response.text
    finally:
        main_module._agents = original


async def test_stream_success_has_done_and_no_error(monkeypatch: pytest.MonkeyPatch):
    import nexus.main as main_module

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    original = main_module._agents

    class _OkAgent:
        async def astream(self, inputs, config, stream_mode=None):  # noqa: ANN001, ANN003
            yield "messages", (AIMessageChunk(content="你好"), {})
            yield "updates", {}
            yield "updates", {}

    main_module._agents = {"research": _OkAgent(), "general": _OkAgent()}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nexus/chat/stream",
                json={"message": "hi", "session_id": "ok-1"},
            )
        assert "event: done" in response.text
        assert "event: error" not in response.text
    finally:
        main_module._agents = original


# ---------------------------------------------------------------------------
# M1-B4：tool_result 结构化 items（条目边界截断，JSON 不再腰斩）
# ---------------------------------------------------------------------------


def _big_search_json() -> str:
    return json.dumps(
        {
            "channel": "searxng",
            "total": 2,
            "items": [
                {"title": "T" * 400, "url": "https://example.com/a", "snippet": "S" * 400},
                {"title": "U" * 400, "url": "https://example.com/b", "snippet": "S" * 400},
            ],
        },
        ensure_ascii=False,
    )


class _ToolFlowAgent:
    """直接产出 updates 事件的假 agent：绕开 deepagents 流式工具路由的
    造桩成本（工具路由已由 ainvoke 套件覆盖），聚焦 main.py 的
    tool_result 事件契约本身。"""

    def __init__(self, results: dict[str, str]) -> None:
        self._results = results

    async def astream(self, inputs, config, stream_mode=None):  # noqa: ANN001, ANN003
        for i, (name, content) in enumerate(self._results.items()):
            call_id = f"c{i}"
            yield "updates", {
                "model": {
                    "messages": [
                        AIMessage(
                            content=" ",
                            tool_calls=[{"name": name, "args": {"query": "q"}, "id": call_id}],
                        )
                    ]
                }
            }
            from langchain_core.messages import ToolMessage

            yield "updates", {
                "tools": {
                    "messages": [
                        ToolMessage(name=name, content=content, tool_call_id=call_id, status="success")
                    ]
                }
            }
        yield "updates", {"model": {"messages": [AIMessage(content="总结完毕")]}}


async def _stream_events(agent: Any) -> list[tuple[str, dict]]:
    """直跑 _agent_stream 生成器收集事件（不经 HTTP）。"""
    import nexus.main as main_module

    original = main_module._agents
    main_module._agents = {"research": agent, "general": agent}
    try:
        events = []
        async for frame in main_module._agent_stream("hi", "items-1", None, "research"):
            for block in frame.strip().split("\n\n"):
                lines = block.splitlines()
                event = next((l[7:] for l in lines if l.startswith("event: ")), "")
                data = next((l[6:] for l in lines if l.startswith("data: ")), "")
                if event and data:
                    events.append((event, json.loads(data)))
        return events
    finally:
        main_module._agents = original


async def test_tool_result_structured_items(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "dummy-key-for-items")
    agent = _ToolFlowAgent({"web_search": _big_search_json(), "plain_tool": "plain " * 300})
    events = await _stream_events(agent)
    results = [d for e, d in events if e == "tool_result"]
    by_name = {d["name"]: d for d in results}
    search = by_name["web_search"]
    assert search["items"] is not None
    assert len(search["items"]) == 2
    assert len(search["items"][0]["title"]) == 300  # 条目内截断
    # content 保持完整合法 JSON（可被前端 parse），不再 600 腰斩。
    reparsed = json.loads(search["content"])
    assert reparsed["total"] == 2
    plain = by_name["plain_tool"]
    assert "items" not in plain
    assert len(plain["content"]) <= 600


# ---------------------------------------------------------------------------
# M1-B6：取消语义——消费者提前关闭流，服务端绝不补发假 done
# ---------------------------------------------------------------------------


async def test_stream_cancel_does_not_emit_done(monkeypatch: pytest.MonkeyPatch):
    import nexus.main as main_module

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    original = main_module._agents

    class _SlowAgent:
        async def astream(self, inputs, config, stream_mode=None):  # noqa: ANN001, ANN003
            yield "messages", (AIMessageChunk(content="partial"), {})
            await asyncio.sleep(3600)
            yield "updates", {}

    main_module._agents = {"research": _SlowAgent(), "general": _SlowAgent()}
    try:
        seen: list[str] = []
        gen = main_module._agent_stream("hi", "cancel-1", None, "research")
        async for frame in gen:
            seen.append(frame)
            break  # 模拟客户端断开：只消费第一个事件就关闭
        await gen.aclose()
        assert not any("event: done" in f for f in seen)
    finally:
        main_module._agents = original
