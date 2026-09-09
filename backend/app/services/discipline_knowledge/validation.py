"""DK3 Verifier C：盲证据核验（确定性规则核心）。

盲审约束：只读原文、结构化陈述与 predicate 规范，**不读 Extractor A 的
confidence**（签名上就没有该参数，杜绝泄漏）。

判定能力边界（诚实标注）：
- 能可靠判定：quote 精确对齐失败、否定矛盾、限定条件缺失/无据、
  端点缺失、schema 非法；
- ``supported`` 只授予**可逐字接地的描述性陈述**（defines/has_property，
  且 literal 逐字出现在来源中、无否定、限定齐备）；
- 关系（uses/part_of/…）：仅共现无法证明类型与方向，确定性层一律判
  insufficient + RELATION_UNSUPPORTED（隔离而非发布）；语义蕴含判定
  需 LLM 核验增强（后续在 ``verify_assertion`` 之前以隔离调用接入，
  本规则保持为硬门）。

reason_codes 统一取自 ``knowledge_data/pipeline/ontology.json`` 的
``reason_codes`` 表；新增码必须先写入 ontology。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

#: 否定标记（长串优先匹配）。启发式：标记后窗口内出现断言核心即判矛盾。
_NEGATION_MARKERS = (
    "不是", "并非", "没有", "无法", "不能", "不得", "不会", "不属于",
    "不支持", "不提供", "不保证", "不等于", "不适用", "不同", "不",
    "没", "无", "非", "未", "否",
    "cannot", "isn't", "doesn't", "don't", "won't", "never", "without",
    "not", "no",
)

#: 条件/限定标记：来源含此类标记而断言无 qualifiers 即缺限定。
#: 单字标记（当/若）带排除集，避免“当然/当前/若干”等误触发。
_CONDITIONAL_WORDS = (
    "如果", "假设", "前提", "平均", "最坏", "最好", "通常",
    "情况下", "条件下", "场景", "版本",
    "if", "when", "average", "worst", "best",
)
_CONDITIONAL_CHARS = {
    "当": {"然", "前", "下", "天", "年", "中", "今"},
    "若": {"干"},
}

#: 确定性层可授予 supported 的谓词（描述性、可逐字接地）。
_DESCRIPTIVE_PREDICATES = {"defines", "has_property"}

_WS_RUN_RE = re.compile(r"\s+")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _squash(text: str) -> str:
    """NFKC + 空白折叠（literal 逐字比对口径，大小写敏感）。"""
    return _WS_RUN_RE.sub(" ", _nfc(text)).strip()


def _fold(text: str) -> str:
    """NFKC + casefold（端点名出现检查口径，名称大小写不敏感）。"""
    return _nfc(text).casefold()


def _strip_markers(text: str) -> str:
    core = _squash(text)
    for marker in sorted(_NEGATION_MARKERS, key=len, reverse=True):
        core = core.replace(marker, "")
    return _WS_RUN_RE.sub(" ", core).strip()


def _has_conditional(source: str) -> bool:
    """来源是否含条件/限定标记（单字标记排除非条件用法）。"""
    lowered = _fold(source)
    if any(word in lowered for word in _CONDITIONAL_WORDS):
        return True
    for char, excluded in _CONDITIONAL_CHARS.items():
        start = 0
        while True:
            idx = source.find(char, start)
            if idx < 0:
                break
            nxt = source[idx + 1] if idx + 1 < len(source) else ""
            if nxt not in excluded:
                return True
            start = idx + 1
    return False


def _negation_contradicts(subject: str, literal: str, source: str) -> bool:
    """否定矛盾启发式：来源以否定标记包夹断言核心（主语 + 剩余命题）。"""
    src = _squash(source)
    src_fold = _fold(source)
    subj = _squash(subject)
    lit = _squash(literal)
    if not subj or not lit:
        return False
    rest = lit[len(subj):].strip() if lit.startswith(subj) else lit
    rest_core = _strip_markers(rest)
    if not rest_core:
        return False
    for marker in sorted(_NEGATION_MARKERS, key=len, reverse=True):
        start = 0
        while True:
            idx = src_fold.find(marker.lower(), start)
            if idx < 0:
                break
            left = src[max(0, idx - 12):idx]
            right = src[idx + len(marker):idx + len(marker) + 14]
            window = _fold(left + " " + right)
            if _fold(subj) in window and _fold(rest_core) in window:
                return True
            start = idx + 1
    return False


def verify_assertion(assertion: dict, source_text: str, policy: dict | None = None) -> dict[str, Any]:
    """盲核验单个陈述，返回 supported / contradicted / insufficient + reason_codes。

    Args:
        assertion: ``{assertion_id?, subject, subject_aliases?,
          predicate, object?, object_aliases?, literal?, qualifiers?, span?}``，
          ``span`` 为 ``{start, end, quote}``（相对 source_text 的 code-point 区间）。
        source_text: 规范化后的原文。
        policy: ``{qualifier_policy: strict|lenient}``，默认 strict。
    """
    if not isinstance(assertion, dict):
        raise ValueError("SCHEMA_INVALID: assertion must be an object")
    policy = policy or {}
    if policy.get("qualifier_policy", "strict") not in ("strict", "lenient"):
        raise ValueError("SCHEMA_INVALID: qualifier_policy must be strict|lenient")
    strict = policy.get("qualifier_policy", "strict") == "strict"

    reason_codes: list[str] = []
    checks: dict[str, Any] = {}
    source = _squash(source_text or "")

    subject = str(assertion.get("subject") or "").strip()
    predicate = str(assertion.get("predicate") or "").strip()
    obj = assertion.get("object")
    obj_name = str(obj or "").strip()
    literal = assertion.get("literal")
    literal_text = str(literal) if literal is not None else ""
    qualifiers = assertion.get("qualifiers") or {}

    # -- 0. schema：literal 与 object 至少一个有效 --
    if not literal_text.strip() and not obj_name:
        return {
            "verdict": "insufficient",
            "reason_codes": ["SCHEMA_INVALID"],
            "checks": {"schema": {"passed": False, "detail": "literal/object 至少一个有效"}},
        }
    checks["schema"] = {"passed": True}

    # -- 1. quote 精确对齐 --
    span = assertion.get("span")
    if isinstance(span, dict):
        try:
            start, end, quote = int(span["start"]), int(span["end"]), str(span.get("quote") or "")
        except (KeyError, TypeError, ValueError):
            start, end, quote = -1, -1, ""
        if not (0 <= start < end <= len(source)) or source[start:end] != quote:
            return {
                "verdict": "insufficient",
                "reason_codes": ["GROUNDING_FAILED"],
                "checks": {**checks, "grounding": {"passed": False, "detail": "quote 与原文区间不一致"}},
            }
        checks["grounding"] = {"passed": True}
    else:
        checks["grounding"] = {"passed": True, "detail": "no span claimed"}

    # -- 2. 端点/字面出现检查 --
    src_fold = _fold(source)
    surfaces = [subject, *(assertion.get("subject_aliases") or [])]
    if not any(s and _fold(str(s)) in src_fold for s in surfaces):
        reason_codes.append("RELATION_UNSUPPORTED")
        checks["subject"] = {"passed": False, "detail": "主语未在来源出现"}
    else:
        checks["subject"] = {"passed": True}
    if obj_name:
        obj_surfaces = [obj_name, *(assertion.get("object_aliases") or [])]
        if not any(s and _fold(str(s)) in src_fold for s in obj_surfaces):
            reason_codes.append("RELATION_UNSUPPORTED")
            checks["object"] = {"passed": False, "detail": "宾语未在来源出现"}
        else:
            checks["object"] = {"passed": True}

    # -- 3. 否定矛盾 --
    probe_literal = literal_text if literal_text.strip() else obj_name
    if probe_literal and _negation_contradicts(subject, probe_literal, source):
        return {
            "verdict": "contradicted",
            "reason_codes": ["NEGATION_CONTRADICTED"],
            "checks": {**checks, "negation": {"passed": False, "detail": "来源否定该命题"}},
        }
    checks["negation"] = {"passed": True}

    # -- 4. 限定条件 --
    if isinstance(qualifiers, dict) and qualifiers:
        missing = [
            key for key, value in qualifiers.items()
            if str(value).strip() and _squash(str(value)) not in source
        ]
        if missing:
            return {
                "verdict": "insufficient",
                "reason_codes": ["QUALIFIER_UNSUPPORTED"],
                "checks": {**checks, "qualifier": {"passed": False, "detail": f"无据限定: {missing}"}},
            }
        checks["qualifier"] = {"passed": True}
    elif strict and _has_conditional(source):
        return {
            "verdict": "insufficient",
            "reason_codes": ["QUALIFIER_MISSING"],
            "checks": {**checks, "qualifier": {"passed": False, "detail": "来源含条件限定而断言无 qualifiers"}},
        }
    else:
        checks["qualifier"] = {"passed": True}

    # -- 5. 描述性谓词逐字接地；关系仅共现不能发布 --
    if predicate in _DESCRIPTIVE_PREDICATES and literal_text.strip():
        if _squash(literal_text) in source:
            checks["support"] = {"passed": True, "detail": "literal 逐字接地"}
            if not reason_codes:
                return {"verdict": "supported", "reason_codes": ["VERBATIM_SUPPORT"], "checks": checks}
        else:
            reason_codes.append("LITERAL_NOT_GROUNDED")
            checks["support"] = {"passed": False, "detail": "literal 未逐字出现"}
    elif predicate and predicate not in _DESCRIPTIVE_PREDICATES:
        if "RELATION_UNSUPPORTED" not in reason_codes:
            reason_codes.append("RELATION_UNSUPPORTED")
        checks["support"] = {"passed": False, "detail": "共现不能证明关系类型与方向"}

    if not reason_codes:
        reason_codes.append("EVIDENCE_WEAK")
    return {"verdict": "insufficient", "reason_codes": reason_codes, "checks": checks}
