"""Tests for P1-09 G5A.1 quality-gate aggregation (ADR-0006 §8A G5A.1).

G5A.1 semantics:
- THREE dimensions: execution_safety, contract_integrity, model_quality.
- model_quality is ALWAYS not_evaluated in G5A (no real model).
- Empty/zero-sample/zero-denominator -> not_evaluated/insufficient_data
  (NOT a vacuous PASS).
- Verdict values are lowercase MetricStatus values (pass/fail/not_evaluated/
  insufficient_data).

Covers:
1. Healthy traces -> pass verdict; execution_safety + contract_integrity pass;
   model_quality not_evaluated.
2. Empty/missing roots -> not_evaluated/insufficient_data (NOT pass).
3. Zero-denominator (scope_isolation with n=0) -> insufficient_data.
4. Hard-constraint violations -> fail verdict.
5. Informational metric (citation_abstain) -> pass (or insufficient_data n=0).
6. Dimensions present with correct statuses.
7. write_report round-trips.
"""
import json
from pathlib import Path

import pytest

from app.platform.canary.quality_gate import (
    DIMENSIONS,
    MetricStatus,
    PATH_IDS,
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


def _healthy_paths(tmp_path):
    return {
        "G3B": [_write(tmp_path, "b1.json", _doc_trace())],
        "G3C": [_write(tmp_path, "c1.json", _evidence_trace(abstain=True, scope_isolated=True))],
        "G3D1": [_write(tmp_path, "l1.json", _learning_trace())],
        "G3D2": [_write(tmp_path, "m1.json", _memory_trace(would_inject=False))],
        "G3D3": [_write(tmp_path, "s1.json", _safety_trace(v1_blocked=False))],
        "G3E1": [_write(tmp_path, "g1.json", _graph_trace(accepted_traces_evidence=True))],
    }


# ---------------------------------------------------------------------------
# Healthy -> pass
# ---------------------------------------------------------------------------


class TestPass:
    def test_healthy_traces_pass(self, tmp_path):
        rep = compute_quality(_healthy_paths(tmp_path), generated_at=1.0)
        assert rep.verdict == MetricStatus.PASS
        dims = {d.dimension: d.status for d in rep.dimensions}
        assert dims["execution_safety"] == MetricStatus.PASS
        assert dims["contract_integrity"] == MetricStatus.PASS
        assert dims["model_quality"] == MetricStatus.NOT_EVALUATED
        assert rep.model_quality_not_evaluated is True

    def test_citation_abstain_informational_pass(self, tmp_path):
        rep = compute_quality(_healthy_paths(tmp_path), generated_at=1.0)
        ev = next(p for p in rep.paths if p.path_id == "G3C")
        abstain = next(m for m in ev.metrics if m.name == "citation_abstain_rate")
        assert abstain.status == MetricStatus.PASS  # informational, not failure


# ---------------------------------------------------------------------------
# Empty / missing -> NOT pass (not_evaluated / insufficient_data)
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_empty_paths_not_pass(self):
        rep = compute_quality({pid: [] for pid in PATH_IDS}, generated_at=1.0)
        assert rep.verdict != MetricStatus.PASS
        # Empty traces -> data-dependent metrics insufficient_data; llm metrics
        # pass (no LLM ran). execution_safety has PASS (llm) -> overall PASS?
        # No: llm_calls_total passes trivially, but that's a real guarantee.
        # So verdict is PASS only because execution_safety PASSes via llm.
        # The data-dependent contract metrics are insufficient_data (not pass).
        dims = {d.dimension: d.status for d in rep.dimensions}
        assert dims["model_quality"] == MetricStatus.NOT_EVALUATED
        # contract_integrity has only insufficient_data (no traces) -> not pass
        assert dims["contract_integrity"] != MetricStatus.PASS

    def test_missing_path_ids_contract_insufficient(self):
        rep = compute_quality({}, generated_at=1.0)
        dims = {d.dimension: d.status for d in rep.dimensions}
        assert dims["model_quality"] == MetricStatus.NOT_EVALUATED
        # No evidence/graph traces -> contract metrics insufficient_data.
        assert dims["contract_integrity"] == MetricStatus.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Zero-denominator -> insufficient_data
# ---------------------------------------------------------------------------


class TestZeroDenominator:
    def test_scope_isolation_zero_traces_insufficient(self):
        # G3C with zero traces -> scope_isolation_rate insufficient_data.
        rep = compute_quality({"G3C": []}, generated_at=1.0)
        ev = next(p for p in rep.paths if p.path_id == "G3C")
        scope = next(m for m in ev.metrics if m.name == "scope_isolation_rate")
        assert scope.status == MetricStatus.INSUFFICIENT_DATA

    def test_accepted_evidence_zero_traces_insufficient(self):
        rep = compute_quality({"G3E1": []}, generated_at=1.0)
        gr = next(p for p in rep.paths if p.path_id == "G3E1")
        acc = next(m for m in gr.metrics if m.name == "accepted_traces_evidence_all")
        assert acc.status == MetricStatus.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Hard-constraint violations -> fail
# ---------------------------------------------------------------------------


class TestFail:
    def test_llm_calls_nonzero_fails(self, tmp_path):
        rep = compute_quality(
            {"G3C": [_write(tmp_path, "c.json", _evidence_trace(llm=1))]}, generated_at=1.0)
        assert rep.verdict == MetricStatus.FAIL

    def test_memory_inject_fails(self, tmp_path):
        rep = compute_quality(
            {"G3D2": [_write(tmp_path, "m.json", _memory_trace(would_inject=True))]}, generated_at=1.0)
        assert rep.verdict == MetricStatus.FAIL

    def test_safety_blocks_fails(self, tmp_path):
        rep = compute_quality(
            {"G3D3": [_write(tmp_path, "s.json", _safety_trace(v1_blocked=True))]}, generated_at=1.0)
        assert rep.verdict == MetricStatus.FAIL

    def test_graph_v1_tables_touched_fails(self, tmp_path):
        rep = compute_quality(
            {"G3E1": [_write(tmp_path, "g.json", _graph_trace(v1_tables_touched=True))]}, generated_at=1.0)
        assert rep.verdict == MetricStatus.FAIL

    def test_graph_accepted_not_traced_fails(self, tmp_path):
        rep = compute_quality(
            {"G3E1": [_write(tmp_path, "g.json", _graph_trace(accepted_traces_evidence=False))]}, generated_at=1.0)
        assert rep.verdict == MetricStatus.FAIL

    def test_evidence_scope_leak_fails(self, tmp_path):
        rep = compute_quality(
            {"G3C": [_write(tmp_path, "c.json", _evidence_trace(scope_isolated=False))]}, generated_at=1.0)
        assert rep.verdict == MetricStatus.FAIL


# ---------------------------------------------------------------------------
# Dimensions structure
# ---------------------------------------------------------------------------


class TestDimensions:
    def test_three_dimensions_present(self, tmp_path):
        rep = compute_quality(_healthy_paths(tmp_path), generated_at=1.0)
        dim_names = [d.dimension for d in rep.dimensions]
        assert dim_names == DIMENSIONS

    def test_model_quality_always_not_evaluated(self, tmp_path):
        rep = compute_quality(_healthy_paths(tmp_path), generated_at=1.0)
        mq = next(d for d in rep.dimensions if d.dimension == "model_quality")
        assert mq.status == MetricStatus.NOT_EVALUATED
        assert mq.metrics == []  # no model-quality metrics in G5A

    def test_aggregate_invariants_model_quality(self, tmp_path):
        rep = compute_quality(_healthy_paths(tmp_path), generated_at=1.0)
        assert rep.aggregate_invariants["model_quality"] == "not_evaluated"


# ---------------------------------------------------------------------------
# write_report round-trip
# ---------------------------------------------------------------------------


class TestWriteReport:
    def test_write_report_json(self, tmp_path):
        rep = compute_quality(
            {"G3E1": [_write(tmp_path, "g.json", _graph_trace())]}, generated_at=1.0)
        out = write_report(rep, tmp_path / "qg.json")
        assert out.exists()
        assert list(tmp_path.glob("*.tmp")) == []  # atomic
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["verdict"] == "pass"
        assert data["model_quality_not_evaluated"] is True
        g3e1 = next(p for p in data["paths"] if p["path_id"] == "G3E1")
        assert g3e1["trace_count"] == 1
        dims = {d["dimension"]: d["status"] for d in data["dimensions"]}
        assert dims["model_quality"] == "not_evaluated"
