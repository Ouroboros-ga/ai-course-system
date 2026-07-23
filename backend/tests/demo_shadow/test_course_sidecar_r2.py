from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import evidence_v2
from app.core import feature_flags as ff
from app.core.security import get_current_user
from app.platform.retrieval_demo.course_provider import CourseSidecarR2Provider
from app.platform.retrieval_demo.service import DemoService
from app.platform.retrieval_demo.store import DemoRunStore
from app.platform.shadow.course_evidence_sidecar import CourseEvidenceSidecarStore, build_sidecar
from app.platform.shadow.doc_shadow import ShadowArtifactStore, trigger_doc_shadow


def _document_ir(document_id: str, artifact_id: str) -> dict:
    return {
        "schema_version": "document-ir/1.0", "document_id": document_id,
        "artifact_id": artifact_id, "source_sha256": "a" * 64,
    }


def _modes() -> dict[str, str]:
    configured = {name: ff.LEGAL_VALUES[name][0] for name in ff.ALL_FLAGS}
    configured[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    configured[ff.DOCUMENT_KG_RUNTIME_MODE] = "v2_shadow"
    configured[ff.EVIDENCE_CITATION_MODE] = "v2_shadow"
    return configured


def test_sidecar_is_course_scoped_and_citation_closed(tmp_path):
    store = CourseEvidenceSidecarStore(tmp_path / "sidecars")
    one = build_sidecar(
        course_id="101", document_ir=_document_ir("doc_101", "art_101"),
        markdown="# 课程\n\n## 第 1 页\n\n二叉树的高度与深度。",
    )
    two = build_sidecar(
        course_id="202", document_ir=_document_ir("doc_202", "art_202"),
        markdown="# 课程\n\n## 第 1 页\n\n数据库事务的隔离级别。",
    )
    store.write(one)
    store.write(two)

    assert store.course_ids() == ("101", "202")
    for snapshot in (store.read_course("101"), store.read_course("202")):
        assert snapshot is not None
        assert snapshot["source_kind"] == "document_ir_shadow_parse_result"
        assert all(chunk["evidence_ids"] for chunk in snapshot["corpus"])
        assert all(item["citation_key"].startswith("cite_") for item in snapshot["evidence"])


def test_evidence_api_reads_nonempty_document_sidecar(tmp_path):
    store = CourseEvidenceSidecarStore(tmp_path / "sidecars")
    snapshot = build_sidecar(
        course_id="101", document_ir=_document_ir("doc_101", "art_101"),
        markdown="# 课程\n\n## 第 1 页\n\n二叉树的高度与深度。",
    )
    store.write(snapshot)
    app = FastAPI()
    app.include_router(evidence_v2.router, prefix="/api/v1/evidence-v2")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "role": "admin"}
    with patch("app.api.v1.endpoints.evidence_v2._configured_modes", return_value=_modes()), \
         patch("app.api.v1.endpoints.evidence_v2.CourseEvidenceSidecarStore", return_value=store):
        client = TestClient(app)
        spans = client.get("/api/v1/evidence-v2/documents/doc_101/evidence")
        assert spans.status_code == 200
        body = spans.json()["evidence_spans"]
        assert len(body) == 1
        assert body[0]["document_id"] == "doc_101"
        assert body[0]["block_id"]
        evidence = snapshot["evidence"][0]
        closed = client.post(
            "/api/v1/evidence-v2/documents/doc_101/citations/validate",
            json={"citations": [{"key": evidence["citation_key"], "evidence_ref": evidence["evidence_id"]}]},
        )
    assert closed.status_code == 200
    assert closed.json()["status"] == "valid"


def test_r2_adapter_rejects_other_course_before_indexing(tmp_path):
    store = CourseEvidenceSidecarStore(tmp_path / "sidecars")
    store.write(build_sidecar(
        course_id="101", document_ir=_document_ir("doc_101", "art_101"),
        markdown="# 课程\n\n## 第 1 页\n\n二叉树的高度与深度。",
    ))
    provider = CourseSidecarR2Provider(store=store, cache_dir=tmp_path / "cache")
    result = provider.retrieve(course_id="202", question="数据库事务")
    assert result == {"status": "abstain", "abstain_reason": "course_sidecar_not_available", "hits": []}


def test_r2_adapter_runs_bm25_dense_rrf_on_parsed_sidecar_only(tmp_path):
    store = CourseEvidenceSidecarStore(tmp_path / "sidecars")
    store.write(build_sidecar(
        course_id="101", document_ir=_document_ir("doc_101", "art_101"),
        markdown=(
            "# 数据结构\n\n## 第 1 页\n\n二叉树的高度是从根节点到最远叶子节点的路径长度。\n"
            "\n## 第 2 页\n\n数据库事务的隔离级别与二叉树没有关系。"
        ),
    ))
    provider = CourseSidecarR2Provider(store=store, cache_dir=tmp_path / "cache")
    result = provider.retrieve(course_id="101", question="二叉树的高度是什么")
    assert result["status"] == "ok"
    assert result["hits"]
    assert all(hit["course_id"] == "101" for hit in result["hits"])
    assert all(hit["citations"] and hit["citations"][0]["citation_key"].startswith("cite_") for hit in result["hits"])
    assert provider.metadata["data_source"] == "test_course_documentir_evidence_sidecar"


def test_parse_shadow_to_sidecar_to_r2_uses_one_real_course_source(tmp_path, monkeypatch):
    class ParseResult:
        doc_title = "数据结构"
        pages = []
        markdown_content = "# 数据结构\n\n## 第 1 页\n\n二叉树的高度与深度。"

    source = tmp_path / "course.pptx"
    source.write_bytes(b"test course source")
    artifacts = ShadowArtifactStore(tmp_path / "artifacts")
    sidecars = CourseEvidenceSidecarStore(tmp_path / "sidecars")
    modes = _modes()
    monkeypatch.setattr(
        "app.platform.shadow.doc_shadow._configured_modes_from_settings",
        lambda: modes,
    )
    result = trigger_doc_shadow(
        source, "course.pptx", ParseResult(), course_key="301", store=artifacts,
        sidecar_store=sidecars, sync=True,
    )
    assert result.triggered is True
    snapshot = sidecars.read_course("301")
    assert snapshot is not None and snapshot["document_ir_schema_version"] == "document-ir/1.0"
    provider = CourseSidecarR2Provider(store=sidecars, cache_dir=tmp_path / "cache")
    retrieved = provider.retrieve(course_id="301", question="二叉树高度")
    assert retrieved["status"] == "ok"
    assert retrieved["hits"][0]["citations"]
    response = DemoService(
        configured_mode="demo_compare", environment="test", provider=provider,
        store=DemoRunStore(tmp_path / "runs"),
    ).query(course_id="301", question="二叉树高度")
    assert response["data_source"] == "course_sidecar"
    assert response["result"]["hits"][0]["citations"]
