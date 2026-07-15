"""Tests for P1-09 G3D3 safety dry-run shadow (ADR-0006 §G3D3)."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.platform.shadow.safety_dryrun_shadow import (
    SafetyDryRunStore,
    SafetyDryRunResult,
    trigger_safety_dryrun,
)
from app.core import feature_flags as ff


@pytest.fixture
def tmp_store(tmp_path):
    return SafetyDryRunStore(base_dir=tmp_path / "safety_store")


@pytest.fixture
def v2_safety_settings():
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    configured[ff.SAFETY_GOVERNANCE_MODE] = "shadow"
    with patch(
        "app.platform.shadow.safety_dryrun_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


@pytest.fixture
def v1_settings():
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    with patch(
        "app.platform.shadow.safety_dryrun_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


class TestFlagGated:
    def test_disabled_no_trigger(self, tmp_store, v1_settings):
        r = trigger_safety_dryrun("q", 101, store=tmp_store)
        assert not r.triggered
        assert list(tmp_store.base_dir().glob("*.json")) == []

    def test_shadow_triggers(self, tmp_store, v2_safety_settings):
        r = trigger_safety_dryrun("q", 101, store=tmp_store)
        assert r.triggered
        assert r.reason_code is not None


class TestNeverBlocksV1:
    def test_v1_blocked_always_false(self, tmp_store, v2_safety_settings):
        """HARD CONSTRAINT: dry-run never blocks V1."""
        r = trigger_safety_dryrun("q", 101, store=tmp_store)
        assert r.v1_blocked is False
        trace = json.loads(Path(r.trace_path).read_text(encoding="utf-8"))
        assert trace["v1_blocked"] is False

    def test_would_refuse_does_not_block_v1(self, tmp_store, v2_safety_settings):
        """Even if safety would refuse, V1 is not blocked."""
        r = trigger_safety_dryrun("q", 101, store=tmp_store)
        assert r.v1_blocked is False  # regardless of would_refuse


class TestRecordsDecision:
    def test_records_would_allow_or_refuse(self, tmp_store, v2_safety_settings):
        r = trigger_safety_dryrun("q", 101, store=tmp_store)
        trace = json.loads(Path(r.trace_path).read_text(encoding="utf-8"))
        assert "would_allow" in trace
        assert "would_refuse" in trace
        assert trace["would_allow"] != trace["would_refuse"]  # mutually exclusive
        assert trace["reason_code"]


class TestIsolation:
    def test_never_raises_into_v1(self, tmp_store, v2_safety_settings):
        with patch(
            "app.platform.shadow.safety_dryrun_shadow._evaluate_safety_dryrun",
            side_effect=RuntimeError("boom"),
        ):
            r = trigger_safety_dryrun("q", 101, store=tmp_store)
        assert not r.triggered
        assert "shadow_runtime_error" in (r.fallback_reason or "")

    def test_question_stored_as_sha256(self, tmp_store, v2_safety_settings):
        r = trigger_safety_dryrun("secret q", 101, store=tmp_store)
        trace = json.loads(Path(r.trace_path).read_text(encoding="utf-8"))
        assert "question_sha256" in trace
        assert "secret q" not in Path(r.trace_path).read_text(encoding="utf-8")


class TestResultFrozen:
    def test_frozen(self):
        r = SafetyDryRunResult(triggered=False, effective_mode="disabled")
        with pytest.raises(Exception):
            r.triggered = True
