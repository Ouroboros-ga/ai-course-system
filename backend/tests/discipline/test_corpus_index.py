"""CR3 索引发布验收：组装、FTS、校验、激活、引用与 worker 接线。

合成数据 + 确定性 fake 向量（不下载模型、不调网络）。
FTS/正文目录按测试隔离；连接在 teardown 关闭。
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

import pytest
from sqlmodel import select

from app.models.discipline_knowledge_model import DisciplineWorkItem
from app.services.discipline_knowledge import corpus_index as index_svc
from app.services.discipline_knowledge import work_items as item_svc

TEST_FP = "emfp_cr3_test_001"
TEST_DIM = 8

CORPUS_CHUNKER = {
    "normalizer": "corpus-norm/2",
    "chunker": "corpus-chunk/1",
    "target_tokens": 320,
    "overlap_tokens": 32,
    "max_tokens": 512,
}

DOC_OS = (
    "合成发布文档甲：页表记录虚拟页与物理页的映射，缺页时触发换入换出。"
    "虚拟内存让程序看到连续的地址空间。"
)
DOC_NET = (
    "合成发布文档乙：TCP 通过三次握手建立连接，用序号与确认号保证可靠有序交付。"
    "发送方维护拥塞窗口。"
)
DOC_EN = (
    "Synthetic release doc gamma. A page table maps each virtual page "
    "to a physical frame. Paging divides memory into fixed-size frames."
)


def _fake_vector(text: str) -> list[float]:
    digest = hashlib.sha256(f"{TEST_FP}|passage|{text}".encode()).digest()
    vals: list[float] = []
    while len(vals) < TEST_DIM:
        digest = hashlib.sha256(digest).digest()
        vals.extend([(b - 128) / 128.0 for b in digest])
    vals = vals[:TEST_DIM]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


@pytest.fixture
def fts_env(tmp_path, monkeypatch):
    fts_root = tmp_path / "fts"
    fts_root.mkdir()
    monkeypatch.setenv("DISCIPLINE_FTS_ROOT", str(fts_root))
    yield {"fts_root": fts_root}
    index_svc.close_fts_connections()


def _ingest(session, external_id, text, source_kind="textbook"):
    from app.services.discipline_knowledge.ingest import ingest_document

    return ingest_document(session, {
        "source_kind": source_kind,
        "external_id": external_id,
        "source_family_id": f"fam-{external_id}",
        "title": f"合成标题-{external_id}",
        "language": "zh",
        "domains": ["os"],
        "license_code": "CC-BY-SA-4.0",
        "text": text,
    }, chunker_config=CORPUS_CHUNKER)


def _cache_vectors(session, chunk_ids, fingerprint=TEST_FP):
    from app.platform.knowledge.corpus_embedding import (
        VectorCache,
        input_hash_for,
    )
    from app.services.discipline_knowledge.corpus_text import read_chunk_text

    cache = VectorCache(session)
    for chunk_id in chunk_ids:
        text = read_chunk_text(session, chunk_id)
        cache.put(model_fingerprint=fingerprint,
                  input_hash=input_hash_for(text, "passage", fingerprint),
                  vector=_fake_vector(text), dimension=TEST_DIM,
                  token_count=max(1, len(text) // 4), commit=False)
    session.commit()


def _make_release(session, tag, texts=(DOC_OS, DOC_NET), with_vectors=True):
    chunk_ids: list[str] = []
    for i, text in enumerate(texts):
        result = _ingest(session, f"synth-cr3-{tag}-{i}", text)
        chunk_ids.extend(result["chunk_ids"])
    if with_vectors:
        _cache_vectors(session, chunk_ids)
    return index_svc.create_release(
        session, chunk_ids=chunk_ids, model_fingerprint=TEST_FP,
        dimension=TEST_DIM, title=f"合成发布-{tag}")


@pytest.fixture
def index_fixture(session, fts_env):
    """旧版本已激活 + 新版本 building（对应计划验收片段形状）。"""
    old = _make_release(session, "old", (DOC_OS,))
    index_svc.build_fts(session, old["release_id"])
    assert index_svc.validate_index(session, old["release_id"])["ready"] is True
    head_before = index_svc.read_head(session)
    activated = index_svc.activate_index(
        session, old["release_id"], head_before["revision"])
    assert activated["error_code"] == ""
    incomplete = _make_release(session, "new", (DOC_NET,))

    class _Fixture:
        pass

    fixture = _Fixture()
    fixture.old_id = old["release_id"]
    fixture.incomplete_id = incomplete["release_id"]
    fixture.head_revision = activated["revision"]

    def _read_head():
        return index_svc.read_head(session)["release_id"]

    fixture.read_head = _read_head
    return fixture


def test_incomplete_index_does_not_replace_active(session, index_fixture):
    from app.services.discipline_knowledge.corpus_index import activate_index
    result = activate_index(session, index_fixture.incomplete_id,
                            index_fixture.head_revision)
    assert result["error_code"] == "INDEX_NOT_READY"
    assert index_fixture.read_head() == index_fixture.old_id


def test_build_fts_meta_and_idempotent_reuse(session, fts_env):
    release = _make_release(session, "fts", (DOC_OS, DOC_NET))
    first = index_svc.build_fts(session, release["release_id"])
    assert first["reused"] is False
    assert first["paragraphs"] == 2
    assert first["object_key"] == index_svc.fts_object_key_for(
        release["release_id"])
    # meta 可读且版本正确
    conn = index_svc.open_fts_readonly(
        first["object_key"], expected_release_id=release["release_id"])
    row = conn.execute(
        "SELECT release_id, schema_version, input_manifest_hash FROM meta"
    ).fetchone()
    assert row[0] == release["release_id"]
    assert row[1] == index_svc.FTS_SCHEMA_VERSION
    assert row[2] == release["input_manifest_hash"]
    second = index_svc.build_fts(session, release["release_id"])
    assert second["reused"] is True
    assert second["sha256"] == first["sha256"]


def test_fts_meta_mismatch_rejected(session, fts_env):
    bogus = fts_env["fts_root"] / "corpus-fts" / "v1" / "dkr_bogus.sqlite3"
    bogus.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(bogus)
    conn.execute("CREATE TABLE meta(release_id TEXT PRIMARY KEY, "
                 "schema_version TEXT, tokenizer TEXT, tokenizer_hash TEXT, "
                 "input_manifest_hash TEXT)")
    conn.execute("INSERT INTO meta VALUES ('dkr_other', 'wrong-schema', "
                 "'x', 'y', 'z')")
    conn.commit()
    conn.close()
    with pytest.raises(index_svc.CorpusIndexError) as exc_info:
        index_svc.open_fts_readonly("corpus-fts/v1/dkr_bogus.sqlite3",
                                    expected_release_id="dkr_bogus")
    assert exc_info.value.error_code == "FTS_META_MISMATCH"


def test_validate_catches_wrong_model_vector(session, fts_env):
    release = _make_release(session, "wrongmodel", (DOC_OS,))
    # 把成员指向异模型向量（同维，绝不混算）
    from app.models.discipline_corpus_index_model import (
        DisciplineCorpusIndexMember,
    )
    from app.platform.knowledge.corpus_embedding import (
        VectorCache,
        input_hash_for,
    )
    from app.services.discipline_knowledge.corpus_text import read_chunk_text

    member = session.exec(
        select(DisciplineCorpusIndexMember).where(
            DisciplineCorpusIndexMember.release_id == release["release_id"])
    ).first()
    text = read_chunk_text(session, member.chunk_id)
    cache = VectorCache(session)
    row = cache.put(
        model_fingerprint="emfp_other_model",
        input_hash=input_hash_for(text, "passage", "emfp_other_model"),
        vector=_fake_vector(text), dimension=TEST_DIM, token_count=5)
    member.embedding_id = row.embedding_id
    session.add(member)
    session.commit()
    index_svc.build_fts(session, release["release_id"])
    report = index_svc.validate_index(session, release["release_id"])
    assert report["ready"] is False
    assert report["error_code"] == "INDEX_NOT_READY"
    assert any("vector_identity_mismatch" in r for r in report["reasons"])


def test_activate_cas_conflict_keeps_old_head(session, index_fixture):
    ready = _make_release(session, "cas", (DOC_EN,))
    index_svc.build_fts(session, ready["release_id"])
    assert index_svc.validate_index(session, ready["release_id"])["ready"]
    conflict = index_svc.activate_index(
        session, ready["release_id"], expected_revision=999)
    assert conflict["error_code"] == "RELEASE_CONFLICT"
    assert conflict["head_release_id"] == index_fixture.old_id
    assert index_fixture.read_head() == index_fixture.old_id
    ok = index_svc.activate_index(
        session, ready["release_id"], index_fixture.head_revision)
    assert ok["error_code"] == ""
    assert ok["revision"] == index_fixture.head_revision + 1
    assert index_fixture.read_head() == ready["release_id"]


def test_rollback_to_old_head(session, index_fixture):
    ready = _make_release(session, "rollback", (DOC_EN,))
    index_svc.build_fts(session, ready["release_id"])
    index_svc.validate_index(session, ready["release_id"])
    first = index_svc.activate_index(
        session, ready["release_id"], index_fixture.head_revision)
    # 回退：旧版本仍 ready，可重新激活；撤回来源不能恢复展示（见引用测试）
    back = index_svc.activate_index(
        session, index_fixture.old_id, first["revision"])
    assert back["error_code"] == ""
    assert index_fixture.read_head() == index_fixture.old_id
    manifest = index_svc.get_release_manifest(session, ready["release_id"])
    assert manifest["release_id"] == ready["release_id"]
    assert manifest["members"] >= 1


def test_activate_rejects_interleaved_commit(session, fts_env, monkeypatch):
    """检查→写入之间若有别的发布者已提交，必须以数据库当前 revision 为准。

    在 activate_index 的"读 head → 写 head"窗口内注入一次成功激活（同一
    session 提交），旧实现会用陈旧 revision 覆盖 head；新实现的条件 UPDATE
    必须落空并返回 RELEASE_CONFLICT。
    """
    import app.services.discipline_knowledge.corpus_index as index_mod

    release_a = _make_release(session, "atomic-a", (DOC_OS,))
    index_svc.build_fts(session, release_a["release_id"])
    assert index_svc.validate_index(session, release_a["release_id"])["ready"]
    release_b = _make_release(session, "atomic-b", (DOC_NET,))
    index_svc.build_fts(session, release_b["release_id"])
    assert index_svc.validate_index(session, release_b["release_id"])["ready"]
    base_revision = index_svc.read_head(session)["revision"]

    real_now = index_mod.utcnow_aware
    state = {"injected": False}

    def hooked_now():
        if not state["injected"]:
            state["injected"] = True
            injected = index_svc.activate_index(
                session, release_a["release_id"], base_revision)
            assert injected["error_code"] == ""
        return real_now()

    monkeypatch.setattr(index_mod, "utcnow_aware", hooked_now)
    result = index_svc.activate_index(
        session, release_b["release_id"], base_revision)
    assert result["error_code"] == "RELEASE_CONFLICT"
    assert index_svc.read_head(session)["release_id"] == \
        release_a["release_id"]


def test_validate_rejects_fts_without_index_rows(session, fts_env):
    """FTS 段落表非空但索引行为空：探针必须命中>0，不得判 ready。"""
    release = _make_release(session, "empty-fts", (DOC_OS,))
    built = index_svc.build_fts(session, release["release_id"])
    index_svc.close_fts_connections()
    path = fts_env["fts_root"] / built["object_key"]
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE corpus_fts")
    conn.execute("CREATE VIRTUAL TABLE corpus_fts USING fts5("
                 "title, body, tokenize='unicode61', content='')")
    conn.commit()
    conn.close()
    index_svc.close_fts_connections()
    report = index_svc.validate_index(session, release["release_id"])
    assert report["ready"] is False
    assert any(reason.startswith("fts:") for reason in report["reasons"])


def test_reference_roundtrip_withdrawn_and_cross_release(session, fts_env):
    release = _make_release(session, "ref", (DOC_OS, DOC_NET))
    other = _make_release(session, "ref-other", (DOC_EN,))
    from app.models.discipline_corpus_index_model import (
        DisciplineCorpusIndexMember,
    )
    from app.models.discipline_knowledge_model import (
        DisciplineChunk,
        DisciplineDocumentVersion,
    )

    chunk_id = session.exec(
        select(DisciplineCorpusIndexMember.chunk_id).where(
            DisciplineCorpusIndexMember.release_id == release["release_id"])
        .order_by(DisciplineCorpusIndexMember.id)).first()
    ref = index_svc.get_chunk_reference(session, chunk_id,
                                        release["release_id"])
    assert ref["reference_id"] == f"{release['release_id']}:{chunk_id}"
    assert ref["text"] and ref["is_supplementary"] is True
    # 越版本引用拒绝
    with pytest.raises(index_svc.CorpusIndexError) as exc_info:
        index_svc.get_chunk_reference(session, chunk_id, other["release_id"])
    assert exc_info.value.error_code == "NOT_IN_RELEASE"
    # 撤回后不展示
    chunk = session.exec(
        select(DisciplineChunk).where(
            DisciplineChunk.chunk_id == chunk_id)).one()
    version = session.exec(
        select(DisciplineDocumentVersion).where(
            DisciplineDocumentVersion.version_id == chunk.version_id)).one()
    version.status = "withdrawn"
    session.add(version)
    session.commit()
    with pytest.raises(index_svc.CorpusIndexError) as exc_info:
        index_svc.get_chunk_reference(session, chunk_id, release["release_id"])
    assert exc_info.value.error_code == "SOURCE_WITHDRAWN"


def test_worker_fts_validate_stages(session, fts_env):
    from app.services.discipline_knowledge import builds as build_svc

    manifest_chunks: list[str] = []
    ingested = _ingest(session, "synth-cr3-worker-0", DOC_OS)
    manifest_chunks.extend(ingested["chunk_ids"])
    _cache_vectors(session, manifest_chunks)
    release = index_svc.create_release(
        session, chunk_ids=manifest_chunks, model_fingerprint=TEST_FP,
        dimension=TEST_DIM)
    created = build_svc.create_corpus_build(
        session, owner_user_id=21,
        scope={"document_version_ids": [ingested["version_id"]]},
        config={"model_fingerprint": TEST_FP, "dimension": TEST_DIM,
                "batch_size": 4})
    # fts 单件无 release 回填时诚实等待，不伪造成功
    fts_item = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == created["build_id"],
            DisciplineWorkItem.stage == "fts")).first()
    with pytest.raises(item_svc.DisciplineWorkError) as exc_info:
        item_svc.run_item(session, {"stage": "fts", "chunk_id": "",
                                    "payload_ref": fts_item.payload_ref}, {})
    assert exc_info.value.error_code == "RELEASE_NOT_READY"
    assert exc_info.value.retryable is True
    # 回填后真实执行
    fts_item.payload_ref = json.dumps({"release_id": release["release_id"]})
    session.add(fts_item)
    session.commit()
    fts_summary = item_svc.run_item(
        session, {"stage": "fts", "chunk_id": "",
                  "payload_ref": fts_item.payload_ref}, {})
    assert fts_summary["paragraphs"] == 1
    validate_item = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == created["build_id"],
            DisciplineWorkItem.stage == "validate")).first()
    validate_item.payload_ref = json.dumps(
        {"release_id": release["release_id"]})
    session.add(validate_item)
    session.commit()
    validate_summary = item_svc.run_item(
        session, {"stage": "validate", "chunk_id": "",
                  "payload_ref": validate_item.payload_ref}, {})
    assert validate_summary["ready"] is True
