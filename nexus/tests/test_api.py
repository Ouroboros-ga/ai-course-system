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


async def test_chat_fails_closed_without_llm_key():
    get_settings.cache_clear()
    import nexus.main as main_module

    main_module._agent = None
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

    main_module._agent = None
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
