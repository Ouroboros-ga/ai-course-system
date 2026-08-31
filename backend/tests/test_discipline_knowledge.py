"""CS 学科垂类知识库服务与 API 测试（挑战杯 XH-202620）。

覆盖：服务层（检索排序、来源可追溯、节点/邻居、概览统计）与 API 契约
（鉴权、检索、节点、概览、重载）。全部本地数据，不调用任何外部服务。
"""
from __future__ import annotations

import pytest

from app.core.security import get_current_user
from app.platform.knowledge.discipline_kb import (
    get_knowledge_base,
    get_node,
    overview,
    search_nodes,
)

EXPECTED_NODE_COUNT = 112
EXPECTED_RELATION_COUNT = 106


# ---------------------------------------------------------------------------
# 服务层
# ---------------------------------------------------------------------------


def test_search_finds_hashtable_with_source():
    results = search_nodes("哈希表", top_k=3)
    assert results
    top = results[0]
    assert top["name"] == "哈希表"
    # 内容可追溯：结果必须携带权威来源
    assert top["source"]["title"]
    assert top["source"]["chapter"]


def test_search_english_terms_finds_quick_sort():
    results = search_nodes("quick sort", top_k=5)
    names = [r["name"] for r in results]
    assert "快速排序" in names


def test_search_english_hash_table():
    results = search_nodes("hash table", top_k=5)
    assert results[0]["name"] == "哈希表"


def test_search_os_concepts():
    results = search_nodes("虚拟内存", top_k=3)
    assert results[0]["name"] == "虚拟内存"
    assert results[0]["source"]["title"]

    results2 = search_nodes("进程调度", top_k=3)
    assert results2[0]["name"] == "进程调度"


def test_search_network_and_database_concepts():
    results = search_nodes("TCP 三次握手", top_k=3)
    assert results[0]["name"] == "TCP 三次握手与四次挥手"

    results2 = search_nodes("事务 ACID", top_k=3)
    assert results2[0]["name"] == "事务与 ACID"

    results3 = search_nodes("B+ 树索引", top_k=3)
    assert results3[0]["name"] == "索引与查询优化"


def test_search_se_and_ml_concepts():
    results = search_nodes("敏捷开发", top_k=3)
    assert results[0]["name"] == "敏捷开发与 DevOps"

    results2 = search_nodes("过拟合", top_k=3)
    assert results2[0]["name"] == "机器学习基本概念"

    results3 = search_nodes("随机森林", top_k=3)
    assert results3[0]["name"] == "决策树与集成学习"


def test_search_compiler_and_arch_concepts():
    results = search_nodes("词法分析", top_k=3)
    assert results[0]["name"] == "词法分析"

    results2 = search_nodes("IEEE 754", top_k=3)
    assert results2[0]["name"] == "数据表示与运算"

    results3 = search_nodes("流水线", top_k=3)
    assert results3[0]["name"] == "流水线"


def test_search_discrete_math_concepts():
    results = search_nodes("欧拉图", top_k=3)
    assert results[0]["name"] == "欧拉图与哈密顿图"

    results2 = search_nodes("等价关系", top_k=3)
    assert results2[0]["name"] == "二元关系与等价/偏序"

    results3 = search_nodes("数学归纳", top_k=3)
    assert results3[0]["name"] == "证明方法与数学归纳法"


def test_search_graphics_concepts():
    results = search_nodes("光线追踪", top_k=3)
    assert results[0]["name"] == "光线追踪与真实感渲染"

    results2 = search_nodes("齐次坐标", top_k=3)
    assert results2[0]["name"] == "几何变换与齐次坐标"

    results3 = search_nodes("z buffer", top_k=3)
    assert results3[0]["name"] == "消隐与可见面判定"


def test_new_courses_in_overview_and_neighbors():
    stats = overview()
    assert stats["courses"].get("离散数学") == 12
    assert stats["courses"].get("计算机图形学") == 10

    node = get_node("dm-009")
    outgoing = {nb["other_id"] for nb in node["neighbors"] if nb["direction"] == "outgoing"}
    assert {"ds-007", "algo-012"}.issubset(outgoing)


def test_search_ranked_by_relevance():
    results = search_nodes("动态规划", top_k=3)
    assert results[0]["name"] == "动态规划"
    assert results[0]["score"] >= results[-1]["score"]


def test_search_empty_or_no_match_returns_empty():
    assert search_nodes("") == []
    # 纯未知拉丁词元（不含中文通用单字），确保真正无匹配时返回空
    assert search_nodes("qqxzzz") == []
    assert search_nodes("   ") == []


def test_get_node_with_neighbors():
    node = get_node("ds-005")
    assert node["name"] == "哈希表"
    assert any(nb["relation_type"] == "uses" and nb["direction"] == "incoming" for nb in node["neighbors"])


def test_get_unknown_node_returns_none():
    assert get_node("no-such-id") is None


def test_overview_stats_match_data_files():
    stats = overview()
    assert stats["node_count"] == EXPECTED_NODE_COUNT
    assert stats["relation_count"] == EXPECTED_RELATION_COUNT
    assert stats["node_types"].get("concept", 0) >= 10
    assert stats["node_types"].get("method", 0) >= 10
    assert stats["courses"]  # 至少一门课程
    assert stats["version"]  # 数据版本指纹


def test_force_reload_reloads_knowledge_base():
    kb = get_knowledge_base(force_reload=True)
    assert len(kb.nodes) == EXPECTED_NODE_COUNT
    assert len(kb.relations) == EXPECTED_RELATION_COUNT


# ---------------------------------------------------------------------------
# API 契约
# ---------------------------------------------------------------------------


def test_api_search_requires_auth(client):
    resp = client.get("/api/v1/discipline-knowledge/search", params={"q": "哈希表"})
    assert resp.status_code in (401, 403)


def test_api_search_with_auth(fastapi_app, client):
    fastapi_app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "tester"}
    try:
        resp = client.get("/api/v1/discipline-knowledge/search", params={"q": "快速排序", "top_k": 3})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        assert data["query"] == "快速排序"
        assert data["results"][0]["name"] == "快速排序"
        assert data["results"][0]["source"]["title"]
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_api_get_node(fastapi_app, client):
    fastapi_app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "tester"}
    try:
        resp = client.get("/api/v1/discipline-knowledge/nodes/ds-007")
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "二叉树"

        missing = client.get("/api/v1/discipline-knowledge/nodes/not-exist")
        assert missing.status_code == 404
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_api_overview_and_reload(fastapi_app, client):
    fastapi_app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "tester"}
    try:
        resp = client.get("/api/v1/discipline-knowledge/overview")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["node_count"] == EXPECTED_NODE_COUNT

        reloaded = client.post("/api/v1/discipline-knowledge/reload")
        assert reloaded.status_code == 200
        assert reloaded.json()["data"]["node_count"] == EXPECTED_NODE_COUNT
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
