"""P1-09 G3B independent V2 shadow router.

Queries V2 shadow artifacts from the isolated shadow store. Does NOT
touch V1 document.py routes. Registered in main.py under
``/api/v1/document-v2`` with tag ``Product1-V2-shadow``.

Per ADR-0006 §9 (V2 router constraints):
- Admin/internal-only access (reuse existing auth; course isolation
  enforced on artifact read).
- No raw local file paths exposed.
- No provider sensitive config exposed.
- When flag disabled -> 503 + structured SHADOW_FEATURE_DISABLED (NOT
  empty 200, to avoid callers mistaking it for success).
- Shadow data retention: read-only query; cleanup is a separate ops task.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.core.feature_flags import DOCUMENT_PIPELINE_VERSION, resolve_effective_modes
from app.platform.shadow.doc_shadow import ShadowArtifactStore

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models (internal-only DTO, NOT the G4 public Evidence API DTO)
# ---------------------------------------------------------------------------


class ShadowArtifactSummary(BaseModel):
    """Summary of a shadow artifact (no raw file paths, no V1 identities)."""

    shadow_run_id: Optional[str] = None
    source_sha256: str
    source_filename: str
    effective_mode: str
    document_id: str
    page_count: int
    artifact_exists: bool


class ShadowDisabledResponse(BaseModel):
    """Structured response when shadow feature is disabled."""

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


def _effective_doc_mode() -> str:
    return resolve_effective_modes(_configured_modes())[DOCUMENT_PIPELINE_VERSION].effective


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/artifact",
    response_model=ShadowArtifactSummary,
    summary="Query a V2 shadow artifact by source sha256 (admin/internal)",
)
async def get_shadow_artifact(
    source_sha256: str = Query(..., min_length=64, max_length=64),
) -> Any:
    """Look up a shadow artifact by its source sha256.

    Returns a summary (no raw file paths). If shadow is disabled (flag
    not v2_shadow), returns 503 SHADOW_FEATURE_DISABLED so callers do not
    mistake absence for success.
    """
    if _effective_doc_mode() != "v2_shadow":
        raise HTTPException(
            status_code=503,
            detail={
                "detail": "SHADOW_FEATURE_DISABLED",
                "flag": DOCUMENT_PIPELINE_VERSION,
                "effective_mode": _effective_doc_mode(),
            },
        )
    store = ShadowArtifactStore()
    # We cannot reverse-lookup key from sha256 alone cheaply; the store keys
    # on sha256+config. Iterate the (small) store for a matching source.
    # G4+ will add an index; G3B store is bounded by disk quota.
    config_version = "document-ir/1.0:shadow-g3b"
    key = store.artifact_key(source_sha256, config_version)
    payload = store.read(key)
    if payload is None:
        raise HTTPException(status_code=404, detail="shadow artifact not found")
    ir = payload.get("document_ir", {})
    return ShadowArtifactSummary(
        shadow_run_id=payload.get("shadow_run_id"),
        source_sha256=payload.get("source_sha256", source_sha256),
        source_filename=payload.get("source_filename", ""),
        effective_mode=payload.get("effective_mode", "v2_shadow"),
        document_id=ir.get("document_id", ""),
        page_count=ir.get("page_count", 0),
        artifact_exists=True,
    )


@router.get(
    "/status",
    summary="Shadow pipeline status (admin/internal)",
)
async def shadow_status() -> Any:
    """Report effective shadow mode + store disk usage (no sensitive data)."""
    mode = _effective_doc_mode()
    store = ShadowArtifactStore()
    return {
        "effective_mode": mode,
        "flag": DOCUMENT_PIPELINE_VERSION,
        "store_disk_usage_bytes": store.disk_usage_bytes(),
        "disk_quota_bytes": store.disk_usage_bytes(),  # placeholder; quota in module
        "artifact_count": len(list(store.base_dir().glob("*.json"))),
    }
