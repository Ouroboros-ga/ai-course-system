"""CR3 统一检索验收：混合融合、引用、降级、过滤与门面委托。

合成三文档（中文 OS / 中文网络 / 英文），关键词概念 fake 向量
（同概念共享维度，测跨语言召回），不下载模型、不调网络。
"""

from __future__ import annotations

import math

import pytest
from sqlmodel import select

from app.services.discipline_knowledge import corpus_index as index_svc
from app.services.discipline_knowledge.corpus_search import (
    CorpusSearchService,
    reset_vector_cooldown,
)

TEST_FP = "emfp_cr3_search_001"
TEST_DIM = 5

CORPUS_CHUNKER = {
    "normalizer": "corpus-norm/2",
    "chunker": "corpus-chunk/1",
    "target_tokens": 320,
    "overlap_tokens": 32,
    "max_tokens": 512,
}

DOC_OS = (
    "合成检索文档甲：页表记录虚拟页与物理页的映射，缺页时触发换入换出。"
    "虚拟内存让程序看到连续的地址空间。"
)
DOC_NET = (
    "合成检索文档乙：TCP 通过三次握手建立连接，用序号与确认号保证可靠有序交付。"
    "发送方维护拥塞窗口。"
)
DOC_EN = (
    "Synthetic retrieval doc gamma. A page table maps each virtual page "
    "to a physical frame. Paging divides memory into fixed-size frames."
)

#: 同概念共享维度（中英别名同维，跨语言可召回）。
CONCEPTS = [
    ("页表", "page table"),
    ("虚拟", "virtual"),
    ("TCP", "tcp"),
    ("握手", "handshake"),
    ("哈希", "hash"),
]


class KeywordFakeEmbed:
    """概念 multi-hot + L2（语义由概念表决定，与 hash fake 正交）。"""

    def __init__(self, fingerprint=TEST_FP):
        self.fingerprint = fingerprint
        self.calls: list[tuple[list[str], str]] = []
        self.fail_with: str | None = None

    def _vector(self, text: str) -> list[float]:
        lowered = text.lower()
        vals = [1.0 if any(alias in lowered for alias in concept)
                else 0.0 for concept in CONCEPTS]
        norm = math.sqrt(sum(v * v for v in vals))
        if norm == 0.0:
            return [0.0] * len(CONCEPTS)
        return [v / norm for v in vals]

    def embed(self, texts, kind="query"):
        from app.platform.knowledge.corpus_embedding import (
            EmbeddingValidationError,
        )

        self.calls.append((list(texts), kind))
        if self.fail_with:
            raise EmbeddingValidationError(self.fail_with, "fake failure")
        return {"vectors": [self._vector(t) for t in texts],
                "token_counts": [max(1, len(t) // 4) for t in texts],
                "model_fingerprint": self.fingerprint}


@pytest.fixture
def fts_env(tmp_path, monkeypatch):
    fts_root = tmp_path / "fts"
    fts_root.mkdir()
    monkeypatch.setenv("DISCIPLINE_FTS_ROOT", str(fts_root))
    yield {"fts_root": fts_root}
    index_svc.close_fts_connections()


@pytest.fixture
def search_env(session, fts_env):
    from app.platform.knowledge.corpus_embedding import (
        VectorCache,
        input_hash_for,
    )
    from app.services.discipline_knowledge.corpus_text import read_chunk_text
    from app.services.discipline_knowledge.ingest import ingest_document

    reset_vector_cooldown()
    chunk_ids: list[str] = []
    for i, (text, kind) in enumerate(
            [(DOC_OS, "textbook"), (DOC_NET, "textbook"), (DOC_EN, "enwiki")]):
        result = ingest_document(session, {
            "source_kind": kind,
            "external_id": f"synth-cr3s-{i}",
            "source_family_id": f"synth-cr3s-{i}",
            "title": f"合成检索标题{i}",
            "language": "zh" if kind != "enwiki" else "en",
            "domains": ["os"],
            "license_code": "CC-BY-SA-4.0",
            "text": text,
        }, chunker_config=CORPUS_CHUNKER)
        chunk_ids.extend(result["chunk_ids"])
    cache = VectorCache(session)
    for chunk_id in chunk_ids:
        text = read_chunk_text(session, chunk_id)
        vec = KeywordFakeEmbed()._vector(text)
        assert any(vec), text[:20]
        cache.put(model_fingerprint=TEST_FP,
                  input_hash=input_hash_for(text, "passage", TEST_FP),
                  vector=vec, dimension=TEST_DIM,
                  token_count=max(1, len(text) // 4), commit=False)
    session.commit()
    release = index_svc.create_release(
        session, chunk_ids=chunk_ids, model_fingerprint=TEST_FP,
        dimension=TEST_DIM, title="合成检索发布")
    index_svc.build_fts(session, release["release_id"])
    assert index_svc.validate_index(session, release["release_id"])["ready"]
    activated = index_svc.activate_index(session, release["release_id"], 0)
    # head 可能已被他用例推进：冲突则按当前 head 重试，保证本发布激活
    if activated["error_code"] == "RELEASE_CONFLICT":
        activated = index_svc.activate_index(
            session, release["release_id"], activated["head_revision"])
    assert activated["error_code"] == ""
    return {"release_id": release["release_id"], "chunk_ids": chunk_ids,
            "client": KeywordFakeEmbed()}


def test_hybrid_zh_query(session, search_env):
    service = CorpusSearchService()
    result = service.search(
        session, "页表是什么", release_id=search_env["release_id"],
        embed_client=search_env["client"])
    assert result["schema_version"] == "discipline-corpus/2"
    assert result["release_id"] == search_env["release_id"]
    assert result["status"] == "ok"
    assert result["match"] == "hit"
    assert result["results"]
    first = result["results"][0]
    assert first["reference_id"] == (
        f"{search_env['release_id']}:{first['chunk_id']}")
    assert first["is_supplementary"] is True
    assert first["snippet"] and first["context_text"]
    assert result["coverage"]["eligible_chunks"] == 3
    assert result["coverage"]["embedded_chunks"] == 3


def test_chinese_query_hits_english_chunk(session, search_env):
    from app.models.discipline_corpus_index_model import (
        DisciplineCorpusIndexMember,
    )

    service = CorpusSearchService()
    result = service.search(
        session, "页表是什么", release_id=search_env["release_id"],
        embed_client=search_env["client"])
    members = session.exec(
        select(DisciplineCorpusIndexMember).where(
            DisciplineCorpusIndexMember.release_id == search_env["release_id"])
    ).all()
    en_chunk = next(
        m.chunk_id for m in members
        if dict(m.display_metadata or {}).get("source_kind") == "enwiki")
    assert en_chunk in [r["chunk_id"] for r in result["results"]]
    en_result = next(r for r in result["results"] if r["chunk_id"] == en_chunk)
    # 英文块无中文词：只能来自向量路
    assert en_result["matched_by"] == ["vector"]


def test_no_answer_returns_empty(session, search_env):
    service = CorpusSearchService()
    result = service.search(
        session, "qqxzzz 不存在的内容", release_id=search_env["release_id"],
        embed_client=search_env["client"])
    assert result["match"] == "none"
    assert result["results"] == []
    assert result["status"] == "ok"


def test_vector_outage_degrades_to_fts(session, search_env):
    service = CorpusSearchService()
    search_env["client"].fail_with = "PROVIDER_UNAVAILABLE"
    try:
        result = service.search(
            session, "页表", release_id=search_env["release_id"],
            embed_client=search_env["client"])
    finally:
        search_env["client"].fail_with = None
    assert result["status"] == "degraded"
    assert "VECTOR_UNAVAILABLE" in result["degraded_reasons"]
    # FTS 仍返回中文命中
    assert result["results"]
    assert all("vector" not in r["matched_by"] for r in result["results"])


def test_both_paths_fail_is_unavailable(session, search_env, fts_env):
    import shutil

    service = CorpusSearchService()
    search_env["client"].fail_with = "PROVIDER_UNAVAILABLE"
    # 先释放只读句柄（Windows 删文件需要），再删 FTS 文件模拟双路失败
    index_svc.close_fts_connections()
    shutil.rmtree(fts_env["fts_root"])
    index_svc.close_fts_connections()
    try:
        result = service.search(
            session, "页表", release_id=search_env["release_id"],
            embed_client=search_env["client"])
    finally:
        search_env["client"].fail_with = None
        reset_vector_cooldown()
    assert result["status"] == "unavailable"
    assert result["results"] == []


def test_multi_chunk_dedup_overlap_and_context_budget(session, fts_env,
                                                      monkeypatch):
    """D1：每文档块上限、相邻块合并、上下文预算截断（此前无覆盖）。"""
    from app.platform.knowledge.corpus_embedding import (
        VectorCache,
        input_hash_for,
    )
    from app.services.discipline_knowledge import corpus_search as search_mod
    from app.services.discipline_knowledge.corpus_text import read_chunk_text
    from app.services.discipline_knowledge.ingest import ingest_document

    paragraphs = [
        f"第{i}段：页表记录虚拟页与物理页的映射，缺页时触发换入换出，"
        "虚拟内存保证程序看到连续地址空间。"
        for i in range(8)
    ]
    ingested = ingest_document(session, {
        "source_kind": "textbook",
        "external_id": "synth-cr3s-multichunk",
        "source_family_id": "synth-cr3s-multichunk",
        "title": "合成多块文档",
        "language": "zh",
        "domains": ["os"],
        "license_code": "CC-BY-SA-4.0",
        "text": "\n\n".join(paragraphs),
    }, chunker_config={
        "normalizer": "corpus-norm/2", "chunker": "corpus-chunk/1",
        "target_tokens": 48, "overlap_tokens": 8, "max_tokens": 64})
    chunk_ids = ingested["chunk_ids"]
    assert len(chunk_ids) >= 3
    cache = VectorCache(session)
    for chunk_id in chunk_ids:
        text = read_chunk_text(session, chunk_id)
        cache.put(model_fingerprint=TEST_FP,
                  input_hash=input_hash_for(text, "passage", TEST_FP),
                  vector=KeywordFakeEmbed()._vector(text), dimension=TEST_DIM,
                  token_count=max(1, len(text) // 4), commit=False)
    session.commit()
    release = index_svc.create_release(
        session, chunk_ids=chunk_ids, model_fingerprint=TEST_FP,
        dimension=TEST_DIM, title="合成多块发布")
    index_svc.build_fts(session, release["release_id"])
    report = index_svc.validate_index(session, release["release_id"])
    assert report["ready"], report["reasons"]

    service = CorpusSearchService()
    result = service.search(
        session, "页表 虚拟内存", release_id=release["release_id"],
        embed_client=KeywordFakeEmbed(), top_k=6)
    assert result["status"] == "ok"
    assert result["results"]
    # 同一文档：去重（每文档 ≤2 块）+ 相邻块合并后不超过 2 条
    assert len(result["results"]) <= 2
    # 两路都召回时标记 matched_by 含 fts 与 vector（RRF 融合入口）
    assert any(set(item["matched_by"]) == {"fts", "vector"}
               for item in result["results"])

    # 上下文预算收紧 → 邻块扩展放不下，必须显式标记截断
    monkeypatch.setattr(search_mod, "CONTEXT_BUDGET_TOKENS", 1)
    tight = service.search(
        session, "页表 虚拟内存", release_id=release["release_id"],
        embed_client=KeywordFakeEmbed(), top_k=6)
    assert tight["results"]
    assert all(item["context_truncated"] for item in tight["results"])


def test_fts_no_hit_with_vector_down_is_degraded_not_unavailable(
        session, search_env):
    """FTS 正常但零命中 + 向量不可用 ≠ 两路失败：不得报 unavailable。"""
    service = CorpusSearchService()
    search_env["client"].fail_with = "PROVIDER_UNAVAILABLE"
    try:
        result = service.search(
            session, "qqxzzz 不存在的内容", release_id=search_env["release_id"],
            embed_client=search_env["client"])
    finally:
        search_env["client"].fail_with = None
        reset_vector_cooldown()
    assert result["status"] == "degraded"
    assert result["match"] == "none"
    assert result["results"] == []
    assert result["degraded_reasons"] == ["VECTOR_UNAVAILABLE"]


def test_vector_cooldown_and_reset(session, search_env):
    service = CorpusSearchService()
    search_env["client"].fail_with = "PROVIDER_UNAVAILABLE"
    try:
        first = service.search(
            session, "页表", release_id=search_env["release_id"],
            embed_client=search_env["client"])
        assert first["status"] == "degraded"
        calls_after_fail = len(search_env["client"].calls)
        # 冷却中不再调推理（同一客户端恢复也先被冷却拦截）
        search_env["client"].fail_with = None
        second = service.search(
            session, "页表", release_id=search_env["release_id"],
            embed_client=search_env["client"])
        assert len(search_env["client"].calls) == calls_after_fail
        assert second["status"] == "degraded"
    finally:
        search_env["client"].fail_with = None
    reset_vector_cooldown()
    third = service.search(
        session, "页表", release_id=search_env["release_id"],
        embed_client=search_env["client"])
    assert third["status"] == "ok"


def test_fts_only_member(session, search_env):
    from app.models.discipline_corpus_index_model import (
        DisciplineCorpusIndexMember,
    )
    from app.services.discipline_knowledge.ingest import ingest_document

    result = ingest_document(session, {
        "source_kind": "rfc",
        "external_id": "synth-cr3s-fts-only",
        "source_family_id": "synth-cr3s-fts-only",
        "title": "合成 RFC",
        "language": "zh",
        "domains": ["net"],
        "license_code": "IETF",
        "text": "合成 RFC 文档：TCP 报文段包含序号字段，用于可靠传输排序。",
    }, chunker_config=CORPUS_CHUNKER)
    new_chunk = result["chunk_ids"][0]
    release = index_svc.create_release(
        session, chunk_ids=[*search_env["chunk_ids"], new_chunk],
        model_fingerprint=TEST_FP, dimension=TEST_DIM)
    index_svc.build_fts(session, release["release_id"])
    assert index_svc.validate_index(session, release["release_id"])["ready"]
    service = CorpusSearchService()
    found = service.search(
        session, "TCP 报文段序号", release_id=release["release_id"],
        embed_client=search_env["client"])
    only = next(r for r in found["results"] if r["chunk_id"] == new_chunk)
    assert only["matched_by"] == ["fts"]
    assert found["coverage"]["embedded_chunks"] == 3
    assert found["coverage"]["eligible_chunks"] == 4


def test_withdrawn_filtered_and_coverage(session, search_env):
    from app.models.discipline_knowledge_model import (
        DisciplineChunk,
        DisciplineDocumentVersion,
    )

    chunk = session.exec(
        select(DisciplineChunk).where(
            DisciplineChunk.chunk_id == search_env["chunk_ids"][0])).one()
    version = session.exec(
        select(DisciplineDocumentVersion).where(
            DisciplineDocumentVersion.version_id == chunk.version_id)).one()
    version.status = "withdrawn"
    session.add(version)
    session.commit()
    try:
        service = CorpusSearchService()
        result = service.search(
            session, "页表", release_id=search_env["release_id"],
            embed_client=search_env["client"])
        assert all(r["chunk_id"] != search_env["chunk_ids"][0]
                   for r in result["results"])
        assert result["coverage"]["withdrawn_filtered"] == 1
    finally:
        version.status = "active"
        session.add(version)
        session.commit()


def test_filters_source_kind(session, search_env):
    service = CorpusSearchService()
    result = service.search(
        session, "TCP", release_id=search_env["release_id"],
        filters={"source_kind": ["textbook"]},
        embed_client=search_env["client"])
    assert result["results"]
    assert {r["source_kind"] for r in result["results"]} == {"textbook"}


def test_unified_adapter_delegates_to_release_search(session, search_env):
    from app.platform.knowledge.discipline_corpus import (
        search_corpus_unified,
    )

    result = search_corpus_unified(
        session, "页表", release_id=search_env["release_id"],
        embed_client=search_env["client"])
    assert result["schema_version"] == "discipline-corpus/2"
    assert result["release_id"] == search_env["release_id"]
    assert all(r.get("result_type") == "corpus_chunk"
               for r in result["results"])
    assert all("reference_id" in r for r in result["results"])


def test_explicit_unready_release_rejected(session, fts_env):
    from app.services.discipline_knowledge.ingest import ingest_document

    service = CorpusSearchService()
    result = ingest_document(session, {
        "source_kind": "textbook",
        "external_id": "synth-cr3s-unready",
        "source_family_id": "synth-cr3s-unready",
        "title": "未就绪",
        "language": "zh",
        "domains": ["os"],
        "license_code": "CC-BY-SA-4.0",
        "text": "未就绪文档正文：页表用于地址转换。",
    }, chunker_config=CORPUS_CHUNKER)
    release = index_svc.create_release(
        session, chunk_ids=result["chunk_ids"],
        model_fingerprint=TEST_FP, dimension=TEST_DIM)
    with pytest.raises(index_svc.CorpusIndexError) as exc_info:
        service.search(session, "页表", release_id=release["release_id"],
                       embed_client=KeywordFakeEmbed())
    assert exc_info.value.error_code == "INDEX_NOT_READY"
