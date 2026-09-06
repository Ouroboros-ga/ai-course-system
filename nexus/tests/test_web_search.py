import httpx
import pytest
import respx
from importlib import import_module

web_search_module = import_module("nexus.tools.web_search")
web_search = web_search_module.web_search


def _searxng_response() -> dict:
    return {
        "results": [
            {"title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "content": "The Transformer", "engine": "yandex"},
            {"title": "nanoGPT", "url": "https://github.com/karpathy/nanoGPT", "content": "minimal GPT", "engine": "360search"},
        ],
        "unresponsive_engines": [],
    }


async def test_searxng_primary_channel_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_SEARXNG_URL", "http://127.0.0.1:8888")
    with respx.mock:
        respx.get("http://127.0.0.1:8888/search").mock(
            return_value=httpx.Response(200, json=_searxng_response())
        )
        result = await web_search.ainvoke({"query": "attention is all you need"})
    assert result["channel"] == "searxng"
    assert result["total"] == 2
    assert result["is_supplementary"] is True
    assert result["items"][0]["title"] == "Attention Is All You Need"


async def test_fallback_to_ddg_when_searxng_down(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_SEARXNG_URL", "http://127.0.0.1:8888")

    def fake_ddg(query: str, max_results: int) -> dict:
        return {
            "channel": "duckduckgo",
            "query": query,
            "items": [{"title": "DDG result", "url": "https://example.com", "snippet": "s"}],
            "total": 1,
            "is_supplementary": True,
        }

    monkeypatch.setattr(web_search_module, "_ddg_search_sync", fake_ddg)
    with respx.mock:
        respx.get("http://127.0.0.1:8888/search").mock(
            return_value=httpx.Response(502, text="bad gateway")
        )
        result = await web_search.ainvoke({"query": "machine learning"})
    assert result["channel"] == "duckduckgo"
    assert result["total"] == 1


async def test_both_channels_fail_reports_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_SEARXNG_URL", "http://127.0.0.1:8888")

    def failing_ddg(query: str, max_results: int) -> dict:
        raise RuntimeError("ddgs blocked")

    monkeypatch.setattr(web_search_module, "_ddg_search_sync", failing_ddg)
    with respx.mock:
        respx.get("http://127.0.0.1:8888/search").mock(
            return_value=httpx.Response(500, text="server error")
        )
        result = await web_search.ainvoke({"query": "test"})
    assert result["channel"] == "none"
    assert result["error"] == "WEB_SEARCH_UNAVAILABLE"
    assert result["total"] == 0


async def test_searxng_not_configured_skips_primary(monkeypatch: pytest.MonkeyPatch):
    def fake_ddg(query: str, max_results: int) -> dict:
        return {"channel": "duckduckgo", "query": query, "items": [], "total": 0, "is_supplementary": True}

    monkeypatch.setattr(web_search_module, "_ddg_search_sync", fake_ddg)
    result = await web_search.ainvoke({"query": "test"})
    assert result["channel"] == "duckduckgo"
