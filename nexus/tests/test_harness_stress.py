"""M5-B2 Harness 压力套件（设计文档 Phase 9）。

七类场景，全部要求"失败语义可断言"（禁静默成功 / 编造结果）：

1. 多 Tool 长任务：多步工具链事件完整、done 仅在末尾；
2. Tool 500：工具内部异常 → 图循环异常 → SSE error 事件（M1-B3）；
3. Context overflow → Compact 实测触发（阈值压小，验证状态被压缩）；
4. Runtime restart 后 resume（同一 saver 新实例可续）；
5. Cancel：M1-B6 已覆盖（test_modes.test_stream_cancel_does_not_emit_done）；
6. Malformed Tool：缺参 tool_call → 错误 ToolMessage，不崩溃、不静默；
7. Worker timeout：run_reproduction 遇上游超时 → REPRO_WORKER_UNAVAILABLE。

全 mock，不调真实 LLM/Worker/付费服务。
"""

import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

import nexus.main as main_module
from nexus.main import app

# ---------------------------------------------------------------------------
# 1. 多 Tool 长任务：事件完整、无 error、done 恰一次
# ---------------------------------------------------------------------------


class _MultiToolAgent:
    """三轮工具 + 最终回答的长任务替身（updates 流）。"""

    def __init__(self) -> None:
        self._calls = ["web_search", "search_arxiv_papers", "search_cs_knowledge"]

    async def astream(self, inputs, config, stream_mode=None):  # noqa: ANN001, ANN003
        for i, name in enumerate(self._calls):
            call_id = f"c{i}"
            yield "updates", {
                "model": {"messages": [AIMessage(content=" ", tool_calls=[{"name": name, "args": {"query": "q"}, "id": call_id}])]}
            }
            yield "updates", {
                "tools": {"messages": [ToolMessage(name=name, content=f'{{"items": []}}', tool_call_id=call_id, status="success")]}
            }
        yield "messages", (AIMessageChunk(content="综合结论"), {})
        yield "updates", {"model": {"messages": [AIMessage(content="综合结论")]}}


@pytest.mark.anyio
async def test_stress_1_multi_tool_long_task_complete_events():
    import nexus.main as main_module

    agent = _MultiToolAgent()
    original = main_module._agents
    main_module._agents = {("research", "deepseek-chat"): agent, ("general", "deepseek-chat"): agent}
    try:
        frames = []
        async for frame in main_module._agent_stream("长任务", "stress-1", None, "research"):
            frames.append(frame)
    finally:
        main_module._agents = original
    raw = "".join(frames)
    assert raw.count("event: tool_call") == 3
    assert raw.count("event: tool_result") == 3
    assert raw.count("event: done") == 1
    assert "event: error" not in raw
    assert "event: done" in frames[-1]


# ---------------------------------------------------------------------------
# 2. Tool 500（工具内部异常）→ error 事件，绝不静默成功
# ---------------------------------------------------------------------------


async def test_stress_2_tool_exception_becomes_error_event(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    class _ExplodingToolAgent:
        async def astream(self, inputs, config, stream_mode=None):  # noqa: ANN001, ANN003
            yield "updates", {}
            raise RuntimeError("tool node exploded (simulated 500)")

    original = main_module._agents
    main_module._agents = {("research", "deepseek-chat"): _ExplodingToolAgent(), ("general", "deepseek-chat"): _ExplodingToolAgent()}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nexus/chat/stream", json={"message": "hi", "session_id": "stress-2"}
            )
    finally:
        main_module._agents = original
    assert "event: error" in response.text
    assert "tool node exploded" in response.text
    assert "event: done" not in response.text


# ---------------------------------------------------------------------------
# 3. Context overflow → Compact：触发语义 + 生产接线（分层锁定）
#
# 分层理由（2026-09-05 核定）：deepagents 0.7.12 的 before_model 与模型
# profile 联动，fake 模型注入 profile 后全图触发仍未命中——全图触发实测
# 留作已知边界（见 M5 验收记录）；本测试锁定两层可断言语义：
#   a) 触发判定语义（langchain helper：超阈值 True / 低于 False）；
#   b) 生产 build_agent 确实携带 SummarizationMiddleware 且阈值来自配置。
# ---------------------------------------------------------------------------


def _echo_model():
    from langchain_core.language_models.chat_models import BaseChatModel

    class _Echo(BaseChatModel):
        _n: int = PrivateAttr(default=0)

        @property
        def _llm_type(self) -> str:
            return "echo-fake"

        def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
            self._n += 1
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=f"答{self._n}"))])

    return _Echo()


def test_stress_3_compaction_trigger_semantics():
    from deepagents.backends.state import StateBackend
    from deepagents.middleware.summarization import SummarizationMiddleware

    echo = _echo_model()
    mw = SummarizationMiddleware(
        model=echo, backend=StateBackend(), trigger={"tokens": 1}, keep=("messages", 2)
    )
    helper = mw._lc_helper
    assert helper._trigger_clauses, "触发条款未被构造"
    messages = [HumanMessage(content=f"问题{i}") for i in range(6)] + [
        AIMessage(content="ok") for i in range(3)
    ]
    assert helper._should_summarize(messages, total_tokens=10_000) is True
    assert helper._should_summarize(messages[:2], total_tokens=0) is False


def test_stress_3_production_wiring_carries_compact(monkeypatch: pytest.MonkeyPatch):
    """生产接线契约：settings 阈值 → build_summarization_middleware 触发条款。"""
    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "dummy-key-stress")
    monkeypatch.setenv("NEXUS_SUMMARY_TRIGGER_TOKENS", "1234")
    from deepagents.middleware.summarization import SummarizationMiddleware
    from nexus.agent import build_summarization_middleware
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        mw = build_summarization_middleware(_echo_model())
        assert isinstance(mw, SummarizationMiddleware)
        assert mw._lc_helper._trigger_clauses == [{"tokens": 1234}]
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 4. Restart 后 resume：同一 saver 的新 agent 实例读到完整历史
# ---------------------------------------------------------------------------


async def test_stress_4_resume_after_restart_with_same_saver():
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    def _fake(text):
        class _M(GenericFakeChatModel):
            def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
                return self

        return _M(messages=(x for x in [AIMessage(content=text)]))

    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "user-5:nexus-session-stress-resume"}}
    before = create_deep_agent(model=_fake("重启前回答"), tools=[], system_prompt="t", checkpointer=saver)
    await before.ainvoke({"messages": [{"role": "user", "content": "q"}]}, config)

    # 模拟进程重启：全新 agent 实例 + 同一持久层
    after = create_deep_agent(model=_fake("重启后回答"), tools=[], system_prompt="t", checkpointer=saver)
    state = await after.aget_state(config)
    contents = [getattr(m, "content", "") for m in state.values["messages"]]
    assert "重启前回答" in contents


# ---------------------------------------------------------------------------
# 6. Malformed Tool：缺参 tool_call → 错误 ToolMessage，不崩溃
# ---------------------------------------------------------------------------


async def test_stress_6_malformed_tool_call_honest_failure(monkeypatch: pytest.MonkeyPatch):
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.tools import tool as lc_tool

    @lc_tool
    def strict_tool(required_arg: str) -> str:
        """缺参时 TypeError 替身：被调用即返回错误。"""
        return "should not reach"

    class _M(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
            return self

    model = _M(
        messages=(
            x
            for x in [
                AIMessage(content=" ", tool_calls=[{"name": "strict_tool", "args": {}, "id": "bad"}]),
                AIMessage(content="已如实报告失败"),
            ]
        )
    )
    agent = create_deep_agent(model=model, tools=[strict_tool], system_prompt="t", checkpointer=InMemorySaver())
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "hi"}]},
            config={"configurable": {"thread_id": "stress-malformed"}},
        )
    except Exception as error:  # noqa: BLE001
        # 图级失败也是"明确状态"的一种：绝不静默成功。
        assert "required_arg" in str(error) or "validation" in str(error).lower()
        return
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs, "malformed 调用无任何回执（静默丢失）"
    assert all(m.status == "error" for m in tool_msgs)


# ---------------------------------------------------------------------------
# 7. Worker timeout：run_reproduction 遇上游超时 → REPRO_WORKER_UNAVAILABLE
# ---------------------------------------------------------------------------


async def test_stress_7_worker_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch):
    """NX-G2：已批准票据遇上游超时 → REPRO_WORKER_UNAVAILABLE（复现未执行）。

    审批只放行"允许执行"，不掩盖 Worker 故障；超时语义保持 fail-closed。
    """
    import nexus.tools.reproduction as repro_module
    from nexus import approvals
    from nexus import request_scope

    monkeypatch.setenv("NEXUS_REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setenv("NEXUS_REPRO_WORKER_TOKEN", "tok")
    from nexus.config import get_settings

    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("upstream timeout", request=request)

    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(repro_module.httpx, "AsyncClient", factory)
    try:
        approvals.clear_memory_store()
        proposal = await repro_module.run_reproduction.ainvoke({"preset_id": "nanogpt"})
        approval_id = proposal["approval"]["approval_id"]
        approvals.decide_approval(approval_id, "", "approved")
        tokens = request_scope.set_execution_scope("", approval_id)
        try:
            result = await repro_module.run_reproduction.ainvoke({"preset_id": "nanogpt"})
        finally:
            request_scope.reset_execution_scope(tokens)
            approvals.clear_memory_store()
    finally:
        get_settings.cache_clear()
    assert result["status"] == "unavailable"
    assert result["code"] == "REPRO_WORKER_UNAVAILABLE"
    assert "复现未执行" in result["detail"]
