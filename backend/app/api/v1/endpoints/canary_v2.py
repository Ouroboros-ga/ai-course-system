"""P1-09 G5A independent V2 Canary API router.

Admin-only canary control surface (ADR-0006 §G5A + §9 V2 router
constraints). Triggers an end-to-end canary run (no real services) and
serves the latest quality-gate report. Registered in main.py under
``/api/v1/canary-v2`` with tag ``Product1-V2-shadow``.

Per ADR-0006 §9:
- Admin-only (``Depends(admin_only)``); no raw file paths; no provider config.
- Flag-gated ``EVIDENCE_CITATION_MODE``; not v2_shadow -> 503
  SHADOW_FEATURE_DISABLED.

G5A does NOT call real services (no LLM/Docling/OCR/vector). G5B
(real-provider canary) is deferred until CLAUDE.md constraint relaxation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.feature_flags import EVIDENCE_CITATION_MODE, resolve_effective_modes
from app.core.security import admin_only
from app.platform.canary.canary_runner import CanaryConfig, run_canary
from app.platform.canary.quality_gate import QualityGateReport, compute_quality

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models (no raw file paths, no V1 identities)
# ---------------------------------------------------------------------------


class CanaryPathSummary(BaseModel):
    path_id: str
    triggered: bool
    fallback_reason: Optional[str] = None


class CanaryCourseSummary(BaseModel):
    course_id: str
    paths: List[CanaryPathSummary] = Field(default_factory=list)


class CanaryRunRequest(BaseModel):
    course_ids: List[Any] = Field(default_factory=list)


class CanaryRunResponse(BaseModel):
    overall_passed: bool
    real_services_called: bool
    verdict: str
    course_count: int
    courses: List[CanaryCourseSummary] = Field(default_factory=list)


class QualityGateResponse(BaseModel):
    verdict: str
    aggregate_invariants: Dict[str, bool]
    path_count: int


class CanaryDisabledDetail(BaseModel):
    detail: str = "SHADOW_FEATURE_DISABLED"
    flag: str
    effective_mode: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configured_modes() -> Dict[str, str]:
    try:
        from app.core.config import settings
        from app.core.feature_flags import ALL_FLAGS

        return {f: getattr(settings, f) for f in ALL_FLAGS}
    except Exception:
        return {}


def _effective_evidence_mode() -> str:
    return resolve_effective_modes(_configured_modes())[EVIDENCE_CITATION_MODE].effective


def _require_shadow_enabled() -> None:
    mode = _effective_evidence_mode()
    if mode != "v2_shadow":
        raise HTTPException(
            status_code=503,
            detail={
                "detail": "SHADOW_FEATURE_DISABLED",
                "flag": EVIDENCE_CITATION_MODE,
                "effective_mode": mode,
            },
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=CanaryRunResponse,
    summary="Run an end-to-end canary (admin-only, no real services)",
)
async def run_canary_endpoint(
    body: CanaryRunRequest,
    _admin: Any = Depends(admin_only),
) -> Any:
    """G5A: run the 6-path shadow canary for the given course allowlist.

    No real services are called. Returns a per-course/path summary (no raw
    file paths). 503 SHADOW_FEATURE_DISABLED when flag off.
    """
    _require_shadow_enabled()
    if not body.course_ids:
        raise HTTPException(status_code=400, detail="course_ids required (canary scope control)")

    result = run_canary(CanaryConfig(course_ids=body.course_ids))
    courses = []
    for cr in result.course_results:
        paths = []
        for pid in ("G3B", "G3C", "G3D1", "G3D2", "G3D3", "G3E1"):
            pr = cr.path_results.get(pid, {})
            paths.append(CanaryPathSummary(
                path_id=pid,
                triggered=bool(pr.get("triggered", False)),
                fallback_reason=pr.get("fallback_reason"),
            ))
        courses.append(CanaryCourseSummary(course_id=str(cr.course_id), paths=paths))

    qg = result.quality_gate
    return CanaryRunResponse(
        overall_passed=result.overall_passed,
        real_services_called=result.real_services_called,
        verdict=qg.verdict if qg else "N/A",
        course_count=len(courses),
        courses=courses,
    )


@router.get(
    "/report",
    response_model=QualityGateResponse,
    summary="Latest quality-gate verdict (admin-only)",
)
async def canary_report(
    _admin: Any = Depends(admin_only),
) -> Any:
    """G5A: report the aggregate quality-gate verdict + invariants.

    Recomputes from the on-disk shadow trace stores (no raw paths in the
    response). 503 SHADOW_FEATURE_DISABLED when flag off.
    """
    _require_shadow_enabled()
    # Aggregate on-disk trace roots.
    from pathlib import Path

    from app.platform.shadow.doc_shadow import DEFAULT_SHADOW_ROOT as doc_root
    from app.platform.shadow.evidence_shadow import DEFAULT_EVIDENCE_TRACE_ROOT as ev_root
    from app.platform.shadow.learning_shadow import DEFAULT_LEARNING_SHADOW_ROOT as lr_root
    from app.platform.shadow.memory_candidate_shadow import DEFAULT_MEMORY_SHADOW_ROOT as mem_root
    from app.platform.shadow.safety_dryrun_shadow import DEFAULT_SAFETY_SHADOW_ROOT as sf_root
    from app.platform.shadow.graph_shadow import DEFAULT_GRAPH_SHADOW_ROOT as gr_root

    import time as _time

    roots = {
        "G3B": sorted(Path(doc_root).glob("*.json")),
        "G3C": sorted(Path(ev_root).glob("*.json")),
        "G3D1": sorted(Path(lr_root).glob("*.json")),
        "G3D2": sorted(Path(mem_root).glob("*.json")),
        "G3D3": sorted(Path(sf_root).glob("*.json")),
        "G3E1": sorted(Path(gr_root).glob("*.json")),
    }
    report = compute_quality(roots, generated_at=_time.time())
    return QualityGateResponse(
        verdict=report.verdict,
        aggregate_invariants=report.aggregate_invariants,
        path_count=len(report.paths),
    )
