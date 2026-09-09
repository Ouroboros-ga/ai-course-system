"""DK3 Adjudicator D：按需裁决（只处理分歧/冲突）。

铁律：
- 无法消除的不确定性一律写 ``quarantine``，绝不为提高覆盖率强制 ``accept``；
- ``accept`` 只在显式规则命中时作出（单精确候选 + 领域一致、无反证票）；
- 语料内指令 / 伪造引文一律 ``reject``；
- 版本冲突先按时间/版本/条件区分，可区分则 ``keep_separate``（带版本
  限定并存），否则 ``quarantine``，新陈述永不覆盖旧描述。

输入 ``disagreement`` 格式::

    {
      "kind": "identity" | "verification" | "conflict" | "grounding",
      "target_type": ..., "target_id": ...,
      "votes": {"resolver": {...}, "verifier": {...}},  # DK3 模块输出原样
      "candidates": [...],          # identity/conflict 候选项
      "reason_codes": [...],        # 上游汇总码
      "context": {"high_risk": bool, "versions": [...], ...},
      "policy": {"high_risk_predicates": [...]},
    }
"""

from __future__ import annotations

from typing import Any

_HIGH_RISK_DEFAULT = {"defines", "prerequisite_candidate"}

_REJECT_CODES = {"INSTRUCTION_IN_CORPUS", "GROUNDING_FAILED_FABRICATED"}


def _votes(disagreement: dict) -> dict:
    votes = disagreement.get("votes") or {}
    return votes if isinstance(votes, dict) else {}


def _is_high_risk(disagreement: dict) -> bool:
    context = disagreement.get("context") or {}
    if context.get("high_risk") is True:
        return True
    policy = disagreement.get("policy") or {}
    predicates = set(policy.get("high_risk_predicates") or _HIGH_RISK_DEFAULT)
    return str(context.get("predicate") or "") in predicates


def adjudicate(disagreement: dict) -> dict[str, Any]:
    """裁决单项分歧，返回 accept / keep_separate / quarantine / reject。"""
    if not isinstance(disagreement, dict):
        raise ValueError("SCHEMA_INVALID: disagreement must be an object")
    kind = str(disagreement.get("kind") or "").strip()
    if kind not in ("identity", "verification", "conflict", "grounding"):
        raise ValueError(
            "SCHEMA_INVALID: kind must be identity|verification|conflict|grounding"
        )
    votes = _votes(disagreement)
    upstream = list(disagreement.get("reason_codes") or [])
    context = disagreement.get("context") or {}
    high_risk = _is_high_risk(disagreement)

    # -- 1. 语料内指令：直接拒绝，不进入知识 --
    if "INSTRUCTION_IN_CORPUS" in upstream or context.get("prompt_injected") is True:
        return {
            "decision": "reject",
            "reason_codes": ["INSTRUCTION_IN_CORPUS"],
            "basis": "corpus_instructions_are_text_not_commands",
        }

    # -- 2. 核验反证：来源否定该命题，拒绝肯定形式 --
    verifier = votes.get("verifier") or {}
    if verifier.get("verdict") == "contradicted":
        return {
            "decision": "reject",
            "reason_codes": ["NEGATION_CONTRADICTED"],
            "basis": "evidence_contradicts_positive_claim",
        }

    # -- 3. 引文问题：编造引文拒绝；错位（可重定位）则隔离 --
    if kind == "grounding" or "GROUNDING_FAILED" in upstream:
        if context.get("fabricated") is True:
            return {
                "decision": "reject",
                "reason_codes": ["GROUNDING_FAILED"],
                "basis": "quote_not_verbatim_in_source",
            }
        return {
            "decision": "quarantine",
            "reason_codes": ["GROUNDING_FAILED"],
            "basis": "misaligned_span_isolated_for_regrounding",
        }

    # -- 4. 版本冲突：可区分则带限定并存，否则隔离 --
    if kind == "conflict":
        versions = context.get("versions") or []
        if len(versions) >= 2 and all(
            isinstance(v, dict) and v.get("version") for v in versions
        ):
            return {
                "decision": "keep_separate",
                "reason_codes": ["VERSION_CONFLICT"],
                "basis": "versioned_coexistence",
                "after": {"coexist": [v.get("version") for v in versions]},
            }
        return {
            "decision": "quarantine",
            "reason_codes": ["VERSION_CONFLICT"],
            "basis": "unresolvable_conflict_isolated",
        }

    # -- 5. 身份分歧 --
    if kind == "identity":
        resolver = votes.get("resolver") or {}
        if resolver.get("decision") == "resolved" and not high_risk:
            return {
                "decision": "accept",
                "concept_id": resolver.get("concept_id"),
                "reason_codes": ["EXACT_ALIAS"],
                "basis": "single_exact_candidate_no_counter_evidence",
            }
        candidates = disagreement.get("candidates") or []
        if len(candidates) >= 2 or resolver.get("decision") == "ambiguous":
            if high_risk:
                return {
                    "decision": "quarantine",
                    "reason_codes": ["IDENTITY_AMBIGUOUS"],
                    "basis": "high_risk_identity_isolated",
                }
            return {
                "decision": "keep_separate",
                "reason_codes": ["IDENTITY_AMBIGUOUS"],
                "basis": "ambiguous_identities_kept_apart_not_merged",
            }
        return {
            "decision": "quarantine",
            "reason_codes": ["IDENTITY_AMBIGUOUS"],
            "basis": "identity_undecidable",
        }

    # -- 6. 核验不足（verification）：证据可修复则隔离，不拒绝 --
    if "QUALIFIER_MISSING" in upstream or "QUALIFIER_UNSUPPORTED" in upstream:
        return {
            "decision": "quarantine",
            "reason_codes": [c for c in upstream if "QUALIFIER" in c] or ["QUALIFIER_MISSING"],
            "basis": "fixable_evidence_gap_isolated",
        }
    if "GROUNDING_FAILED" in upstream or "LITERAL_NOT_GROUNDED" in upstream:
        return {
            "decision": "quarantine",
            "reason_codes": ["GROUNDING_FAILED"],
            "basis": "missing_span_isolated_for_regrounding",
        }
    if verifier.get("verdict") == "supported" and not high_risk:
        return {
            "decision": "accept",
            "reason_codes": ["VERBATIM_SUPPORT"],
            "basis": "blind_verification_supported",
        }
    return {
        "decision": "quarantine",
        "reason_codes": upstream or ["EVIDENCE_WEAK"],
        "basis": "uncertainty_isolated_never_force_accepted",
    }
