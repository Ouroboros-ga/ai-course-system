"""Course-scoped, supplementary web research with fail-closed egress."""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
from datetime import timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from app.core.time_utils import utcnow_naive
from app.models.web_research_model import (
    DEFAULT_ALLOWED_DOMAINS,
    WebResearchConfig,
    WebResearchResult,
    ExternalReference,
    ResearchStatus,
)

SENSITIVE_PATTERNS = [
    "student_id", "username", "password", "email", "phone", "token",
    "student number", "identity card", "mobile", "mailbox",
    "\u5b66\u53f7", "\u8eab\u4efd\u8bc1", "\u624b\u673a\u53f7", "\u90ae\u7bb1", "\u5bc6\u7801",
]
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
)


def sanitize_query(query: str) -> str:
    """Remove obvious identity data before a query can leave this process."""
    sanitized = query
    for pattern in SENSITIVE_PATTERNS:
        sanitized = re.sub(
            rf"{re.escape(pattern)}\s*[:\uff1a=]\s*\S+",
            "[REDACTED]",
            sanitized,
            flags=re.IGNORECASE,
        )
    for value_pattern in SENSITIVE_VALUE_PATTERNS:
        sanitized = value_pattern.sub("[REDACTED]", sanitized)
    return sanitized.strip()


def normalize_allowed_domains(domains: list[str]) -> list[str]:
    """Accept DNS domain names only; reject URLs, IP literals and wildcards."""
    normalized: set[str] = set()
    for raw in domains:
        value = str(raw).strip().lower().rstrip(".")
        if not value or "://" in value or any(ch in value for ch in "/*@:#?"):
            raise ValueError(f"invalid allowlist domain: {raw}")
        try:
            ipaddress.ip_address(value)
        except ValueError:
            pass
        else:
            raise ValueError("IP literals are not allowed in the domain allowlist")
        try:
            ascii_value = value.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError(f"invalid allowlist domain: {raw}") from exc
        if (
            len(ascii_value) > 253
            or "." not in ascii_value
            or any(
                not label
                or len(label) > 63
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
                for label in ascii_value.split(".")
            )
        ):
            raise ValueError(f"invalid allowlist domain: {raw}")
        normalized.add(ascii_value)
    return sorted(normalized)


def _trusted_result_domain(result: dict[str, Any]) -> Optional[str]:
    parsed = urlparse(str(result.get("source_url") or "").strip())
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    return parsed.hostname.lower().rstrip(".") if parsed.hostname else None


def _domain_allowed(domain: str, allowed_domains: list[str]) -> bool:
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains)


def get_or_create_config(session: Session, course_id: int) -> WebResearchConfig:
    config = session.exec(
        select(WebResearchConfig).where(WebResearchConfig.course_id == course_id)
    ).first()
    if config is None:
        config = WebResearchConfig(course_id=course_id, enabled=False)
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


def execute_research(
    session: Session, course_id: int, query: str, *, user_id: Optional[int] = None
) -> WebResearchResult:
    """Return only supplemental sources; it can never alter course facts."""
    config = get_or_create_config(session, course_id)
    sanitized_query = sanitize_query(query)
    if not config.enabled:
        return _create_result(session, course_id, sanitized_query, ResearchStatus.DISABLED, "disabled by teacher")

    query_hash = hashlib.sha256(sanitized_query.encode()).hexdigest()
    cached = _check_cache(session, course_id, query_hash)
    if cached:
        cached.status = ResearchStatus.CACHE_HIT
        session.add(cached)
        session.commit()
        return cached

    used = _count_recent_searches(session, course_id)
    if used >= config.search_budget_per_query:
        return _create_result(session, course_id, sanitized_query, ResearchStatus.BUDGET_EXCEEDED, "search budget exhausted")

    try:
        candidates = _perform_search(sanitized_query, config)
    except Exception:
        return _create_result(session, course_id, sanitized_query, ResearchStatus.SEARCH_FAILED, "provider unavailable")

    allowed = normalize_allowed_domains(config.allowed_domains or [])
    results = []
    for candidate in candidates:
        domain = _trusted_result_domain(candidate)
        if domain and _domain_allowed(domain, allowed):
            results.append({**candidate, "source_domain": domain})
    if not results:
        return _create_result(session, course_id, sanitized_query, ResearchStatus.NO_RESULTS, "no allowlisted source")

    result = WebResearchResult(
        course_id=course_id,
        query_hash=query_hash,
        query_text=sanitized_query,
        status=ResearchStatus.SUCCESS,
        results=results[:config.max_results_per_search],
        searches_used=1,
        expires_at=utcnow_naive() + timedelta(minutes=config.cache_ttl_minutes),
    )
    session.add(result)
    session.flush()
    for item in result.results:
        session.add(ExternalReference(
            course_id=course_id,
            research_result_id=result.id,
            source_domain=item["source_domain"],
            source_url=item.get("source_url", ""),
            title=item.get("title", ""),
            snippet=item.get("snippet", ""),
            purpose="supplementary_reference",
            is_supplementary=True,
        ))
    session.commit()
    session.refresh(result)
    return result


def _perform_search(query: str, config: WebResearchConfig) -> list[dict[str, Any]]:
    """Call only a reviewed HTTPS provider configured by the operator.

    The provider receives the sanitized query only. It is intentionally
    unavailable without both deployment settings; this avoids accidental
    egress to an arbitrary public search service.
    """
    endpoint = os.getenv("WEB_RESEARCH_PROVIDER_URL", "").strip()
    api_key = os.getenv("WEB_RESEARCH_PROVIDER_API_KEY", "").strip()
    if not endpoint or not api_key:
        raise RuntimeError("provider not configured")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("provider must use HTTPS")
    response = httpx.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"query": query, "limit": min(config.max_results_per_search, 20)},
        timeout=httpx.Timeout(8.0, connect=3.0),
        follow_redirects=False,
    )
    response.raise_for_status()
    payload = response.json()
    raw_results = payload.get("results", []) if isinstance(payload, dict) else []
    if not isinstance(raw_results, list):
        raise RuntimeError("invalid provider response")
    return [
        {
            "source_url": str(item.get("source_url") or item.get("url") or ""),
            "title": str(item.get("title") or "")[:500],
            "snippet": str(item.get("snippet") or item.get("content") or "")[:2000],
        }
        for item in raw_results if isinstance(item, dict)
    ]


def _check_cache(session: Session, course_id: int, query_hash: str) -> Optional[WebResearchResult]:
    cached = session.exec(
        select(WebResearchResult).where(
            WebResearchResult.course_id == course_id,
            WebResearchResult.query_hash == query_hash,
            WebResearchResult.status.in_([ResearchStatus.SUCCESS, ResearchStatus.CACHE_HIT]),
        )
    ).first()
    return cached if cached and not cached.is_expired else None


def _count_recent_searches(session: Session, course_id: int) -> int:
    recent = utcnow_naive() - timedelta(hours=1)
    records = session.exec(
        select(WebResearchResult).where(
            WebResearchResult.course_id == course_id,
            WebResearchResult.created_at >= recent,
            WebResearchResult.status.in_([ResearchStatus.SUCCESS, ResearchStatus.CACHE_HIT]),
        )
    ).all()
    return sum(record.searches_used for record in records)


def _create_result(
    session: Session, course_id: int, query: str, status: ResearchStatus, reason: str
) -> WebResearchResult:
    result = WebResearchResult(
        course_id=course_id,
        query_hash=hashlib.sha256(query.encode()).hexdigest() if query else "",
        query_text=query,
        status=status,
        failure_reason=reason,
        results=[],
        searches_used=0,
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def serialize_result(result: WebResearchResult) -> dict[str, Any]:
    return {
        "id": result.id, "course_id": result.course_id, "status": result.status.value,
        "failure_reason": result.failure_reason, "query_text": result.query_text,
        "results": result.results, "searches_used": result.searches_used,
        "is_supplementary": True, "cannot_modify_mastery": True,
        "cannot_modify_recommendation": True, "cannot_modify_graph": True,
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "expires_at": result.expires_at.isoformat() if result.expires_at else None,
    }


def serialize_config(config: WebResearchConfig) -> dict[str, Any]:
    return {
        "course_id": config.course_id, "enabled": config.enabled,
        "allowed_domains": config.allowed_domains,
        "search_budget_per_query": config.search_budget_per_query,
        "max_results_per_search": config.max_results_per_search,
        "cache_ttl_minutes": config.cache_ttl_minutes,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
