"""Tests for P1-09 G3D2 memory-candidate shadow (ADR-0006 §G3D2)."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.platform.shadow.memory_candidate_shadow import (
    MemoryCandidateShadowStore,
    MemoryCandidateShadowResult,
    trigger_memory_candidate_shadow,
)
from app.core import feature_flags as ff


@pytest.fixture
def tmp_store(tmp_path):
    return MemoryCandidateShadowStore(base_dir=tmp_path / "memory_store")


@pytest.fixture
def v2_memory_settings():
    """STUDENT_MEMORY_MODE=shadow requires LEARNING_EVENT_MODE=v2_shadow."""
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    configured[ff.LEARNING_EVENT_MODE] = "v2_shadow"
    configured[ff.STUDENT_MEMORY_MODE] = "shadow"
    with patch(
        "app.platform.shadow.memory_candidate_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


@pytest.fixture
def v1_settings():
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    with patch(
        "app.platform.shadow.memory_candidate_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


def _v1_ctx(n=2):
    return {"rag_sources": [
        {"path": f"p{i}", "score": 0.8, "content_preview": f"content {i}"}
        for i in range(n)
    ]}


class TestFlagGated:
    def test_disabled_no_trigger(self, tmp_store, v1_settings):
        r = trigger_memory_candidate_shadow("q", 1, 101, v1_context=_v1_ctx(), store=tmp_store)
        assert not r.triggered
        assert list(tmp_store.base_dir().glob("*.json")) == []

    def test_shadow_triggers(self, tmp_store, v2_memory_settings):
        r = trigger_memory_candidate_shadow("q", 1, 101, v1_context=_v1_ctx(2), store=tmp_store)
        assert r.triggered
        assert r.candidate_count == 2


class TestNotInjectedIntoQA:
    def test_would_inject_always_false(self, tmp_store, v2_memory_settings):
        """HARD CONSTRAINT: memory NOT injected into QA prompt."""
        r = trigger_memory_candidate_shadow("q", 1, 101, v1_context=_v1_ctx(), store=tmp_store)
        assert r.would_inject is False
        trace = json.loads(Path(r.trace_path).read_text(encoding="utf-8"))
        assert trace["would_inject"] is False
        assert "NOT injected" in trace["would_inject_context"]["note"]

    def test_no_chat_summary_as_truth(self, tmp_store, v2_memory_settings):
        """Each candidate has generation_reason + evidence_ref, not free-form chat summary."""
        r = trigger_memory_candidate_shadow("q", 1, 101, v1_context=_v1_ctx(1), store=tmp_store)
        trace = json.loads(Path(r.trace_path).read_text(encoding="utf-8"))
        for c in trace["candidate_memory"]:
            assert c["generation_reason"]
            assert c["evidence_refs"]  # not a bare chat summary


class TestScope:
    def test_missing_student_fail_closed(self, tmp_store, v2_memory_settings):
        r = trigger_memory_candidate_shadow("q", None, 101, v1_context=_v1_ctx(), store=tmp_store)
        assert not r.triggered
        assert "missing_student_or_course_scope" in (r.fallback_reason or "")

    def test_missing_course_fail_closed(self, tmp_store, v2_memory_settings):
        r = trigger_memory_candidate_shadow("q", 1, None, v1_context=_v1_ctx(), store=tmp_store)
        assert not r.triggered


class TestIsolation:
    def test_never_raises_into_v1(self, tmp_store, v2_memory_settings):
        with patch(
            "app.platform.shadow.memory_candidate_shadow._build_candidate_memory",
            side_effect=RuntimeError("boom"),
        ):
            r = trigger_memory_candidate_shadow("q", 1, 101, v1_context=_v1_ctx(), store=tmp_store)
        assert not r.triggered
        assert "shadow_runtime_error" in (r.fallback_reason or "")

    def test_question_stored_as_sha256(self, tmp_store, v2_memory_settings):
        r = trigger_memory_candidate_shadow("secret q", 1, 101, v1_context=_v1_ctx(), store=tmp_store)
        trace = json.loads(Path(r.trace_path).read_text(encoding="utf-8"))
        assert "question_sha256" in trace
        assert "secret q" not in Path(r.trace_path).read_text(encoding="utf-8")


class TestResultFrozen:
    def test_frozen(self):
        r = MemoryCandidateShadowResult(triggered=False, effective_mode="disabled")
        with pytest.raises(Exception):
            r.triggered = True
