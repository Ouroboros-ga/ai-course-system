"""DK3 决策审计：追加记录、乐观锁、合并与撤销。

- 模型裁决（B/C/D）、自动隔离、可选人工纠错与撤销均为追加事件，
  写 ``discipline_decisions``；``expected_revision`` 冲突即拒绝
  （stale 写返回错误，调用方以 409 语义处理）；
- 合并（merge）搬运 mention/alias 引用并记 before/after，目标 concept
  ``revision + 1``；撤销（revert）按 before_ref 精确归位并再 ``+1``，
  全程只产生新 revision，不改写历史；
- 冻结发布版本（``discipline_release_items`` 快照）不受合并/撤销影响。
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.discipline_knowledge_model import (
    DisciplineAlias,
    DisciplineConcept,
    DisciplineDecision,
    DisciplineMention,
)

_ACTOR_TYPES = {"model", "policy", "admin"}
#: 决策词表：裁决结果（accept/keep_separate/quarantine/reject/override）+
#: 角色 verdict（B/C 输出，待裁决或自动路由）。角色 verdict 不是终局，
#: adjudicate 处理器据此生成裁决行（actor_ref=adjudicator-d）。
_DECISIONS = {
    "accept", "keep_separate", "quarantine", "reject", "override",
    "resolved", "new", "ambiguous",
    "supported", "contradicted", "insufficient",
}
_ADJUDICATION_OUTCOMES = {"accept", "keep_separate", "quarantine", "reject", "override"}
_REVISIONED_TARGETS = {"concept", "assertion", "mention"}


class DisciplineDecisionError(ValueError):
    """携带错误码的决策失败（STALE_REVISION / TARGET_NOT_FOUND / ...）。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code


def _new_decision_id() -> str:
    return "dkd_" + uuid.uuid4().hex[:16]


def _concept_by_id(session: Session, concept_id: str) -> Optional[DisciplineConcept]:
    return session.exec(
        select(DisciplineConcept).where(DisciplineConcept.concept_id == concept_id)
    ).first()


def record_decision(
    session: Session,
    *,
    target_type: str,
    target_id: str,
    expected_revision: Optional[int],
    decision: str,
    reason_codes: list[str],
    actor_type: str,
    actor_ref: str,
    before_ref: Optional[dict] = None,
    after_ref: Optional[dict] = None,
) -> dict[str, Any]:
    """追加一条决策审计；带 revision 的目标做乐观锁比较。

    没有人工 override 也能完成发布——本函数只做记录与并发保护，
    不阻塞流水线（隔离项天然跳过发布）。
    """
    if decision not in _DECISIONS:
        raise DisciplineDecisionError(
            "SCHEMA_INVALID", f"unknown decision '{decision}'"
        )
    if actor_type not in _ACTOR_TYPES:
        raise DisciplineDecisionError(
            "SCHEMA_INVALID", f"unknown actor_type '{actor_type}'"
        )
    if not target_id:
        raise DisciplineDecisionError("SCHEMA_INVALID", "target_id is required")
    if not isinstance(reason_codes, list) or not reason_codes:
        raise DisciplineDecisionError("SCHEMA_INVALID", "reason_codes must be non-empty")

    if target_type in _REVISIONED_TARGETS and expected_revision is not None:
        current = None
        if target_type == "concept":
            row = _concept_by_id(session, target_id)
            current = row.revision if row is not None else None
        elif target_type == "assertion":
            from app.models.discipline_knowledge_model import DisciplineAssertion

            row = session.exec(
                select(DisciplineAssertion).where(
                    DisciplineAssertion.assertion_id == target_id
                )
            ).first()
            current = row.revision if row is not None else None
        else:  # mention 无 revision 列：仅校验存在性
            from app.models.discipline_knowledge_model import DisciplineMention

            row = session.exec(
                select(DisciplineMention).where(
                    DisciplineMention.mention_id == target_id
                )
            ).first()
            current = expected_revision if row is not None else None
        if current is None:
            raise DisciplineDecisionError(
                "TARGET_NOT_FOUND", f"{target_type} '{target_id}' 不存在"
            )
        if current != expected_revision:
            raise DisciplineDecisionError(
                "STALE_REVISION",
                f"{target_type} '{target_id}' 已是 revision {current}，"
                f"期望 {expected_revision}（调用方应重读后重试）",
            )

    now = utcnow_aware()
    row = DisciplineDecision(
        decision_id=_new_decision_id(),
        target_type=target_type,
        target_id=target_id,
        expected_revision=expected_revision or 0,
        decision=decision,
        reason_codes=list(reason_codes),
        actor_type=actor_type,
        actor_ref=actor_ref,
        before_ref=before_ref,
        after_ref=after_ref,
        created_at=now,
    )
    session.add(row)
    session.commit()
    return {
        "decision_id": row.decision_id,
        "target_type": target_type,
        "target_id": target_id,
        "decision": decision,
        "reason_codes": list(reason_codes),
        "actor_type": actor_type,
        "actor_ref": actor_ref,
    }


def merge_concepts(
    session: Session,
    *,
    source_id: str,
    target_id: str,
    actor_ref: str,
    reason_codes: list[str],
    expected_target_revision: Optional[int] = None,
) -> dict[str, Any]:
    """把 source 概念并入 target：搬运引用、记审计、目标 revision + 1。

    - mentions：``concept_id`` 改指 target（行保留，不删除）；
    - aliases：改指 target，同 (language, normalized) 已存在则跳过并记录；
    - source 置 ``merged``；target ``revision + 1``。
    - 两阶段提交：先记审计（含乐观锁），再落应用。``expected_target_revision``
      用于调用方并发保护（与当前不符即 STALE）。
    """
    if source_id == target_id:
        raise DisciplineDecisionError("SCHEMA_INVALID", "source 与 target 相同，拒绝自合并")
    source = _concept_by_id(session, source_id)
    target = _concept_by_id(session, target_id)
    if source is None or target is None:
        raise DisciplineDecisionError("TARGET_NOT_FOUND", "合并端点不存在")
    if source.status == "merged":
        raise DisciplineDecisionError("ALREADY_MERGED", f"concept '{source_id}' 已合并")
    if expected_target_revision is not None and target.revision != expected_target_revision:
        raise DisciplineDecisionError(
            "STALE_REVISION",
            f"concept '{target_id}' 已是 revision {target.revision}，"
            f"期望 {expected_target_revision}（调用方应重读后重试）",
        )

    mention_rows = session.exec(
        select(DisciplineMention).where(DisciplineMention.concept_id == source_id)
    ).all()
    alias_rows = session.exec(
        select(DisciplineAlias).where(DisciplineAlias.concept_id == source_id)
    ).all()
    clashing: set[int] = set()
    for alias in alias_rows:
        clash = session.exec(
            select(DisciplineAlias)
            .where(DisciplineAlias.concept_id == target_id)
            .where(DisciplineAlias.language == alias.language)
            .where(DisciplineAlias.normalized_alias == alias.normalized_alias)
        ).first()
        if clash is not None and alias.id is not None:
            clashing.add(alias.id)

    before_ref = {
        "kind": "merge",
        "source_id": source_id,
        "target_id": target_id,
        "source_status": source.status,
        "target_revision": target.revision,
        "moved_mention_ids": [m.mention_id for m in mention_rows],
        "moved_alias_ids": [a.id for a in alias_rows if a.id not in clashing],
        "skipped_alias_ids": sorted(clashing),
    }
    after_ref = {
        "kind": "merge",
        "source_status": "merged",
        "target_revision": target.revision + 1,
    }
    record = record_decision(
        session,
        target_type="concept",
        target_id=target_id,
        expected_revision=target.revision,
        decision="accept",
        reason_codes=list(reason_codes) or ["EXACT_ALIAS"],
        actor_type="model",
        actor_ref=actor_ref,
        before_ref=before_ref,
        after_ref=after_ref,
    )

    for mention in mention_rows:
        mention.concept_id = target_id
        session.add(mention)
    for alias in alias_rows:
        if alias.id in clashing:
            continue
        alias.concept_id = target_id
        session.add(alias)
    source.status = "merged"
    source.updated_at = utcnow_aware()
    target.revision += 1
    target.updated_at = utcnow_aware()
    session.add(source)
    session.add(target)
    session.commit()

    record["moved_mentions"] = len(before_ref["moved_mention_ids"])
    record["moved_aliases"] = len(before_ref["moved_alias_ids"])
    record["skipped_aliases"] = len(before_ref["skipped_alias_ids"])
    return record


def revert_decision(
    session: Session,
    *,
    decision_id: str,
    actor_ref: str,
    reason: str,
) -> dict[str, Any]:
    """撤销一次合并决策：按 before_ref 精确归位，产生新 revision 与新审计行。

    仅支持 ``after.kind == "merge"`` 的决策；其余类型拒绝（不可逆类型需
    另行设计补偿，不在此静默处理）。
    """
    original = session.exec(
        select(DisciplineDecision).where(DisciplineDecision.decision_id == decision_id)
    ).first()
    if original is None:
        raise DisciplineDecisionError("TARGET_NOT_FOUND", f"决策 '{decision_id}' 不存在")
    before = original.before_ref or {}
    if (original.after_ref or {}).get("kind") != "merge" or before.get("kind") != "merge":
        raise DisciplineDecisionError(
            "IRREVERSIBLE_DECISION", "仅 merge 决策支持撤销"
        )
    source = _concept_by_id(session, before["source_id"])
    target = _concept_by_id(session, before["target_id"])
    if source is None or target is None:
        raise DisciplineDecisionError("TARGET_NOT_FOUND", "合并端点已缺失，无法撤销")

    current_revision = target.revision
    record = record_decision(
        session,
        target_type="concept",
        target_id=target.concept_id,
        expected_revision=current_revision,
        decision="override",
        reason_codes=["HUMAN_OVERRIDE"] if actor_ref else ["REVERT"],
        actor_type="admin",
        actor_ref=actor_ref,
        before_ref={"kind": "revert", "reverts": decision_id, "reason": reason},
        after_ref={"kind": "revert", "target_revision": current_revision + 1},
    )

    restored_mentions = 0
    for mention_id in before.get("moved_mention_ids") or []:
        mention = session.exec(
            select(DisciplineMention).where(DisciplineMention.mention_id == mention_id)
        ).first()
        if mention is not None and mention.concept_id == target.concept_id:
            mention.concept_id = source.concept_id
            session.add(mention)
            restored_mentions += 1
    for alias_id in before.get("moved_alias_ids") or []:
        alias = session.get(DisciplineAlias, alias_id)
        if alias is not None and alias.concept_id == target.concept_id:
            alias.concept_id = source.concept_id
            session.add(alias)

    source.status = before.get("source_status") or "active"
    source.updated_at = utcnow_aware()
    target.revision += 1
    target.updated_at = utcnow_aware()
    session.add(source)
    session.add(target)
    session.commit()

    record["restored_mentions"] = restored_mentions
    record["after_ref"] = {"kind": "revert", "target_revision": target.revision,
                           "restored_mentions": restored_mentions}
    return record
