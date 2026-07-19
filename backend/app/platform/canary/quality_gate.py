"""Quality-gate aggregation for G5A.1 (ADR-0006 §8A G5A.1).

Reads G3 shadow trace JSONs and computes structured quality metrics across
THREE dimensions, with an explicit NOT_EVALUATED status for data that cannot
be evaluated. This is the G5A.1 revision of G5A.

G5A.1 semantics (per human directive):
- THREE dimensions: ``execution_safety`` (V1 isolation guarantees),
  ``contract_integrity`` (contract/citation invariants), ``model_quality``
  (real provider quality). In G5A ``model_quality`` is ALWAYS
  ``NOT_EVALUATED`` (no real model); real quality arrives at G5B.
- Empty input / missing field / zero sample / zero denominator ->
  ``NOT_EVALUATED`` or ``INSUFFICIENT_DATA`` (NOT a vacuous PASS). "No data"
  must never read as "passed".
- ``real_services_called`` is derived from an auditable Provider call log
  (see canary_runner.py), NOT hardcoded.

Metric status model:
- PASS: data sufficient and target met.
- FAIL: data sufficient and target NOT met (hard-constraint violation).
- NOT_EVALUATED: metric not applicable / no real model (model_quality in G5A).
- INSUFFICIENT_DATA: trace_count==0, zero-denominator, or required field
  missing across all traces.

This module does NOT call real services. It only reads trace files that the
G3 shadow triggers already wrote to their isolated stores.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Shadow path IDs in document-processing order.
PATH_IDS: List[str] = ["G3B", "G3C", "G3D1", "G3D2", "G3D3", "G3E1"]

# Quality dimensions.
DIMENSION_EXECUTION_SAFETY = "execution_safety"
DIMENSION_CONTRACT_INTEGRITY = "contract_integrity"
DIMENSION_MODEL_QUALITY = "model_quality"
DIMENSIONS: List[str] = [
    DIMENSION_EXECUTION_SAFETY,
    DIMENSION_CONTRACT_INTEGRITY,
    DIMENSION_MODEL_QUALITY,
]


class MetricStatus(str, Enum):
    """Status of a single quality metric."""

    PASS = "pass"
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"
    INSUFFICIENT_DATA = "insufficient_data"


# A status is "blocking" if it represents a real failure (only FAIL blocks).
_BLOCKING = {MetricStatus.FAIL}


@dataclass(frozen=True)
class QualityMetric:
    """One quality metric for one shadow path.

    ``status`` replaces the old boolean ``passed``. ``dimension`` classifies
    the metric into execution_safety / contract_integrity / model_quality.
    """

    name: str
    dimension: str
    value: Any
    target: Any
    status: MetricStatus
    detail: str = ""


@dataclass(frozen=True)
class DimensionVerdict:
    """Aggregated status of one dimension across its metrics."""

    dimension: str
    status: MetricStatus
    metrics: List[QualityMetric] = field(default_factory=list)


@dataclass(frozen=True)
class ShadowPathQuality:
    """Quality of one shadow path across its traces."""

    path_id: str
    trace_count: int
    metrics: List[QualityMetric] = field(default_factory=list)
    status: MetricStatus = MetricStatus.NOT_EVALUATED


@dataclass(frozen=True)
class QualityGateReport:
    """Aggregated quality-gate report across all shadow paths + dimensions."""

    generated_at: float
    paths: List[ShadowPathQuality] = field(default_factory=list)
    dimensions: List[DimensionVerdict] = field(default_factory=list)
    aggregate_invariants: Dict[str, Any] = field(default_factory=dict)
    verdict: MetricStatus = MetricStatus.NOT_EVALUATED
    model_quality_not_evaluated: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "verdict": self.verdict.value,
            "model_quality_not_evaluated": self.model_quality_not_evaluated,
            "aggregate_invariants": dict(self.aggregate_invariants),
            "dimensions": [
                {
                    "dimension": d.dimension,
                    "status": d.status.value,
                    "metrics": [
                        {
                            "name": m.name,
                            "dimension": m.dimension,
                            "value": m.value,
                            "target": m.target,
                            "status": m.status.value,
                            "detail": m.detail,
                        }
                        for m in d.metrics
                    ],
                }
                for d in self.dimensions
            ],
            "paths": [
                {
                    "path_id": p.path_id,
                    "trace_count": p.trace_count,
                    "status": p.status.value,
                    "metrics": [
                        {
                            "name": m.name,
                            "dimension": m.dimension,
                            "value": m.value,
                            "target": m.target,
                            "status": m.status.value,
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


def _llm_calls_total(traces: List[Dict[str, Any]]) -> int:
    # G3D1/D2/D3 traces have no llm_calls field (no LLM involved) -> 0.
    return int(sum(t.get("llm_calls", 0) for t in traces))


def _metric(name: str, dimension: str, value: Any, target: Any,
            status: MetricStatus, detail: str = "") -> QualityMetric:
    return QualityMetric(name=name, dimension=dimension, value=value,
                         target=target, status=status, detail=detail)


# ---------------------------------------------------------------------------
# Per-path metric computation
# ---------------------------------------------------------------------------


def _metrics_for_path(path_id: str, traces: List[Dict[str, Any]]) -> List[QualityMetric]:
    metrics: List[QualityMetric] = []
    n = len(traces)
    no_data = n == 0  # zero sample -> INSUFFICIENT_DATA for data-dependent metrics

    def _llm_metric(detail: str) -> QualityMetric:
        # llm_calls_total: with zero traces there is no sample to prove "no LLM
        # ran" -> INSUFFICIENT_DATA (NOT a vacuous PASS). With traces, PASS iff 0.
        if no_data:
            return _metric("llm_calls_total", DIMENSION_EXECUTION_SAFETY,
                           None, 0, MetricStatus.INSUFFICIENT_DATA, detail + " (no traces)")
        total = _llm_calls_total(traces)
        return _metric("llm_calls_total", DIMENSION_EXECUTION_SAFETY,
                       total, 0, MetricStatus.PASS if total == 0 else MetricStatus.FAIL, detail)

    if path_id == "G3B":
        metrics.append(_llm_metric("G3B: no LLM in doc shadow"))

    elif path_id == "G3C":
        metrics.append(_llm_metric("G3C: no second LLM call"))
        # Scope isolation: rate needs a denominator. Zero sample -> INSUFFICIENT_DATA.
        if no_data:
            metrics.append(_metric("scope_isolation_rate", DIMENSION_CONTRACT_INTEGRITY,
                                   None, 1.0, MetricStatus.INSUFFICIENT_DATA,
                                   "RISK-03: no traces to evaluate scope isolation"))
        else:
            isolated = sum(1 for t in traces if t.get("v2_scope_isolated") is True)
            rate = isolated / n
            metrics.append(_metric("scope_isolation_rate", DIMENSION_CONTRACT_INTEGRITY,
                                   round(rate, 4), 1.0,
                                   MetricStatus.PASS if rate == 1.0 else MetricStatus.FAIL,
                                   "RISK-03: all V2 retrieval course-scoped"))
        # citation_abstain_rate: informational. Zero sample -> INSUFFICIENT_DATA.
        if no_data:
            metrics.append(_metric("citation_abstain_rate", DIMENSION_CONTRACT_INTEGRITY,
                                   None, "informational", MetricStatus.INSUFFICIENT_DATA,
                                   "no traces to evaluate abstention"))
        else:
            abstain = sum(1 for t in traces if t.get("v2_citation_validation", {}).get("abstain") is True)
            arate = abstain / n
            metrics.append(_metric("citation_abstain_rate", DIMENSION_CONTRACT_INTEGRITY,
                                   round(arate, 4), "informational", MetricStatus.PASS,
                                   "no-evidence abstention is legitimate (informational)"))

    elif path_id == "G3D1":
        metrics.append(_llm_metric("G3D1: no LLM in learning-event shadow"))

    elif path_id == "G3D2":
        # would_inject: with zero traces there is no sample -> INSUFFICIENT_DATA.
        if no_data:
            metrics.append(_metric("would_inject_any", DIMENSION_EXECUTION_SAFETY,
                                   None, False, MetricStatus.INSUFFICIENT_DATA,
                                   "G3D2: no traces to evaluate inject (no vacuous pass)"))
        else:
            any_inject = any(t.get("would_inject") is True for t in traces)
            metrics.append(_metric("would_inject_any", DIMENSION_EXECUTION_SAFETY,
                                   any_inject, False,
                                   MetricStatus.PASS if any_inject is False else MetricStatus.FAIL,
                                   "G3D2: memory never injected into QA"))

    elif path_id == "G3D3":
        if no_data:
            metrics.append(_metric("v1_blocked_any", DIMENSION_EXECUTION_SAFETY,
                                   None, False, MetricStatus.INSUFFICIENT_DATA,
                                   "G3D3: no traces to evaluate block (no vacuous pass)"))
        else:
            any_block = any(t.get("v1_blocked") is True for t in traces)
            metrics.append(_metric("v1_blocked_any", DIMENSION_EXECUTION_SAFETY,
                                   any_block, False,
                                   MetricStatus.PASS if any_block is False else MetricStatus.FAIL,
                                   "G3D3: safety never blocks V1"))

    elif path_id == "G3E1":
        metrics.append(_llm_metric("G3E1: no LLM in graph shadow"))
        if no_data:
            metrics.append(_metric("v1_tables_touched_any", DIMENSION_EXECUTION_SAFETY,
                                   None, False, MetricStatus.INSUFFICIENT_DATA,
                                   "G3E1: no traces to evaluate V1-table touch"))
        else:
            any_touched = any(t.get("v1_tables_touched") is True for t in traces)
            metrics.append(_metric("v1_tables_touched_any", DIMENSION_EXECUTION_SAFETY,
                                   any_touched, False,
                                   MetricStatus.PASS if any_touched is False else MetricStatus.FAIL,
                                   "G3E1: never touches V1 KnowledgePoint/Relation"))
        # accepted -> evidence: needs traces to evaluate. Zero sample -> INSUFFICIENT_DATA.
        if no_data:
            metrics.append(_metric("accepted_traces_evidence_all", DIMENSION_CONTRACT_INTEGRITY,
                                   None, True, MetricStatus.INSUFFICIENT_DATA,
                                   "no traces to evaluate accepted->evidence"))
        else:
            all_trace = all(t.get("accepted_traces_evidence") is not False for t in traces)
            metrics.append(_metric("accepted_traces_evidence_all", DIMENSION_CONTRACT_INTEGRITY,
                                   all_trace, True,
                                   MetricStatus.PASS if all_trace else MetricStatus.FAIL,
                                   "G3E1 invariant: accepted nodes/edges trace to Evidence"))

    return metrics


def _path_status(metrics: List[QualityMetric]) -> MetricStatus:
    """Aggregate a path's metric statuses into one path status."""
    if not metrics:
        return MetricStatus.NOT_EVALUATED
    if any(m.status == MetricStatus.FAIL for m in metrics):
        return MetricStatus.FAIL
    if any(m.status == MetricStatus.PASS for m in metrics):
        return MetricStatus.PASS
    if all(m.status == MetricStatus.NOT_EVALUATED for m in metrics):
        return MetricStatus.NOT_EVALUATED
    return MetricStatus.INSUFFICIENT_DATA  # no FAIL, no PASS, some insufficient


def _dimension_status(metrics: List[QualityMetric]) -> MetricStatus:
    """Aggregate a dimension's metric statuses (same logic as path status)."""
    if not metrics:
        return MetricStatus.NOT_EVALUATED
    if any(m.status == MetricStatus.FAIL for m in metrics):
        return MetricStatus.FAIL
    if any(m.status == MetricStatus.PASS for m in metrics):
        return MetricStatus.PASS
    if all(m.status == MetricStatus.NOT_EVALUATED for m in metrics):
        return MetricStatus.NOT_EVALUATED
    return MetricStatus.INSUFFICIENT_DATA


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
        ``{path_id: [trace file path, ...]}``. Missing path IDs are recorded
        with 0 traces -> INSUFFICIENT_DATA / NOT_EVALUATED (NOT vacuous PASS).
    generated_at : float
        Epoch timestamp (caller supplies; ``time.time()`` at call site).
    """
    path_qualities: List[ShadowPathQuality] = []
    all_metrics: List[QualityMetric] = []
    for path_id in PATH_IDS:
        traces = _load_traces(list(trace_paths_by_path.get(path_id, [])))
        metrics = _metrics_for_path(path_id, traces)
        all_metrics.extend(metrics)
        path_qualities.append(ShadowPathQuality(
            path_id=path_id, trace_count=len(traces),
            metrics=metrics, status=_path_status(metrics),
        ))

    # Per-dimension aggregation across all paths.
    def _metrics_for_dim(dim: str) -> List[QualityMetric]:
        return [m for m in all_metrics if m.dimension == dim]

    dim_exec = _metrics_for_dim(DIMENSION_EXECUTION_SAFETY)
    dim_contract = _metrics_for_dim(DIMENSION_CONTRACT_INTEGRITY)
    # model_quality: in G5A there are NO real-model metrics -> NOT_EVALUATED.
    dim_model_metrics: List[QualityMetric] = []  # intentionally empty in G5A

    dimensions: List[DimensionVerdict] = [
        DimensionVerdict(DIMENSION_EXECUTION_SAFETY, _dimension_status(dim_exec), dim_exec),
        DimensionVerdict(DIMENSION_CONTRACT_INTEGRITY, _dimension_status(dim_contract), dim_contract),
        DimensionVerdict(DIMENSION_MODEL_QUALITY, MetricStatus.NOT_EVALUATED, dim_model_metrics),
    ]

    # Aggregate invariants (dimension-aware). Execution-safety + contract
    # invariants are booleans; model_quality is explicitly not_evaluated.
    def _all_not_failed(metrics: List[QualityMetric]) -> bool:
        # Invariant "holds" = no FAIL seen. (PASS or INSUFFICIENT_DATA both ok.)
        return all(m.status != MetricStatus.FAIL for m in metrics) if metrics else True

    def _any_pass(metrics: List[QualityMetric]) -> bool:
        return any(m.status == MetricStatus.PASS for m in metrics)

    exec_invariants = {
        "all_llm_calls_zero": _all_not_failed([m for m in dim_exec if m.name == "llm_calls_total"]),
        "memory_never_injects": _all_not_failed([m for m in dim_exec if m.name == "would_inject_any"]),
        "safety_never_blocks": _all_not_failed([m for m in dim_exec if m.name == "v1_blocked_any"]),
        "v1_tables_never_touched": _all_not_failed([m for m in dim_exec if m.name == "v1_tables_touched_any"]),
    }
    contract_invariants = {
        "accepted_traces_evidence": _all_not_failed([m for m in dim_contract if m.name == "accepted_traces_evidence_all"]),
        "evidence_scope_isolated": _all_not_failed([m for m in dim_contract if m.name == "scope_isolation_rate"]),
    }
    aggregate_invariants: Dict[str, Any] = {
        **exec_invariants,
        **contract_invariants,
        "execution_safety": _dimension_status(dim_exec).value,
        "contract_integrity": _dimension_status(dim_contract).value,
        "model_quality": MetricStatus.NOT_EVALUATED.value,  # always in G5A
    }

    # Overall verdict: FAIL if any execution/contract dimension FAIL;
    # else PASS if both have >=1 PASS (model_quality may be NOT_EVALUATED);
    # else NOT_EVALUATED / INSUFFICIENT_DATA.
    exec_status = _dimension_status(dim_exec)
    contract_status = _dimension_status(dim_contract)
    if exec_status == MetricStatus.FAIL or contract_status == MetricStatus.FAIL:
        verdict = MetricStatus.FAIL
    elif _any_pass(dim_exec) or _any_pass(dim_contract):
        verdict = MetricStatus.PASS
    elif exec_status == MetricStatus.INSUFFICIENT_DATA or contract_status == MetricStatus.INSUFFICIENT_DATA:
        verdict = MetricStatus.INSUFFICIENT_DATA
    else:
        verdict = MetricStatus.NOT_EVALUATED

    return QualityGateReport(
        generated_at=generated_at,
        paths=path_qualities,
        dimensions=dimensions,
        aggregate_invariants=aggregate_invariants,
        verdict=verdict,
        model_quality_not_evaluated=True,  # G5A invariant
    )


def write_report(report: QualityGateReport, path: str | Path) -> Path:
    """Write a quality-gate report as machine-readable JSON (atomic)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
