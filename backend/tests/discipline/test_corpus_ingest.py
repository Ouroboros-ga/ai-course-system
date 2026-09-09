"""CR1 可回读的文档/块登记验收测试（合成数据，临时对象存储）。

fixture 通过 DISCIPLINE_TEXT_STORE_ROOT 指向临时目录；
禁止用 manifest 内联文本临时重建来通过回读验收。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from test_alembic_migration import _run_alembic

CORPUS_CHUNKER = {
    "normalizer": "corpus-norm/2",
    "chunker": "corpus-chunk/1",
    "target_tokens": 40,
    "overlap_tokens": 8,
    "max_tokens": 64,
}


@pytest.fixture
def meta_doc(public_doc):
    """标题可变的独立文档（避免污染共享 public_doc 行）。"""
    return dict(public_doc, external_id="synth-corpus-meta-001",
               source_family_id="synth-corpus-meta")


def test_chunk_can_be_read_after_importer_exits(session, public_doc):
    from app.services.discipline_knowledge.corpus_text import read_chunk_text
    from app.services.discipline_knowledge.ingest import ingest_document

    result = ingest_document(session, public_doc)
    body = read_chunk_text(session, result["chunk_ids"][0])
    assert body and "栈" in body


def test_read_back_fails_without_store(session, public_doc, tmp_path):
    from app.services.discipline_knowledge.corpus_text import (
        CorpusTextError,
        read_chunk_text,
    )
    from app.services.discipline_knowledge.ingest import ingest_document

    result = ingest_document(session, public_doc)
    # 存储目录被清空后回读必须失败，不能用内存/清单文本兜底
    store = tmp_path / "corpus_texts"
    for child in store.glob("**/*"):
        if child.is_file():
            child.unlink()
    with pytest.raises(CorpusTextError) as exc_info:
        read_chunk_text(session, result["chunk_ids"][0])
    assert exc_info.value.error_code == "TEXT_UNAVAILABLE"


def test_corpus_normalizer_preserves_code_and_case():
    from app.services.discipline_knowledge.corpus_text import (
        normalize_corpus_text,
    )

    raw = "ＡＢＣ CamelCase `x = a+b`\r\n第二行 e\u0301公式 Ο(n)"
    normalized = normalize_corpus_text(raw)
    assert "ＡＢＣ" in normalized  # NFC 保留全角形（与 NFKC 折叠区分）
    assert "CamelCase" in normalized  # 大小写保留
    assert "`x = a+b`" in normalized  # 代码原样保留
    assert "\r" not in normalized  # 换行统一
    assert "é" in normalized and "e\u0301" not in normalized  # NFC 合成单码点


def test_same_doc_new_chunker_builds_new_chunks(session, public_doc):
    from app.services.discipline_knowledge.ingest import ingest_document

    record = dict(public_doc, external_id="synth-corpus-chunker-001",
                  source_family_id="synth-corpus-chunker")
    legacy = ingest_document(session, record)
    assert legacy["created"] is True
    again = ingest_document(session, record)
    assert again["created"] is False
    assert again["chunk_ids"] == legacy["chunk_ids"]

    corpus = ingest_document(session, record, chunker_config=CORPUS_CHUNKER)
    assert corpus["chunker_version"].startswith("corpus-chunk/1+")
    assert set(corpus["chunk_ids"]).isdisjoint(set(legacy["chunk_ids"]))
    assert corpus["version_id"] != legacy["version_id"]  # 新 normalizer → 新版本
    # 同 chunker 重跑幂等
    repeat = ingest_document(session, record, chunker_config=CORPUS_CHUNKER)
    assert repeat["created"] is False
    assert repeat["chunk_ids"] == corpus["chunk_ids"]


def test_same_doc_chunker_param_change_builds_new_chunks(session, public_doc):
    """P2-13：只改分块参数（同 tokenizer）也必须生成新块。

    此前 ``chunker_version`` 只含 ``{基名}+{tokenizer}``，改 target_tokens
    会静默复用旧块（实测 320→24 仍是 1 块）；分块参数必须参与分块身份。
    """
    from app.services.discipline_knowledge.ingest import ingest_document

    record = dict(public_doc, external_id="synth-corpus-param-001",
                  source_family_id="synth-corpus-param")
    wide = ingest_document(session, record, chunker_config={
        "normalizer": "corpus-norm/2", "chunker": "corpus-chunk/1",
        "target_tokens": 320, "overlap_tokens": 32, "max_tokens": 512})
    narrow = ingest_document(session, record, chunker_config={
        "normalizer": "corpus-norm/2", "chunker": "corpus-chunk/1",
        "target_tokens": 24, "overlap_tokens": 6, "max_tokens": 40})
    assert narrow["version_id"] == wide["version_id"]  # 同文档同 normalizer
    assert narrow["chunker_version"] != wide["chunker_version"]
    assert len(narrow["chunk_ids"]) > len(wide["chunk_ids"])
    assert set(narrow["chunk_ids"]).isdisjoint(set(wide["chunk_ids"]))
    # 参数相同重跑仍幂等
    repeat = ingest_document(session, record, chunker_config={
        "normalizer": "corpus-norm/2", "chunker": "corpus-chunk/1",
        "target_tokens": 24, "overlap_tokens": 6, "max_tokens": 40})
    assert repeat["created"] is False
    assert repeat["chunk_ids"] == narrow["chunk_ids"]


def test_metadata_only_update_keeps_version(session, meta_doc):
    from app.services.discipline_knowledge.ingest import ingest_document
    from app.models.discipline_knowledge_model import (
        DisciplineChunk,
        DisciplineDocumentVersion,
    )
    from sqlmodel import select

    first = ingest_document(session, meta_doc)
    changed = dict(meta_doc, title="合成教材样例（修订版标题）")
    second = ingest_document(session, changed)
    assert second["version_id"] == first["version_id"]
    assert second["chunk_ids"] == first["chunk_ids"]
    assert second["metadata_updated"] is True
    rows = session.exec(
        select(DisciplineDocumentVersion).where(
            DisciplineDocumentVersion.version_id == first["version_id"])
    ).all()
    assert len(rows) == 1
    assert rows[0].title == "合成教材样例（修订版标题）"
    chunks = session.exec(
        select(DisciplineChunk).where(
            DisciplineChunk.version_id == first["version_id"])
    ).all()
    assert len(chunks) == len(first["chunk_ids"])


def test_chunk_document_token_windows_overlap_and_cover():
    from app.services.discipline_knowledge.corpus_text import (
        CharFallbackTokenizer,
        chunk_document,
    )

    paras = "".join(
        f"第{i}段测试分块窗口。\n\n" for i in range(12))
    chunks = chunk_document(paras, CharFallbackTokenizer(), {
        "target_tokens": 30, "overlap_tokens": 8, "max_tokens": 48})
    assert len(chunks) >= 3
    for chunk in chunks:
        assert chunk["token_count"] <= 48
        assert chunk["text"] == paras[chunk["char_start"]:chunk["char_end"]]
    # 相邻块区间重叠且共享正文；全覆盖无截断（覆盖全部非空字符）
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt["char_start"] < prev["char_end"]
        shared = prev["text"][-8:]
        assert shared and shared in nxt["text"]
    covered = set()
    for chunk in chunks:
        covered.update(range(chunk["char_start"], chunk["char_end"]))
    nonblank = {i for i, c in enumerate(paras) if c.strip()}
    assert nonblank <= covered


def test_long_paragraph_splits_explicitly_and_covers_all_text():
    """D3：单段超长走显式拆分路径（此前无用例触发），无截断、全覆盖。"""
    from app.services.discipline_knowledge.corpus_text import (
        CharFallbackTokenizer,
        chunk_document,
    )

    long_para = "页表记录虚拟页与物理页的映射，缺页时触发换入换出。" * 120
    chunks = chunk_document(long_para, CharFallbackTokenizer(), {
        "target_tokens": 40, "overlap_tokens": 8, "max_tokens": 64})
    assert len(chunks) >= 5
    for chunk in chunks:
        assert chunk["token_count"] <= 64
        assert chunk["text"] == long_para[
            chunk["char_start"]:chunk["char_end"]]
    covered = set()
    for chunk in chunks:
        covered.update(range(chunk["char_start"], chunk["char_end"]))
    nonblank = {i for i, c in enumerate(long_para) if c.strip()}
    assert nonblank <= covered


def test_iter_source_records_adapts_five_formats(tmp_path):
    from app.services.discipline_knowledge.corpus_source import (
        iter_source_records,
    )

    files = {
        "corpus_textbooks.jsonl": [
            {"id": "ostep-cpu", "title": "CPU 章", "book": "OSTEP",
             "source": "s", "license": "CC BY-NC-ND 3.0", "text": "正文甲乙丙丁戊己庚辛壬癸。"},
        ],
        "corpus_zhwiki_cs.jsonl": [
            {"id": "zhwiki-1", "title": "词条", "source": "zh.wikipedia.org",
             "license": "CC BY-SA 4.0", "text": "正文甲乙丙丁戊己庚辛壬癸。"},
        ],
        "corpus_enwiki_cs.jsonl": [
            {"id": "enwiki-2", "title": "Entry", "source": "en.wikipedia.org",
             "license": "CC BY-SA 4.0", "text": "Body text here and there."},
        ],
        "corpus_rfc.jsonl": [
            {"id": "rfc-793", "title": "TCP", "source": "rfc-editor.org",
             "license": "IETF", "text": "正文甲乙丙丁戊己庚辛壬癸。"},
        ],
        "corpus_arxiv_cs.jsonl": [
            {"id": "arxiv-2101.00001v2", "title": "Paper", "source": "arxiv.org",
             "license": "CC BY 4.0", "text": "正文甲乙丙丁戊己庚辛壬癸。"},
        ],
    }
    specs = []
    for filename, docs in files.items():
        (tmp_path / filename).write_text(
            "\n".join(json.dumps(d, ensure_ascii=False) for d in docs)
            + "\n", encoding="utf-8")
        kind = {"corpus_textbooks.jsonl": "textbook",
                "corpus_zhwiki_cs.jsonl": "zhwiki",
                "corpus_enwiki_cs.jsonl": "enwiki",
                "corpus_rfc.jsonl": "rfc",
                "corpus_arxiv_cs.jsonl": "arxiv"}[filename]
        specs.append({"source_kind": kind, "file": filename})
    records = []
    for spec in specs:
        records.extend(iter_source_records(spec, source_root=tmp_path))
    assert len(records) == 5
    by_kind = {r["source_kind"]: r for r in records}
    assert by_kind["textbook"]["external_id"] == "ostep-cpu"
    assert by_kind["textbook"]["title"] == "CPU 章"
    assert by_kind["arxiv"]["external_id"] == "arxiv-2101.00001v2"
    # arxiv 同族去版本后缀
    assert by_kind["arxiv"]["source_family_id"] == "arxiv-2101.00001"
    assert all(r["text"] and r["license_code"] for r in records)


def test_iter_source_records_skips_bad_lines_with_stats(tmp_path):
    from app.services.discipline_knowledge.corpus_source import (
        iter_source_records,
    )

    (tmp_path / "corpus_rfc.jsonl").write_text(
        '{"id": "rfc-1", "title": "T", "text": "正文甲乙丙丁戊己庚辛壬癸。", '
        '"source": "s", "license": "x"}\n'
        '{"id": "", "title": "NoId", "text": "正文。", "source": "s"}\n'
        '{"id": "rfc-2", "title": "Empty", "text": "  ", "source": "s"}\n',
        encoding="utf-8")
    stats: dict = {}
    records = list(iter_source_records(
        {"source_kind": "rfc", "file": "corpus_rfc.jsonl"},
        source_root=tmp_path, stats=stats))
    # 无明确 external_id 按“来源类型 + 文件内稳定行号”生成，不用全库行号
    assert [r["external_id"] for r in records] == ["rfc-1", "rfc:corpus_rfc:2"]
    assert records[1].get("generated_id") is True
    reasons = [s["reason"] for s in stats["skipped"]]
    assert reasons == ["empty_text"]


def test_corpus_migration_roundtrip(tmp_path):
    db_path = tmp_path / "corpus_cr1.db"
    db_url = f"sqlite:///{db_path}"
    _run_alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        cols = {c["name"] for c in inspect(engine).get_columns(
            "discipline_document_versions")}
        assert {"title", "metadata_hash"} <= cols
        chunk_cols = {c["name"] for c in inspect(engine).get_columns(
            "discipline_chunks")}
        assert {"token_count", "section_path"} <= chunk_cols
        tables = set(inspect(engine).get_table_names())
        assert {"discipline_corpus_vectors",
                "discipline_corpus_index_members"} <= tables
        with engine.connect() as conn:
            head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert head is not None and head.startswith("dk")
    finally:
        engine.dispose()

    _run_alembic(db_url, "downgrade", "dk20260908v2")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        cols = {c["name"] for c in inspect(engine).get_columns(
            "discipline_document_versions")}
        assert "title" not in cols
        assert "discipline_corpus_vectors" not in set(
            inspect(engine).get_table_names())
    finally:
        engine.dispose()

    _run_alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        tables = set(inspect(engine).get_table_names())
        assert {"discipline_corpus_vectors",
                "discipline_corpus_index_members"} <= tables
    finally:
        engine.dispose()
