"""arXiv-backed scholarly metadata provider for ResearchAgent.

The provider follows arXiv's public API guidance: requests are serialized with
a three-second minimum interval, identical queries are cached for one day, and
the Atom response is normalized before it enters an agent workflow.  It does
not download PDFs or claim that metadata-only results have been verified.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import logging
import re
import time
from typing import Any, Mapping
from xml.etree import ElementTree

import httpx

from app.core.time_utils import utcnow_aware

from ...contracts.research import PaperSearchPort

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV = "http://arxiv.org/schemas/atom"
# Bound the in-process cache so a long-running server never grows without
# limit even under many distinct queries.
_MAX_CACHE_ENTRIES = 500


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _build_arxiv_query(query: str) -> str:
    """Build a conservative token-AND query instead of an over-strict phrase."""
    terms = [term.replace('"', " ").strip() for term in query.split()]
    terms = [term for term in terms if term][:12]
    return " AND ".join(f'all:"{term}"' for term in terms)


@dataclass(frozen=True)
class _CacheEntry:
    expires_at_monotonic: float
    payload: Mapping[str, Any]


class ArxivPaperSearchProvider(PaperSearchPort):
    """Search and normalize arXiv paper metadata with fail-closed degradation."""

    def __init__(
        self,
        *,
        api_url: str = ARXIV_API_URL,
        timeout_seconds: float = 15.0,
        minimum_interval_seconds: float = 3.0,
        cache_ttl_seconds: float = 86400.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_url = api_url
        self._timeout = timeout_seconds
        self._minimum_interval = minimum_interval_seconds
        self._cache_ttl = cache_ttl_seconds
        self._transport = transport
        self._request_lock = asyncio.Lock()
        self._last_request_monotonic = 0.0
        self._cache: "OrderedDict[tuple[str, int, str], _CacheEntry]" = OrderedDict()

    async def search(
        self,
        *,
        query: str,
        limit: int = 10,
        cursor: str | None = None,
    ) -> Mapping[str, Any]:
        normalized_query = _clean_text(query)
        safe_limit = min(max(int(limit), 1), 20)
        try:
            start = min(max(int(cursor or "0"), 0), 30000)
        except (TypeError, ValueError):
            start = 0
        if len(normalized_query) < 2:
            return self._failure("invalid_query", normalized_query, "QUERY_TOO_SHORT")

        cache_key = (normalized_query.casefold(), safe_limit, str(start))
        now_monotonic = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at_monotonic > now_monotonic:
            return {**dict(cached.payload), "cache_hit": True}

        try:
            await self._wait_for_request_slot()
            headers = {
                "Accept": "application/atom+xml",
                "User-Agent": "ai-course-system-research-preview/0.1",
            }
            params = {
                "search_query": _build_arxiv_query(normalized_query),
                "start": start,
                "max_results": safe_limit,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                transport=self._transport,
            ) as client:
                response = await client.get(self._api_url, params=params, headers=headers)
                response.raise_for_status()
            payload = self._parse_feed(
                response.text,
                query=normalized_query,
                start=start,
                limit=safe_limit,
            )
        except Exception as error:  # noqa: BLE001 - upstream failures degrade, never fabricate
            logger.info("arXiv paper search degraded: %s", type(error).__name__)
            return self._failure("upstream_unavailable", normalized_query, "ARXIV_UNAVAILABLE")

        self._cache[cache_key] = _CacheEntry(
            expires_at_monotonic=time.monotonic() + self._cache_ttl,
            payload=payload,
        )
        self._cache.move_to_end(cache_key)
        self._trim_cache(now_monotonic=time.monotonic())
        return payload

    def _trim_cache(self, *, now_monotonic: float) -> None:
        """Drop expired entries, then the oldest entries while over capacity."""
        expired = [
            key for key, entry in self._cache.items()
            if entry.expires_at_monotonic <= now_monotonic
        ]
        for key in expired:
            self._cache.pop(key, None)
        while len(self._cache) > _MAX_CACHE_ENTRIES:
            self._cache.popitem(last=False)

    async def _wait_for_request_slot(self) -> None:
        async with self._request_lock:
            elapsed = time.monotonic() - self._last_request_monotonic
            wait_seconds = self._minimum_interval - elapsed
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_monotonic = time.monotonic()

    @staticmethod
    def _parse_feed(xml_text: str, *, query: str, start: int, limit: int) -> Mapping[str, Any]:
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
            pdf_url = next(
                (link.get("href", "") for link in links if link.get("title") == "pdf"),
                "",
            )
            authors = [
                _clean_text(author.findtext("atom:name", default="", namespaces=namespaces))
                for author in entry.findall("atom:author", namespaces)
            ]
            authors = [author for author in authors if author]
            categories = [
                category.get("term", "")
                for category in entry.findall("atom:category", namespaces)
                if category.get("term")
            ]
            primary = entry.find("arxiv:primary_category", namespaces)
            published_at = _clean_text(entry.findtext("atom:published", default="", namespaces=namespaces))
            doi = _clean_text(entry.findtext("arxiv:doi", default="", namespaces=namespaces))
            items.append({
                "provider": "arxiv",
                "paper_id": paper_id,
                "title": _clean_text(entry.findtext("atom:title", default="", namespaces=namespaces)),
                "abstract": _clean_text(entry.findtext("atom:summary", default="", namespaces=namespaces)),
                "authors": authors,
                "published_at": published_at,
                "year": int(published_at[:4]) if published_at[:4].isdigit() else None,
                "updated_at": _clean_text(entry.findtext("atom:updated", default="", namespaces=namespaces)),
                "source_url": alternate_url,
                "pdf_url": pdf_url,
                "doi": doi or None,
                "categories": categories,
                "primary_category": primary.get("term") if primary is not None else None,
                "evidence_status": "metadata_only",
                "is_supplementary": True,
                "cannot_modify_mastery": True,
                "cannot_modify_recommendation": True,
                "cannot_modify_graph": True,
            })

        retrieved_at = utcnow_aware().isoformat()
        return {
            "status": "success" if items else "no_results",
            "provider": "arxiv",
            "query": query,
            "retrieved_at": retrieved_at,
            "items": items,
            "total": len(items),
            "next_cursor": str(start + len(items)) if len(items) == limit else None,
            "cache_hit": False,
            "is_supplementary": True,
        }

    @staticmethod
    def _failure(status: str, query: str, code: str) -> Mapping[str, Any]:
        return {
            "status": status,
            "provider": "arxiv",
            "query": query,
            "retrieved_at": utcnow_aware().isoformat(),
            "items": [],
            "total": 0,
            "next_cursor": None,
            "cache_hit": False,
            "warnings": [code],
            "is_supplementary": True,
        }


__all__ = ["ARXIV_API_URL", "ArxivPaperSearchProvider"]
