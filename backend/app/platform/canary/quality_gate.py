"""Quality-gate aggregation for G5A (ADR-0006 §G5A).

Reads G3 shadow trace JSONs and computes structured quality metrics +
an overall PASS/FAIL verdict. The hard constraints enforced here mirror
the G3 per-batch hard constraints (llm_calls==0, never-inject, never-block,
accepted->evidence, V1-tables-untouched, scope isolation). Informational
metrics (citation abstain rate, fallback rate) are recorded but do not
fail the gate.

This module does NOT call real services. It only reads trace files that
the G3 shadow triggers already wrote to their isolated stores.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Shadow path IDs in document-processing order.
PATH_IDS: List[str] = ["G3B", "G3C", "G3D1", "G3D2", "G3D3", "G3E1"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityMetric:
    """One quality metric for one shadow path.

    ``passed`` is True when ``value`` satisfies ``target`` per the
    comparator. Informational metrics set ``passed=True`` (recorded only).
    """

    name: str
    value: Any
    target: Any
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class ShadowPathQuality:
    """Quality of one shadow path across its traces."""

    path_id: str
    trace_count: int
    metrics: List[QualityMetric] = field(default_factory=list)
    passed: bool = True


@dataclass(frozen=True)
class QualityGateReport:
    """Aggregated quality-gate report across all shadow paths."""

    generated_at: float
    paths: List[ShadowPathQuality] = field(default_factory=list)
    aggregate_invariants: Dict[str, bool] = field(default_factory=dict)
    verdict: str = "PASS"  # "PASS" | "FAIL"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "verdict": self.verdict,
            "aggregate_invariants": dict(self.aggregate_invariants),
            "paths": [
                {
                    "path_id": p.path_id,
                    "trace_count": p.trace_count,
                    "passed": p.passed,
                    "metrics": [
                        {
                            "name": m.name,
                            "value": m.value,
                            "target": m.target,
                            "passed": m.passed,
                            "detail": m.detail,
                        }
                        for m in p.metrics
                    ],
                }
                for p in self.paths
            ],
        }


# ---------------------------------------------------------------------------
# Trace loading
# ---------------------------------------------------------------------------


def _load_traces(paths: List[Path]) -> List[Dict[str, Any]]:
    traces: List[Dict[str, Any]] = []
    for p in paths:
        try:
            raw = Path(p).read_text(encoding="utf-8")
            traces.append(json.loads(raw))
        except Exception as e:  # noqa: BLE001 - skip unreadable trace
            logger.warning(f"[quality_gate] skipping unreadable trace {p}: {e}")
    return traces


# ---------------------------------------------------------------------------
# Per-path metric computation
# ---------------------------------------------------------------------------


def _llm_calls_total(traces: List[Dict[str, Any]]) -> int:
    # G3D1/D2/D3 traces have no llm_calls field (no LLM involved) -> 0.
    return int(sum(t.get("llm_calls", 0) for t in traces))


def _metrics_for_path(path_id: str, traces: List[Dict[str, Any]]) -> List[QualityMetric]:
    metrics: List[QualityMetric] = []
    n = len(traces)

    if path_id == "G3B":
        total = _llm_calls_total(traces)
        metrics.append(QualityMetric("llm_calls_total", total, 0, total == 0,
                                     "G3B hard constraint: no LLM in doc shadow"))

    elif path_id == "G3C":
        total = _llm_calls_total(traces)
        metrics.append(QualityMetric("llm_calls_total", total, 0, total == 0,
                                     "G3C hard constraint: no second LLM call"))
        # Scope isolation: every evidence trace must be course-scoped.
        isolated = sum(1 for t in traces if t.get("v2_scope_isolated") is True)
        rate = isolated / n if n else 1.0
        metrics.append(QualityMetric("scope_isolation_rate", round(rate, 4), 1.0, rate == 1.0,
                                     "RISK-03: all V2 retrieval course-scoped (no global leak)"))
        # Informational: citation abstain rate (abstain is legitimate, not a failure).
        abstain = sum(1 for t in traces if t.get("v2_citation_validation", {}).get("abstain") is True)
        arate = abstain / n if n else 0.0
        metrics.append(QualityMetric("citation_abstain_rate", round(arate, 4), "informational", True,
                                     "no-evidence abstention is legitimate (not a failure)"))

    elif path_id == "G3D1":
        # No LLM, no scope field in learning trace; idempotency is tested elsewhere.
        total = _llm_calls_total(traces)
        metrics.append(QualityMetric("llm_calls_total", total, 0, total == 0,
                                     "G3D1: no LLM in learning-event shadow"))

    elif path_id == "G3D2":
        any_inject = any(t.get("would_inject") is True for t in traces)
        metrics.append(QualityMetric("would_inject_any", any_inject, False, any_inject is False,
                                     "G3D2 hard constraint: memory never injected into QA"))

    elif path_id == "G3D3":
        any_block = any(t.get("v1_blocked") is True for t in traces)
        metrics.append(QualityMetric("v1_blocked_any", any_block, False, any_block is False,
                                     "G3D3 hard constraint: safety never blocks V1"))

    elif path_id == "G3E1":
        total = _llm_calls_total(traces)
        metrics.append(QualityMetric("llm_calls_total", total, 0, total == 0,
                                     "G3E1: no LLM in graph shadow"))
        any_touched = any(t.get("v1_tables_touched") is True for t in traces)
        metrics.append(QualityMetric("v1_tables_touched_any", any_touched, False, any_touched is False,
                                     "G3E1 hard constraint: never touches V1 KnowledgePoint/Relation"))
        # accepted -> evidence: every trace's self-check must be True (vacuous if no accepts).
        all_trace = all(t.get("accepted_traces_evidence") is not False for t in traces)
        metrics.append(QualityMetric("accepted_traces_evidence_all", all_trace, True, all_trace is True,
                                     "G3E1 invariant: accepted nodes/edges trace to Evidence"))

    return metrics


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_quality(
    trace_paths_by_path: Dict[str, List[Any]],
    generated_at: float,
) -> QualityGateReport:
    """Compute a quality-gate report from trace file paths grouped by path ID.

    Parameters
    ----------
    trace_paths_by_path : dict
        ``{path_id: [trace file path, ...]}``. Paths may be str or Path.
        Missing path IDs are recorded with 0 traces (vacuous pass).
    generated_at : float
        Epoch timestamp (caller supplies; ``time.time()`` at call site).
    """
    path_qualities: List[ShadowPathQuality] = []
    for path_id in PATH_IDS:
        traces = _load_traces(list(trace_paths_by_path.get(path_id, [])))
        metrics = _metrics_for_path(path_id, traces)
        passed = all(m.passed for m in metrics)
        path_qualities.append(ShadowPathQuality(
            path_id=path_id, trace_count=len(traces), metrics=metrics, passed=passed,
        ))

    # Aggregate invariants across paths. A named metric may appear on
    # multiple paths (e.g. llm_calls_total on G3B/G3C/G3D1/G3E1); the
    # invariant holds only if EVERY such metric passed.
    def _all_metrics_named(name: str) -> List[QualityMetric]:
        return [m for pq in path_qualities for m in pq.metrics if m.name == name]

    llm = _all_metrics_named("llm_calls_total")
    inject = _all_metrics_named("would_inject_any")
    block = _all_metrics_named("v1_blocked_any")
    touched = _all_metrics_named("v1_tables_touched_any")
    acc_evid = _all_metrics_named("accepted_traces_evidence_all")
    scope = _all_metrics_named("scope_isolation_rate")

    def _all_passed(metrics: List[QualityMetric]) -> bool:
        return all(m.passed for m in metrics) if metrics else True

    aggregate_invariants: Dict[str, bool] = {
        "all_llm_calls_zero": _all_passed(llm),
        "memory_never_injects": _all_passed(inject),
        "safety_never_blocks": _all_passed(block),
        "v1_tables_never_touched": _all_passed(touched),
        "accepted_traces_evidence": _all_passed(acc_evid),
        "evidence_scope_isolated": _all_passed(scope),
        "all_paths_passed": all(pq.passed for pq in path_qualities),
    }

    verdict = "PASS" if all(aggregate_invariants.values()) else "FAIL"
    return QualityGateReport(
        generated_at=generated_at,
        paths=path_qualities,
        aggregate_invariants=aggregate_invariants,
        verdict=verdict,
    )


def write_report(report: QualityGateReport, path: str | Path) -> Path:
    """Write a quality-gate report as machine-readable JSON (atomic)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
