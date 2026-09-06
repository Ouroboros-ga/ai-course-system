"""P1-C2 会话列表与历史 API 回归（全 mock，不连真实 PG/LLM）."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from nexus.config import get_settings
from nexus.main import app, _title_from_message


def test_title_from_message_flattens_and_truncates():
    assert _title_from_message("  调研一下\n\nnanoGPT  论文 ") == "调研一下 nanoGPT 论文"
    assert _title_from_message("x" * 200) == "x" * 60
    assert _title_from_message("") == ""


async def test_list_sessions_memory_mode_returns_empty():
    get_settings.cache_clear()
    import nexus.main as main_module

    main_module._agents = {}
    main_module._pg_saver = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/nexus/sessions", headers={"X-Nexus-User-Id": "42"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body == {"persistence": "memory", "sessions": []}


async def test_list_sessions_scopes_to_requesting_user(monkeypatch: pytest.MonkeyPatch):
    """PG 启用时按 X-Nexus-User-Id 过滤，且透传 title/updated_at。"""
    import nexus.main as main_module

    monkeypatch.setenv("NEXUS_POSTGRES_DSN", "postgresql://u:p@127.0.0.1:5432/db")
    monkeypatch.setenv("NEXUS_API_KEY", "")
    get_settings.cache_clear()
    main_module._pg_saver = object()  # 仅表示"已启用持久化"，不触达真实 saver

    captured: dict = {}

    def _fake_list(dsn: str, schema: str, user_id: str, limit: int = 50):
        captured["dsn"] = dsn
        captured["user_id"] = user_id
        return [
            {"session_id": "s1", "title": "调研 nanoGPT", "updated_at": "2026-09-04T20:00:00+08:00"}
        ]

    import nexus.persistence as persistence_module

    monkeypatch.setattr(persistence_module, "list_user_threads_sync", _fake_list)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/nexus/sessions", headers={"X-Nexus-User-Id": "42"}
            )
        assert response.status_code == 200
        body = response.json()
        assert body["persistence"] == "postgres"
        assert body["sessions"][0]["session_id"] == "s1"
        assert body["sessions"][0]["title"] == "调研 nanoGPT"
        assert captured["user_id"] == "42"
        assert "127.0.0.1" in captured["dsn"]
    finally:
        main_module._pg_saver = None
        get_settings.cache_clear()


async def test_session_messages_from_real_checkpoint():
    """真实图 + InMemorySaver：对话后历史接口投影 user/assistant 文本。"""
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    import nexus.main as main_module

    monkeypatch_delenv = None

    def _fake_responses():
        while True:
            yield AIMessage(content="这是回答")

    class _NoToolsFake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    agent = create_deep_agent(
        model=_NoToolsFake(messages=_fake_responses()),
        tools=[],
        system_prompt="test",
        checkpointer=InMemorySaver(),
    )
    original = main_module._agents
    main_module._agents = {("research", "deepseek-chat"): agent, ("general", "deepseek-chat"): agent}
    main_module._pg_saver = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            chat = await client.post(
                "/api/v1/nexus/chat",
                json={"message": "你好", "session_id": "hist-1"},
                headers={"X-Nexus-User-Id": "77"},
            )
            assert chat.status_code == 200
            history = await client.get(
                "/api/v1/nexus/sessions/hist-1/messages",
                headers={"X-Nexus-User-Id": "77"},
            )
        assert history.status_code == 200
        body = history.json()
        assert body["session_id"] == "hist-1"
        assert body["messages"] == [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "这是回答"},
        ]
    finally:
        main_module._agents = original


async def test_session_messages_isolated_between_users():
    """同 session_id 不同用户 → 历史互不可见（thread 命名空间隔离）。"""
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    import nexus.main as main_module

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
    original = main_module._agents
    main_module._agents = {("research", "deepseek-chat"): agent, ("general", "deepseek-chat"): agent}
    main_module._pg_saver = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/v1/nexus/chat",
                json={"message": "只有用户 A 能看到", "session_id": "shared-2"},
                headers={"X-Nexus-User-Id": "A"},
            )
            other = await client.get(
                "/api/v1/nexus/sessions/shared-2/messages",
                headers={"X-Nexus-User-Id": "B"},
            )
        assert other.status_code == 200
        assert other.json()["messages"] == []
    finally:
        main_module._agents = original
