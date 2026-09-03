import httpx
import pytest
import respx

from nexus.tools import paper_search as paper_search_module
from nexus.tools.paper_search import search_arxiv_papers

_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All You Need</title>
    <summary>The dominant sequence transduction models are based on complex recurrent networks.</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <published>2017-06-12T17:57:34-04:00</published>
    <link rel="alternate" href="http://arxiv.org/abs/1706.03762v7"/>
    <link title="pdf" href="http://arxiv.org/pdf/1706.03762v7"/>
    <primary_category xmlns="http://arxiv.org/schemas/atom" term="cs.CL"/>
  </entry>
</feed>"""


async def test_arxiv_search_success():
    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(200, text=_ARXIV_XML)
        )
        result = await search_arxiv_papers.ainvoke({"query": "attention transformer"})
    assert result["status"] == "success"
    assert result["is_supplementary"] is True
    item = result["items"][0]
    assert item["paper_id"] == "1706.03762v7"
    assert item["title"] == "Attention Is All You Need"
    assert item["year"] == 2017
    assert item["primary_category"] == "cs.CL"


async def test_arxiv_upstream_failure_degrades(monkeypatch: pytest.MonkeyPatch):
    """无 SearXNG（conftest 已清空）且 DDG 关闭时，全链 fail-closed。"""
    monkeypatch.setenv("NEXUS_DDGS_ENABLED", "false")
    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(500, text="boom")
        )
        result = await search_arxiv_papers.ainvoke({"query": "llm survey"})
    assert result["status"] == "upstream_unavailable"
    assert result["error"] == "ARXIV_UNAVAILABLE"
    assert result["items"] == []


async def test_arxiv_short_query_rejected():
    result = await search_arxiv_papers.ainvoke({"query": "a"})
    assert result["status"] == "invalid_query"


# ---------------------------------------------------------------------------
# 降级链（2026-09-03 冒烟后新增）：直连 arXiv → SearXNG site:arxiv.org → DDG
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    paper_search_module._cache.clear()
    yield
    paper_search_module._cache.clear()


_SEARXNG_PAYLOAD = {
    "results": [
        {"title": "Language Models are Unsupervised Multitask Learners",
         "url": "https://arxiv.org/abs/1911.04252v2", "content": "GPT-2 paper page"},
        {"title": "not arxiv", "url": "https://example.com/other", "content": "should be filtered"},
        {"title": "pdf link", "url": "https://arxiv.org/pdf/2005.14165v4", "content": "GPT-3 paper"},
    ],
}


async def test_fallback_to_searxng_when_arxiv_direct_down(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_SEARXNG_URL", "http://127.0.0.1:8888")
    monkeypatch.setattr(paper_search_module, "_respect_rate_limit_async", lambda: _noop())
    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(500, text="boom")
        )
        respx.get("http://127.0.0.1:8888/search").mock(
            return_value=httpx.Response(200, json=_SEARXNG_PAYLOAD)
        )
        result = await search_arxiv_papers.ainvoke({"query": "gpt-2 language models"})

    assert result["status"] == "success"
    assert result["channel"] == "searxng"
    assert result["degraded"] is True
    assert result["is_supplementary"] is True
    ids = [item["paper_id"] for item in result["items"]]
    # 非 arXiv 链接被过滤；abs 与 pdf 链接都能解析出论文 ID。
    assert ids == ["1911.04252v2", "2005.14165v4"]
    assert result["items"][0]["title"].startswith("Language Models")


async def test_fallback_to_ddg_when_searxng_also_down(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_SEARXNG_URL", "http://127.0.0.1:8888")
    monkeypatch.setattr(paper_search_module, "_respect_rate_limit_async", lambda: _noop())

    def fake_ddg(query: str, max_results: int) -> dict:
        # patch 的是 web_search 的底层同步实现：真实 _ddg_paper_search_sync 会
        # 先拼上 site:arxiv.org 前缀再调用它。
        assert query.startswith("site:arxiv.org")
        return {"channel": "duckduckgo", "items": [
            {"title": "GPT-2 paper", "href": "https://arxiv.org/abs/1911.04252", "body": "s"},
        ]}

    monkeypatch.setattr(paper_search_module, "_ddg_search_sync", fake_ddg)
    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(500, text="boom")
        )
        respx.get("http://127.0.0.1:8888/search").mock(
            return_value=httpx.Response(500, text="boom")
        )
        result = await search_arxiv_papers.ainvoke({"query": "gpt-2 paper"})

    assert result["status"] == "success"
    assert result["channel"] == "duckduckgo"
    assert result["degraded"] is True
    assert result["items"][0]["paper_id"] == "1911.04252"


async def test_all_channels_down_stays_fail_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_SEARXNG_URL", "http://127.0.0.1:8888")
    monkeypatch.setattr(paper_search_module, "_respect_rate_limit_async", lambda: _noop())

    def failing_ddg(query: str, max_results: int) -> dict:
        raise RuntimeError("ddgs blocked")

    monkeypatch.setattr(paper_search_module, "_ddg_paper_search_sync", failing_ddg)
    with respx.mock:
        respx.get("https://export.arxiv.org/api/query").mock(
            return_value=httpx.Response(500, text="boom")
        )
        respx.get("http://127.0.0.1:8888/search").mock(
            return_value=httpx.Response(500, text="boom")
        )
        result = await search_arxiv_papers.ainvoke({"query": "no where to run"})

    assert result["status"] == "upstream_unavailable"
    assert result["error"] == "ARXIV_UNAVAILABLE"
    assert result["items"] == []


async def _noop() -> None:
    return None
