"""Tests for P1-09 G3D1 learning-event shadow (ADR-0006 §G3D1)."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.platform.shadow.learning_shadow import (
    LearningEventShadowStore,
    LearningShadowResult,
    trigger_learning_event_shadow,
)
from app.core import feature_flags as ff


@pytest.fixture
def tmp_store(tmp_path):
    return LearningEventShadowStore(base_dir=tmp_path / "learning_store")


@pytest.fixture
def v2_settings():
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    configured[ff.LEARNING_EVENT_MODE] = "v2_shadow"
    with patch(
        "app.platform.shadow.learning_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


@pytest.fixture
def v1_settings():
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    with patch(
        "app.platform.shadow.learning_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


class TestFlagGated:
    def test_disabled_no_trigger(self, tmp_store, v1_settings):
        r = trigger_learning_event_shadow("prerequisite_jump", 1, 101, 1, store=tmp_store)
        assert not r.triggered
        assert "flag_not_v2_shadow" in (r.fallback_reason or "")
        assert list(tmp_store.base_dir().glob("*.json")) == []

    def test_v2_triggers_writes_event(self, tmp_store, v2_settings):
        r = trigger_learning_event_shadow(
            "prerequisite_jump", 1, 101, 1, payload={"to_node_id": 5}, store=tmp_store
        )
        assert r.triggered
        assert r.event_id is not None
        assert Path(r.trace_path).exists()
        trace = json.loads(Path(r.trace_path).read_text(encoding="utf-8"))
        assert trace["learning_event"]["event_type"] == "prereq_jump_started"
        assert trace["learning_event"]["student_id"] == 1
        assert trace["learning_event"]["course_id"] == 101
        assert trace["learning_event"]["metadata"]["to_node_id"] == 5


class TestIdempotency:
    def test_same_key_skip(self, tmp_store, v2_settings):
        r1 = trigger_learning_event_shadow("prerequisite_jump", 1, 101, 1, store=tmp_store)
        assert r1.triggered
        r2 = trigger_learning_event_shadow("prerequisite_jump", 1, 101, 1, store=tmp_store)
        assert not r2.triggered
        assert "idempotent_skip" in (r2.fallback_reason or "")
        assert r1.event_id == r2.event_id
        # only one file
        assert len(list(tmp_store.base_dir().glob("*.json"))) == 1

    def test_different_sequence_different_event(self, tmp_store, v2_settings):
        r1 = trigger_learning_event_shadow("prerequisite_jump", 1, 101, 1, store=tmp_store)
        r2 = trigger_learning_event_shadow("prerequisite_jump", 1, 101, 2, store=tmp_store)
        assert r1.event_id != r2.event_id
        assert len(list(tmp_store.base_dir().glob("*.json"))) == 2


class TestScope:
    def test_missing_student_fail_closed(self, tmp_store, v2_settings):
        r = trigger_learning_event_shadow("prerequisite_jump", None, 101, 1, store=tmp_store)
        assert not r.triggered
        assert "missing_student_or_course_scope" in (r.fallback_reason or "")

    def test_missing_course_fail_closed(self, tmp_store, v2_settings):
        r = trigger_learning_event_shadow("prerequisite_jump", 1, None, 1, store=tmp_store)
        assert not r.triggered
        assert "missing_student_or_course_scope" in (r.fallback_reason or "")


class TestIsolation:
    def test_never_raises_into_v1(self, tmp_store, v2_settings):
        with patch(
            "app.platform.shadow.learning_shadow._build_learning_event",
            side_effect=RuntimeError("boom"),
        ):
            r = trigger_learning_event_shadow("prerequisite_jump", 1, 101, 1, store=tmp_store)
        assert not r.triggered
        assert "shadow_runtime_error" in (r.fallback_reason or "")

    def test_isolated_from_v1(self, tmp_store, v2_settings):
        trigger_learning_event_shadow("prerequisite_jump", 1, 101, 1, store=tmp_store)
        files = list(tmp_store.base_dir().glob("*.json"))
        assert len(files) == 1
        assert tmp_store.base_dir().name == "learning_store"
        # no V1 table identity leak beyond student/course id (which is the
        # event scope, not a V1 row reference)
        trace = json.loads(files[0].read_text(encoding="utf-8"))
        assert "v1_row_id" not in trace


class TestAppendOnly:
    def test_store_does_not_overwrite(self, tmp_store, v2_settings):
        r1 = trigger_learning_event_shadow("prerequisite_jump", 1, 101, 1, store=tmp_store)
        path = Path(r1.trace_path)
        original = path.read_text(encoding="utf-8")
        # try to append same event_id with different payload (should not overwrite)
        tmp_store.append(r1.event_id, {"different": True})
        assert path.read_text(encoding="utf-8") == original


class TestResultFrozen:
    def test_frozen(self):
        r = LearningShadowResult(triggered=False, effective_mode="v1_only")
        with pytest.raises(Exception):
            r.triggered = True
