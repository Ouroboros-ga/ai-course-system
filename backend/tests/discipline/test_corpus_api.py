"""CR5 学科页 API 契约：资料模式检索、版本化概览、原文引用端点。

合成 release（FTS-only）+ 真实路由；不调外部服务。
"""

from __future__ import annotations

import pytest

from app.core.security import get_current_user

CORPUS_CHUNKER = {
    "normalizer": "corpus-norm/2",
    "chunker": "corpus-chunk/1",
    "target_tokens": 320,
    "overlap_tokens": 32,
    "max_tokens": 512,
}


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


@pytest.fixture
def published_release(session, tmp_path, monkeypatch):
    from app.services.discipline_knowledge import corpus_index as index_svc

    fts_root = tmp_path / "fts"
    fts_root.mkdir()
    monkeypatch.setenv("DISCIPLINE_FTS_ROOT", str(fts_root))
    chunk_ids: list[str] = []
    for external_id, text in (
        ("synth-cr5-os", "合成页面文档甲：页表记录虚拟页与物理页的映射，缺页时换入换出。"),
        ("synth-cr5-net", "合成页面文档乙：TCP 通过三次握手建立连接，保证可靠有序交付。"),
    ):
        result = _ingest(session, external_id, text)
        chunk_ids.extend(result["chunk_ids"])
    release = index_svc.create_release(
        session, chunk_ids=chunk_ids, model_fingerprint="emfp_cr5_test",
        dimension=8, title="合成页面发布")
    index_svc.build_fts(session, release["release_id"])
    assert index_svc.validate_index(session, release["release_id"])["ready"]
    head = index_svc.read_head(session)
    activated = index_svc.activate_index(
        session, release["release_id"], head["revision"])
    assert activated["error_code"] == ""
    yield {"release_id": release["release_id"], "chunk_ids": chunk_ids}
    index_svc.close_fts_connections()


def _authed(fastapi_app):
    fastapi_app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "tester"}
    return fastapi_app


def test_search_requires_auth(client):
    resp = client.get("/api/v1/discipline-knowledge/search", params={"q": "页表", "mode": "corpus"})
    assert resp.status_code in (401, 403)


def test_search_default_concept_compat(fastapi_app, client):
    _authed(fastapi_app)
    try:
        resp = client.get("/api/v1/discipline-knowledge/search", params={"q": "哈希表"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["query"] == "哈希表"
        assert data["mode"] == "concept"
        assert data["results"]
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_search_corpus_mode_returns_versioned_chunks(fastapi_app, client, published_release):
    _authed(fastapi_app)
    try:
        resp = client.get("/api/v1/discipline-knowledge/search", params={"q": "页表", "mode": "corpus"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["release_id"] == published_release["release_id"]
        assert data["results"]
        for row in data["results"]:
            assert row["result_type"] == "corpus_chunk"
            assert row["reference_id"] == f"{published_release['release_id']}:{row['chunk_id']}"
            assert row["is_supplementary"] is True
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_search_all_mode_mixes_concept_and_corpus(fastapi_app, client, published_release):
    _authed(fastapi_app)
    try:
        resp = client.get("/api/v1/discipline-knowledge/search", params={"q": "页表", "mode": "all"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        kinds = {row.get("result_type") for row in data["results"]}
        assert "concept" in kinds
        assert "corpus_chunk" in kinds
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_overview_keeps_legacy_fields_and_adds_corpus(fastapi_app, client, published_release):
    _authed(fastapi_app)
    try:
        resp = client.get("/api/v1/discipline-knowledge/overview")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["node_count"] == 112
        assert data["relation_count"] == 106
        corpus = data["corpus"]
        assert corpus["release_id"] == published_release["release_id"]
        assert corpus["eligible_chunks"] >= 2
        assert corpus["scope"] == "corpus:cs"
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_chunks_reference_roundtrip(fastapi_app, client, published_release):
    _authed(fastapi_app)
    try:
        chunk_id = published_release["chunk_ids"][0]
        resp = client.get(
            f"/api/v1/discipline-knowledge/chunks/{chunk_id}",
            params={"release_id": published_release["release_id"]},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["reference_id"] == f"{published_release['release_id']}:{chunk_id}"
        assert "页表" in data["text"]
        assert "object_key" not in data
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_chunks_reference_rejects_foreign_release(fastapi_app, client, published_release):
    _authed(fastapi_app)
    try:
        resp = client.get(
            f"/api/v1/discipline-knowledge/chunks/{published_release['chunk_ids'][0]}",
            params={"release_id": "dkr_nonexistent"},
        )
        assert resp.status_code == 404
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_chunks_reference_gone_after_withdraw(
    fastapi_app, client, session, published_release,
):
    from app.models.discipline_knowledge_model import (
        DisciplineChunk,
        DisciplineDocumentVersion,
    )
    from sqlmodel import select

    _authed(fastapi_app)
    chunk = session.exec(
        select(DisciplineChunk).where(
            DisciplineChunk.chunk_id == published_release["chunk_ids"][0])).one()
    version = session.exec(
        select(DisciplineDocumentVersion).where(
            DisciplineDocumentVersion.version_id == chunk.version_id)).one()
    version.status = "withdrawn"
    session.add(version)
    session.commit()
    try:
        resp = client.get(
            f"/api/v1/discipline-knowledge/chunks/{chunk.chunk_id}",
            params={"release_id": published_release["release_id"]},
        )
        assert resp.status_code == 410
    finally:
        version.status = "active"
        session.add(version)
        session.commit()
        fastapi_app.dependency_overrides.pop(get_current_user, None)
