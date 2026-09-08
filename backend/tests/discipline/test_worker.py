"""DK4 Worker、租约与预算验收测试（合成数据；PG 并发路径本地未覆盖见注）。"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.discipline_knowledge_model import (
    DisciplineAlias,
    DisciplineAssertion,
    DisciplineConcept,
    DisciplineDecision,
    DisciplineMention,
    DisciplineSupport,
    DisciplineWorkItem,
)
from app.services.discipline_knowledge import builds as build_svc
from app.services.discipline_knowledge import work_items as item_svc
from app.services.discipline_knowledge.ingest import ingest_document

DOC_A = (
    "合成构建文档甲：栈是后进先出表，压栈弹栈均为常数时间。"
    "队列是先进先出表，循环队列取模回绕。"
)
DOC_B = (
    "合成构建文档乙：哈希表用哈希函数把键映射到槽位。"
    "冲突时链地址法把元素挂到同一槽位链表。"
)


def _write_manifest(tmp_path: Path, name: str, texts: list[str]) -> str:
    documents = [{
        "source_kind": "textbook",
        "external_id": f"synth-w-{name}-{i}",
        "source_family_id": f"synth-w-{name}",
        "version": "v1",
        "domains": ["data_structures"],
        "license_code": "CC-BY-SA-4.0",
        "text": text,
    } for i, text in enumerate(texts)]
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"documents": documents}, ensure_ascii=False),
                    encoding="utf-8")
    return str(path)


def _make_build(session, manifest_path, **kwargs):
    params = {"owner_user_id": 1, "scope": {"manifest_path": manifest_path}}
    params.update(kwargs)
    created = build_svc.create_build(session, **params)
    build_svc.start_build(session, created["build_id"])
    return created


def _claim(session, worker="w1", lease=180):
    return item_svc.claim_item(session, worker, utcnow_aware(), lease)


def test_stale_worker_cannot_commit(session, tmp_path):
    created = _make_build(session, _write_manifest(tmp_path, "m1", [DOC_A]))
    leased = _claim(session)
    assert leased is not None
    # 过期/伪造 token 不能落库（对应计划 DK4 验收片段）
    assert item_svc.complete_item(session, leased["item_id"], "expired-token",
                                  "public-test-result") is False
    assert item_svc.complete_item(session, leased["item_id"],
                                  leased["lease_token"], "public-test-result") is True


def test_expired_lease_reclaimed_new_owner_wins(session, tmp_path):
    _make_build(session, _write_manifest(tmp_path, "m2", [DOC_A]))
    first = _claim(session, worker="wA")
    assert first is not None
    # 租约过期后另一 worker 接管
    row = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.item_id == first["item_id"])
    ).one()
    row.lease_until = utcnow_aware() - timedelta(seconds=1)
    session.add(row)
    session.commit()
    # 与 worker 主循环同序：先回收过期租约，再认领
    assert item_svc.reap_expired_leases(session, utcnow_aware()) == {
        "requeued": 1, "cancelled": 0}
    second = _claim(session, worker="wB")
    assert second is not None
    assert second["item_id"] == first["item_id"]
    assert second["lease_token"] != first["lease_token"]
    assert item_svc.complete_item(session, first["item_id"],
                                  first["lease_token"], "late") is False
    assert item_svc.complete_item(session, second["item_id"],
                                  second["lease_token"], "ok") is True


def test_competing_sessions_claim_distinct_items(session, test_engine, tmp_path):
    # 注：SQLite 单测为顺序竞争；PG 下 SELECT FOR UPDATE SKIP LOCKED 的
    # 真并发验收需一次性 PG 测试库（本地无 PG，未执行）。
    _make_build(session, _write_manifest(tmp_path, "m3", [DOC_A]))
    first = _claim(session, worker="w1")
    assert first is not None
    with Session(test_engine) as other:
        # 同一工作项运行中：第二个认领者拿不到它（至多拿到别的项）
        again = item_svc.claim_item(other, "w2", utcnow_aware(), 180)
        assert again is None or again["item_id"] != first["item_id"]


def test_renew_lease_owner_only(session, tmp_path):
    _make_build(session, _write_manifest(tmp_path, "m4", [DOC_A]))
    leased = _claim(session)
    assert leased is not None
    assert item_svc.renew_lease(session, leased["item_id"], "bad-token",
                                utcnow_aware(), 180) is False
    assert item_svc.renew_lease(session, leased["item_id"],
                                leased["lease_token"], utcnow_aware(), 180) is True


def test_reap_expired_running_items(session, tmp_path):
    created = _make_build(session, _write_manifest(tmp_path, "m5", [DOC_A]))
    leased = _claim(session)
    assert leased is not None
    row = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.item_id == leased["item_id"])
    ).one()
    row.lease_until = utcnow_aware() - timedelta(seconds=1)
    session.add(row)
    session.commit()
    # 构建仍 running：退回 pending
    assert item_svc.reap_expired_leases(session, utcnow_aware()) == {
        "requeued": 1, "cancelled": 0}
    build_svc.cancel_build(session, created["build_id"])
    # 构建已取消：再次过期直接取消（此处先重新认领再过期）
    build_svc.retry_build(session, created["build_id"])
    build_svc.start_build(session, created["build_id"])
    leased2 = _claim(session, worker="w2")
    assert leased2 is not None
    row2 = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.item_id == leased2["item_id"])
    ).one()
    row2.lease_until = utcnow_aware() - timedelta(seconds=1)
    session.add(row2)
    session.commit()
    build_svc.cancel_build(session, created["build_id"])
    assert item_svc.reap_expired_leases(session, utcnow_aware()) == {
        "requeued": 0, "cancelled": 1}


def _seed_hash_concept(session):
    session.add(DisciplineConcept(
        concept_id="dkt_hash", canonical_name="哈希表", domain="data_structures",
        node_type="concept", status="active", revision=1,
    ))
    session.add(DisciplineAlias(
        concept_id="dkt_hash", language="zh", normalized_alias="哈希表",
        raw_alias="哈希表", domain="data_structures", basis="test",
    ))
    session.commit()


def _build_chunk_id(session, build_id):
    return session.exec(
        select(DisciplineWorkItem.chunk_id).where(
            DisciplineWorkItem.build_id == build_id)
    ).first()


def test_run_resolve_end_to_end(session, tmp_path):
    created = _make_build(session, _write_manifest(tmp_path, "m6", [DOC_B]))
    chunk_id = _build_chunk_id(session, created["build_id"])
    _seed_hash_concept(session)
    session.add(DisciplineMention(
        mention_id="dkt_m1", chunk_id=chunk_id, char_start=0, char_end=3,
        surface_text="哈希表", domain="data_structures", node_type="concept",
        context="", run_id="r1",
    ))
    session.commit()
    claimed = None
    for _ in range(6):
        claimed = _claim(session)
        assert claimed is not None
        if claimed["stage"] == "resolve":
            break
        item_svc.complete_item(session, claimed["item_id"],
                               claimed["lease_token"], '{"stage": "skipped"}')
    assert claimed["stage"] == "resolve"
    summary = item_svc.run_item(session, claimed, {})
    assert summary["resolved"] == 1
    assert item_svc.complete_item(session, claimed["item_id"],
                                  claimed["lease_token"],
                                  json.dumps(summary)) is True
    mention = session.exec(
        select(DisciplineMention).where(DisciplineMention.mention_id == "dkt_m1")
    ).one()
    assert mention.decision == "resolved"
    assert mention.concept_id == "dkt_hash"
    audit = session.exec(
        select(DisciplineDecision).where(
            DisciplineDecision.target_id == "dkt_m1",
            DisciplineDecision.actor_ref == "resolver-b")
    ).all()
    assert len(audit) == 1


def test_run_resolve_zero_mentions_is_honest_success(session, tmp_path):
    created = _make_build(session, _write_manifest(tmp_path, "m7", [DOC_A]),
                          stages=["resolve"])
    claimed = _claim(session)
    assert claimed is not None and claimed["stage"] == "resolve"
    summary = item_svc.run_item(session, claimed, {})
    assert summary == {"stage": "resolve", "chunk_id": claimed["chunk_id"],
                       "mentions": 0, "resolved": 0, "new": 0, "ambiguous": 0}
    assert item_svc.complete_item(session, claimed["item_id"],
                                  claimed["lease_token"], "{}") is True


def test_run_verify_supported(session, tmp_path):
    text = ("堆排序是速度较快的排序方法，分治策略的实例之一。"
            "它先建堆再逐个取出堆顶，整体流程清晰稳定。")
    created = _make_build(session, _write_manifest(tmp_path, "m8", [text]),
                          stages=["verify"])
    chunk_id = _build_chunk_id(session, created["build_id"])
    session.add(DisciplineConcept(
        concept_id="dkt_qs", canonical_name="堆排序", domain="algorithms",
        node_type="method", status="active", revision=1,
    ))
    literal = "分治策略的实例之一"
    start = text.find(literal)
    assert start >= 0
    session.add(DisciplineAssertion(
        assertion_id="dkt_a1", subject_id="dkt_qs", predicate="defines",
        literal=literal, qualifiers={}, status="extracted", revision=1,
    ))
    session.add(DisciplineSupport(
        support_id="dkt_s1", assertion_id="dkt_a1", chunk_id=chunk_id,
        char_start=start, char_end=start + len(literal),
        quote_hash="q", stance="supports", run_id="r1",
    ))
    session.commit()
    claimed = _claim(session)
    assert claimed is not None and claimed["stage"] == "verify"
    summary = item_svc.run_item(session, claimed, {chunk_id: text})
    assert summary["supported"] == 1
    support = session.exec(
        select(DisciplineSupport).where(DisciplineSupport.support_id == "dkt_s1")
    ).one()
    assert support.validation_state == "supported"
    assertion = session.exec(
        select(DisciplineAssertion).where(
            DisciplineAssertion.assertion_id == "dkt_a1")
    ).one()
    assert assertion.status == "model_verified"


def test_run_adjudicate_keeps_ambiguous_apart(session, tmp_path):
    created = _make_build(session, _write_manifest(tmp_path, "m9", [DOC_A]),
                          stages=["resolve", "adjudicate"])
    chunk_id = _build_chunk_id(session, created["build_id"])
    session.add(DisciplineMention(
        mention_id="dkt_m9", chunk_id=chunk_id, char_start=0, char_end=2,
        surface_text="未知结构", domain="", node_type="",
        context="", run_id="r1",
    ))
    session.commit()
    resolved_claim = None
    for _ in range(6):
        claimed = _claim(session)
        assert claimed is not None
        if claimed["stage"] == "resolve":
            resolved_claim = claimed
            break
        item_svc.complete_item(session, claimed["item_id"],
                               claimed["lease_token"], "{}")
    summary = item_svc.run_item(session, resolved_claim, {})
    assert summary["ambiguous"] == 1
    item_svc.complete_item(session, resolved_claim["item_id"],
                           resolved_claim["lease_token"], "{}")
    for _ in range(6):
        claimed = _claim(session)
        assert claimed is not None
        if claimed["stage"] == "adjudicate":
            break
        item_svc.complete_item(session, claimed["item_id"],
                               claimed["lease_token"], "{}")
    assert claimed["stage"] == "adjudicate"
    summary = item_svc.run_item(session, claimed, {})
    assert summary["disputes"] == 1
    assert summary["keep_separate"] == 1
    audit = session.exec(
        select(DisciplineDecision).where(
            DisciplineDecision.target_id == "dkt_m9",
            DisciplineDecision.actor_ref == "adjudicator-d")
    ).all()
    assert len(audit) == 1
    assert audit[0].decision == "keep_separate"


def test_deferred_stage_fails_honest(session):
    with pytest.raises(item_svc.DisciplineWorkError) as exc_info:
        item_svc.run_item(session, {"stage": "extract", "chunk_id": "dkch_x"}, {})
    assert exc_info.value.error_code == "STAGE_DEFERRED"
    assert exc_info.value.retryable is False


def test_budget_reserve_and_settle(session, tmp_path):
    created = _make_build(
        session, _write_manifest(tmp_path, "m10", [DOC_A]),
        budget={"max_chunks": 10, "max_input_tokens": 1000,
                "max_output_tokens": 100,
                "role_budgets": {"B": {"max_input_tokens": 100}}},
    )
    build_id = created["build_id"]
    assert build_svc.reserve_budget(session, build_id, "B", 60, 10) is True
    # 总量超限拒绝
    assert build_svc.reserve_budget(session, build_id, "B", 950, 0) is False
    # 角色超限拒绝（总量仍充足）
    assert build_svc.reserve_budget(session, build_id, "B", 50, 0) is False
    settled = build_svc.settle_budget(session, build_id, "B", 60, 10, 40, 5)
    counters = settled["counters"]
    assert counters["used"] == {"input": 40, "output": 5}
    assert counters["reserved"] == {"input": 0, "output": 0}
    assert counters["roles"]["B"]["used_in"] == 40
    # 超时无 usage 记 unknown，不当免费
    settled = build_svc.settle_budget(session, build_id, "C", 30, 20, 0, 0,
                                      unknown_tokens=50)
    assert settled["counters"]["unknown"] == 50


def test_chunk_cap_pauses_without_fake_success(test_engine, tmp_path):
    import importlib.util

    from sqlmodel import Session as _Session

    script = (Path(__file__).resolve().parents[3] / "backend" / "scripts"
              / "run_discipline_worker.py")
    spec = importlib.util.spec_from_file_location("run_discipline_worker", script)
    worker_mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(worker_mod)

    manifest = _write_manifest(tmp_path, "m11", [DOC_A, DOC_B])
    with _Session(test_engine) as setup_session:
        created = build_svc.create_build(
            setup_session, owner_user_id=7, scope={"manifest_path": manifest},
            budget={"max_chunks": 1})
        build_svc.start_build(setup_session, created["build_id"])
        build_id = created["build_id"]

    def factory():
        return _Session(test_engine)

    assert worker_mod.process_one(factory, "w-cap", 180,
                                    "legacy_extraction") == "done"
    assert worker_mod.process_one(factory, "w-cap", 180,
                                  "legacy_extraction") == "paused"
    # CR2 行为变更：默认管线（corpus_rag）不再认领旧抽取任务
    assert worker_mod.process_one(factory, "w-cap", 180) == "idle"
    with _Session(test_engine) as check_session:
        view = build_svc.get_build(check_session, build_id)
        # 到顶暂停：构建保持 running（可恢复），不伪装成功
        assert view["status"] == "running"
        assert view["items_by_status"].get("succeeded", 0) == 1
        assert view["items_by_status"].get("failed", 0) == 0
