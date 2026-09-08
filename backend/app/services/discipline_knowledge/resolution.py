"""DK3 Resolver B：概念身份消歧（确定性规则核心）。

管线：别名召回 → domain/type 过滤 → 向量候选 → 定义语境判定。

V1 实现状态（诚实标注）：
- 别名召回：归一化精确匹配（传入候选的 name/aliases；DB 全局召回由调用方
  经 ``discipline_aliases`` 完成后再传入），中英统一口径；
- domain/type 过滤：确定性硬规则。类型未知不自动强合并（判 ambiguous）；
- 向量候选：V1 未启用——现有中文 BGE 子集只覆盖教材+中文维基，
  不能声明为跨语种完整方案。``candidates`` 中可附带 ``vector_score``，
  仅作参考信号，绝不单独作为合并依据；
- 定义语境判定：token 交叠启发式（CJK 二元组 + ASCII 词），阈值见
  ``DEF_OVERLAP_MIN``，仅用于多候选并列时的决胜，失败即 ambiguous。

LLM 语义判定是后续增强点：在“定义语境判定”前插入隔离模型调用
（输入仅 mention 上下文 + 候选概念 + 必要定义，不读 Extractor confidence），
本模块确定性规则保持为硬门。Verifier C 盲核验见 ``validation.py``。
"""

from __future__ import annotations

import re
from typing import Any

from app.services.discipline_knowledge.identity import normalize_alias

#: 定义交叠决胜阈值（启发式常量，未经人工真值校准；调参需重跑挑战集）。
DEF_OVERLAP_MIN = 0.3
DEF_OVERLAP_MARGIN = 2.0

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_RE = re.compile(r"[a-z0-9]+")


def _content_tokens(text: str) -> set[str]:
    """CJK 二元组 + ASCII 词（与概念检索同族口径，仅用于交叠比较）。"""
    lowered = str(text or "").lower()
    tokens = set(_ASCII_RE.findall(lowered))
    cjk = _CJK_RE.findall(lowered)
    tokens.update(cjk)
    tokens.update(a + b for a, b in zip(cjk, cjk[1:]))
    return tokens


def _overlap_ratio(a: str, b: str) -> float:
    ta, tb = _content_tokens(a), _content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _candidate_names(candidate: dict) -> list[str]:
    names = [candidate.get("name") or ""]
    names.extend(candidate.get("aliases") or [])
    return [n for n in names if n]


def resolve_identity(mention: dict, candidates: list[dict]) -> dict[str, Any]:
    """消歧单个提及，返回 resolved / new / ambiguous。

    Args:
        mention: ``{name|surface_text, domain?, node_type?, definition?, context?}``。
        candidates: ``[{concept_id, name?, aliases?, domain?, node_type?, definition?}]``。

    Returns:
        ``{decision, concept_id?, basis, reason_codes, scores?}``。
        ``new`` 表示无合理候选、可登记新概念（``concept_id`` 为 None）；
        ``ambiguous`` 表示必须隔离，不得静默合并。
    """
    if not isinstance(mention, dict):
        raise ValueError("SCHEMA_INVALID: mention must be an object")
    surface = str(mention.get("name") or mention.get("surface_text") or "").strip()
    if not surface:
        return {
            "decision": "ambiguous",
            "concept_id": None,
            "basis": "empty_surface",
            "reason_codes": ["EMPTY_SURFACE"],
        }
    norm = normalize_alias(surface)
    mention_domain = str(mention.get("domain") or "").strip()
    mention_type = str(mention.get("node_type") or "").strip()
    mention_def = str(mention.get("definition") or mention.get("context") or "")

    if not isinstance(candidates, list):
        raise ValueError("SCHEMA_INVALID: candidates must be a list")

    # -- 1. 别名召回：归一化精确匹配 --
    recalled = []
    for cand in candidates:
        if not isinstance(cand, dict) or not cand.get("concept_id"):
            continue
        if any(normalize_alias(n) == norm for n in _candidate_names(cand)):
            recalled.append(cand)
    if not recalled:
        if mention_domain and mention_type:
            return {
                "decision": "new",
                "concept_id": None,
                "basis": "no_candidate",
                "reason_codes": ["NO_CANDIDATE"],
            }
        return {
            "decision": "ambiguous",
            "concept_id": None,
            "basis": "no_candidate_type_unknown",
            "reason_codes": ["NO_CANDIDATE", "TYPE_UNKNOWN"],
        }

    # -- 2. domain/type 过滤：双方已知且不同即排除 --
    survivors = []
    filtered = 0
    for cand in recalled:
        cand_domain = str(cand.get("domain") or "").strip()
        cand_type = str(cand.get("node_type") or "").strip()
        if mention_domain and cand_domain and mention_domain != cand_domain:
            filtered += 1
            continue
        if mention_type and cand_type and mention_type != cand_type:
            filtered += 1
            continue
        survivors.append(cand)

    if not survivors:
        # 全部因领域/类型冲突被排除：与现存概念互斥，可建新概念
        # （同名异域如 数据结构-堆 vs 内存管理-堆 必须并存，不得合并）。
        if mention_domain and mention_type:
            return {
                "decision": "new",
                "concept_id": None,
                "basis": "domain_type_excluded_all",
                "reason_codes": ["DOMAIN_FILTERED"],
            }
        return {
            "decision": "ambiguous",
            "concept_id": None,
            "basis": "excluded_but_type_unknown",
            "reason_codes": ["DOMAIN_FILTERED", "TYPE_UNKNOWN"],
        }

    # -- 3. 类型未知不强合并 --
    if not mention_type or any(not str(c.get("node_type") or "").strip() for c in survivors):
        return {
            "decision": "ambiguous",
            "concept_id": None,
            "basis": "type_unknown_no_forced_merge",
            "reason_codes": ["TYPE_UNKNOWN"],
            "scores": {c["concept_id"]: 0.0 for c in survivors},
        }

    if len(survivors) == 1:
        winner = survivors[0]
        return {
            "decision": "resolved",
            "concept_id": winner["concept_id"],
            "basis": "exact_alias_domain_type",
            "reason_codes": ["EXACT_ALIAS"],
        }

    # -- 4. 多候选：定义语境决胜，否则隔离 --
    scored = sorted(
        ((c, _overlap_ratio(mention_def, str(c.get("definition") or ""))) for c in survivors),
        key=lambda pair: (-pair[1], str(pair[0]["concept_id"])),
    )
    (best, best_score), (_, second_score) = scored[0], scored[1]
    if (
        mention_def.strip()
        and best_score >= DEF_OVERLAP_MIN
        and (second_score <= 0 or best_score >= DEF_OVERLAP_MARGIN * second_score)
    ):
        return {
            "decision": "resolved",
            "concept_id": best["concept_id"],
            "basis": "definition_context",
            "reason_codes": ["EXACT_ALIAS", "DEFINITION_CONTEXT"],
            "scores": {c["concept_id"]: round(s, 4) for c, s in scored},
        }
    return {
        "decision": "ambiguous",
        "concept_id": None,
        "basis": "multiple_candidates_no_winner",
        "reason_codes": ["MULTIPLE_CANDIDATES"],
        "scores": {c["concept_id"]: round(s, 4) for c, s in scored},
    }
