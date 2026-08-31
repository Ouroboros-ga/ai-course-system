"""CS 学科垂类知识库检索服务（挑战杯 XH-202620）。

加载 ``knowledge_data/`` 下的学科知识 JSON（节点 + 关系），提供：
- 关键词检索（含来源引用的可追溯结果）
- 节点查询与图邻居查询
- 知识库概览统计

诚实边界：本服务是**独立可运行的学科知识层**，数据来自公开教材内容摘要
（见 ``knowledge_data/README.md``）；它不冒充已接入课程检索白名单——
与 ``ActiveBundleCourseRetrievalPort`` 的接线属于后续集成目标。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "cs-knowledge/1.0"

NODE_FILES = ("data_structures.json", "algorithms.json", "os.json", "net.json", "db.json", "se.json", "ml.json", "compiler.json", "arch.json", "discrete.json", "graphics.json")
RELATION_FILE = "relations.json"

_TOKEN_RE = re.compile(r"[a-z0-9_+.-]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_NAME_WEIGHT = 3.0
_ALIAS_WEIGHT = 2.5
_DEFINITION_WEIGHT = 2.0
_KEYPOINT_WEIGHT = 1.0
_EXAMPLE_WEIGHT = 0.5

# 教学口语化查询中的无信息量引导词（出现即剥离，避免其参与二元组匹配）。
_QUERY_NOISE_WORDS = (
    "如何", "怎么", "怎样", "什么", "为什么", "请问", "解释", "讲解",
    "讲清楚", "说明", "介绍一下", "介绍", "学生", "学生们", "同学",
    "老师", "给我", "帮我", "理解", "区分",
)

# 精确命中 name/alias 的概念置顶加成（对比类查询"堆和栈的区别"依赖此规则）。
_EXACT_CONCEPT_BONUS = 1e6

# 查询精确命中某概念时，与该概念同课程的节点得分加成：
# 同课程节点更可能是教学相关的姊妹概念（如"动态规划"→"贪心算法"），
# 压制其他课程仅靠偶然单字命中（"动作"/"状态"中的"动"/"态"）的节点。
_SAME_COURSE_BOOST = 1.5


@dataclass(frozen=True)
class KnowledgeNode:
    id: str
    name: str
    node_type: str
    definition: str
    key_points: tuple[str, ...]
    example: str
    aliases: tuple[str, ...]
    source: dict[str, str]
    course: str
    file: str


@dataclass(frozen=True)
class KnowledgeRelation:
    from_id: str
    to_id: str
    relation_type: str
    note: str


@dataclass
class KnowledgeBase:
    nodes: dict[str, KnowledgeNode] = field(default_factory=dict)
    relations: list[KnowledgeRelation] = field(default_factory=list)
    version: str = ""


def _resolve_knowledge_data_dir() -> Path:
    """优先 env 覆盖，其次沿仓库目录向上查找 knowledge_data/。"""
    import os

    override = os.environ.get("KNOWLEDGE_DATA_DIR")
    if override:
        return Path(override).resolve()
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / "knowledge_data"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("找不到 knowledge_data/ 目录（可设置 KNOWLEDGE_DATA_DIR 覆盖）")


def _tokenize(text: str) -> list[str]:
    """英文词元 + CJK 单字 + CJK 二元组（二元组提升短语匹配精度）。"""
    text = text.lower()
    tokens = _TOKEN_RE.findall(text)
    cjk = _CJK_RE.findall(text)
    tokens.extend(cjk)
    tokens.extend(a + b for a, b in zip(cjk, cjk[1:]))
    return tokens


def _content_fingerprint(kb_dir: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    for filename in (*NODE_FILES, RELATION_FILE):
        path = kb_dir / filename
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def load_knowledge_base(kb_dir: Path | None = None) -> KnowledgeBase:
    """加载知识库；文件缺失时对缺失文件降级（空），不整体崩溃。"""
    directory = kb_dir or _resolve_knowledge_data_dir()
    kb = KnowledgeBase()
    kb.version = _content_fingerprint(directory)

    for filename in NODE_FILES:
        path = directory / filename
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        course = data.get("course", "")
        for node in data.get("nodes", []):
            nid = node.get("id", "")
            if not nid:
                continue
            source = node.get("source") or {}
            kb.nodes[nid] = KnowledgeNode(
                id=nid,
                name=node.get("name", ""),
                node_type=node.get("node_type", ""),
                definition=node.get("definition", ""),
                key_points=tuple(node.get("key_points", [])),
                example=node.get("example", ""),
                aliases=tuple(node.get("aliases", [])),
                source={
                    "title": source.get("title", ""),
                    "authors": source.get("authors", ""),
                    "chapter": source.get("chapter", ""),
                },
                course=course,
                file=filename,
            )

    rel_path = directory / RELATION_FILE
    if rel_path.exists():
        data = json.loads(rel_path.read_text(encoding="utf-8"))
        for rel in data.get("relations", []):
            kb.relations.append(
                KnowledgeRelation(
                    from_id=rel.get("from", ""),
                    to_id=rel.get("to", ""),
                    relation_type=rel.get("relation_type", ""),
                    note=rel.get("note", ""),
                )
            )
    return kb


@lru_cache(maxsize=1)
def _kb_cache() -> KnowledgeBase:
    return load_knowledge_base()


def get_knowledge_base(force_reload: bool = False) -> KnowledgeBase:
    """带缓存的入口；force_reload 用于数据文件更新后刷新。"""
    if force_reload:
        _kb_cache.cache_clear()
    return _kb_cache()


def _document_terms(node: KnowledgeNode) -> dict[str, float]:
    terms: dict[str, float] = {}
    fields = (
        (node.name, _NAME_WEIGHT),
        (" ".join(node.aliases), _ALIAS_WEIGHT),
        (node.definition, _DEFINITION_WEIGHT),
        (" ".join(node.key_points), _KEYPOINT_WEIGHT),
        (node.example, _EXAMPLE_WEIGHT),
    )
    for text, weight in fields:
        for token in _tokenize(text):
            terms[token] = terms.get(token, 0.0) + weight
    return terms


def _inverse_doc_frequency(nodes: dict[str, KnowledgeNode]) -> dict[str, float]:
    doc_freq: dict[str, int] = {}
    for node in nodes.values():
        for token in _document_terms(node):
            doc_freq[token] = doc_freq.get(token, 0) + 1
    n = max(len(nodes), 1)
    return {token: math.log(1.0 + n / (1 + freq)) for token, freq in doc_freq.items()}


def _strip_query_noise(query: str) -> str:
    """剥离教学口语化查询中的无信息量引导词，保留概念性内容。

    剥离后为空（如"如何理解"）时返回空串，由调用方判定为无效查询。
    长引导词先于短引导词剥离，避免"学生们"被"学生"截断残留"们"。
    """
    cleaned = query
    for word in sorted(_QUERY_NOISE_WORDS, key=len, reverse=True):
        cleaned = cleaned.replace(word, " ")
    return cleaned.strip()


def _has_standalone_occurrence(
    query: str, pattern: str, all_patterns: list[str],
) -> bool:
    """判断 pattern 在 query 中是否至少出现一次"独立"出现。

    独立 = 出现位置左右各 2 字的窗口不是任何其他概念名/别名的子串。
    用于避免单字泛概念误命中："B+ 树索引"中的"树"右侧窗口"索引"
    属于"索引与查询优化"，"欧拉图"中的"图"左侧窗口"欧拉"属于
    "欧拉图与哈密顿图"——这些是复合词内部成分，不算精确命中；
    而"堆和栈的区别"中的"堆""栈"窗口不属于任何概念，算精确命中。
    """
    start = query.find(pattern)
    while start != -1:
        end = start + len(pattern)
        left = query[max(0, start - 2):start]
        right = query[end:end + 2]
        embedded = any(
            (left and left in other) or (right and right in other)
            for other in all_patterns
            if other != pattern
        )
        if not embedded:
            return True
        start = query.find(pattern, start + 1)
    return False


def _match_concepts(kb: KnowledgeBase, query: str) -> list[str]:
    """返回查询中精确命中的概念节点 id（name/alias 独立出现在查询中）。

    用于对比类查询（如"堆和栈的区别"）：把被明确提及的概念置顶，
    修复纯关键词打分下"堆排序"这类同字前缀节点挤掉次概念的问题；
    同时通过独立出现检查，避免"B+ 树索引"误命中"树"这类单字泛概念。
    """
    patterns: dict[str, list[str]] = {
        node.id: [p for p in (node.name, *node.aliases) if p]
        for node in kb.nodes.values()
    }
    all_patterns = [p for ps in patterns.values() for p in ps]
    matched: list[str] = []
    for node in kb.nodes.values():
        if any(
            _has_standalone_occurrence(query, p, all_patterns)
            for p in patterns[node.id]
        ):
            matched.append(node.id)
    return matched


def search_nodes(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """BM25 风格关键词检索（CJK 单字 + 英文词元），返回带来源与相关性分数的结果。

    排序规则：
    1. 查询中独立出现的概念（name/alias 精确命中）置顶，按 name 长度降序
       （更具体的匹配优先）；
    2. 精确命中某概念时，同课程节点（教学上的姊妹概念）得分乘以加成；
    3. 其余按关键词相关性分数排序。
    """
    kb = get_knowledge_base()
    query = str(query or "").strip()
    if not query:
        return []
    exact_ids = set(_match_concepts(kb, query))
    cleaned = _strip_query_noise(query)
    query_tokens = _tokenize(cleaned)
    if not query_tokens and not exact_ids:
        return []
    exact_courses = {kb.nodes[nid].course for nid in exact_ids}
    idf = _inverse_doc_frequency(kb.nodes)
    scored: list[tuple[float, KnowledgeNode]] = []
    for node in kb.nodes.values():
        terms = _document_terms(node)
        score = 0.0
        for token in set(query_tokens):
            if token in terms:
                score += terms[token] * idf.get(token, 1.0)
        if node.id in exact_ids:
            score += _EXACT_CONCEPT_BONUS
        if score > 0:
            if node.course in exact_courses:
                score *= _SAME_COURSE_BOOST
            scored.append((score, node))

    def _sort_key(pair: tuple[float, KnowledgeNode]):
        score, node = pair
        # 精确命中者按 name 长度降序（"二叉查找树"优先于"树"），其余按分数排。
        exact_rank = -len(node.name) if node.id in exact_ids else 0
        return (-score, exact_rank, node.id)

    scored.sort(key=_sort_key)
    return [
        {
            "id": node.id,
            "name": node.name,
            "node_type": node.node_type,
            "definition": node.definition,
            "key_points": list(node.key_points),
            "example": node.example,
            "aliases": list(node.aliases),
            "source": node.source,
            "course": node.course,
            "score": round(score, 4),
        }
        for score, node in scored[:top_k]
    ]


def get_node(node_id: str) -> dict[str, Any] | None:
    kb = get_knowledge_base()
    node = kb.nodes.get(node_id)
    if node is None:
        return None
    neighbors = [
        {
            "relation_type": rel.relation_type,
            "direction": "outgoing" if rel.from_id == node_id else "incoming",
            "other_id": rel.to_id if rel.from_id == node_id else rel.from_id,
            "note": rel.note,
        }
        for rel in kb.relations
        if rel.from_id == node_id or rel.to_id == node_id
    ]
    return {
        "id": node.id,
        "name": node.name,
        "node_type": node.node_type,
        "definition": node.definition,
        "key_points": list(node.key_points),
        "example": node.example,
        "aliases": list(node.aliases),
        "source": node.source,
        "course": node.course,
        "neighbors": neighbors,
    }


def overview() -> dict[str, Any]:
    kb = get_knowledge_base()
    node_types: dict[str, int] = {}
    relation_types: dict[str, int] = {}
    courses: dict[str, int] = {}
    for node in kb.nodes.values():
        node_types[node.node_type] = node_types.get(node.node_type, 0) + 1
        courses[node.course] = courses.get(node.course, 0) + 1
    for rel in kb.relations:
        relation_types[rel.relation_type] = relation_types.get(rel.relation_type, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "version": kb.version,
        "node_count": len(kb.nodes),
        "relation_count": len(kb.relations),
        "courses": courses,
        "node_types": node_types,
        "relation_types": relation_types,
        "data_dir": str(_resolve_knowledge_data_dir()),
    }
