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


def search_nodes(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """BM25 风格关键词检索（CJK 单字 + 英文词元），返回带来源与相关性分数的结果。"""
    kb = get_knowledge_base()
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []
    idf = _inverse_doc_frequency(kb.nodes)
    scored: list[tuple[float, KnowledgeNode]] = []
    for node in kb.nodes.values():
        terms = _document_terms(node)
        score = 0.0
        for token in set(query_tokens):
            if token in terms:
                score += terms[token] * idf.get(token, 1.0)
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
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
