"""Tests for P1-09 G5A quality-gate aggregation (ADR-0006 §G5A).

Covers:
1. Healthy traces -> PASS verdict, all invariants True.
2. Empty/missing roots -> vacuous PASS (0 traces, no failures).
3. Hard-constraint violations -> FAIL: llm_calls>0, would_inject=True,
   v1_blocked=True, v1_tables_touched=True, accepted_traces_evidence=False,
   scope_isolation<1.0.
4. Informational metrics (citation_abstain_rate) do not fail the gate.
5. write_report round-trips machine-readable JSON.
"""
import json
from pathlib import Path

import pytest

from app.platform.canary.quality_gate import (
    PATH_IDS,
    QualityGateReport,
    compute_quality,
    write_report,
)


# ---------------------------------------------------------------------------
# Trace fixtures
# ---------------------------------------------------------------------------


def _evidence_trace(*, abstain=False, scope_isolated=True, llm=0):
    return {
        "shadow_run_id": "r1", "triggered_at": 1.0, "course_id": "1",
        "effective_mode": "v2_shadow", "llm_calls": llm,
        "v2_scope_isolated": scope_isolated,
        "v2_citation_validation": {"abstain": abstain},
        "diff": {},
    }


def _memory_trace(*, would_inject=False):
    return {
        "run_id": "r1", "triggered_at": 1.0, "student_id": 1, "course_id": 1,
        "effective_mode": "shadow", "would_inject": would_inject,
        "candidate_memory": [], "would_inject_context": {},
    }


def _safety_trace(*, v1_blocked=False):
    return {
        "run_id": "r1", "triggered_at": 1.0, "course_id": "1",
        "effective_mode": "shadow", "v1_blocked": v1_blocked,
        "would_allow": True, "would_refuse": False, "reason_code": "ok",
    }


def _graph_trace(*, llm=0, accepted_traces_evidence=True, v1_tables_touched=False):
    return {
        "shadow_run_id": "r1", "triggered_at": 1.0, "course_id": "1",
        "effective_mode": "v2_shadow", "llm_calls": llm,
        "v2_accepted_count": 0, "v2_evidence_backed_count": 0,
        "accepted_traces_evidence": accepted_traces_evidence,
        "v1_tables_touched": v1_tables_touched, "diff": {},
    }


def _doc_trace(*, llm=0):
    return {"shadow_run_id": "r1", "triggered_at": 1.0, "effective_mode": "v2_shadow", "llm_calls": llm}


def _learning_trace():
    return {"event_id": "e1", "triggered_at": 1.0, "learning_event": {}, "shadow_store": "x"}


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Healthy -> PASS
# ---------------------------------------------------------------------------


class TestPass:
    def test_healthy_traces_pass(self, tmp_path):
        paths = {
            "G3B": [_write(tmp_path, "b1.json", _doc_trace())],
            "G3C": [_write(tmp_path, "c1.json", _evidence_trace(abstain=True, scope_isolated=True))],
            "G3D1": [_write(tmp_path, "l1.json", _learning_trace())],
            "G3D2": [_write(tmp_path, "m1.json", _memory_trace(would_inject=False))],
            "G3D3": [_write(tmp_path, "s1.json", _safety_trace(v1_blocked=False))],
            "G3E1": [_write(tmp_path, "g1.json", _graph_trace(accepted_traces_evidence=True))],
        }
        rep = compute_quality(paths, generated_at=1.0)
        assert rep.verdict == "PASS"
        assert all(rep.aggregate_invariants.values())
        assert rep.aggregate_invariants["all_paths_passed"] is True

    def test_citation_abstain_is_informational_not_failure(self, tmp_path):
        # All evidence abstains (no evidence) -> abstain_rate=1.0 but still PASS.
        paths = {"G3C": [_write(tmp_path, "c.json", _evidence_trace(abstain=True))]}
        rep = compute_quality(paths, generated_at=1.0)
        assert rep.verdict == "PASS"
        abstain_metric = next(m for p in rep.paths if p.path_id == "G3C" for m in p.metrics if m.name == "citation_abstain_rate")
        assert abstain_metric.value == 1.0
        assert abstain_metric.passed is True  # informational


# ---------------------------------------------------------------------------
# Empty / missing -> vacuous PASS
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_empty_paths_vacuous_pass(self):
        rep = compute_quality({pid: [] for pid in PATH_IDS}, generated_at=1.0)
        assert rep.verdict == "PASS"
        assert all(pq.trace_count == 0 for pq in rep.paths)

    def test_missing_path_ids_vacuous_pass(self):
        rep = compute_quality({}, generated_at=1.0)
        assert rep.verdict == "PASS"
        assert len(rep.paths) == len(PATH_IDS)


# ---------------------------------------------------------------------------
# Hard-constraint violations -> FAIL
# ---------------------------------------------------------------------------


class TestFail:
    def test_llm_calls_nonzero_fails(self, tmp_path):
        paths = {"G3C": [_write(tmp_path, "c.json", _evidence_trace(llm=1))]}
        rep = compute_quality(paths, generated_at=1.0)
        assert rep.verdict == "FAIL"
        assert rep.aggregate_invariants["all_llm_calls_zero"] is False

    def test_memory_inject_fails(self, tmp_path):
        paths = {"G3D2": [_write(tmp_path, "m.json", _memory_trace(would_inject=True))]}
        rep = compute_quality(paths, generated_at=1.0)
        assert rep.verdict == "FAIL"
        assert rep.aggregate_invariants["memory_never_injects"] is False

    def test_safety_blocks_fails(self, tmp_path):
        paths = {"G3D3": [_write(tmp_path, "s.json", _safety_trace(v1_blocked=True))]}
        rep = compute_quality(paths, generated_at=1.0)
        assert rep.verdict == "FAIL"
        assert rep.aggregate_invariants["safety_never_blocks"] is False

    def test_graph_v1_tables_touched_fails(self, tmp_path):
        paths = {"G3E1": [_write(tmp_path, "g.json", _graph_trace(v1_tables_touched=True))]}
        rep = compute_quality(paths, generated_at=1.0)
        assert rep.verdict == "FAIL"
        assert rep.aggregate_invariants["v1_tables_never_touched"] is False

    def test_graph_accepted_not_traced_fails(self, tmp_path):
        paths = {"G3E1": [_write(tmp_path, "g.json", _graph_trace(accepted_traces_evidence=False))]}
        rep = compute_quality(paths, generated_at=1.0)
        assert rep.verdict == "FAIL"
        assert rep.aggregate_invariants["accepted_traces_evidence"] is False

    def test_evidence_scope_leak_fails(self, tmp_path):
        paths = {"G3C": [_write(tmp_path, "c.json", _evidence_trace(scope_isolated=False))]}
        rep = compute_quality(paths, generated_at=1.0)
        assert rep.verdict == "FAIL"
        assert rep.aggregate_invariants["evidence_scope_isolated"] is False


# ---------------------------------------------------------------------------
# write_report round-trip
# ---------------------------------------------------------------------------


class TestWriteReport:
    def test_write_report_json(self, tmp_path):
        paths = {"G3E1": [_write(tmp_path, "g.json", _graph_trace())]}
        rep = compute_quality(paths, generated_at=1.0)
        out = write_report(rep, tmp_path / "qg.json")
        assert out.exists()
        assert list((tmp_path).glob("*.tmp")) == []  # atomic, no leftover
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["verdict"] == "PASS"
        g3e1 = next(p for p in data["paths"] if p["path_id"] == "G3E1")
        assert g3e1["trace_count"] == 1
