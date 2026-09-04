import pytest

from nexus.config import get_settings


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_SEARXNG_URL", raising=False)
    monkeypatch.delenv("NEXUS_DDGS_ENABLED", raising=False)
    monkeypatch.delenv("NEXUS_REPRO_WORKER_URL", raising=False)
    monkeypatch.delenv("NEXUS_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("NEXUS_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("NEXUS_POSTGRES_SCHEMA", raising=False)
    monkeypatch.delenv("NEXUS_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("NEXUS_SUMMARY_TRIGGER_TOKENS", raising=False)
    monkeypatch.delenv("NEXUS_SUMMARY_KEEP_MESSAGES", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
