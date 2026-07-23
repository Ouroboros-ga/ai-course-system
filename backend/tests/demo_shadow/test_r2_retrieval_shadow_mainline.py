"""R2 sidecar retrieval shadow -- /chat/ask mainline wiring tests.

Covers the shadow trigger that plugs real R2 retrieval (BM25 + local BGE
Dense + RRF, citation-closed) into ``qa_service.ask_question_with_rag``
behind ``DOCUMENT_KG_RUNTIME_MODE``. Default flag v1_only = pure V1.
"""
from __future__ import annotations

from unittest.mock import patch

from app.core import feature_flags as ff
from app.platform.retrieval_demo.course_provider import CourseSidecarR2Provider
from app.platform.shadow.course_evidence_sidecar import (
    CourseEvidenceSidecarStore,
    build_sidecar,
)
from app.platform.shadow.r2_retrieval_shadow import trigger_r2_retrieval_shadow


def _document_ir(document_id: str, artifact_id: str) -> dict:
    return {
        "schema_version": "document-ir/1.0",
        "document_id": document_id,
        "artifact_id": artifact_id,
        "source_sha256": "a" * 64,
    }


def _modes(**overrides: str) -> dict[str, str]:
    configured = {name: ff.LEGAL_VALUES[name][0] for name in ff.ALL_FLAGS}
    configured[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    configured[ff.DOCUMENT_KG_RUNTIME_MODE] = "v2_shadow"
    configured[ff.EVIDENCE_CITATION_MODE] = "v2_shadow"
    configured.update(overrides)
    return configured


def _v1_sources() -> list[dict]:
    return [{"path": "legacy/tree", "score": 0.5, "match_type": "tree_keyword", "content_preview": "v1 text"}]


def _write_sidecar(tmp_path, course_id: str = "101") -> CourseEvidenceSidecarStore:
    store = CourseEvidenceSidecarStore(tmp_path / "sidecars")
    store.write(build_sidecar(
        course_id=course_id,
        document_ir=_document_ir(f"doc_{course_id}", f"art_{course_id}"),
        markdown=(
            "# 数据结构\n\n## 第 1 页\n\n二叉树的高度是从根节点到最远叶子节点的路径长度。\n"
            "\n## 第 2 页\n\n数据库事务的隔离级别与二叉树没有关系。"
        ),
    ))
    return store


# ---------------------------------------------------------------------------
# Flag off -> pure V1
# ---------------------------------------------------------------------------


def test_flag_v1_only_keeps_v1_sources(tmp_path):
    store = _write_sidecar(tmp_path)
    with patch("app.platform.shadow.r2_retrieval_shadow._configured_modes", return_value=_modes(DOCUMENT_KG_RUNTIME_MODE="v1_only")), \
         patch("app.platform.retrieval_demo.course_provider.CourseEvidenceSidecarStore", return_value=store):
        result = trigger_r2_retrieval_shadow(
            question="二叉树的高度", course_id="101",
            v1_context="v1 ctx", v1_sources=_v1_sources(),
        )
    assert result.triggered is False
    assert result.fallback_reason == "flag_not_v2_shadow"
    # Caller keeps V1 values (result carries no replacements).
    assert result.rag_context is None
    assert result.rag_sources is None


def test_flag_off_due_to_upstream_conflict(tmp_path):
    # DOCUMENT_PIPELINE_VERSION v1_only -> DOCUMENT_KG_RUNTIME_MODE downgrades.
    store = _write_sidecar(tmp_path)
    with patch("app.platform.shadow.r2_retrieval_shadow._configured_modes",
               return_value=_modes(DOCUMENT_PIPELINE_VERSION="v1_only")), \
         patch("app.platform.retrieval_demo.course_provider.CourseEvidenceSidecarStore", return_value=store):
        result = trigger_r2_retrieval_shadow(
            question="二叉树", course_id="101",
            v1_context="v1", v1_sources=_v1_sources(),
        )
    assert result.triggered is False
    assert result.effective_mode != "v2_shadow"


# ---------------------------------------------------------------------------
# Flag on, course has no sidecar -> silent fallback to V1 (no error, no fabrication)
# ---------------------------------------------------------------------------


def test_course_without_sidecar_falls_back_to_v1(tmp_path):
    store = _write_sidecar(tmp_path, course_id="101")  # only 101 has a sidecar
    with patch("app.platform.shadow.r2_retrieval_shadow._configured_modes", return_value=_modes()), \
         patch("app.platform.retrieval_demo.course_provider.CourseEvidenceSidecarStore", return_value=store):
        result = trigger_r2_retrieval_shadow(
            question="二叉树", course_id="999",  # no sidecar
            v1_context="v1", v1_sources=_v1_sources(),
        )
    assert result.triggered is False
    assert result.fallback_reason == "course_sidecar_not_available"
    assert result.rag_sources is None  # no fabricated hits


# ---------------------------------------------------------------------------
# Flag on + sidecar + R2 ok -> replaces V1 sources with R2 hits
# ---------------------------------------------------------------------------


def test_r2_ok_replaces_v1_sources(tmp_path):
    store = _write_sidecar(tmp_path)
    with patch("app.platform.shadow.r2_retrieval_shadow._configured_modes", return_value=_modes()), \
         patch("app.platform.retrieval_demo.course_provider.CourseEvidenceSidecarStore", return_value=store):
        result = trigger_r2_retrieval_shadow(
            question="二叉树的高度是什么", course_id="101",
            v1_context="v1 ctx", v1_sources=_v1_sources(),
        )
    assert result.triggered is True
    assert result.effective_mode == "v2_shadow"
    assert result.hit_count > 0
    assert result.rag_sources is not None
    # V1 rag_sources shape preserved.
    src = result.rag_sources[0]
    assert {"path", "score", "match_type", "content_preview"} <= set(src.keys())
    assert src["match_type"] == "rrf_hybrid_bm25_dense"
    assert src["path"]  # research_chunk_id
    assert result.rag_context  # rebuilt context text


# ---------------------------------------------------------------------------
# Flag on + R2 abstain (no relevant hit) -> fallback to V1
# ---------------------------------------------------------------------------


def test_r2_abstain_falls_back_to_v1(tmp_path):
    store = _write_sidecar(tmp_path, course_id="202")
    with patch("app.platform.shadow.r2_retrieval_shadow._configured_modes", return_value=_modes()), \
         patch("app.platform.retrieval_demo.course_provider.CourseEvidenceSidecarStore", return_value=store):
        # Course 999 has no sidecar -> provider returns abstain before indexing.
        result = trigger_r2_retrieval_shadow(
            question="无关问题", course_id="999",
            v1_context="v1", v1_sources=_v1_sources(),
        )
    assert result.triggered is False
    assert result.fallback_reason and result.fallback_reason.startswith("course_sidecar_not_available")


# ---------------------------------------------------------------------------
# Flag on + provider raises -> business fail-closed, V1 unaffected
# ---------------------------------------------------------------------------


def test_provider_runtime_error_fail_closed(tmp_path):
    store = _write_sidecar(tmp_path)
    real_provider = CourseSidecarR2Provider(store=store, cache_dir=tmp_path / "cache")

    def boom(self, *, course_id, question):  # noqa: ARG001
        raise RuntimeError("model load failed")

    with patch("app.platform.shadow.r2_retrieval_shadow._configured_modes", return_value=_modes()), \
         patch("app.platform.retrieval_demo.course_provider.CourseSidecarR2Provider.course_ids", new=real_provider.course_ids), \
         patch("app.platform.retrieval_demo.course_provider.CourseSidecarR2Provider.retrieve", boom):
        result = trigger_r2_retrieval_shadow(
            question="二叉树", course_id="101",
            v1_context="v1", v1_sources=_v1_sources(),
        )
    assert result.triggered is False
    assert result.fallback_reason and result.fallback_reason.startswith("runtime_error")
    assert result.rag_sources is None  # V1 untouched


# ---------------------------------------------------------------------------
# RISK-03: missing course scope -> no global retrieval
# ---------------------------------------------------------------------------


def test_missing_course_scope_no_global_retrieval(tmp_path):
    store = _write_sidecar(tmp_path)
    with patch("app.platform.shadow.r2_retrieval_shadow._configured_modes", return_value=_modes()), \
         patch("app.platform.retrieval_demo.course_provider.CourseEvidenceSidecarStore", return_value=store):
        result = trigger_r2_retrieval_shadow(
            question="二叉树", course_id=None,
            v1_context="v1", v1_sources=_v1_sources(),
        )
    assert result.triggered is False
    assert result.fallback_reason == "missing_course_scope"


# ---------------------------------------------------------------------------
# llm_calls hard constraint: never calls an LLM
# ---------------------------------------------------------------------------


def test_never_calls_llm(tmp_path):
    store = _write_sidecar(tmp_path)
    with patch("app.platform.shadow.r2_retrieval_shadow._configured_modes", return_value=_modes()), \
         patch("app.platform.retrieval_demo.course_provider.CourseEvidenceSidecarStore", return_value=store):
        result = trigger_r2_retrieval_shadow(
            question="二叉树的高度", course_id="101",
            v1_context="v1", v1_sources=_v1_sources(),
        )
    assert result.llm_calls == 0
