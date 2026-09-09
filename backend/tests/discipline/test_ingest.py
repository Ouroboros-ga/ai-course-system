"""DK1 持久化、导入与身份验收测试。

合成来源/正文 fixture，不复制生产数据；不调用模型与外部服务。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.models.discipline_knowledge_model import (
    DisciplineAssertion,
    DisciplineChunk,
    DisciplineConcept,
    DisciplineDocumentVersion,
    DisciplineSupport,
)
from app.services.discipline_knowledge.identity import (
    CHUNKER_VERSION,
    NORMALIZER_VERSION,
    chunk_spans,
    normalize_alias,
    normalize_text,
)
from app.services.discipline_knowledge.ingest import (
    DisciplineIngestError,
    import_legacy_seed,
    ingest_document,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DATA_DIR = REPO_ROOT / "knowledge_data"


def _counts(session):
    doc_versions = session.exec(
        select(func.count()).select_from(DisciplineDocumentVersion)
    ).one()
    chunks = session.exec(select(func.count()).select_from(DisciplineChunk)).one()
    return doc_versions, chunks


def test_ingest_is_idempotent(session, public_doc):
    a = ingest_document(session, public_doc)
    before = _counts(session)
    b = ingest_document(session, public_doc)
    assert a["version_id"] == b["version_id"]
    assert a["chunk_ids"] == b["chunk_ids"]
    assert b["created"] is False
    # 新表文档版本和 chunks COUNT 不增加
    assert _counts(session) == before


def test_ingest_new_version_on_text_change(session, public_doc):
    a = ingest_document(session, public_doc)
    changed = dict(public_doc)
    changed["text"] = public_doc["text"] + "\n\n补充段落：散列表用哈希函数把键映射到槽位，冲突时用链地址法解决。"
    b = ingest_document(session, changed)
    assert b["created"] is True
    assert b["version_id"] != a["version_id"]
    # 旧版本保留（版本变化产生新行，不覆盖旧行）
    versions = session.exec(
        select(DisciplineDocumentVersion)
        .where(DisciplineDocumentVersion.source_kind == public_doc["source_kind"])
        .where(DisciplineDocumentVersion.external_id == public_doc["external_id"])
    ).all()
    assert {v.version_id for v in versions} >= {a["version_id"], b["version_id"]}


def test_ingest_rejects_bad_record(session, public_doc):
    before = _counts(session)
    empty = dict(public_doc, external_id="synth-bad-empty-001", text="   ")
    with pytest.raises(DisciplineIngestError) as exc_info:
        ingest_document(session, empty)
    assert exc_info.value.error_code == "SCHEMA_INVALID"
    unknown = dict(public_doc, external_id="synth-bad-kind-001", source_kind="blog")
    with pytest.raises(DisciplineIngestError) as exc_info:
        ingest_document(session, unknown)
    assert exc_info.value.error_code == "SCHEMA_INVALID"
    assert _counts(session) == before


def test_chunk_spans_are_contiguous_code_point_intervals():
    para1 = "第一段内容，讲解栈的基本定义与后进先出原则。" * 4
    para2 = "第二段内容，包含中文与 emoji 🚀 符号，以及队列的先进先出语义说明。" * 4
    para3 = "第三段内容，二分查找要求搜索空间有序。" * 4
    text = normalize_text(f"{para1}\n\n{para2}\n\n{para3}")
    assert len(text) > 200
    spans = chunk_spans(text)
    assert spans
    for _chunk_no, start, end, piece in spans:
        assert piece == text[start:end]
        assert 0 <= start < end <= len(text)


def test_alias_normalization_does_not_imply_synonymy():
    # 规范化只做键归一（大小写/Unicode），语义同义必须另行决策
    assert normalize_alias("Hash Table") == normalize_alias("hash table")
    assert normalize_alias("Ｂ＋树") == normalize_alias("b＋树")
    assert NORMALIZER_VERSION == "norm/1"
    assert CHUNKER_VERSION == "chunk/1"


def test_import_legacy_seed_retains_ids(session):
    first = import_legacy_seed(session, KNOWLEDGE_DATA_DIR)
    assert first["errors"] == []
    assert first["concepts"] == 112
    assert first["assertions"] == 106
    assert first["legacy_unverified"] == 112
    assert first["mapping"]["ds-001"]
    assert first["mapping"]["ds-005"]
    assert len(set(first["mapping"].values())) == 112

    concepts = session.exec(select(DisciplineConcept)).all()
    by_legacy = {c.legacy_id: c for c in concepts if c.legacy_id}
    assert by_legacy["ds-005"].canonical_name == "哈希表"
    assert all(c.status == "legacy_unverified" for c in by_legacy.values())

    second = import_legacy_seed(session, KNOWLEDGE_DATA_DIR)
    assert second["mapping"] == first["mapping"]
    assert second["aliases"] == 0
    assert second["assertions"] == 0


def test_legacy_assertions_have_no_fabricated_supports(session):
    import_legacy_seed(session, KNOWLEDGE_DATA_DIR)
    supports = session.exec(select(func.count()).select_from(DisciplineSupport)).one()
    assert supports == 0
    assertions = session.exec(
        select(DisciplineAssertion).where(
            DisciplineAssertion.status == "legacy_unverified"
        )
    ).all()
    assert len(assertions) == 106
    assert all(a.qualifiers.get("legacy") is True for a in assertions)
    assert all(a.qualifiers.get("legacy_relation_type") for a in assertions)
