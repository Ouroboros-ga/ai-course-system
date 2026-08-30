"""学科知识库对齐分类器（纯确定性，无 LLM / 无网络调用）。

用途：在上传 PPT/PDF 提取图候选时，判断一个候选"是不是知识库里已知的标准概念"，
用于把"超库知识点"自动分流到 needs_review 人工审查（AGENTS.md 数据边界：不调用
付费 LLM、不伪造对齐结论，只做可审计的确定性匹配）。

对齐策略（名称锚定，经实测校定）：
  - 归一化候选 label（剥离 `3.2` 序号、`第X章/节` 前缀，去空白/标点）；
  - 与知识库节点 `name` / `aliases` 做：
      exact     候选 == 概念名            （最优）
      contains  概念名 是 候选的子串        （如 '快速排序算法' 含 '快速排序'）
      abbrev    候选 是 概念名的子串，且长度 >= 4（避免 '排序' 误配 '快速排序'）
  - 命中 -> kb_aligned，返回标准 node_key / 权威来源；
  - 未命中 -> out_of_kb（含结构性标题、泛化词），由调用方决定置 needs_review。

关键：**不**使用 discipline_kb.search_nodes 的 BM25 分数（实测 score>0 即命中对
'本章小结'/'思考与练习'/'第3章 排序' 全部误判为某个概念，无法区分超库）。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import settings
from app.platform.knowledge.discipline_kb import get_knowledge_base

# 候选归一化前要剥离的前缀（序号、章节词，以及常见的"结构词+内容"复合形式）
_PREFIX_RE = re.compile(
    r"^\s*(第[0-9一二三四五六七八九十]+[章节课讲]?\s*|"
    r"[0-9]+(\.[0-9]+)*\s*|"
    r"(?:案例演示|课堂演示|上机实验|内容简介|本章小结|章节小结|思考与练习|课后习题|复习思考|"
    r"相关习题|实验内容|实验目的|演示实验|案例|演示|实践|练习|思考|小结|拓展|简介|实验|习题|"
    r"课后|复习|总结|目录|导论|引言|前言)"
    r"\s*[:：]?\s*)"
)

# 即使归一化后也不应视为"知识点概念"的词（结构性标题/泛化词）
_NON_CONCEPT_WORDS = frozenset({
    "本章", "小结", "思考", "练习", "习题", "案例", "演示", "目录", "引言",
    "前言", "复习", "总结", "课后", "作业", "实验", "拓展", "简介", "概述",
    "导论", "章节", "排序", "查找", "算法", "数据结构", "系统", "课件",
    "运行时间", "数据分析",
})

# 简称匹配的最短长度：小于它不允许"候选是概念名子串"（'排序'(2) 不得配 '快速排序'(4)）
_ABBREV_MIN_CHARS = 4


@dataclass(frozen=True)
class AlignResult:
    status: str          # kb_aligned | out_of_kb | unknown(对齐被禁用/无KB)
    reason: str          # 判定依据
    kb_node_key: str | None = None   # 知识库标准节点 id（如 algo-007）
    matched_name: str | None = None  # 命中的概念名
    matched_by: str | None = None    # name / alias 哪个字段命中
    match_kind: str | None = None    # exact / contains / abbrev
    course: str | None = None
    source: dict | None = None       # 权威来源 {title,authors,chapter}
    definition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "kb_node_key": self.kb_node_key,
            "matched_name": self.matched_name,
            "matched_by": self.matched_by,
            "match_kind": self.match_kind,
            "course": self.course,
            "source": self.source,
        }


def normalize_label(label: str) -> str:
    """剥离序号/章节/结构词前缀，去空白与标点。"""
    text = (label or "").strip()
    text = _PREFIX_RE.sub("", text)
    return re.sub(r"[\s：:、，。.;；()（）\[\]【】]", "", text)


def align_candidate(label: str) -> AlignResult:
    """判断候选 label 是否为知识库已知标准概念（名称锚定）。

    对齐被禁用（settings.KNOWLEDGE_KB_ALIGNMENT_ENABLED=False）或知识库为空时
    返回 status='unknown'，调用方走原有 proposed 语义（不强制人工、不误标）。
    """
    if not getattr(settings, "KNOWLEDGE_KB_ALIGNMENT_ENABLED", True):
        return AlignResult(status="unknown", reason="kb_alignment_disabled")

    kb = get_knowledge_base()
    if not kb.nodes:
        return AlignResult(status="unknown", reason="knowledge_base_empty")

    c = normalize_label(label)
    if not c:
        return AlignResult(status="out_of_kb", reason="empty_label")
    if c in _NON_CONCEPT_WORDS:
        return AlignResult(status="out_of_kb", reason="structural_or_generic_word")

    best: AlignResult | None = None
    for node in kb.nodes.values():
        for name in (node.name, *node.aliases):
            n = normalize_label(name)
            if not n:
                continue
            if c == n:
                return AlignResult(
                    status="kb_aligned", reason="exact_name_match",
                    kb_node_key=node.id, matched_name=node.name,
                    matched_by=name, match_kind="exact",
                    course=node.course, source=node.source, definition=node.definition,
                )
            if n in c:
                if best is None or len(normalize_label(best.matched_name or "")) < len(n):
                    best = AlignResult(
                        status="kb_aligned", reason="candidate_contains_concept",
                        kb_node_key=node.id, matched_name=node.name,
                        matched_by=name, match_kind="contains",
                        course=node.course, source=node.source, definition=node.definition,
                    )
            elif c in n and len(c) >= _ABBREV_MIN_CHARS:
                if best is None or len(normalize_label(best.matched_name or "")) < len(n):
                    best = AlignResult(
                        status="kb_aligned", reason="candidate_is_abbreviation",
                        kb_node_key=node.id, matched_name=node.name,
                        matched_by=name, match_kind="abbrev",
                        course=node.course, source=node.source, definition=node.definition,
                    )

    if best is not None:
        return best
    return AlignResult(status="out_of_kb", reason="name_not_in_knowledge_base")


def kb_relation_map() -> dict[tuple[str, str], dict[str, Any]]:
    """返回知识库语义关系索引：{(from_id, to_id): {relation_type, note}}。

    只在开启对齐时有值；关闭或知识库为空返回空。纯确定性，无 LLM。
    """
    if not getattr(settings, "KNOWLEDGE_KB_ALIGNMENT_ENABLED", True):
        return {}
    kb = get_knowledge_base()
    return {
        (rel.from_id, rel.to_id): {"relation_type": rel.relation_type, "note": rel.note}
        for rel in kb.relations
    }


def enrich_relations_from_kb(
    node_candidates: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """用学科知识库语义关系增强候选关系集（prerequisite_of / uses / defines / …）。

    规则：
      - 对每个节点候选做名称锚定，得到 kb_node_key 映射；
      - 对知识库中任何"两端都在候选集内"的语义关系，追加为图关系候选；
      - 图谱关系类型用 KB 的 relation_type（而非一律 next_topic），note 作证据说明；
      - 已存在的同端点关系去重（保留 KB 语义版本优先）。
    """
    if not getattr(settings, "KNOWLEDGE_KB_ALIGNMENT_ENABLED", True):
        return relations
    kb_rels = kb_relation_map()
    if not kb_rels:
        return relations

    node_by_kb: dict[str, dict[str, Any]] = {}
    for candidate in node_candidates or []:
        align = align_candidate(str(candidate.get("label") or candidate.get("title") or "").strip())
        if align.status == "kb_aligned" and align.kb_node_key:
            node_by_kb[align.kb_node_key] = candidate

    existing_by_endpoints: dict[tuple[str, str], dict[str, Any]] = {}
    for item in relations or []:
        existing_by_endpoints.setdefault(
            (str(item.get("source_candidate_id") or ""), str(item.get("target_candidate_id") or "")),
            item,
        )

    added: list[dict[str, Any]] = []
    for (from_kb, to_kb), meta in kb_rels.items():
        if from_kb not in node_by_kb or to_kb not in node_by_kb:
            continue
        src = node_by_kb[from_kb]
        tgt = node_by_kb[to_kb]
        pair = (str(src.get("candidate_id", "")), str(tgt.get("candidate_id", "")))
        existing = existing_by_endpoints.get(pair)
        if existing is not None:
            # 已有同端点顺序边（如 next_topic）：升级为 KB 语义类型，不重复添加。
            existing["relation_type"] = meta["relation_type"]
            existing["kb_relation_note"] = meta.get("note", "")
            continue
        # A semantic KB relation always represents a stable concept-to-concept
        # edge, so we point it to the candidate identity (course-scoped).
        added.append({
            "candidate_id": "gcrkb_" + hashlib.sha256(
                f"{src['candidate_id']}:{tgt['candidate_id']}:{meta['relation_type']}".encode("utf-8")
            ).hexdigest()[:24],
            "source_candidate_id": src["candidate_id"],
            "target_candidate_id": tgt["candidate_id"],
            "relation_type": meta["relation_type"],
            "status": "proposed",
            "confidence": 0.9,
            "anchor_ids": list(dict.fromkeys((src.get("anchor_ids") or []) + (tgt.get("anchor_ids") or []))),
            "kb_relation_note": meta.get("note", ""),
        })
    return [*relations, *added]
