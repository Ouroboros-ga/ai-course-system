"""M2 知识接入工具回归（全 mock，不连真实 Backend/PG/LLM）。

锁定三件事：
1. course_id 只信请求作用域（代理层注入），无绑定课程时 fail-closed；
2. 内部端点未配置/不可达/403 时如实返回错误码，绝不假造检索结果；
3. 成功路径的条目映射带权威标签（课程资料=经核实 / CS=权威来源），
   is_supplementary=False，与 web 检索的"补充参考"边界区分。
"""

import json
from contextlib import contextmanager

import httpx
import pytest

import nexus.tools.course_retrieval as cr
from nexus import request_scope
from nexus.tools.course_retrieval import search_course_materials, search_cs_knowledge

TOKEN = "test-internal-token"
URL = "http://127.0.0.1:8000"


@contextmanager
def _settings_ready(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", URL)
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", TOKEN)
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@contextmanager
def _mock_backend(handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cr.httpx, "AsyncClient", factory)
        yield


def _course_evidence_body() -> dict:
    return {
        "code": 200,
        "data": {
            "authority": "course",
            "course_id": 1,
            "items": [
                {
                    "evidence_id": "ev-1",
                    "resource_id": "doc-9",
                    "page": 3,
                    "text": "快速排序的平均复杂度为 O(n log n)。",
                    "node_key": "kn_1",
                    "citation_ids": ["c1"],
                }
            ],
        },
    }


def _cs_body() -> dict:
    return {
        "code": 200,
        "data": {
            "authority": "cs_kb",
            "items": [
                {
                    "id": "kb-hash-1",
                    "name": "哈希表",
                    "node_type": "concept",
                    "definition": "平均 O(1) 查找的键值映射结构。",
                    "source": "教材第 6 章",
                    "course": "数据结构与算法",
                }
            ],
        },
    }


async def test_course_search_requires_bound_course():
    """未绑定课程：fail-closed，绝不回退到"任意课程"。"""
    request_scope.set_scope("42", None)
    result = await search_course_materials.ainvoke({"query": "快速排序"})
    assert result["status"] == "no_course_context"
    assert result["code"] == "COURSE_CONTEXT_MISSING"
    assert result["items"] == []


async def test_course_search_fails_closed_when_unconfigured():
    request_scope.set_scope("42", 1)
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        result = await search_course_materials.ainvoke({"query": "快速排序"})
        assert result["code"] == "KNOWLEDGE_RETRIEVAL_UNCONFIGURED"
    finally:
        get_settings.cache_clear()


async def test_course_search_success_maps_items(monkeypatch: pytest.MonkeyPatch):
    with _settings_ready(monkeypatch), _mock_backend(
        lambda request: httpx.Response(200, json=_course_evidence_body())
    ) as _:
        request_scope.set_scope("42", 1)
        result = await search_course_materials.ainvoke({"query": "快速排序"})
    assert result["status"] == "success"
    assert result["authority_label"] == "课程资料（经核实）"
    assert result["is_supplementary"] is False
    assert result["items"][0]["evidence_id"] == "ev-1"


async def test_course_search_denied_maps_403(monkeypatch: pytest.MonkeyPatch):
    with _settings_ready(monkeypatch), _mock_backend(
        lambda request: httpx.Response(403, json={"detail": "denied"})
    ):
        request_scope.set_scope("42", 99)
        result = await search_course_materials.ainvoke({"query": "快速排序"})
    assert result["status"] == "rejected"
    assert result["code"] == "COURSE_ACCESS_DENIED"


async def test_course_search_unreachable_fails_closed(monkeypatch: pytest.MonkeyPatch):
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with _settings_ready(monkeypatch), _mock_backend(_boom):
        request_scope.set_scope("42", 1)
        result = await search_course_materials.ainvoke({"query": "快速排序"})
    assert result["code"] == "KNOWLEDGE_RETRIEVAL_UNAVAILABLE"
    assert result["items"] == []


async def test_internal_call_sends_identity_and_token(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["user"] = request.headers.get("X-Nexus-User-Id")
        seen["path"] = request.url.path
        return httpx.Response(200, json=_cs_body())

    with _settings_ready(monkeypatch), _mock_backend(handler):
        request_scope.set_scope("42", None)
        result = await search_cs_knowledge.ainvoke({"query": "哈希表"})
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert seen["user"] == "42"
    assert seen["path"] == "/api/v1/nexus-internal/cs-knowledge"
    assert result["authority_label"] == "CS 知识库（权威来源）"
    assert result["is_supplementary"] is False
    assert result["items"][0]["name"] == "哈希表"
    assert result["items"][0]["source"] == "教材第 6 章"


async def test_cs_search_works_without_course_binding(monkeypatch: pytest.MonkeyPatch):
    with _settings_ready(monkeypatch), _mock_backend(
        lambda request: httpx.Response(200, json=_cs_body())
    ):
        request_scope.set_scope("42", None)
        result = await search_cs_knowledge.ainvoke({"query": "哈希表"})
    assert result["status"] == "success"


def test_scope_reset_restores_defaults():
    tokens = request_scope.set_scope("7", 3)
    assert request_scope.current_user_id() == "7"
    assert request_scope.current_course_id() == 3
    request_scope.reset_scope(tokens)
    assert request_scope.current_user_id() is None
    assert request_scope.current_course_id() is None


def test_tool_surface_includes_retrieval_tools():
    """两工具已注册进产品工具面（M0-B1 收敛口径的增量）。"""
    from nexus.tools import NEXUS_TOOLS

    names = {t.name for t in NEXUS_TOOLS}
    assert {"search_course_materials", "search_cs_knowledge"} <= names
