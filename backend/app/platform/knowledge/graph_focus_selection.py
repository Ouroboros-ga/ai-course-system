"""重点节点筛选：把 GraphRAG 草稿图收敛到可教学审阅的核心规模。

GraphRAG 对单讲课件的抽取常产生大量近重复（"集合U/顶点集U/U顶点集"、
"PRIM算法/普里姆算法"）与微观实现细节（"元素0"、"U={0，5}"、
"LOWCOST[K]=0"、循环变量"顶点J"）。本模块在 identity reconcile 之后、
草稿落库之前做**确定性**收敛（无任何模型调用）：

1. 标题归并——同一概念的书写变体合并为一个节点（union 证据锚点与关系）；
2. 噪声剔除——赋值式公式、循环变量、单字泛概念等不可教学节点直接排除；
3. 重点打分——按（类型权重 × 关系度 + 证据锚点数）排序，截取目标规模；
4. 关系收敛——只保留两端都在入选集合内的关系，合并去重、去自环。

配置 ``GRAPHRAG_GRAPH_TARGET_NODES``（默认 0 = 关闭，保持原行为，fail-closed）。
被剔除的节点不进入草稿快照；其对应的 CANDIDATE 身份记录仍留在库中，
教师可在节点审核界面追溯。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

from app.services.graphrag_identity_service import ReconciledGraph

# 类型权重：方法/原理/概念是教学重点，公式/过程偏实现细节，
# 例子/思考题不承担图谱结构职责。
_TYPE_WEIGHTS: dict[str, float] = {
    "method": 1.2,
    "principle": 1.1,
    "concept": 1.0,
    "skill": 0.9,
    "misconception": 0.8,
    "procedure": 0.55,
    "formula": 0.5,
    "example": 0.2,
    "assessment": 0.1,
}

# 已知同义别名（小写）：英文缩写/音译/中文名 → 规范名（归并键形态）。
_ALIAS_MAP = {
    "prim": "普里姆",
    "最小代价数组": "lowcost数组",
    "最近顶点数组": "closest数组",
}

# 归并后仍是泛概念/无教学承担力的标题（merge_key 形态）。
_GENERIC_TITLES = {
    "输出", "调整", "命题", "最优结果", "遍历过程", "结果表达式",
    "顶点", "存储方法", "存储结构",
}

_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")
_STRIP_PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)
_SET_PREFIX_RE = re.compile(r"^(顶点集合|顶点集|集合)")
_TRAILING_VAR_RE = re.compile(r"(?<=[\u4e00-\u9fff])[a-z]$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _merge_key(title: str) -> str:
    """标题归并键：书写变体折叠到同一概念。"""
    text = unicodedata.normalize("NFKC", str(title or "")).casefold()
    text = _PAREN_RE.sub("", text)  # "普里姆（PRIM）算法" → "普里姆算法"
    text = _STRIP_PUNCT_RE.sub("", text)
    for alias, canonical in _ALIAS_MAP.items():
        text = text.replace(alias, canonical)
    text = _SET_PREFIX_RE.sub("", text)  # "顶点集合U/顶点集U/集合U" → "u"
    text = _TRAILING_VAR_RE.sub("", text)  # "带权连通图G" → "带权连通图"
    return text


def _title_quality(title: str) -> tuple[int, int, int]:
    """组内保留主标题的依据：中文字符数优先、非中文字符越少越好、再取更长。"""
    cjk = len(_CJK_RE.findall(title))
    return (cjk, -(len(title) - cjk), len(title))


def _is_noise(title: str, node_type: str, merge_key_value: str) -> bool:
    """不可教学的微观实体：循环变量、赋值式公式、单字泛概念等。"""
    key = merge_key_value
    raw = str(title or "")
    # 单字/双字符泛概念（图、边、树、顶点、集合、元素、u、k、vu）
    if len(key) <= 1:
        return True
    # 纯拉丁短标识（循环变量与数组下标：u、vu、k、j）
    if len(key) <= 3 and re.fullmatch(r"[a-z0-9\-]+", key):
        return True
    # 赋值/判断式伪公式（"U={0，5}"、"LOWCOST[K]=0"、"初始化条件U={V}"）
    if any(mark in raw for mark in ("=", "＝", "!=")):
        return True
    # 纯 ASCII 标识符形态的公式（"G.EDGES[K][J]"、"O(N2)"、"LOWCOST[K]"）
    if node_type == "formula" and re.fullmatch(r"[a-z0-9]+", key):
        return True
    # 循环变量与字面元素（"顶点J"、"元素0"）。注意顶点[a-z] 必须对原始
    # 标题判定：归并键已剥掉尾缀变量，会把"顶点J"误折成泛概念"顶点"。
    if re.fullmatch(r"顶点\s*[A-Za-z]", raw) or re.fullmatch(r"元素\d+", key):
        return True
    # 代码下标形态（"边 (J, CLOSEST[J])…"——标题携带数组下标即实现细节）
    if "[" in raw or "]" in raw:
        return True
    # 纯编程原语（"FOR循环"、"两重FOR循环"）
    if re.fullmatch(r"(两重)?for循环", key):
        return True
    return key in _GENERIC_TITLES


def _absorb(dst: dict, src: Mapping[str, Any]) -> None:
    """把 src 节点的证据与别名并入 dst（保留更优标题）。"""
    for field in ("source_anchor_ids", "source_text_unit_ids", "graphrag_entity_fingerprints"):
        dst[field] = sorted({*(dst.get(field) or []), *(src.get(field) or [])})
    dst["aliases"] = list(dict.fromkeys([*(dst.get("aliases") or []), *(src.get("aliases") or [])]))
    if len(str(src.get("description") or "")) > len(str(dst.get("description") or "")):
        dst["description"] = src.get("description")
    if _title_quality(str(src.get("title") or "")) > _title_quality(str(dst.get("title") or "")):
        dst["title"] = dst["label"] = src.get("title")


def apply_focus_selection(graph: ReconciledGraph, *, target: int) -> ReconciledGraph:
    """对 reconcile 产物做重点节点筛选；target<=0 时原样返回（fail-closed）。"""
    if target <= 0 or not graph.nodes:
        return graph

    # 1) 标题归并：变体折叠，证据/别名/关系端点随之合并。
    groups: dict[str, dict] = {}
    id_to_retained: dict[str, str] = {}
    for node in graph.nodes:
        key = _merge_key(str(node.get("title") or ""))
        if not key:
            continue
        retained = groups.get(key)
        if retained is None:
            retained = dict(node)
            groups[key] = retained
        else:
            _absorb(retained, node)
        id_to_retained[str(node.get("id"))] = str(retained["id"])
    merged_count = len(groups)

    # 2) 噪声剔除。
    kept: dict[str, dict] = {}
    noise_titles: list[str] = []
    for key, node in groups.items():
        if _is_noise(str(node.get("title") or ""), str(node.get("type") or ""), key):
            noise_titles.append(str(node.get("title") or ""))
        else:
            kept[key] = node
    kept_ids = {str(node["id"]) for node in kept.values()}

    # 3) 关系收敛：端点重映射到保留节点，去自环、去重复，锚点取并集。
    relations_by_edge: dict[tuple[str, str, str], dict] = {}
    for relation in graph.relations:
        source = id_to_retained.get(str(relation.get("source") or ""))
        target_id = id_to_retained.get(str(relation.get("target") or ""))
        if not source or not target_id:
            continue
        if source == target_id:
            continue
        if source not in kept_ids or target_id not in kept_ids:
            continue
        edge = (source, target_id, str(relation.get("type") or "RELATED_TO"))
        existing = relations_by_edge.get(edge)
        if existing is None:
            existing = dict(relation)
            existing["source"], existing["target"] = source, target_id
            relations_by_edge[edge] = existing
        else:
            existing["source_anchor_ids"] = sorted({
                *(existing.get("source_anchor_ids") or []),
                *(relation.get("source_anchor_ids") or []),
            })
            existing["confidence"] = max(
                float(existing.get("confidence") or 0.0),
                float(relation.get("confidence") or 0.0),
            )
    relations = list(relations_by_edge.values())

    # 4) 重点打分：类型权重 × (1+关系度) + 证据锚点加成。
    degree: dict[str, int] = {}
    for relation in relations:
        degree[relation["source"]] = degree.get(relation["source"], 0) + 1
        degree[relation["target"]] = degree.get(relation["target"], 0) + 1

    def _score(node: dict) -> float:
        weight = _TYPE_WEIGHTS.get(str(node.get("type") or "").lower(), 0.8)
        anchors = len(node.get("source_anchor_ids") or [])
        return weight * (1 + degree.get(str(node["id"]), 0)) + 0.2 * min(anchors, 10)

    ranked = sorted(kept.values(), key=lambda node: (-_score(node), str(node.get("title") or "")))
    selected = ranked[:target]
    selected_ids = {str(node["id"]) for node in selected}
    final_relations = [
        relation for relation in relations
        if relation["source"] in selected_ids and relation["target"] in selected_ids
    ]

    quality_report = {
        **graph.quality_report,
        "focus_selection": {
            "target": target,
            "source_node_count": len(graph.nodes),
            "merged_node_count": merged_count,
            "noise_filtered_count": len(noise_titles),
            "noise_filtered_titles": sorted(noise_titles)[:40],
            "selected_node_count": len(selected),
            "source_relation_count": len(graph.relations),
            "selected_relation_count": len(final_relations),
        },
    }
    return ReconciledGraph(
        tuple(selected),
        tuple(final_relations),
        quality_report,
    )


__all__ = ["apply_focus_selection"]
