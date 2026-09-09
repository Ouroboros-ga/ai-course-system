"""DK4 工作项：事务认领、租约续期/回收、取消语义与分阶段执行分发。

- 一个批次映射一条 ``TaskRecord``，细粒度状态只放 ``discipline_work_items``，
  片段不膨胀成通用 TaskRecord；
- 认领是单条原子 UPDATE（PG 下子查询带 ``FOR UPDATE SKIP LOCKED``，
  SQLite 靠单写者串行 + 行数校验），lease 过期只回收该任务；
- ``complete_item`` 比较 ``lease_token``：过期旧 worker 的结果不能覆盖
  新 owner（token 每次认领唯一，失配即 False）；
- ``run_item`` 分发 DK4 可处理的阶段（resolve/verify/adjudicate，全部经
  DK1–DK3 真实服务）；extract/ground/card/index 由 DK2/DK5 接线，
  ``create_build`` 直接拒绝，不伪造进度。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import update
from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.discipline_knowledge_model import (
    DisciplineAlias,
    DisciplineAssertion,
    DisciplineBuild,
    DisciplineChunk,
    DisciplineConcept,
    DisciplineDecision,
    DisciplineMention,
    DisciplineSupport,
    DisciplineWorkItem,
)
from app.services.discipline_knowledge.adjudication import adjudicate
from app.services.discipline_knowledge.decisions import record_decision
from app.services.discipline_knowledge.identity import sha16
from app.services.discipline_knowledge.resolution import resolve_identity
from app.services.discipline_knowledge.validation import verify_assertion

#: DK4 worker 可处理的阶段 → 模型角色（预算分角色记录用）。
#: legacy 管线沿用 B/C/D；corpus_rag 管线统一记角色 E（embedding）。
STAGE_ROLE = {"resolve": "B", "verify": "C", "adjudicate": "D",
              "embed": "E", "fts": "E", "validate": "E"}

#: DK2/DK5 的阶段：worker 遇到即诚实失败，不伪造成功。
DEFERRED_STAGES = ("extract", "ground", "card", "index")

#: corpus_rag 中 CR3 接线的阶段：CR2 的 worker 不认领（§4.1 显式依赖）。
CORPUS_DEFERRED_STAGES = ("fts", "validate")


class DisciplineWorkError(ValueError):
    """携带错误码与可重试性的工作项执行失败。"""

    def __init__(self, error_code: str, message: str, *, retryable: bool = True):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.retryable = retryable


def fingerprint_for(
    stage: str,
    chunk_id: str,
    config_hash: str,
    *,
    build_id: Optional[str] = None,
) -> str:
    """幂等键：legacy 管线保持全局 ``(stage, chunk, 配置)``；corpus 管线
    传入 ``build_id`` 后每批次自有身份（跨批次复用走向量缓存，不走工作项）。"""
    if build_id:
        return "fp_" + sha16(
            "discipline-work", build_id, stage, chunk_id, config_hash or "")
    return "fp_" + sha16("discipline-work", stage, chunk_id, config_hash or "")


def _dialect(session: Session) -> str:
    try:
        bind = session.get_bind()
        return bind.dialect.name if bind is not None else ""
    except Exception:  # noqa: BLE001 - 方言探测失败即走通用路径
        return ""


def claim_item(
    session: Session,
    worker_id: str,
    now: datetime,
    lease_seconds: int = 180,
    *,
    pipeline_kind: Optional[str] = None,
    stages: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    """事务认领一个 pending 工作项（仅 running 构建），返回认领信息或 None。

    - ``pipeline_kind`` 非空时只认领该管线（corpus worker 默认
      ``corpus_rag``，不再默认认领旧 ``legacy_extraction`` 任务）；
    - ``stages`` 非空时只认领这些阶段（CR2 的 corpus worker 传
      ``["embed"]``；fts/validate 由 CR3 接线）；
    - corpus 管线的 fts/validate 有前置依赖（见 ``_deps_met``），未满足
      即跳过该项、继续看下一项，不阻塞 embed。
    """
    token = f"{worker_id}:{uuid.uuid4().hex[:8]}"
    expires = now + timedelta(seconds=max(1, lease_seconds))
    query = (
        select(DisciplineWorkItem)
        .join(DisciplineBuild, DisciplineBuild.build_id == DisciplineWorkItem.build_id)
        .where(
            DisciplineWorkItem.status == "pending",
            DisciplineBuild.status == "running",
        )
        .order_by(DisciplineWorkItem.id)
    )
    if pipeline_kind:
        query = query.where(DisciplineBuild.pipeline_kind == pipeline_kind)
    if stages:
        query = query.where(DisciplineWorkItem.stage.in_(stages))
    if _dialect(session) == "postgresql":
        query = query.with_for_update(skip_locked=True)
    for candidate in session.exec(query).all():
        if not _deps_met(session, candidate.build_id, candidate.stage):
            continue
        result = session.execute(
            update(DisciplineWorkItem)
            .where(
                DisciplineWorkItem.id == candidate.id,
                DisciplineWorkItem.status == "pending",
            )
            .values(
                status="running",
                lease_token=token,
                lease_until=expires,
                attempts=DisciplineWorkItem.attempts + 1,
                updated_at=now,
            )
        )
        session.commit()
        if result.rowcount != 1:
            continue  # 并发认领落败，看下一项
        row = session.get(DisciplineWorkItem, candidate.id)
        if row is None:
            return None
        return {
            "item_id": row.item_id,
            "build_id": row.build_id,
            "chunk_id": row.chunk_id,
            "stage": row.stage,
            "unit_kind": row.unit_kind,
            "unit_key": row.unit_key,
            "payload_ref": row.payload_ref,
            "fingerprint": row.fingerprint,
            "attempts": row.attempts,
            "lease_token": token,
            "lease_until": expires,
        }
    return None


def _deps_met(session: Session, build_id: str, stage: str) -> bool:
    """阶段前置依赖检查（§4.1）：fts 需全部 embed 终态成功。

    - embed：无依赖；
    - fts：同 build 无 pending/running/failed 的 embed 项；
    - validate：fts 已成功（CR3 执行，CR2 仅做门检查）；
    - legacy 阶段：无依赖（旧行为）。
    """
    from app.services.discipline_knowledge.builds import STAGE_DEPENDENCIES

    deps = STAGE_DEPENDENCIES.get(stage)
    if not deps:
        return True
    rows = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == build_id,
        )
    ).all()
    by_stage: dict[str, list[str]] = {}
    for row in rows:
        by_stage.setdefault(row.stage, []).append(row.status)
    for dep in deps:
        statuses = by_stage.get(dep, [])
        if not statuses:
            return False
        if any(s in ("pending", "running", "failed") for s in statuses):
            return False
    return True


def complete_item(
    session: Session,
    item_id: str,
    lease_token: str,
    result_ref: str,
) -> bool:
    """提交成功：token 失配（旧 lease/新 owner）或非 running 即 False。"""
    now = utcnow_aware()
    result = session.execute(
        update(DisciplineWorkItem)
        .where(
            DisciplineWorkItem.item_id == item_id,
            DisciplineWorkItem.lease_token == lease_token,
            DisciplineWorkItem.status == "running",
        )
        .values(
            status="succeeded",
            result_ref=str(result_ref or "")[:512],
            error_code="",
            updated_at=now,
        )
    )
    session.commit()
    return result.rowcount == 1


def fail_item(
    session: Session,
    item_id: str,
    lease_token: str,
    error_code: str,
    *,
    retryable: bool = True,
    max_retries: int = 2,
    now: Optional[datetime] = None,
) -> str:
    """提交失败：可重试且未超限退回 pending，否则记 failed。返回新状态（""=失配）。

    ``BUDGET_EXCEEDED`` 是预算门暂停而非失败：恒退回 pending、清租约，并
    抵消本次认领的 attempts 自增（认领即 +1，见 ``claim_item``），使反复
    暂停（worker 重启循环）既不消耗重试额度也不会被误判为 failed。
    """
    now = now or utcnow_aware()
    row = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.item_id == item_id,
            DisciplineWorkItem.lease_token == lease_token,
            DisciplineWorkItem.status == "running",
        )
    ).first()
    if row is None:
        return ""
    if error_code == "BUDGET_EXCEEDED":
        row.status = "pending"
        row.lease_token = ""
        row.lease_until = None
        row.attempts = max(0, int(row.attempts or 0) - 1)
        new_status = "pending"
    elif retryable and row.attempts <= max(0, max_retries):
        row.status = "pending"
        row.lease_token = ""
        row.lease_until = None
        new_status = "pending"
    else:
        row.status = "failed"
        new_status = "failed"
    row.error_code = error_code
    row.updated_at = now
    session.add(row)
    session.commit()
    return new_status


def renew_lease(
    session: Session,
    item_id: str,
    lease_token: str,
    now: datetime,
    lease_seconds: int = 180,
) -> bool:
    """续租：仅 owner（token 一致）且 running 可续。"""
    result = session.execute(
        update(DisciplineWorkItem)
        .where(
            DisciplineWorkItem.item_id == item_id,
            DisciplineWorkItem.lease_token == lease_token,
            DisciplineWorkItem.status == "running",
        )
        .values(
            lease_until=now + timedelta(seconds=max(1, lease_seconds)),
            updated_at=now,
        )
    )
    session.commit()
    return result.rowcount == 1


def reap_expired_leases(session: Session, now: datetime) -> dict[str, int]:
    """回收过期租约：所属构建仍 running 则退回 pending，否则随构建取消。

    进程退出后未完成项经此恢复（重认领而非续跑），已完成结果保留。
    """
    rows = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.status == "running",
            DisciplineWorkItem.lease_until != None,  # noqa: E711
            DisciplineWorkItem.lease_until < now,
        )
    ).all()
    requeued = 0
    cancelled = 0
    for row in rows:
        build = session.exec(
            select(DisciplineBuild).where(DisciplineBuild.build_id == row.build_id)
        ).first()
        if build is not None and build.status == "running":
            row.status = "pending"
            row.lease_token = ""
            row.lease_until = None
            requeued += 1
        else:
            row.status = "cancelled"
            cancelled += 1
        row.updated_at = now
        session.add(row)
    if rows:
        session.commit()
    return {"requeued": requeued, "cancelled": cancelled}


# ---------------------------------------------------------------------------
# 分阶段执行（DK1–DK3 真实服务）
# ---------------------------------------------------------------------------


def _concept_candidates(session: Session, norm_surface: str) -> list[dict[str, Any]]:
    alias_rows = session.exec(
        select(DisciplineAlias).where(DisciplineAlias.normalized_alias == norm_surface)
    ).all()
    concept_ids = sorted({row.concept_id for row in alias_rows})
    candidates = []
    for concept_id in concept_ids:
        concept = session.exec(
            select(DisciplineConcept).where(DisciplineConcept.concept_id == concept_id)
        ).first()
        if concept is None or concept.status == "withdrawn":
            continue
        raw_aliases = session.exec(
            select(DisciplineAlias.raw_alias).where(
                DisciplineAlias.concept_id == concept_id
            )
        ).all()
        candidates.append({
            "concept_id": concept.concept_id,
            "name": concept.canonical_name,
            "aliases": list(raw_aliases),
            "domain": concept.domain,
            "node_type": concept.node_type,
            "definition": "",
        })
    return candidates


def _run_resolve(session: Session, chunk_id: str) -> dict[str, Any]:
    from app.services.discipline_knowledge.identity import normalize_alias

    mentions = session.exec(
        select(DisciplineMention).where(
            DisciplineMention.chunk_id == chunk_id,
            DisciplineMention.decision == "undecided",
        )
    ).all()
    summary = {"stage": "resolve", "chunk_id": chunk_id, "mentions": 0,
               "resolved": 0, "new": 0, "ambiguous": 0}
    for mention in mentions:
        candidates = _concept_candidates(session, normalize_alias(mention.surface_text))
        outcome = resolve_identity(
            {"name": mention.surface_text, "domain": mention.domain,
             "node_type": mention.node_type,
             "definition": mention.context, "context": mention.context},
            candidates,
        )
        summary["mentions"] += 1
        summary[outcome["decision"]] += 1
        if outcome["decision"] == "resolved":
            mention.concept_id = outcome["concept_id"]
        mention.decision = outcome["decision"]
        session.add(mention)
        record_decision(
            session, target_type="mention", target_id=mention.mention_id,
            expected_revision=None, decision=outcome["decision"],
            reason_codes=outcome["reason_codes"],
            actor_type="model", actor_ref="resolver-b",
        )
    session.commit()
    return summary


def _assertion_view(
    session: Session, assertion: DisciplineAssertion
) -> dict[str, Any]:
    subject = session.exec(
        select(DisciplineConcept).where(
            DisciplineConcept.concept_id == assertion.subject_id
        )
    ).first()
    view: dict[str, Any] = {
        "assertion_id": assertion.assertion_id,
        "subject": subject.canonical_name if subject else assertion.subject_id,
        "subject_aliases": [],
        "predicate": assertion.predicate,
        "literal": assertion.literal,
        "qualifiers": dict(assertion.qualifiers or {}),
    }
    if assertion.object_id:
        obj = session.exec(
            select(DisciplineConcept).where(
                DisciplineConcept.concept_id == assertion.object_id
            )
        ).first()
        view["object"] = obj.canonical_name if obj else assertion.object_id
    return view


def _run_verify(
    session: Session, chunk_id: str, texts: dict[str, str]
) -> dict[str, Any]:
    if chunk_id not in texts:
        raise DisciplineWorkError(
            "TEXT_UNAVAILABLE",
            f"chunk '{chunk_id}' 无可用原文（构建 scope 未提供 manifest 文本）",
            retryable=False,
        )
    source = texts[chunk_id]
    supports = session.exec(
        select(DisciplineSupport).where(
            DisciplineSupport.chunk_id == chunk_id,
            DisciplineSupport.validation_state == "unreviewed",
        )
    ).all()
    summary = {"stage": "verify", "chunk_id": chunk_id, "supports": 0,
               "supported": 0, "contradicted": 0, "insufficient": 0}
    for support in supports:
        assertion = session.exec(
            select(DisciplineAssertion).where(
                DisciplineAssertion.assertion_id == support.assertion_id
            )
        ).first()
        if assertion is None:
            continue
        view = _assertion_view(session, assertion)
        view["span"] = {
            "start": support.char_start,
            "end": support.char_end,
            "quote": source[support.char_start:support.char_end],
        }
        outcome = verify_assertion(view, source, {})
        summary["supports"] += 1
        summary[outcome["verdict"]] += 1
        support.validation_state = outcome["verdict"]
        session.add(support)
        if outcome["verdict"] == "supported" and assertion.status in (
            "extracted", "grounded", "resolved",
        ):
            assertion.status = "model_verified"
            assertion.updated_at = utcnow_aware()
            session.add(assertion)
        elif outcome["verdict"] == "contradicted":
            others = session.exec(
                select(DisciplineSupport).where(
                    DisciplineSupport.assertion_id == assertion.assertion_id,
                    DisciplineSupport.support_id != support.support_id,
                    DisciplineSupport.validation_state != "contradicted",
                )
            ).first()
            if others is None and assertion.status != "model_verified":
                assertion.status = "quarantined"
                assertion.updated_at = utcnow_aware()
                session.add(assertion)
        record_decision(
            session, target_type="assertion", target_id=assertion.assertion_id,
            expected_revision=assertion.revision, decision=outcome["verdict"],
            reason_codes=outcome["reason_codes"],
            actor_type="model", actor_ref="verifier-c",
        )
    session.commit()
    return summary


def _latest_decision(
    session: Session, target_type: str, target_id: str
) -> Optional[DisciplineDecision]:
    rows = session.exec(
        select(DisciplineDecision)
        .where(
            DisciplineDecision.target_type == target_type,
            DisciplineDecision.target_id == target_id,
        )
        .order_by(DisciplineDecision.id.desc())
    ).all()
    return rows[0] if rows else None


def _needs_adjudication(row: Optional[DisciplineDecision]) -> bool:
    if row is None:
        return False
    if row.actor_ref == "adjudicator-d":
        return False
    return row.decision in ("ambiguous", "insufficient", "contradicted")


def _run_adjudicate(session: Session, chunk_id: str) -> dict[str, Any]:
    summary = {"stage": "adjudicate", "chunk_id": chunk_id, "disputes": 0,
               "accept": 0, "keep_separate": 0, "quarantine": 0, "reject": 0}
    mentions = session.exec(
        select(DisciplineMention).where(DisciplineMention.chunk_id == chunk_id)
    ).all()
    for mention in mentions:
        latest = _latest_decision(session, "mention", mention.mention_id)
        if not _needs_adjudication(latest) or latest is None:
            continue
        outcome = adjudicate({
            "kind": "identity",
            "target_type": "mention",
            "target_id": mention.mention_id,
            "votes": {"resolver": {"decision": latest.decision,
                                   "concept_id": mention.concept_id}},
            "candidates": ([{"concept_id": mention.concept_id}]
                           if mention.concept_id else []),
            "reason_codes": list(latest.reason_codes or []),
        })
        summary["disputes"] += 1
        summary[outcome["decision"]] += 1
        if outcome["decision"] == "accept" and outcome.get("concept_id"):
            mention.concept_id = outcome["concept_id"]
            mention.decision = "resolved"
            session.add(mention)
        record_decision(
            session, target_type="mention", target_id=mention.mention_id,
            expected_revision=None, decision=outcome["decision"],
            reason_codes=outcome["reason_codes"],
            actor_type="model", actor_ref="adjudicator-d",
        )
    support_rows = session.exec(
        select(DisciplineSupport).where(DisciplineSupport.chunk_id == chunk_id)
    ).all()
    assertion_ids = sorted({s.assertion_id for s in support_rows})
    for assertion_id in assertion_ids:
        latest = _latest_decision(session, "assertion", assertion_id)
        if not _needs_adjudication(latest) or latest is None:
            continue
        assertion = session.exec(
            select(DisciplineAssertion).where(
                DisciplineAssertion.assertion_id == assertion_id
            )
        ).first()
        if assertion is None:
            continue
        outcome = adjudicate({
            "kind": "verification",
            "target_type": "assertion",
            "target_id": assertion_id,
            "votes": {"verifier": {"verdict": latest.decision,
                                   "reason_codes": list(latest.reason_codes or [])}},
            "reason_codes": list(latest.reason_codes or []),
        })
        summary["disputes"] += 1
        summary[outcome["decision"]] += 1
        if outcome["decision"] == "quarantine":
            assertion.status = "quarantined"
            assertion.updated_at = utcnow_aware()
            session.add(assertion)
        elif outcome["decision"] == "reject":
            assertion.status = "rejected"
            assertion.updated_at = utcnow_aware()
            session.add(assertion)
        record_decision(
            session, target_type="assertion", target_id=assertion_id,
            expected_revision=assertion.revision, decision=outcome["decision"],
            reason_codes=outcome["reason_codes"],
            actor_type="model", actor_ref="adjudicator-d",
        )
    session.commit()
    return summary


def run_item(
    session: Session, item: dict[str, Any], texts: dict[str, str]
) -> dict[str, Any]:
    """执行单个已认领工作项的阶段逻辑，返回可 JSON 序列化的结果摘要。

    每阶段单独提交可重用的中间产物（mention 决策、support 核验态、
    assertion 状态、追加审计）；失败抛 ``DisciplineWorkError``。
    """
    stage = item.get("stage")
    chunk_id = item.get("chunk_id") or ""
    if stage == "resolve":
        return _run_resolve(session, chunk_id)
    if stage == "verify":
        return _run_verify(session, chunk_id, texts)
    if stage == "adjudicate":
        return _run_adjudicate(session, chunk_id)
    if stage in DEFERRED_STAGES:
        raise DisciplineWorkError(
            "STAGE_DEFERRED",
            f"阶段 '{stage}' 由 DK2/DK5 接线，DK4 worker 不处理",
            retryable=False,
        )
    if stage in CORPUS_DEFERRED_STAGES:
        return _run_build_stage(session, item, stage)
    raise DisciplineWorkError("STAGE_UNKNOWN", f"未知阶段 '{stage}'", retryable=False)


def _run_build_stage(session: Session, item: dict[str, Any],
                     stage: str) -> dict[str, Any]:
    """执行 corpus build 级单件：fts（建 FTS）/ validate（索引验收）。

    release 由 ``create_release``（CLI/服务）创建并回填进本项
    ``payload_ref``；缺失即 ``RELEASE_NOT_READY``（可重试，等 release
    创建）；CR3 服务函数真实执行，不伪造成功。
    """
    from app.services.discipline_knowledge import corpus_index as index_svc

    try:
        payload = json.loads(item.get("payload_ref") or "{}")
    except (TypeError, ValueError):
        payload = {}
    release_id = str(payload.get("release_id") or "")
    if not release_id:
        raise DisciplineWorkError(
            "RELEASE_NOT_READY", f"阶段 '{stage}' 尚无 release（等创建）",
            retryable=True)
    try:
        if stage == "fts":
            return {"stage": "fts",
                    **index_svc.build_fts(session, release_id)}
        report = index_svc.validate_index(session, release_id)
        if not report.get("ready"):
            raise DisciplineWorkError(
                "INDEX_NOT_READY",
                f"release 未就绪：{report.get('reasons')}",
                retryable=True)
        return {"stage": "validate", **report}
    except index_svc.CorpusIndexError as exc:
        raise DisciplineWorkError(
            exc.error_code, str(exc),
            retryable=exc.error_code in (
                "RELEASE_NOT_READY", "INDEX_NOT_READY",
                "TEXT_UNAVAILABLE", "FTS_UNAVAILABLE")) from exc


# ---------------------------------------------------------------------------
# corpus_rag 批量执行：分片 embed（文本按批读取、缓存复用、短事务提交）
# ---------------------------------------------------------------------------

#: embed 错误码中可重试的子集（其余一律进 failed，不无限重试）。
RETRYABLE_EMBED_ERRORS = frozenset({
    "PROVIDER_UNAVAILABLE", "PROVIDER_BUSY", "WORKER_CRASH",
})


def _parse_batch_chunks(payload_ref: str) -> list[str]:
    try:
        payload = json.loads(payload_ref or "{}")
    except (TypeError, ValueError):
        raise DisciplineWorkError(
            "SCHEMA_INVALID", "分片 payload_ref 非法", retryable=False)
    chunk_ids = payload.get("chunk_ids") or []
    if not isinstance(chunk_ids, list) or not chunk_ids or not all(
            isinstance(c, str) and c for c in chunk_ids):
        raise DisciplineWorkError(
            "SCHEMA_INVALID", "分片缺少 chunk_ids 清单", retryable=False)
    return list(chunk_ids)


def run_corpus_batch(
    session_factory,
    claimed: dict[str, Any],
    embed_client,
) -> dict[str, Any]:
    """执行一个已认领的 embed 分片，返回结果摘要。

    流程（§4.1/§3.2 约束）：
    1. 读 chunk 行取 token 估计，原子预留预算（角色 E）；
    2. 事务外按批读原文、调推理（长任务不持有长事务；心跳见下）；
    3. 推理后用**独立短连接**续租一次：失败说明 lease 已丢/构建已取消，
       直接返回 ``lease-lost``，不写任何产物；
    4. 短事务内一并检查（item token + running、build running）、批量写
       向量缓存、结算预算、标记完成、投影任务进度并提交；
    5. 取消后到达的迟到产物：提交检查行数为 0 即拒绝（向量缓存为内容寻址，
       残留行无害且可被后继构建复用，但工作项不标记成功）。

    Returns:
        ``{stage, unit_key, chunks, computed, cached, tokens,
        outcome}``，outcome ∈ {done, lease-lost, cancelled-race}。
        失败抛 ``DisciplineWorkError``（调用方按 retryable 退回/记失败）。
    """
    from app.platform.knowledge.corpus_embedding import (
        EmbeddingValidationError,
        VectorCache,
        input_hash_for,
    )
    from app.services.discipline_knowledge import builds as build_svc
    from app.services.discipline_knowledge.corpus_text import (
        CorpusTextError,
        read_chunk_text,
    )

    item_id = claimed["item_id"]
    build_id = claimed["build_id"]
    if claimed.get("stage") != "embed":
        raise DisciplineWorkError(
            "STAGE_UNKNOWN",
            f"run_corpus_batch 只处理 embed（当前 {claimed.get('stage')}）",
            retryable=False)
    chunk_ids = _parse_batch_chunks(claimed.get("payload_ref") or "")

    with session_factory() as session:
        build = build_svc.get_build(session, build_id)
    budget = build["budget"]
    model_fingerprint = build.get("model_version") or ""
    if not model_fingerprint:
        raise DisciplineWorkError(
            "SCHEMA_INVALID", "构建无冻结模型指纹", retryable=False)

    # -- 1. 估计与预留（token 按 chunk 行实数，缺失按字符粗估） --
    with session_factory() as session:
        rows = session.exec(
            select(DisciplineChunk).where(
                DisciplineChunk.chunk_id.in_(chunk_ids))
        ).all()
        by_id = {row.chunk_id: row for row in rows}
        missing = [c for c in chunk_ids if c not in by_id]
        if missing:
            raise DisciplineWorkError(
                "TEXT_UNAVAILABLE", f"chunk 行缺失：{missing[:3]}",
                retryable=False)
        estimate = sum(
            row.token_count if row.token_count else max(1, row.char_count // 4)
            for row in rows)
        reserved = build_svc.reserve_budget(
            session, build_id, "E", estimate, 0)
    if not reserved:
        raise DisciplineWorkError("BUDGET_EXCEEDED", "embedding 预算不足（可恢复）",
                                  retryable=True)

    # -- 2. 事务外读原文 + 缓存分区（命中不重算） + 推理 --
    texts: list[str] = []
    with session_factory() as session:
        for chunk_id in chunk_ids:
            try:
                texts.append(read_chunk_text(session, chunk_id))
            except CorpusTextError as exc:
                build_svc.settle_budget(session, build_id, "E",
                                        estimate, 0, 0, 0)
                raise DisciplineWorkError(
                    exc.error_code, str(exc), retryable=False) from exc
    with session_factory() as session:
        cache_probe = VectorCache(session)
        hits: dict[str, Any] = {}
        miss_texts: list[str] = []
        miss_index: list[int] = []
        for position, text in enumerate(texts):
            key = input_hash_for(text, "passage", model_fingerprint)
            hit = cache_probe.get(model_fingerprint, key)
            if hit is not None:
                hits[chunk_ids[position]] = hit
            else:
                miss_texts.append(text)
                miss_index.append(position)
    vectors: list[list[float]] = [[] for _ in texts]
    token_counts = [0] * len(texts)
    cached_tokens = 0
    for chunk_id, row in hits.items():
        position = chunk_ids.index(chunk_id)
        vectors[position] = list(row.embedding or [])
        token_counts[position] = row.token_count
        cached_tokens += row.token_count
    if miss_texts:
        try:
            result = embed_client.embed(miss_texts, "passage")
        except EmbeddingValidationError as exc:
            with session_factory() as session:
                build_svc.settle_budget(session, build_id, "E",
                                        estimate, 0, 0, 0,
                                        unknown_tokens=estimate)
            raise DisciplineWorkError(
                exc.error_code, str(exc),
                retryable=exc.error_code in RETRYABLE_EMBED_ERRORS) from exc
        if str(result.get("model_fingerprint") or "") != model_fingerprint:
            with session_factory() as session:
                build_svc.settle_budget(session, build_id, "E",
                                        estimate, 0, 0, 0)
            raise DisciplineWorkError(
                "MODEL_MISMATCH", "推理返回指纹与构建冻结指纹不一致",
                retryable=False)
        miss_vectors = result.get("vectors") or []
        miss_counts = list(result.get("token_counts") or [0] * len(miss_texts))
        from app.platform.knowledge.corpus_embedding import validate_vectors

        validate_vectors(miss_vectors,
                         expected_dimension=int(budget.get("dimension") or 0),
                         expected_count=len(miss_texts))
        for position, vector, tokens in zip(miss_index, miss_vectors, miss_counts):
            vectors[position] = list(vector)
            token_counts[position] = tokens
    actual_tokens = sum(token_counts)

    # -- 3. 独立短连接心跳（仅当发生推理；全命中无需长等待） --
    if miss_texts:
        with session_factory() as heartbeat:
            alive = renew_lease(heartbeat, item_id, claimed["lease_token"],
                                utcnow_aware())
        if not alive:
            with session_factory() as session:
                build_svc.settle_budget(session, build_id, "E",
                                        estimate, 0, 0, 0,
                                        unknown_tokens=estimate)
            return {"stage": "embed", "unit_key": claimed.get("unit_key"),
                    "chunks": len(chunk_ids), "computed": 0, "cached": 0,
                    "tokens": 0, "outcome": "lease-lost"}

    # -- 4. 短事务：检查 + 批量写缓存 + 结算 + 完成 + 进度 --
    with session_factory() as session:
        build_row = session.exec(
            select(DisciplineBuild).where(
                DisciplineBuild.build_id == build_id)
        ).first()
        if build_row is None or build_row.status != "running":
            build_svc.settle_budget(session, build_id, "E",
                                    estimate, 0, 0, 0)
            return {"stage": "embed", "unit_key": claimed.get("unit_key"),
                    "chunks": len(chunk_ids), "computed": 0, "cached": 0,
                    "tokens": 0, "outcome": "cancelled-race"}
        cache = VectorCache(session)
        computed = 0
        cached_tokens = 0
        for chunk_id, text, vector, tokens in zip(
                chunk_ids, texts, vectors, token_counts):
            key = input_hash_for(text, "passage", model_fingerprint)
            hit = cache.get(model_fingerprint, key)
            if hit is not None:
                cached_tokens += tokens
                continue
            cache.put(model_fingerprint=model_fingerprint, input_hash=key,
                      vector=vector, dimension=len(vector),
                      token_count=tokens, commit=False)
            computed += 1
        session.flush()
        build_row.counters = build_svc.apply_settle_counters(
            build_row.counters, "E", estimate, 0, actual_tokens, 0,
            cached_tokens=cached_tokens)
        session.add(build_row)
        done = session.execute(
            update(DisciplineWorkItem)
            .where(
                DisciplineWorkItem.item_id == item_id,
                DisciplineWorkItem.lease_token == claimed["lease_token"],
                DisciplineWorkItem.status == "running",
            )
            .values(
                status="succeeded",
                result_ref=json.dumps(
                    {"stage": "embed", "chunk_ids": chunk_ids,
                     "computed": computed, "cached": len(chunk_ids) - computed,
                     "tokens": actual_tokens}, ensure_ascii=False)[:512],
                error_code="",
                updated_at=utcnow_aware(),
            )
        )
        if done.rowcount != 1:
            session.rollback()
            return {"stage": "embed", "unit_key": claimed.get("unit_key"),
                    "chunks": len(chunk_ids), "computed": 0, "cached": 0,
                    "tokens": 0, "outcome": "cancelled-race"}
        try:
            from app.services.task_service import TaskService

            if build_row.task_id:
                view = build_svc.get_build(session, build_id)
                total = max(1, view["items_total"])
                finished = view["items_by_status"].get("succeeded", 0)
                TaskService().mark_progress(
                    session, build_row.task_id,
                    progress=min(99, finished * 100 // total),
                    stage="embed",
                    message=f"embed {claimed.get('unit_key')}",
                )
        except Exception:  # noqa: BLE001 - 进度投影失败不影响产物提交
            pass
        session.commit()
    return {"stage": "embed", "unit_key": claimed.get("unit_key"),
            "chunks": len(chunk_ids), "computed": computed,
            "cached": len(chunk_ids) - computed, "tokens": actual_tokens,
            "outcome": "done"}
