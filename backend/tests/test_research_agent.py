"""ResearchAgent literature-search contracts and API isolation."""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx

from app.core.security import create_access_token, get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.platform.agents.providers.research.paper_search import ArxivPaperSearchProvider
from app.platform.agents.research.workflow import ResearchTools, build_research_workflow
from app.services.course_access_service import activate_student_membership, establish_course_access_baseline


ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2005.11401v4</id>
    <updated>2021-04-12T18:47:48Z</updated>
    <published>2020-05-22T17:10:46Z</published>
    <title>Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks</title>
    <summary>A retrieval-augmented generation baseline.</summary>
    <author><name>Patrick Lewis</name></author>
    <author><name>Ethan Perez</name></author>
    <category term="cs.CL" />
    <arxiv:primary_category term="cs.CL" />
    <link href="http://arxiv.org/abs/2005.11401v4" rel="alternate" type="text/html" />
    <link title="pdf" href="http://arxiv.org/pdf/2005.11401v4" rel="related" type="application/pdf" />
  </entry>
</feed>"""


def _user(session, name: str, role: UserRole) -> User:
    user = User(username=name, hashed_password=get_password_hash("test"), role=role, is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, owner: User, student: User | None = None) -> Course:
    course = Course(
        fanya_course_id=f"research-{owner.id}-{datetime.now().timestamp()}",
        fanya_course_name="Research",
        title="Research",
        teacher_id=owner.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, owner.id)
    if student is not None:
        activate_student_membership(session, course.id, student.id)
    session.commit()
    return course


def _token(user: User) -> str:
    return create_access_token({"sub": str(user.id), "username": user.username, "role": user.role.value})


def test_arxiv_provider_normalizes_and_stamps_metadata_only_results():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "export.arxiv.org"
        assert " AND " in request.url.params["search_query"]
        return httpx.Response(200, text=ARXIV_FEED, headers={"content-type": "application/atom+xml"})

    provider = ArxivPaperSearchProvider(
        transport=httpx.MockTransport(handler),
        minimum_interval_seconds=0,
    )
    result = asyncio.run(provider.search(query="retrieval augmented generation", limit=5))

    assert result["status"] == "success"
    assert result["total"] == 1
    paper = result["items"][0]
    assert paper["paper_id"] == "2005.11401v4"
    assert paper["provider"] == "arxiv"
    assert paper["evidence_status"] == "metadata_only"
    assert paper["is_supplementary"] is True
    assert paper["cannot_modify_mastery"] is True
    assert paper["cannot_modify_graph"] is True


def test_arxiv_provider_degrades_without_fabricating_results_on_transport_failure():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("network blocked")

    provider = ArxivPaperSearchProvider(
        transport=httpx.MockTransport(handler),
        minimum_interval_seconds=0,
    )
    result = asyncio.run(provider.search(query="retrieval augmented generation", limit=5))

    assert result["status"] == "upstream_unavailable"
    assert result["items"] == []
    assert result["warnings"] == ["ARXIV_UNAVAILABLE"]


def test_research_workflow_rejects_identity_only_query_without_calling_provider():
    provider = AsyncMock()
    scope_access = AsyncMock()
    graph = build_research_workflow(ResearchTools(
        scope_access=scope_access,
        paper_search=provider,
        workspace=AsyncMock(),
    ))
    state = asyncio.run(graph.ainvoke({
        "course_id": "1",
        "actor_user_id": "7",
        "query": "学号:20210001",
        "max_results": 8,
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }))

    assert state["status"] == "invalid_request"
    assert "RESEARCH_QUERY_TOO_SHORT" in state["errors"]
    scope_access.authorize.assert_not_called()
    provider.search.assert_not_called()


def test_research_workflow_rechecks_course_access_before_search():
    provider = AsyncMock()
    scope_access = AsyncMock()
    scope_access.authorize.return_value = {"allowed": False, "reason_code": "HTTPException"}
    graph = build_research_workflow(ResearchTools(
        scope_access=scope_access,
        paper_search=provider,
        workspace=AsyncMock(),
    ))
    state = asyncio.run(graph.ainvoke({
        "course_id": "1",
        "actor_user_id": "7",
        "query": "retrieval augmented generation",
        "max_results": 8,
        "warnings": [],
        "errors": [],
        "degraded_services": [],
        "trace": [],
    }))

    assert state["status"] == "invalid_request"
    assert "RESEARCH_SCOPE_DENIED" in state["errors"]
    scope_access.authorize.assert_awaited_once()
    provider.search.assert_not_called()


def test_research_api_requires_course_membership(client, session):
    owner = _user(session, "research_owner", UserRole.TEACHER)
    outsider = _user(session, "research_outsider", UserRole.STUDENT)
    course = _course(session, owner)

    response = client.post(
        f"/api/v1/research-agent/courses/{course.id}/search",
        json={"query": "retrieval augmented generation"},
        headers={"Authorization": f"Bearer {_token(outsider)}"},
    )
    assert response.status_code == 403


def test_research_api_returns_auditable_supplementary_results(client, session):
    owner = _user(session, "research_owner_ok", UserRole.TEACHER)
    student = _user(session, "research_student_ok", UserRole.STUDENT)
    course = _course(session, owner, student)
    provider_result = {
        "status": "success",
        "provider": "arxiv",
        "query": "retrieval augmented generation",
        "retrieved_at": "2026-08-07T12:00:00+08:00",
        "items": [{
            "provider": "arxiv",
            "paper_id": "2005.11401v4",
            "title": "Retrieval-Augmented Generation",
            "abstract": "Abstract",
            "authors": ["Patrick Lewis"],
            "published_at": "2020-05-22T17:10:46Z",
            "year": 2020,
            "source_url": "https://arxiv.org/abs/2005.11401",
            "pdf_url": "https://arxiv.org/pdf/2005.11401",
        }],
        "total": 1,
        "next_cursor": None,
        "cache_hit": False,
        "is_supplementary": True,
    }

    with patch.object(
        ArxivPaperSearchProvider,
        "search",
        new=AsyncMock(return_value=provider_result),
    ):
        response = client.post(
            f"/api/v1/research-agent/courses/{course.id}/search",
            json={"query": "retrieval augmented generation", "max_results": 5},
            headers={"Authorization": f"Bearer {_token(student)}"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "success"
    assert data["items"][0]["evidence_status"] == "metadata_only"
    assert data["source_policy"]["cannot_modify_mastery"] is True
    assert data["source_policy"]["cannot_modify_graph"] is True


def test_arxiv_provider_cache_is_bounded_and_prunes_expired_entries():
    """P2: the in-process cache must not grow without limit and must drop
    expired entries before evicting the oldest ones."""
    from app.platform.agents.providers.research.paper_search import (
        _CacheEntry,
        _MAX_CACHE_ENTRIES,
    )
    import time

    provider = ArxivPaperSearchProvider(minimum_interval_seconds=0)
    # Seed 60 entries with a fresh TTL and one expired entry.
    now = time.monotonic()
    for index in range(60):
        key = (f"query-{index}", 5, "0")
        provider._cache[key] = _CacheEntry(
            expires_at_monotonic=now + 3600,
            payload={"status": "success", "items": []},
        )
    expired_key = ("expired-query", 5, "0")
    provider._cache[expired_key] = _CacheEntry(
        expires_at_monotonic=now - 1,
        payload={"status": "success", "items": []},
    )

    provider._trim_cache(now_monotonic=now)

    assert expired_key not in provider._cache
    assert len(provider._cache) <= 60

    # Over-capacity pruning keeps the most recently inserted entries.
    for index in range(60, _MAX_CACHE_ENTRIES + 30):
        key = (f"query-{index}", 5, "0")
        provider._cache[key] = _CacheEntry(
            expires_at_monotonic=now + 3600,
            payload={"status": "success", "items": []},
        )
    provider._trim_cache(now_monotonic=now)
    assert len(provider._cache) <= _MAX_CACHE_ENTRIES
    assert ("query-0", 5, "0") not in provider._cache  # oldest evicted first
    assert (f"query-{_MAX_CACHE_ENTRIES + 29}", 5, "0") in provider._cache
