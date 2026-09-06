"""arXiv 论文检索工具（元数据，不下载 PDF）。

降级链（2026-09-03 冒烟后新增）：直连 arXiv API（境内服务器常不可达）→
SearXNG `site:arxiv.org` 限定检索 → 本机 DuckDuckGo 限定检索 → fail-closed。
沿用旧 ResearchAgent 的 arXiv API 礼仪：请求间隔 ≥3s、缓存 1 天、
失败不伪造。结果均为 `is_supplementary`，不得写入掌握度/课程事实。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from xml.etree import ElementTree

import httpx
from langchain_core.tools import tool

from nexus.config import get_settings
from nexus.tools.web_search import _ddg_search_sync

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV = "http://arxiv.org/schemas/atom"

_request_lock = asyncio.Lock()
_last_request_monotonic = 0.0
_MIN_INTERVAL_SECONDS = 3.0
_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 86400.0
_MAX_CACHE_ENTRIES = 200

_SEARXNG_TIMEOUT = 12.0
_ARXIV_URL_PATTERN = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#\"']+)", re.IGNORECASE)


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _build_arxiv_query(query: str) -> str:
    terms = [term.replace('"', " ").strip() for term in query.split()]
    terms = [term for term in terms if term][:12]
    return " AND ".join(f'all:"{term}"' for term in terms)


async def _respect_rate_limit_async() -> None:
    global _last_request_monotonic
    async with _request_lock:
        elapsed = time.monotonic() - _last_request_monotonic
        wait = _MIN_INTERVAL_SECONDS - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_monotonic = time.monotonic()


def _parse_feed(xml_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    namespaces = {"atom": _ATOM, "arxiv": _ARXIV}
    items: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", namespaces):
        source_url = _clean_text(entry.findtext("atom:id", default="", namespaces=namespaces))
        paper_id = source_url.rstrip("/").split("/")[-1] if source_url else ""
        links = entry.findall("atom:link", namespaces)
        alternate_url = next(
            (link.get("href", "") for link in links if link.get("rel") == "alternate"),
            source_url,
        )
        published_at = _clean_text(entry.findtext("atom:published", default="", namespaces=namespaces))
        items.append({
            "paper_id": paper_id,
            "title": _clean_text(entry.findtext("atom:title", default="", namespaces=namespaces)),
            "abstract": _clean_text(entry.findtext("atom:summary", default="", namespaces=namespaces)),
            "authors": [
                _clean_text(author.findtext("atom:name", default="", namespaces=namespaces))
                for author in entry.findall("atom:author", namespaces)
            ],
            "published_at": published_at,
            "year": int(published_at[:4]) if published_at[:4].isdigit() else None,
            "source_url": alternate_url,
            "primary_category": (
                entry.find("arxiv:primary_category", namespaces).get("term")
                if entry.find("arxiv:primary_category", namespaces) is not None
                else None
            ),
        })
    return items


def _extract_arxiv_id(url: str) -> str:
    """从 arXiv 链接提取论文 ID（abs/2401.12345v2、pdf/2401.12345 均可）。"""
    match = _ARXIV_URL_PATTERN.search(url or "")
    return match.group(1).rstrip("/.,;)") if match else ""


def _search_result_items(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """把搜索引擎（SearXNG/DuckDuckGo）结果过滤转换为论文条目。

    只保留能解析出 arXiv ID 的链接；摘要字段诚实置空（搜索片段不是论文摘要）。
    """
    items: list[dict[str, Any]] = []
    for raw in payload.get("results", []) or payload.get("items", []) or []:
        url = (raw.get("url") or raw.get("href") or "").strip()
        paper_id = _extract_arxiv_id(url)
        if not paper_id:
            continue
        items.append({
            "paper_id": paper_id,
            "title": _clean_text(raw.get("title")),
            "abstract": "",
            "authors": [],
            "published_at": None,
            "year": None,
            "source_url": url,
            "primary_category": None,
            "snippet": _clean_text(raw.get("content") or raw.get("body"))[:400],
        })
        if len(items) >= limit:
            break
    return items


async def _searxng_paper_search(query: str, limit: int) -> list[dict[str, Any]]:
    """SearXNG `site:arxiv.org` 限定检索（主降级通道，服务器自部署）。"""
    settings = get_settings()
    if not settings.searxng_url:
        return []
    params = {"q": f"site:arxiv.org {query}", "format": "json"}
    async with httpx.AsyncClient(timeout=_SEARXNG_TIMEOUT) as client:
        response = await client.get(f"{settings.searxng_url.rstrip('/')}/search", params=params)
        response.raise_for_status()
        return _search_result_items(response.json(), limit)


def _ddg_paper_search_sync(query: str, limit: int) -> list[dict[str, Any]]:
    """DuckDuckGo `site:arxiv.org` 限定检索（末位降级通道，复用 web_search 实现）。"""
    raw = _ddg_search_sync(f"site:arxiv.org {query}", limit)
    return _search_result_items(raw, limit)


async def _paper_fallback(query: str, limit: int) -> dict[str, Any] | None:
    """直连失败后的降级链：SearXNG → DuckDuckGo；全失败返回 None（fail-closed）。"""
    try:
        items = await _searxng_paper_search(query, limit)
        if items:
            return {
                "status": "success",
                "provider": "arxiv",
                "channel": "searxng",
                "degraded": True,
                "query": query,
                "items": items,
                "total": len(items),
                "is_supplementary": True,
            }
    except Exception as error:  # noqa: BLE001 - 通道失败降级，不中断
        logger.warning("SearXNG paper fallback failed: %s", type(error).__name__)

    settings = get_settings()
    if settings.ddgs_enabled:
        try:
            items = await asyncio.to_thread(_ddg_paper_search_sync, query, limit)
            if items:
                return {
                    "status": "success",
                    "provider": "arxiv",
                    "channel": "duckduckgo",
                    "degraded": True,
                    "query": query,
                    "items": items,
                    "total": len(items),
                    "is_supplementary": True,
                }
        except Exception as error:  # noqa: BLE001
            logger.warning("DuckDuckGo paper fallback failed: %s", type(error).__name__)
    return None


@tool
async def search_arxiv_papers(query: str, limit: int = 8) -> dict[str, Any]:
    """检索 arXiv 论文元数据（标题/摘要/作者/年份/链接）。

    用于论文调研与文献综述；返回元数据（未验证），标注为补充参考。
    直连 arXiv API 失败时自动降级到 SearXNG/DuckDuckGo 的 site:arxiv.org 检索。
    """
    normalized = _clean_text(query)
    if len(normalized) < 2:
        return {"status": "invalid_query", "error": "QUERY_TOO_SHORT", "items": [], "total": 0}
    safe_limit = min(max(int(limit), 1), 20)

    cache_key = (normalized.casefold(), safe_limit)
    cached = _cache.get(cache_key)
    if cached and cached[0] > time.monotonic():
        return {**cached[1], "cache_hit": True}

    try:
        await _respect_rate_limit_async()
        headers = {
            "Accept": "application/atom+xml",
            "User-Agent": "code-nexus-nexus-ai/0.1",
        }
        params = {
            "search_query": _build_arxiv_query(normalized),
            "start": 0,
            "max_results": safe_limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(ARXIV_API_URL, params=params, headers=headers)
            response.raise_for_status()
        items = _parse_feed(response.text)
    except Exception:  # noqa: BLE001 - 上游失败降级，不伪造
        fallback = await _paper_fallback(normalized, safe_limit)
        if fallback is not None:
            now = time.monotonic()
            _cache[cache_key] = (now + _CACHE_TTL_SECONDS, fallback)
            if len(_cache) > _MAX_CACHE_ENTRIES:
                for key in list(_cache)[: len(_cache) - _MAX_CACHE_ENTRIES]:
                    _cache.pop(key, None)
            return fallback
        return {
            "status": "upstream_unavailable",
            "error": "ARXIV_UNAVAILABLE",
            "query": normalized,
            "items": [],
            "total": 0,
            "is_supplementary": True,
        }

    payload = {
        "status": "success" if items else "no_results",
        "provider": "arxiv",
        "channel": "arxiv_api",
        "query": normalized,
        "items": items,
        "total": len(items),
        "is_supplementary": True,
    }
    now = time.monotonic()
    _cache[cache_key] = (now + _CACHE_TTL_SECONDS, payload)
    if len(_cache) > _MAX_CACHE_ENTRIES:
        for key in list(_cache)[: len(_cache) - _MAX_CACHE_ENTRIES]:
            _cache.pop(key, None)
    return payload
