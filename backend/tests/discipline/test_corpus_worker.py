"""CR2 corpus_rag 批处理验收：分片规划、批量向量化、缓存复用、预算与租约。

合成数据 + 确定性 fake 推理客户端（不下载模型、不调网络）。
注：PG 双连接真并发与百万片段性能本地未覆盖（SQLite 单测为顺序语义，
test_worker.py 既有注释同样声明），须在专用 PG 测试库另行验证。
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.discipline_knowledge_model import (
    DisciplineBuild,
    DisciplineWorkItem,
)
from app.platform.knowledge.corpus_embedding import (
    EmbeddingValidationError,
    VectorCache,
)
from app.services.discipline_knowledge import builds as build_svc
from app.services.discipline_knowledge import work_items as item_svc

FAKE_FP = "emfp_fake_test_001"
FAKE_DIM = 8

DOC_A = (
    "合成向量文档甲：栈是后进先出表，压栈弹栈均为常数时间。"
    "队列是先进先出表，循环队列取模回绕。"
)
DOC_B = (
    "合成向量文档乙：哈希表用哈希函数把键映射到槽位。"
    "冲突时链地址法把元素挂到同一槽位链表。"
)
DOC_C = (
    "合成向量文档丙：二分查找要求搜索空间有序，每次比较缩小一半区间。"
    "时间复杂度为对数级别。"
)


class FakeEmbedClient:
    """确定性 fake 推理：输入 hash 派生单位向量；可注入失败。"""

    def __init__(self, fingerprint=FAKE_FP, dimension=FAKE_DIM):
        self.fingerprint = fingerprint
        self.dimension = dimension
        self.calls: list[tuple[list[str], str]] = []
        self.fail_with: str | None = None

    def embed(self, texts, kind="passage"):
        self.calls.append((list(texts), kind))
        if self.fail_with:
            raise EmbeddingValidationError(self.fail_with, "fake failure")
        vectors = []
        for text in texts:
            digest = hashlib.sha256(
                f"{self.fingerprint}|{kind}|{text}".encode()).digest()
            vals: list[float] = []
            while len(vals) < self.dimension:
                digest = hashlib.sha256(digest).digest()
                vals.extend([(b - 128) / 128.0 for b in digest])
            vals = vals[:self.dimension]
            norm = math.sqrt(sum(v * v for v in vals)) or 1.0
            vectors.append([v / norm for v in vals])
        return {"vectors": vectors,
                "token_counts": [max(1, len(t) // 4) for t in texts],
                "model_fingerprint": self.fingerprint}


def _write_manifest(tmp_path: Path, name: str, texts: list[str]) -> str:
    documents = [{
        "source_kind": "textbook",
        "external_id": f"synth-vec-{name}-{i}",
        "source_family_id": f"synth-vec-{name}",
        "title": f"合成向量样例{name}-{i}",
        "language": "zh",
        "domains": ["data_structures"],
        "license_code": "CC-BY-SA-4.0",
        "text": text,
    } for i, text in enumerate(texts)]
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"documents": documents}, ensure_ascii=False),
                    encoding="utf-8")
    return str(path)


def _make_corpus_build(session, manifest, **kwargs):
    config = {"model_fingerprint": FAKE_FP, "dimension": FAKE_DIM,
              "batch_size": 2}
    config.update(kwargs.pop("config", {}))
    created = build_svc.create_corpus_build(
        session, owner_user_id=kwargs.pop("owner_user_id", 11),
        scope={"manifest_path": manifest}, config=config, **kwargs)
    build_svc.start_build(session, created["build_id"])
    return created


def test_create_corpus_build_plans_shards(session, tmp_path):
    manifest = _write_manifest(tmp_path, "c1", [DOC_A, DOC_B, DOC_C])
    created = build_svc.create_corpus_build(
        session, owner_user_id=11, scope={"manifest_path": manifest},
        config={"model_fingerprint": FAKE_FP, "dimension": FAKE_DIM,
                "batch_size": 2})
    assert created["created"] is True
    assert created["planned_chunks"] == 3
    assert created["planned_shards"] == 2
    assert created["model_fingerprint"] == FAKE_FP
    view = build_svc.get_build(session, created["build_id"])
    assert view["pipeline_kind"] == "corpus_rag"
    assert view["model_version"] == FAKE_FP
    assert view["stages"] == ["embed", "fts", "validate"]
    assert view["items_by_stage"]["embed"] == {"pending": 2}
    assert view["items_by_stage"]["fts"] == {"pending": 1}
    assert view["items_by_stage"]["validate"] == {"pending": 1}
    shards = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == created["build_id"],
            DisciplineWorkItem.stage == "embed")).all()
    assert all(s.unit_kind == "shard" for s in shards)
    for shard in shards:
        assert len(shard.payload_ref) <= 512
        assert len(json.loads(shard.payload_ref)["chunk_ids"]) <= 2


def test_corpus_build_requires_fingerprint_and_dimension(session, tmp_path):
    manifest = _write_manifest(tmp_path, "c2", [DOC_A])
    with pytest.raises(build_svc.DisciplineBuildError) as exc_info:
        build_svc.create_corpus_build(
            session, owner_user_id=11, scope={"manifest_path": manifest},
            config={"dimension": FAKE_DIM})
    assert exc_info.value.error_code == "SCHEMA_INVALID"
    with pytest.raises(build_svc.DisciplineBuildError) as exc_info:
        build_svc.create_corpus_build(
            session, owner_user_id=11, scope={"manifest_path": manifest},
            config={"model_fingerprint": FAKE_FP})
    assert exc_info.value.error_code == "SCHEMA_INVALID"


def test_embed_batch_end_to_end(session, tmp_path):
    manifest = _write_manifest(tmp_path, "c3", [DOC_A])
    created = _make_corpus_build(session, manifest)
    client = FakeEmbedClient()
    claimed = item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                                  pipeline_kind="corpus_rag", stages=["embed"])
    assert claimed is not None and claimed["stage"] == "embed"
    assert claimed["unit_kind"] == "shard"
    summary = item_svc.run_corpus_batch(_single_session_factory(session),
                                        claimed, client)
    assert summary["outcome"] == "done"
    assert summary["chunks"] == 1 and summary["computed"] == 1
    assert summary["cached"] == 0 and summary["tokens"] > 0
    assert len(client.calls) == 1
    view = build_svc.get_build(session, created["build_id"])
    assert view["counters"]["used"]["input"] == summary["tokens"]
    assert build_svc.embedded_chunks(session, created["build_id"]) == \
        set(json.loads(claimed["payload_ref"])["chunk_ids"])


def test_second_build_reuses_cache_without_recompute(session, tmp_path):
    manifest = _write_manifest(tmp_path, "c4", [DOC_A, DOC_B])
    first = _make_corpus_build(session, manifest,
                               config={"model_fingerprint": FAKE_FP,
                                       "dimension": FAKE_DIM, "batch_size": 2})
    client = FakeEmbedClient()
    _run_all_embeds(session, client)
    calls_after_first = len(client.calls)
    assert calls_after_first >= 1
    # 同一输入的新批次：自有工作项，但推理零新增调用
    second = build_svc.create_corpus_build(
        session, owner_user_id=12, scope={"manifest_path": manifest},
        config={"model_fingerprint": FAKE_FP, "dimension": FAKE_DIM,
                "batch_size": 2})
    build_svc.start_build(session, second["build_id"])
    assert second["build_id"] != first["build_id"]
    second_items = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == second["build_id"],
            DisciplineWorkItem.stage == "embed")).all()
    assert len(second_items) == 1  # 自有工作身份（不复用旧 build 的项）
    _run_all_embeds(session, client)
    assert len(client.calls) == calls_after_first  # 缓存命中，不重算
    view = build_svc.get_build(session, second["build_id"])
    assert view["items_by_status"].get("succeeded", 0) == 1


def test_failed_item_rerun_succeeds(session, tmp_path):
    # 独立正文（避免命中他用例已缓存的向量，确保真实走推理失败路径）
    text = DOC_A + "重跑用例附加句：信号量用于进程同步与互斥。"
    manifest = _write_manifest(tmp_path, "c5", [text])
    created = _make_corpus_build(session, manifest)
    client = FakeEmbedClient()
    client.fail_with = "PROVIDER_UNAVAILABLE"
    claimed = item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                                  pipeline_kind="corpus_rag", stages=["embed"])
    with pytest.raises(item_svc.DisciplineWorkError) as exc_info:
        item_svc.run_corpus_batch(_single_session_factory(session),
                                  claimed, client)
    assert exc_info.value.error_code == "PROVIDER_UNAVAILABLE"
    assert exc_info.value.retryable is True
    status = item_svc.fail_item(session, claimed["item_id"],
                                claimed["lease_token"], "PROVIDER_UNAVAILABLE",
                                retryable=True, max_retries=2)
    assert status == "pending"
    client.fail_with = None
    claimed2 = item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                                   pipeline_kind="corpus_rag", stages=["embed"])
    assert claimed2 is not None and claimed2["item_id"] == claimed["item_id"]
    summary = item_svc.run_corpus_batch(_single_session_factory(session),
                                        claimed2, client)
    assert summary["outcome"] == "done"


def test_budget_pause_on_max_chunks_without_fake_success(session, tmp_path):
    manifest = _write_manifest(tmp_path, "c6", [DOC_A, DOC_B])
    created = _make_corpus_build(
        session, manifest,
        config={"model_fingerprint": FAKE_FP, "dimension": FAKE_DIM,
                "batch_size": 1, "budget": {"max_chunks": 1}})
    client = FakeEmbedClient()
    outcomes = _run_all_embeds_via_worker(session, client)
    assert outcomes[0] == "done"
    assert "paused" in outcomes
    view = build_svc.get_build(session, created["build_id"])
    # 到顶暂停：构建保持 running（可恢复），不伪装成功
    assert view["status"] == "running"
    assert len(build_svc.embedded_chunks(session, created["build_id"])) == 1
    assert view["items_by_status"].get("failed", 0) == 0


def _load_worker_module():
    import importlib.util

    script = (Path(__file__).resolve().parents[3] / "backend" / "scripts"
              / "run_discipline_worker.py")
    spec = importlib.util.spec_from_file_location("run_discipline_worker", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def process_one_factory(session):
    """返回 () -> outcome 调用器：经真实 worker 主循环处理一个工作项。"""
    worker_mod = _load_worker_module()
    engine = session.get_bind()

    def _run():
        return worker_mod.process_one(
            lambda: Session(engine), "w-budget", 180, "corpus_rag",
            FakeEmbedClient())

    return _run


def test_repeated_budget_pauses_stay_recoverable(session, tmp_path):
    """预算到顶反复暂停（模拟 systemd 重启循环）不得退化为 failed。"""
    manifest = _write_manifest(tmp_path, "c8", [DOC_A, DOC_B])
    created = _make_corpus_build(
        session, manifest,
        config={"model_fingerprint": FAKE_FP, "dimension": FAKE_DIM,
                "batch_size": 1, "budget": {"max_chunks": 1, "retries": 2}})
    worker_mod = _load_worker_module()
    engine = session.get_bind()

    def factory():
        return Session(engine)

    client = FakeEmbedClient()
    outcomes = [worker_mod.process_one(factory, "w-cap", 180, "corpus_rag",
                                       client) for _ in range(6)]
    assert outcomes.count("paused") >= 3
    assert "failed" not in outcomes
    view = build_svc.get_build(session, created["build_id"])
    assert view["status"] == "running"
    assert view["items_by_status"].get("failed", 0) == 0
    paused = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == created["build_id"],
            DisciplineWorkItem.stage == "embed",
            DisciplineWorkItem.status == "pending")).all()
    assert paused
    # 预算暂停不算一次失败尝试：attempts 不累积（否则最终仍会翻 failed）
    assert all(item.attempts == 0 for item in paused)


def test_crash_retries_still_fail_after_max_retries(session, tmp_path):
    """反向守卫：真实崩溃仍按 max_retries 语义翻 failed，不被暂停改动放行。"""
    manifest = _write_manifest(tmp_path, "c9", [DOC_A])
    _make_corpus_build(session, manifest)
    claimed = item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                                  pipeline_kind="corpus_rag", stages=["embed"])
    assert claimed is not None
    status = item_svc.fail_item(session, claimed["item_id"],
                                claimed["lease_token"], "WORKER_CRASH",
                                retryable=True, max_retries=0)
    assert status == "failed"


def test_max_time_budget_pauses_without_fake_success(session, tmp_path):
    """max_time_seconds 到顶：暂停可恢复，不伪成功（P2-10 补覆盖）。"""
    manifest = _write_manifest(tmp_path, "c10", [DOC_A])
    created = _make_corpus_build(
        session, manifest,
        config={"model_fingerprint": FAKE_FP, "dimension": FAKE_DIM,
                "batch_size": 1, "budget": {"max_time_seconds": 1}})
    row = session.exec(
        select(DisciplineBuild).where(
            DisciplineBuild.build_id == created["build_id"])).one()
    row.started_at = utcnow_aware() - timedelta(seconds=10)
    session.add(row)
    session.commit()
    outcome = process_one_factory(session)()
    assert outcome == "paused"
    view = build_svc.get_build(session, created["build_id"])
    assert view["status"] == "running"
    assert view["items_by_status"].get("failed", 0) == 0


def test_max_disk_budget_pauses_without_fake_success(session, tmp_path):
    """max_disk_bytes 预估超限：暂停可恢复（P2-10 补覆盖）。"""
    manifest = _write_manifest(tmp_path, "c11", [DOC_A])
    created = _make_corpus_build(
        session, manifest,
        config={"model_fingerprint": FAKE_FP, "dimension": FAKE_DIM,
                "batch_size": 1, "budget": {"max_disk_bytes": 1}})
    outcome = process_one_factory(session)()
    assert outcome == "paused"
    view = build_svc.get_build(session, created["build_id"])
    assert view["status"] == "running"
    assert view["items_by_status"].get("failed", 0) == 0


def test_cancel_rejects_late_commit(session, tmp_path):
    manifest = _write_manifest(tmp_path, "c7", [DOC_A])
    created = _make_corpus_build(session, manifest)
    client = FakeEmbedClient()
    claimed = item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                                  pipeline_kind="corpus_rag", stages=["embed"])
    assert claimed is not None
    build_svc.cancel_build(session, created["build_id"])
    summary = item_svc.run_corpus_batch(_single_session_factory(session),
                                        claimed, client)
    assert summary["outcome"] == "cancelled-race"
    row = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.item_id == claimed["item_id"])).one()
    assert row.status != "succeeded"


def test_lease_expiry_new_owner_wins(session, tmp_path):
    text = DOC_A + "租约用例附加句：管程将共享变量与操作封装在一起。"
    manifest = _write_manifest(tmp_path, "c8", [text])
    _make_corpus_build(session, manifest)
    client = FakeEmbedClient()
    first = item_svc.claim_item(session, "wA", utcnow_aware(), 180,
                                pipeline_kind="corpus_rag", stages=["embed"])
    assert first is not None
    row = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.item_id == first["item_id"])).one()
    row.lease_until = utcnow_aware() - timedelta(seconds=1)
    session.add(row)
    session.commit()
    # 租约过期被新 owner 接管后，旧 owner 的推理结果不得落库
    assert item_svc.reap_expired_leases(session, utcnow_aware())["requeued"] == 1
    second = item_svc.claim_item(session, "wB", utcnow_aware(), 180,
                                 pipeline_kind="corpus_rag", stages=["embed"])
    assert second is not None and second["item_id"] == first["item_id"]
    assert second["lease_token"] != first["lease_token"]
    summary = item_svc.run_corpus_batch(_single_session_factory(session),
                                        first, client)
    assert summary["outcome"] == "lease-lost"
    # 新 owner 接管并成功
    summary = item_svc.run_corpus_batch(_single_session_factory(session),
                                        second, client)
    assert summary["outcome"] == "done"


def test_fts_gated_until_embed_done(session, tmp_path):
    manifest = _write_manifest(tmp_path, "c9", [DOC_A])
    created = _make_corpus_build(session, manifest)
    # embed 未完成时 fts 不可认领
    assert item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                               pipeline_kind="corpus_rag",
                               stages=["fts"]) is None
    client = FakeEmbedClient()
    _run_all_embeds(session, client)
    fts = item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                              pipeline_kind="corpus_rag", stages=["fts"])
    assert fts is not None and fts["stage"] == "fts"
    # CR3 已接线：无 release 回填时可重试等待（由 release 创建方回填），不伪造成功
    with pytest.raises(item_svc.DisciplineWorkError) as exc_info:
        item_svc.run_item(session, fts, {})
    assert exc_info.value.error_code == "RELEASE_NOT_READY"
    assert exc_info.value.retryable is True
    # validate 仍被 fts 阻塞
    assert item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                               pipeline_kind="corpus_rag",
                               stages=["validate"]) is None


def test_legacy_builds_not_claimed_by_corpus_worker(session, tmp_path):
    manifest = _write_manifest(tmp_path, "c10", [DOC_A])
    legacy = build_svc.create_build(
        session, owner_user_id=13, scope={"manifest_path": manifest})
    build_svc.start_build(session, legacy["build_id"])
    assert item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                               pipeline_kind="corpus_rag",
                               stages=["embed"]) is None
    legacy_claim = item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                                       pipeline_kind="legacy_extraction")
    assert legacy_claim is not None
    assert legacy_claim["build_id"] == legacy["build_id"]


def test_model_mismatch_never_writes(session, tmp_path):
    text = DOC_A + "错模型用例附加句：虚拟存储统一管理内存与外存。"
    manifest = _write_manifest(tmp_path, "c11", [text])
    _make_corpus_build(session, manifest)
    claimed = item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                                  pipeline_kind="corpus_rag", stages=["embed"])
    bad_client = FakeEmbedClient(fingerprint="emfp_wrong_model")
    with pytest.raises(item_svc.DisciplineWorkError) as exc_info:
        item_svc.run_corpus_batch(_single_session_factory(session),
                                  claimed, bad_client)
    assert exc_info.value.error_code == "MODEL_MISMATCH"
    assert exc_info.value.retryable is False


# ---------------------------------------------------------------------------
# 小 helpers（顺序认领 + 执行；PG 真并发见模块 docstring 声明）
# ---------------------------------------------------------------------------


def _single_session_factory(session):
    """把当前测试 session 包装成 factory（顺序语义；并发见声明）。"""
    class _Factory:
        def __call__(self):
            return _Borrowed(session)

    class _Borrowed:
        def __init__(self, inner):
            self._inner = inner

        def __enter__(self):
            return self._inner

        def __exit__(self, *exc):
            return False

    return _Factory()


def _run_all_embeds(session, client, limit=20):
    outcomes = []
    for _ in range(limit):
        claimed = item_svc.claim_item(session, "w1", utcnow_aware(), 180,
                                      pipeline_kind="corpus_rag",
                                      stages=["embed"])
        if claimed is None:
            break
        outcomes.append(item_svc.run_corpus_batch(
            _single_session_factory(session), claimed, client)["outcome"])
    return outcomes


def _run_all_embeds_via_worker(session, client, limit=20):
    """经 worker 主循环（预算门/暂停语义与生产一致）。"""
    import importlib.util

    script = (Path(__file__).resolve().parents[3] / "backend" / "scripts"
              / "run_discipline_worker.py")
    spec = importlib.util.spec_from_file_location("run_discipline_worker", script)
    worker_mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(worker_mod)
    engine = session.get_bind()

    def factory():
        return Session(engine)

    outcomes = []
    for _ in range(limit):
        outcome = worker_mod.process_one(factory, "w-cap", 180, "corpus_rag",
                                         client)
        outcomes.append(outcome)
        if outcome in ("idle", "paused"):
            break
    return outcomes
