import pytest
from httpx import ASGITransport, AsyncClient

from nexus.config import get_settings
from nexus.main import app


async def test_health_reports_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_SEARXNG_URL", "http://127.0.0.1:8888")
    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "test-key-for-health-flag-only")
    get_settings.cache_clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["llm_configured"] is True
        assert body["searxng_configured"] is True
        assert body["repro_worker_configured"] is False
        assert "key" not in str(body).lower() or "test-key" not in str(body)
    finally:
        get_settings.cache_clear()


async def test_health_checks_shape_and_probe_semantics(monkeypatch: pytest.MonkeyPatch):
    """NX-G3：checks 为带检查时间+有效期的快照；未配置→unconfigured，
    配了但连不上→degraded；绝不回传密钥与原始日志。"""
    import nexus.main as main_module

    monkeypatch.setenv("NEXUS_REPRO_WORKER_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()
    main_module._probe_cache.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        checks = response.json()["checks"]
        assert set(checks) == {"llm", "searxng", "repro_worker", "backend_internal"}
        for name, check in checks.items():
            assert set(check) == {"status", "checked_at", "ttl_s"}, name
            assert check["status"] in {"ok", "unconfigured", "degraded", "unknown"}, name
            assert check["checked_at"] > 0 and check["ttl_s"] >= 5
        # 本测试环境三依赖均未配置/不可达：
        assert checks["llm"]["status"] == "unconfigured"
        assert checks["searxng"]["status"] == "unconfigured"
        assert checks["backend_internal"]["status"] == "unconfigured"
        # Worker 配了 URL 但端口 9 必然拒绝连接 → degraded（不是 ok，更不是异常）。
        assert checks["repro_worker"]["status"] == "degraded"
        assert "127.0.0.1:9" not in response.text
    finally:
        get_settings.cache_clear()
        main_module._probe_cache.clear()


async def test_chat_fails_closed_without_llm_key():
    get_settings.cache_clear()
    import nexus.main as main_module

    main_module._agents = {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "hello", "session_id": "s1"},
        )
    assert response.status_code == 503
    assert "LLM_NOT_CONFIGURED" in response.json()["detail"]


async def test_chat_stream_fails_closed_without_llm_key():
    get_settings.cache_clear()
    import nexus.main as main_module

    main_module._agents = {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/nexus/chat/stream",
            json={"message": "hello", "session_id": "s1"},
        )
    assert response.status_code == 503


async def test_api_key_enforced_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_API_KEY", "secret-token")
    get_settings.cache_clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nexus/chat",
                json={"message": "hello"},
            )
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


async def test_chat_request_validation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/nexus/chat", json={"message": ""})
    assert response.status_code == 422


async def test_chat_endpoints_against_real_graph(monkeypatch: pytest.MonkeyPatch):
    """回归（2026-09-03 冒烟发现）：非流式 /chat 的 stream_mode 必须是列表形式。

    LangGraph 的 astream 在单字符串 stream_mode 下产出单值，代码按
    ``(mode, payload)`` 二元解包会抛 ValueError（线上 502）。本测试用真实
    deepagents 图 + 假模型（单轮直答、无工具调用）同时走通两个端点，且全程
    不调用真实 LLM。
    """
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver

    import nexus.main as main_module

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    def _fake_responses():
        """无限供给同一回复：deepagents 图可能多次调用模型，迭代器耗尽会以
        StopIteration（PEP 479 下为 RuntimeError）炸掉端点。"""
        while True:
            yield AIMessage(content="你好，我是 Nexus。")

    class _NoToolsFakeChatModel(GenericFakeChatModel):
        """deepagents 会对模型调用 bind_tools；假模型不支持原生工具，直接自返。"""

        def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
            return self

    fake_model = _NoToolsFakeChatModel(
        messages=_fake_responses()
    )
    agent = create_deep_agent(
        model=fake_model,
        tools=[],
        system_prompt="test-only prompt",
        checkpointer=InMemorySaver(),
    )
    original_agents = main_module._agents
    main_module._agents = {("research", "deepseek-chat"): agent, ("general", "deepseek-chat"): agent}
    get_settings.cache_clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nexus/chat",
                json={"message": "hi", "session_id": "regress-chat"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["session_id"] == "regress-chat"
            assert body["message"] == "你好，我是 Nexus。"
            assert body["tool_events"] == []

            stream = await client.post(
                "/api/v1/nexus/chat/stream",
                json={"message": "hi", "session_id": "regress-stream"},
            )
            assert stream.status_code == 200
            assert "event: token" in stream.text
            assert "event: done" in stream.text
    finally:
        main_module._agents = original_agents
        get_settings.cache_clear()
