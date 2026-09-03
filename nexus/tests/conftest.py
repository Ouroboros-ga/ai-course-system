import pytest

from nexus.config import get_settings


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_SEARXNG_URL", raising=False)
    monkeypatch.delenv("NEXUS_DDGS_ENABLED", raising=False)
    monkeypatch.delenv("NEXUS_REPRO_WORKER_URL", raising=False)
    monkeypatch.delenv("NEXUS_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
