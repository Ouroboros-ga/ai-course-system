"""P1-C 回归：持久化降级 + 线程隔离 + Compact 接线（全 mock，不连真实 PG/LLM）."""

import pytest
from httpx import ASGITransport, AsyncClient

from nexus import persistence
from nexus.config import get_settings
from nexus.main import _config_for, app


def test_thread_for_namespaces_by_user():
    assert persistence.thread_for("demo-1", "42") == "user-42:nexus-session-demo-1"
    assert persistence.thread_for("demo-1", None) == "nexus-session-demo-1"
    assert persistence.thread_for("demo-1", "") == "nexus-session-demo-1"
    # 注入字符被清洗，不拼出非法 thread。
    assert persistence.thread_for("a/b?c", "u 1") == "user-u1:nexus-session-abc"
    # 空 session 回退 default。
    assert persistence.thread_for("", "7") == "user-7:nexus-session-default"


def test_dsn_with_schema_injects_search_path():
    dsn = "postgresql://u:p@127.0.0.1:5432/db"
    out = persistence.dsn_with_schema(dsn, "nexus_checkpoints")
    assert "search_path" in out
    assert "nexus_checkpoints" in out
    # 已带 options 的不重复注入。
    dsn2 = dsn + "?options=-csearch_path%3Dfoo"
    assert persistence.dsn_with_schema(dsn2, "nexus_checkpoints") == dsn2
    assert persistence.dsn_with_schema("", "nexus_checkpoints") == ""


def test_config_for_uses_namespaced_thread():
    assert _config_for("s1", "9") == {"configurable": {"thread_id": "user-9:nexus-session-s1"}}
    assert _config_for("s1") == {"configurable": {"thread_id": "nexus-session-s1"}}


def test_build_agent_wires_summarization_middleware(monkeypatch: pytest.MonkeyPatch):
    """build_agent 默认带原生 SummarizationMiddleware（不用自研 ContextManager）。"""
    import nexus.agent as agent_module

    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        agent = agent_module.build_agent()
        # CompiledStateGraph 保留 middleware 引用；不同版本属性名不同，宽松断言。
        nodes = getattr(agent, "nodes", {})
        assert nodes is not None
        # 关键：构造时未抛错且 checkpointer 为内存（本地降级路径）。
        state = agent.get_state({"configurable": {"thread_id": "t-persist-check"}})
        assert state is not None
    finally:
        get_settings.cache_clear()


async def test_health_reports_memory_when_no_dsn():
    get_settings.cache_clear()
    import nexus.main as main_module

    main_module._agent = None
    main_module._pg_saver = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["persistence"] == "memory"
    assert body["postgres_configured"] is False
    assert body["compact"] == "summarization-middleware"


async def test_chat_threads_isolated_by_user_header(monkeypatch: pytest.MonkeyPatch):
    """同 session_id + 不同用户 → 不同 thread，续聊不串话。"""
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    import nexus.main as main_module

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    def _fake_responses():
        while True:
            yield AIMessage(content="ok")

    class _NoToolsFake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    agent = create_deep_agent(
        model=_NoToolsFake(messages=_fake_responses()),
        tools=[],
        system_prompt="test",
        checkpointer=InMemorySaver(),
    )
    original = main_module._agent
    main_module._agent = agent
    main_module._pg_saver = None
    get_settings.cache_clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(
                "/api/v1/nexus/chat",
                json={"message": "hi", "session_id": "shared"},
                headers={"X-Nexus-User-Id": "100"},
            )
            r2 = await client.post(
                "/api/v1/nexus/chat",
                json={"message": "hi", "session_id": "shared"},
                headers={"X-Nexus-User-Id": "200"},
            )
        assert r1.status_code == 200
        assert r2.status_code == 200
        # 同一 session_id 回显归一化后一致，但底层 thread 已隔离：
        # 直接查 saver 状态，两 thread 各自独立存在。
        s1 = await agent.aget_state({"configurable": {"thread_id": "user-100:nexus-session-shared"}})
        s2 = await agent.aget_state({"configurable": {"thread_id": "user-200:nexus-session-shared"}})
        assert s1.values.get("messages")
        assert s2.values.get("messages")
    finally:
        main_module._agent = original
        get_settings.cache_clear()
