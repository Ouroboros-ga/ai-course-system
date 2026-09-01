"""graph_focus_selection 单元测试：归并去重、噪声剔除、重点打分、关系收敛。"""
from __future__ import annotations

from app.platform.knowledge.graph_focus_selection import apply_focus_selection
from app.services.graphrag_identity_service import ReconciledGraph


def _node(node_id: str, title: str, node_type: str = "concept", anchors: int = 2) -> dict:
    return {
        "id": node_id,
        "identity_id": 1,
        "title": title,
        "label": title,
        "aliases": [],
        "type": node_type,
        "description": f"{title} 的描述",
        "source_anchor_ids": [f"ea_{i}" for i in range(anchors)],
        "source_text_unit_ids": [f"tu_{i}" for i in range(anchors)],
        "graphrag_entity_fingerprints": [f"fp_{node_id}"],
    }


def _relation(source: str, target: str, rel_type: str = "RELATED_TO", anchors: int = 1) -> dict:
    return {
        "id": f"kr_{source}_{target}_{rel_type}",
        "source": source,
        "target": target,
        "type": rel_type,
        "description": "",
        "reason": "",
        "confidence": 0.9,
        "weight": 1.0,
        "source_anchor_ids": [f"ea_r{i}" for i in range(anchors)],
        "source_text_unit_ids": [],
    }


def _graph(nodes, relations) -> ReconciledGraph:
    return ReconciledGraph(tuple(nodes), tuple(relations), {"identity_policy": "test"})


def test_target_zero_is_passthrough():
    graph = _graph([_node("kn_1", "最小生成树")], [])
    result = apply_focus_selection(graph, target=0)
    assert result is graph


def test_merges_title_variants():
    nodes = [
        _node("kn_1", "PRIM算法", "method"),
        _node("kn_2", "普里姆算法", "method"),
        _node("kn_3", "普里姆（PRIM）算法", "method"),
        _node("kn_4", "最小生成树"),
        _node("kn_5", "最小生成树"),
    ]
    relations = [
        _relation("kn_1", "kn_4"),
        _relation("kn_2", "kn_5"),
    ]
    result = apply_focus_selection(_graph(nodes, relations), target=10)
    titles = {node["title"] for node in result.nodes}
    assert titles == {"普里姆算法", "最小生成树"}
    # 关系端点重映射到保留节点
    assert all(r["source"] in {n["id"] for n in result.nodes} for r in result.relations)
    assert all(r["target"] in {n["id"] for n in result.nodes} for r in result.relations)
    # 证据锚点取并集
    merged = next(n for n in result.nodes if n["title"] == "最小生成树")
    assert set(merged["source_anchor_ids"]) >= {"ea_0", "ea_1"}


def test_merges_set_prefix_variants():
    nodes = [
        _node("kn_1", "带权连通图"),
        _node("kn_2", "带权连通图G"),
        _node("kn_3", "生成树"),
    ]
    result = apply_focus_selection(_graph(nodes, []), target=10)
    titles = {node["title"] for node in result.nodes}
    assert titles == {"带权连通图", "生成树"}


def test_filters_noise_nodes():
    nodes = [
        _node("kn_1", "最小生成树"),
        _node("kn_2", "元素0"),
        _node("kn_3", "元素5"),
        _node("kn_4", "顶点J"),
        _node("kn_5", "U={0，5}", "formula"),
        _node("kn_6", "LOWCOST[K]=0", "formula"),
        _node("kn_7", "G.EDGES[K][J]", "formula"),
        _node("kn_8", "图"),
        _node("kn_9", "边"),
        _node("kn_10", "K（最近顶点编号）"),
        _node("kn_11", "思考题", "assessment"),
    ]
    result = apply_focus_selection(_graph(nodes, []), target=10)
    titles = {node["title"] for node in result.nodes}
    assert "最小生成树" in titles
    for noise in ("元素0", "顶点J", "U={0，5}", "LOWCOST[K]=0", "G.EDGES[K][J]", "图", "边"):
        assert noise not in titles


def test_selection_respects_target_and_prefers_high_degree():
    nodes = [_node(f"kn_{i}", f"概念{i}") for i in range(1, 51)]
    # 概念1 连接 10 个节点 → 度最高；其余度低
    relations = [_relation("kn_1", f"kn_{i}") for i in range(2, 12)]
    result = apply_focus_selection(_graph(nodes, relations), target=5)
    assert len(result.nodes) == 5
    ids = {node["id"] for node in result.nodes}
    assert "kn_1" in ids
    # 关系只保留两端都入选的
    assert all(r["source"] in ids and r["target"] in ids for r in result.relations)


def test_relations_to_dropped_nodes_removed_and_deduped():
    nodes = [
        _node("kn_1", "最小生成树"),
        _node("kn_2", "普里姆算法", "method"),
        _node("kn_3", "元素0"),  # 噪声，将被剔除
    ]
    relations = [
        _relation("kn_1", "kn_2", "uses"),
        _relation("kn_1", "kn_3"),  # 指向噪声节点 → 删除
        _relation("kn_1", "kn_2", "uses", anchors=2),  # 重复边 → 合并
    ]
    result = apply_focus_selection(_graph(nodes, relations), target=10)
    assert len(result.relations) == 1
    relation = result.relations[0]
    assert relation["source"] == "kn_1" and relation["target"] == "kn_2"
    assert len(relation["source_anchor_ids"]) == 2


def test_self_loop_after_merge_removed():
    nodes = [
        _node("kn_1", "PRIM算法", "method"),
        _node("kn_2", "普里姆算法", "method"),
    ]
    relations = [_relation("kn_1", "kn_2")]  # 合并后成为自环
    result = apply_focus_selection(_graph(nodes, relations), target=10)
    assert len(result.nodes) == 1
    assert len(result.relations) == 0


def test_quality_report_records_selection():
    nodes = [
        _node("kn_1", "最小生成树"),
        _node("kn_2", "元素0"),
        _node("kn_3", "最小生成树"),
    ]
    result = apply_focus_selection(_graph(nodes, []), target=10)
    report = result.quality_report["focus_selection"]
    assert report["source_node_count"] == 3
    assert report["merged_node_count"] == 2
    assert report["noise_filtered_count"] == 1
    assert report["selected_node_count"] == 1


def test_keeps_all_when_below_target():
    nodes = [_node("kn_1", "最小生成树"), _node("kn_2", "生成树")]
    result = apply_focus_selection(_graph(nodes, []), target=35)
    assert len(result.nodes) == 2
