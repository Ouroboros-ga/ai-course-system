"""Tests for the KG-MEST Shadow report store (isolated, scope-bound, atomic)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.platform.agents.kg_mest_report_store import KGMestShadowReportStore


def _report(course_id: str = "c-1", *, status: str = "ok") -> dict:
    return {
        "status": status,
        "course_key": course_id,
        "states": {"k-1": {"observed_performance_score": 0.6, "confidence": "medium"}},
        "recommendations": {"k-1": []},
    }


def test_write_then_read_round_trip(tmp_path: Path):
    store = KGMestShadowReportStore(tmp_path / "reports")
    path = store.write(student_id="s-1", course_id="c-1", report=_report("c-1"))
    assert path.is_file()
    report = store.read("s-1", "c-1")
    assert report is not None
    assert report["course_key"] == "c-1"
    assert report["status"] == "ok"


def test_read_missing_returns_none(tmp_path: Path):
    store = KGMestShadowReportStore(tmp_path / "reports")
    assert store.read("s-1", "c-1") is None


def test_write_rejects_non_ok_status(tmp_path: Path):
    store = KGMestShadowReportStore(tmp_path / "reports")
    with pytest.raises(ValueError, match="status"):
        store.write(student_id="s-1", course_id="c-1", report=_report("c-1", status="draft"))


def test_write_rejects_course_key_mismatch(tmp_path: Path):
    store = KGMestShadowReportStore(tmp_path / "reports")
    with pytest.raises(ValueError, match="course_key"):
        store.write(student_id="s-1", course_id="c-1", report=_report("c-other"))


def test_scope_isolation_no_cross_student_leak(tmp_path: Path):
    store = KGMestShadowReportStore(tmp_path / "reports")
    store.write(student_id="s-1", course_id="c-1", report=_report("c-1"))
    # s-2 has no report; must not see s-1's report.
    assert store.read("s-2", "c-1") is None
    assert store.read("s-1", "c-2") is None


def test_path_traversal_rejected(tmp_path: Path):
    store = KGMestShadowReportStore(tmp_path / "reports")
    with pytest.raises(ValueError):
        store.write(student_id="../escape", course_id="c-1", report=_report("c-1"))
    with pytest.raises(ValueError):
        store.write(student_id="s-1", course_id="c|1", report=_report("c|1"))


def test_list_reports_sorted(tmp_path: Path):
    store = KGMestShadowReportStore(tmp_path / "reports")
    store.write(student_id="s-2", course_id="c-2", report=_report("c-2"))
    store.write(student_id="s-1", course_id="c-1", report=_report("c-1"))
    assert store.list_reports() == [("s-1", "c-1"), ("s-2", "c-2")]


def test_list_reports_empty_when_no_root(tmp_path: Path):
    store = KGMestShadowReportStore(tmp_path / "absent")
    assert store.list_reports() == []


def test_write_is_atomic(tmp_path: Path):
    """A tmp file is used and replaced; no partial JSON is left on disk."""
    store = KGMestShadowReportStore(tmp_path / "reports")
    store.write(student_id="s-1", course_id="c-1", report=_report("c-1"))
    # Only the final report file (no leftover .tmp) should exist.
    files = [p.name for p in (tmp_path / "reports").iterdir()]
    assert files == ["report_s-1__c-1.json"]
    # And it is valid JSON.
    json.loads((tmp_path / "reports" / "report_s-1__c-1.json").read_text(encoding="utf-8"))


def test_read_rechecks_scope_binding(tmp_path: Path):
    """A file whose course_key was tampered with must not be served."""
    store = KGMestShadowReportStore(tmp_path / "reports")
    store.write(student_id="s-1", course_id="c-1", report=_report("c-1"))
    path = tmp_path / "reports" / "report_s-1__c-1.json"
    tampered = _report("c-other")
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert store.read("s-1", "c-1") is None
