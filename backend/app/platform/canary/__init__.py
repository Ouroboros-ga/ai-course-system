"""Product 1 G5A canary quality-gate framework (ADR-0006 §G5A).

Runtime aggregation of G3 shadow traces into structured quality metrics.
This upgrades the G3E2 static shadow-diff report (manually authored) to a
runtime-computed quality gate. It does NOT call real services (no LLM, no
real Docling/OCR/vector) - it reads the trace JSONs that the G3 shadow
triggers already write to their isolated stores.

G5A scope (per user decision, CLAUDE.md compliant):
- Aggregate G3B..G3E1 trace quality metrics (evidence-chain integrity,
  citation parsability, scope isolation, trace-to-evidence, V1-untouched,
  llm-calls-zero, never-inject, never-block).
- End-to-end canary runnability under all-flags-on (see canary_runner.py).
- Canary scope control (course allowlist).
- Real-provider quality comparison (G5B) is deferred until CLAUDE.md
  constraint relaxation (no dep install / no real paid services).
"""
from app.platform.canary.quality_gate import (
    PATH_IDS,
    QualityGateReport,
    QualityMetric,
    ShadowPathQuality,
    compute_quality,
    write_report,
)

__all__ = [
    "PATH_IDS",
    "QualityGateReport",
    "QualityMetric",
    "ShadowPathQuality",
    "compute_quality",
    "write_report",
]
