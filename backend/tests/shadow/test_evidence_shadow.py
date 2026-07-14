"""Tests for P1-09 G3C evidence/retrieval/citation shadow (ADR-0006 §G3C).

Covers:
1. Flag disabled (default) -> no trigger, no trace.
2. Flag v2_shadow -> trigger writes isolated trace.
3. HARD CONSTRAINT: no second LLM call (llm_calls == 0).
4. Conflict downgrade (upstream not v2) -> no trigger.
5. RISK-03: missing course scope -> fail-closed, no global retrieval.
6. No-evidence abstention: citations without evidence -> abstain=True.
7. V1 isolation: shadow never raises into V1.
8. Trace isolation: separate from V1; stores question sha256 not raw.
9. V1-vs-V2 diff shape (contract/integration, not quality).
10. Citation key: no fake key when no evidence.
"""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.platform.shadow.evidence_shadow import (
    DEFAULT_EVIDENCE_TRACE_ROOT,
    EvidenceShadowResult,
    EvidenceTraceStore,
    trigger_evidence_shadow,
)
from app.core import feature_flags as ff


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_store(tmp_path):
    return EvidenceTraceStore(base_dir=tmp_path / "evidence_store")


@pytest.fixture
def v2_evidence_settings():
    """All flags on the doc chain v2_shadow so EVIDENCE_CITATION_MODE is
    effectively v2_shadow (no conflict downgrade)."""
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    configured[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    configured[ff.DOCUMENT_KG_RUNTIME_MODE] = "v2_shadow"
    configured[ff.EVIDENCE_CITATION_MODE] = "v2_shadow"
    with patch(
        "app.platform.shadow.evidence_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


@pytest.fixture
def v1_only_settings():
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    with patch(
        "app.platform.shadow.evidence_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


@pytest.fixture
def conflict_settings():
    """DOCUMENT_KG_RUNTIME_MODE=v1_only downgrades EVIDENCE_CITATION_MODE
    (configured v2_shadow) via conflict rule."""
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    configured[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    configured[ff.DOCUMENT_KG_RUNTIME_MODE] = "v1_only"  # upstream not v2
    configured[ff.EVIDENCE_CITATION_MODE] = "v2_shadow"
    with patch(
        "app.platform.shadow.evidence_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


def _v1_sources(n=2):
    return [
        {"path": f"chap/sect/p{i}", "score": 0.9 - i * 0.1, "match_type": "keyword",
         "content_preview": f"content {i}"}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Flag-gated
# ---------------------------------------------------------------------------


class TestFlagGated:
    def test_disabled_no_trigger(self, tmp_store, v1_only_settings):
        result = trigger_evidence_shadow(
            question="q", course_id=101, v1_sources=_v1_sources(), store=tmp_store
        )
        assert result.triggered is False
        assert "flag_not_v2_shadow" in (result.fallback_reason or "")
        assert list(tmp_store.base_dir().glob("*.json")) == []

    def test_v2_shadow_triggers_and_writes_trace(self, tmp_store, v2_evidence_settings):
        result = trigger_evidence_shadow(
            question="什么是知识点", course_id=101, v1_sources=_v1_sources(2), store=tmp_store
        )
        assert result.triggered is True
        assert result.effective_mode == "v2_shadow"
        assert result.trace_path is not None
        assert Path(result.trace_path).exists()
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert trace["effective_mode"] == "v2_shadow"
        assert trace["course_id"] == "101"
        assert len(trace["v2_candidates"]) == 2

    def test_conflict_downgrade_no_trigger(self, tmp_store, conflict_settings):
        result = trigger_evidence_shadow(
            question="q", course_id=101, v1_sources=_v1_sources(), store=tmp_store
        )
        assert result.triggered is False
        assert result.effective_mode == "v1_only"  # downgraded


# ---------------------------------------------------------------------------
# HARD CONSTRAINT: no second LLM call
# ---------------------------------------------------------------------------


class TestNoSecondLLM:
    def test_llm_calls_always_zero(self, tmp_store, v2_evidence_settings):
        result = trigger_evidence_shadow(
            question="q", course_id=101, v1_sources=_v1_sources(), store=tmp_store
        )
        assert result.llm_calls == 0
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert trace["llm_calls"] == 0

    def test_llm_calls_zero_even_on_fail_closed(self, tmp_store, v2_evidence_settings):
        """Runtime error -> fail-closed, but still 0 LLM calls."""
        with patch(
            "app.platform.shadow.evidence_shadow._build_v2_candidates",
            side_effect=RuntimeError("boom"),
        ):
            result = trigger_evidence_shadow(
                question="q", course_id=101, v1_sources=_v1_sources(), store=tmp_store
            )
        assert result.triggered is False
        assert result.llm_calls == 0


# ---------------------------------------------------------------------------
# RISK-03: course isolation
# ---------------------------------------------------------------------------


class TestCourseIsolation:
    def test_missing_course_scope_fail_closed(self, tmp_store, v2_evidence_settings):
        """No course_id -> fail-closed, NO V2 retrieval (would risk global leak)."""
        result = trigger_evidence_shadow(
            question="q", course_id=None, v1_sources=_v1_sources(), store=tmp_store
        )
        assert result.triggered is False
        assert "missing_course_scope" in (result.fallback_reason or "")
        assert list(tmp_store.base_dir().glob("*.json")) == []

    def test_trace_records_scope_isolated(self, tmp_store, v2_evidence_settings):
        result = trigger_evidence_shadow(
            question="q", course_id=42, v1_sources=_v1_sources(), store=tmp_store
        )
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert trace["v2_scope_isolated"] is True
        assert trace["v2_candidates"][0]["document_id"] == "doc_shadow_42_0"
        # each candidate scoped to course 42
        assert all("42" in c["document_id"] for c in trace["v2_candidates"])


# ---------------------------------------------------------------------------
# No-evidence abstention
# ---------------------------------------------------------------------------


class TestNoEvidenceAbstain:
    def test_abstain_when_no_content(self, tmp_store, v2_evidence_settings):
        """V1 sources with empty content_preview -> no block_id -> abstain."""
        sources = [{"path": "p", "score": 0.5, "match_type": "k", "content_preview": ""}]
        result = trigger_evidence_shadow(
            question="q", course_id=1, v1_sources=sources, store=tmp_store
        )
        assert result.triggered is True
        assert result.citation_abstain is True
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert trace["v2_citation_validation"]["abstain"] is True
        assert trace["v2_citation_validation"]["status"] == "no_evidence"

    def test_no_fake_citation_key_without_evidence(self, tmp_store, v2_evidence_settings):
        sources = [{"path": "p", "score": 0.5, "match_type": "k", "content_preview": ""}]
        result = trigger_evidence_shadow(
            question="q", course_id=1, v1_sources=sources, store=tmp_store
        )
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        for c in trace["v2_candidates"]:
            assert c["citation_key"] is None  # no fake key

    def test_citation_key_present_with_evidence(self, tmp_store, v2_evidence_settings):
        result = trigger_evidence_shadow(
            question="q", course_id=1, v1_sources=_v1_sources(1), store=tmp_store
        )
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert trace["v2_candidates"][0]["citation_key"] is not None
        assert trace["v2_citation_validation"]["abstain"] is False


# ---------------------------------------------------------------------------
# V1 isolation + trace isolation
# ---------------------------------------------------------------------------


class TestIsolation:
    def test_shadow_never_raises_into_v1(self, tmp_store, v2_evidence_settings):
        with patch(
            "app.platform.shadow.evidence_shadow._build_v2_candidates",
            side_effect=ValueError("boom"),
        ):
            result = trigger_evidence_shadow(
                question="q", course_id=1, v1_sources=_v1_sources(), store=tmp_store
            )
        assert result.triggered is False
        assert "shadow_runtime_error" in (result.fallback_reason or "")

    def test_trace_stores_question_sha256_not_raw(self, tmp_store, v2_evidence_settings):
        """Privacy: trace stores question hash, not raw question text."""
        result = trigger_evidence_shadow(
            question="secret question text", course_id=1, v1_sources=_v1_sources(1), store=tmp_store
        )
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert "question_sha256" in trace
        assert trace["question_sha256"] == hashlib.sha256("secret question text".encode()).hexdigest()
        assert "secret question text" not in Path(result.trace_path).read_text(encoding="utf-8")

    def test_trace_isolated_from_v1(self, tmp_store, v2_evidence_settings):
        trigger_evidence_shadow(question="q", course_id=1, v1_sources=_v1_sources(1), store=tmp_store)
        files = list(tmp_store.base_dir().glob("*.json"))
        assert len(files) == 1
        # trace is under evidence store, not V1 DB / Course tables
        assert tmp_store.base_dir().name == "evidence_store"


# ---------------------------------------------------------------------------
# V1-vs-V2 diff shape
# ---------------------------------------------------------------------------


class TestDiffShape:
    def test_diff_is_contract_integration_not_quality(self, tmp_store, v2_evidence_settings):
        result = trigger_evidence_shadow(
            question="q", course_id=1, v1_sources=_v1_sources(3), store=tmp_store
        )
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        diff = trace["diff"]
        assert diff["v1_source_count"] == 3
        assert diff["v2_candidate_count"] == 3
        assert "note" in diff
        assert "not quality comparison" in diff["note"].lower() or "contract" in diff["note"].lower()
        # no second answer field
        assert "v2_answer" not in trace
        assert "generated_answer" not in trace


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_frozen(self):
        r = EvidenceShadowResult(triggered=False, effective_mode="v1_only")
        with pytest.raises(Exception):
            r.triggered = True
