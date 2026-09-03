"""arXiv 论文检索工具（元数据，不下载 PDF）。

沿用旧 ResearchAgent 的 arXiv API 礼仪：请求间隔 ≥3s、缓存 1 天、
fail-closed 降级不伪造。结果均为 `is_supplementary`，不得写入掌握度/课程事实。
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from xml.etree import ElementTree

import httpx
from langchain_core.tools import tool

ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV = "http://arxiv.org/schemas/atom"

_request_lock = asyncio.Lock()
_last_request_monotonic = 0.0
_MIN_INTERVAL_SECONDS = 3.0
_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 86400.0
_MAX_CACHE_ENTRIES = 200


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _build_arxiv_query(query: str) -> str:
    terms = [term.replace('"', " ").strip() for term in query.split()]
    terms = [term for term in terms if term][:12]
    return " AND ".join(f'all:"{term}"' for term in terms)


async def _respect_rate_limit() -> None:
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


@tool
async def search_arxiv_papers(query: str, limit: int = 8) -> dict[str, Any]:
    """检索 arXiv 论文元数据（标题/摘要/作者/年份/链接）。

    用于论文调研与文献综述；返回元数据（未验证），标注为补充参考。
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
        await _respect_rate_limit()
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
