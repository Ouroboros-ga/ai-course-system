"""Web Search 工具：SearXNG 主通道（服务器自部署）+ 本机 DuckDuckGo 降级。

检索结果一律为"补充参考"（AGENTS.md §4.1.5）：不写入掌握度/课程事实/图谱，
Agent 消费时必须标注来源为 Web 检索。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from langchain_core.tools import tool

from nexus.config import get_settings

logger = logging.getLogger(__name__)

_SEARXNG_TIMEOUT = 12.0
_MAX_RESULTS_CAP = 15


def _normalize_searxng(payload: dict[str, Any], *, query: str) -> dict[str, Any]:
    results = payload.get("results", [])[:_MAX_RESULTS_CAP]
    items = [
        {
            "title": (item.get("title") or "").strip(),
            "url": item.get("url") or "",
            "snippet": (item.get("content") or "").strip()[:400],
            "engine": item.get("engine") or "",
        }
        for item in results
    ]
    unresponsive = payload.get("unresponsive_engines") or []
    return {
        "channel": "searxng",
        "query": query,
        "items": [item for item in items if item["title"] or item["url"]],
        "total": len(items),
        "unresponsive_engines": unresponsive if unresponsive else [],
        "is_supplementary": True,
    }


async def _searxng_search(query: str, max_results: int) -> dict[str, Any]:
    settings = get_settings()
    if not settings.searxng_url:
        return {"channel": "searxng", "skipped": "NEXUS_SEARXNG_URL not configured"}
    params = {"q": query, "format": "json"}
    async with httpx.AsyncClient(timeout=_SEARXNG_TIMEOUT) as client:
        response = await client.get(f"{settings.searxng_url.rstrip('/')}/search", params=params)
        response.raise_for_status()
        payload = response.json()
    normalized = _normalize_searxng(payload, query=query)
    normalized["items"] = normalized["items"][:max_results]
    normalized["total"] = len(normalized["items"])
    return normalized


def _ddg_search_sync(query: str, max_results: int) -> dict[str, Any]:
    from duckduckgo_search import DDGS

    raw = DDGS().text(query, max_results=max_results)
    items = [
        {
            "title": (item.get("title") or "").strip(),
            "url": item.get("href") or item.get("url") or "",
            "snippet": (item.get("body") or "").strip()[:400],
        }
        for item in raw
    ]
    return {
        "channel": "duckduckgo",
        "query": query,
        "items": items,
        "total": len(items),
        "is_supplementary": True,
    }


async def _ddg_search(query: str, max_results: int) -> dict[str, Any]:
    return await asyncio.to_thread(_ddg_search_sync, query, max_results)


@tool
async def web_search(query: str, max_results: int = 8) -> dict[str, Any]:
    """搜索互联网，获取论文/技术/新闻等公开信息。

    主通道为服务器自部署 SearXNG；不可用时降级为本机 DuckDuckGo。
    返回结果是"补充参考"，未经核实，不得直接当作已验证事实。
    """
    safe_limit = min(max(int(max_results), 1), _MAX_RESULTS_CAP)
    settings = get_settings()
    primary = None
    try:
        primary = await _searxng_search(query, safe_limit)
        if primary.get("total"):
            return primary
    except Exception as error:  # noqa: BLE001 - 通道失败降级，不中断
        logger.warning("SearXNG search failed: %s", type(error).__name__)
        primary = None

    if not settings.ddgs_enabled:
        return {
            "channel": "none",
            "query": query,
            "items": [],
            "total": 0,
            "error": "WEB_SEARCH_UNAVAILABLE",
            "detail": "SearXNG failed and local DuckDuckGo fallback is disabled",
            "is_supplementary": True,
        }

    try:
        fallback = await _ddg_search(query, safe_limit)
    except Exception as error:  # noqa: BLE001 - 双通道全失败，如实报告
        logger.warning("DuckDuckGo fallback failed: %s", type(error).__name__)
        return {
            "channel": "none",
            "query": query,
            "items": [],
            "total": 0,
            "error": "WEB_SEARCH_UNAVAILABLE",
            "detail": f"both channels failed ({type(primary).__name__ if primary is None else 'no-results'}, ddgs={type(error).__name__})",
            "is_supplementary": True,
        }

    if primary is not None:
        fallback["searxng_had_no_results"] = True
    return fallback
