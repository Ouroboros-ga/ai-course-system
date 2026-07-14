"""Tests for P1-09 G3B document-parse shadow (ADR-0006 §G3B).

Covers:
1. Flag disabled (default) -> no trigger, no artifact.
2. Flag v2_shadow -> trigger writes isolated artifact.
3. Idempotency: same source+config -> skip (artifact exists).
4. Queue-full (inflight limit) -> skip + fallback_reason.
5. Disk quota exceeded -> fail-closed + fallback_reason.
6. Runtime error -> business fail-closed, V1 unaffected.
7. Conflict downgrade: upstream not v2 -> no trigger.
8. Artifact isolation: never writes V1 tables/paths.
9. ShadowTriggerResult shape + fallback_reason semantics.
10. ShadowArtifactStore: path-traversal safe, atomic, checksummed.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.platform.shadow.doc_shadow import (
    DISK_QUOTA_BYTES,
    MAX_INFLIGHT_PER_COURSE,
    ShadowArtifactStore,
    ShadowTriggerResult,
    _InflightTracker,
    _build_shadow_document_ir,
    trigger_doc_shadow,
)
from app.core import feature_flags as ff


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeParseResult:
    """Minimal V1 parse_result stand-in (read-only by shadow)."""

    def __init__(self, doc_title="Test Doc", pages=None, markdown_content="# T\n\nbody"):
        self.doc_title = doc_title
        self.pages = pages or [{"text": "page1"}, {"text": "page2"}]
        self.markdown_content = markdown_content


@pytest.fixture
def tmp_file(tmp_path):
    p = tmp_path / "test.docx"
    p.write_bytes(b"fake document bytes for sha256")
    return p


@pytest.fixture
def tmp_store(tmp_path):
    return ShadowArtifactStore(base_dir=tmp_path / "shadow_store")


@pytest.fixture
def v2_shadow_settings():
    """Patch _configured_modes_from_settings to return v2_shadow for doc pipeline."""
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}  # all default
    configured[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    configured[ff.DOCUMENT_KG_RUNTIME_MODE] = "v2_shadow"  # so no conflict downgrade
    with patch(
        "app.platform.shadow.doc_shadow._configured_modes_from_settings",
        return_value=configured,
    ):
        yield configured


@pytest.fixture
def v1_only_settings():
    """Default settings (all V1/disabled)."""
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    with patch(
        "app.platform.shadow.doc_shadow._configured_modes_from_settings",
        return_value=configured,
    ):
        yield configured


# ---------------------------------------------------------------------------
# Flag-gated trigger
# ---------------------------------------------------------------------------


class TestFlagGated:
    def test_disabled_flag_no_trigger(self, tmp_file, tmp_store, v1_only_settings):
        result = trigger_doc_shadow(
            file_path=tmp_file,
            filename="test.docx",
            parse_result=_FakeParseResult(),
            store=tmp_store,
            sync=True,
        )
        assert result.triggered is False
        assert "flag_not_v2_shadow" in (result.fallback_reason or "")
        # no artifact written
        assert list(tmp_store.base_dir().glob("*.json")) == []

    def test_v2_shadow_triggers_and_writes_artifact(
        self, tmp_file, tmp_store, v2_shadow_settings
    ):
        result = trigger_doc_shadow(
            file_path=tmp_file,
            filename="test.docx",
            parse_result=_FakeParseResult(),
            store=tmp_store,
            sync=True,
        )
        assert result.triggered is True
        assert result.effective_mode == "v2_shadow"
        assert result.artifact_path is not None
        assert Path(result.artifact_path).exists()
        # artifact content is DocumentIR-shaped
        payload = json.loads(Path(result.artifact_path).read_text(encoding="utf-8"))
        assert payload["effective_mode"] == "v2_shadow"
        assert "document_ir" in payload
        assert payload["document_ir"]["schema_version"] == "document-ir/1.0"
        assert payload["document_ir"]["source_filename"] == "test.docx"

    def test_conflict_downgrade_no_trigger(self, tmp_file, tmp_store):
        # DOCUMENT_PIPELINE_VERSION=v1_only but DOCUMENT_KG_RUNTIME_MODE=v2_shadow
        # -> runtime downgraded; but doc pipeline itself is root, so doc shadow
        # checks DOCUMENT_PIPELINE_VERSION directly. Set doc=v1_only to disable.
        configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
        configured[ff.DOCUMENT_PIPELINE_VERSION] = "v1_only"
        with patch(
            "app.platform.shadow.doc_shadow._configured_modes_from_settings",
            return_value=configured,
        ):
            result = trigger_doc_shadow(
                file_path=tmp_file,
                filename="t.docx",
                parse_result=_FakeParseResult(),
                store=tmp_store,
                sync=True,
            )
        assert result.triggered is False
        assert result.effective_mode == "v1_only"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_same_source_skips(self, tmp_file, tmp_store, v2_shadow_settings):
        r1 = trigger_doc_shadow(tmp_file, "t.docx", _FakeParseResult(), store=tmp_store, sync=True)
        assert r1.triggered is True
        r2 = trigger_doc_shadow(tmp_file, "t.docx", _FakeParseResult(), store=tmp_store, sync=True)
        assert r2.triggered is False
        assert "idempotent_skip" in (r2.fallback_reason or "")
        # same artifact path
        assert r1.artifact_path == r2.artifact_path

    def test_different_source_different_artifact(
        self, tmp_file, tmp_path, tmp_store, v2_shadow_settings
    ):
        other = tmp_path / "other.docx"
        other.write_bytes(b"different bytes entirely")
        r1 = trigger_doc_shadow(tmp_file, "a.docx", _FakeParseResult(), store=tmp_store, sync=True)
        r2 = trigger_doc_shadow(other, "b.docx", _FakeParseResult(), store=tmp_store, sync=True)
        assert r1.triggered and r2.triggered
        assert r1.artifact_path != r2.artifact_path


# ---------------------------------------------------------------------------
# Resource rules
# ---------------------------------------------------------------------------


class TestResourceRules:
    def test_queue_full_skips(self, tmp_file, tmp_store, v2_shadow_settings):
        # Saturate the inflight tracker for this course_key.
        tracker = _InflightTracker()
        ckey = "course:test_queue"
        tracker.try_acquire(ckey, "run-1")
        with patch("app.platform.shadow.doc_shadow._tracker", tracker):
            result = trigger_doc_shadow(
                tmp_file, "t.docx", _FakeParseResult(),
                course_key=ckey, store=tmp_store, sync=True,
            )
        assert result.triggered is False
        assert "queue_full" in (result.fallback_reason or "")

    def test_disk_quota_fail_closed(self, tmp_file, tmp_store, v2_shadow_settings):
        # Force disk usage over quota.
        with patch.object(tmp_store, "disk_usage_bytes", return_value=DISK_QUOTA_BYTES + 1):
            result = trigger_doc_shadow(
                tmp_file, "t.docx", _FakeParseResult(), store=tmp_store, sync=True
            )
        assert result.triggered is False
        assert "disk_quota" in (result.fallback_reason or "")

    def test_runtime_error_fail_closed(self, tmp_file, tmp_store, v2_shadow_settings):
        # Force _build_shadow_document_ir to raise.
        with patch(
            "app.platform.shadow.doc_shadow._build_shadow_document_ir",
            side_effect=RuntimeError("boom"),
        ):
            result = trigger_doc_shadow(
                tmp_file, "t.docx", _FakeParseResult(), store=tmp_store, sync=True
            )
        assert result.triggered is False
        assert "shadow_runtime_error" in (result.fallback_reason or "")
        assert "boom" in (result.fallback_reason or "")


# ---------------------------------------------------------------------------
# V1 isolation
# ---------------------------------------------------------------------------


class TestV1Isolation:
    def test_shadow_never_raises_into_v1(self, tmp_file, tmp_store, v2_shadow_settings):
        """Even if shadow internals blow up, trigger_doc_shadow returns a result,
        never raises. document_service seam relies on this."""
        with patch(
            "app.platform.shadow.doc_shadow._source_sha256",
            side_effect=OSError("disk gone"),
        ):
            result = trigger_doc_shadow(
                tmp_file, "t.docx", _FakeParseResult(), store=tmp_store, sync=True
            )
        assert result.triggered is False
        assert "source_read" in (result.fallback_reason or "")

    def test_artifact_isolated_from_v1(self, tmp_file, tmp_store, v2_shadow_settings):
        result = trigger_doc_shadow(
            tmp_file, "t.docx", _FakeParseResult(), store=tmp_store, sync=True
        )
        # artifact is under the shadow store, NOT under V1 paths.
        assert "p1_shadow_artifacts" in str(tmp_store.base_dir()) or tmp_store.base_dir().name == "shadow_store"
        # no V1 DB / Course table touched (shadow store is a separate dir of JSON)
        files = list(tmp_store.base_dir().glob("*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        # artifact references source by sha256, not V1 course_id
        assert "source_sha256" in payload
        assert "course_id" not in payload  # V1 identity not stored in shadow artifact


# ---------------------------------------------------------------------------
# ShadowArtifactStore safety
# ---------------------------------------------------------------------------


class TestShadowArtifactStore:
    def test_path_traversal_safe(self, tmp_path):
        store = ShadowArtifactStore(base_dir=tmp_path / "s")
        # artifact_key produces hex only; a malicious key must be rejected.
        with pytest.raises(ValueError):
            store._safe_rel("../escape")

    def test_atomic_write(self, tmp_store):
        key = tmp_store.artifact_key("abc123" * 8, "v1")
        tmp_store.write(key, {"x": 1})
        assert tmp_store.exists(key)
        assert tmp_store.read(key) == {"x": 1}
        # no leftover .tmp
        assert list(tmp_store.base_dir().glob("*.tmp")) == []

    def test_checksummed_key_deterministic(self, tmp_store):
        k1 = tmp_store.artifact_key("sha" * 20, "cfg1")
        k2 = tmp_store.artifact_key("sha" * 20, "cfg1")
        k3 = tmp_store.artifact_key("sha" * 20, "cfg2")
        assert k1 == k2
        assert k1 != k3


# ---------------------------------------------------------------------------
# Shadow IR builder
# ---------------------------------------------------------------------------


class TestShadowIRBuilder:
    def test_builds_documentir_shape(self, tmp_file):
        import hashlib

        sha = hashlib.sha256(tmp_file.read_bytes()).hexdigest()
        ir = _build_shadow_document_ir(tmp_file, "t.docx", _FakeParseResult(), sha)
        assert ir["schema_version"] == "document-ir/1.0"
        assert ir["document_id"].startswith("doc_")
        assert ir["artifact_id"].startswith("art_")
        assert ir["source_sha256"] == sha
        assert isinstance(ir["units"], list)
        assert all("block_id" in u for u in ir["units"])

    def test_handles_empty_pages(self, tmp_file):
        import hashlib

        sha = hashlib.sha256(tmp_file.read_bytes()).hexdigest()
        ir = _build_shadow_document_ir(
            tmp_file, "t.docx", _FakeParseResult(pages=[]), sha
        )
        assert ir["page_count"] >= 1  # falls back to markdown heading count


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


class TestShadowTriggerResult:
    def test_frozen(self):
        r = ShadowTriggerResult(triggered=False, effective_mode="v1_only")
        with pytest.raises(Exception):
            r.triggered = True
