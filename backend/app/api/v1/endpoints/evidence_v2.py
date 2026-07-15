"""P1-09 G4A independent V2 Evidence API router (internal-evidence-api/1.0).

Serves the frozen Evidence API DTO (``internal-evidence-api/1.0``) to the
P1-04 Evidence Viewer. Registered in main.py under ``/api/v1/evidence-v2``
with tag ``Product1-V2-shadow``.

Per ADR-0006 §8 (G4A) + §9 (V2 router constraints):
- Admin-only access (``Depends(admin_only)``); blocks students so no
  cross-course Evidence read is possible.
- No raw local file paths; no provider sensitive config exposed.
- Flag-gated ``EVIDENCE_CITATION_MODE``; not v2_shadow -> 503 +
  structured ``SHADOW_FEATURE_DISABLED`` (NOT empty 200, to avoid callers
  mistaking absence for success).
- G4 serves DTO-conformant empty/abstain responses. Real per-document
  evidence + page-image rendering arrive at G5/G6. G3C shadow traces are
  per-question, not per-document, so they are not served here.

The DTO shapes (snake_case) mirror the P1-03 frozen contracts
(evidence/1.0, citation/1.0) and match the P1-04 frontend
``contracts.js`` parsers (which accept snake_case or camelCase).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.feature_flags import EVIDENCE_CITATION_MODE, resolve_effective_modes
from app.core.security import admin_only

router = APIRouter()


# ---------------------------------------------------------------------------
# Response DTO models (internal-evidence-api/1.0, snake_case)
# ---------------------------------------------------------------------------


class EvidenceSpanDTO(BaseModel):
    """One evidence span referencing a stable P1-01 block."""

    artifact_id: str
    document_id: str = ""
    unit_id: str = ""
    block_id: str
    version_ref: Optional[str] = None
    page_or_slide: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    text_snippet: Optional[str] = None
    score: Optional[float] = None
    status: str = "active"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CitationDTO(BaseModel):
    """A citation. ``key`` is null when no evidence backs it (no fake key)."""

    key: Optional[str] = None
    statement: str
    evidence_ref: Optional[str] = None
    page_or_slide: Optional[int] = None
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CitationValidationResultDTO(BaseModel):
    """Result of validating citations against evidence."""

    status: str
    abstain: bool
    abstain_reason: Optional[str] = None
    details: List[Dict[str, Any]] = Field(default_factory=list)
    verified_count: int = 0
    total_count: int = 0


class DocumentPageDTO(BaseModel):
    """A rendered document page image."""

    document_id: str
    page_number: int
    image_url: str = ""
    natural_width: int = 0
    natural_height: int = 0


class EvidenceListResponse(BaseModel):
    evidence_spans: List[EvidenceSpanDTO] = Field(default_factory=list)


class CitationListResponse(BaseModel):
    citations: List[CitationDTO] = Field(default_factory=list)


class PageListResponse(BaseModel):
    pages: List[str] = Field(default_factory=list)


class ValidateCitationsRequest(BaseModel):
    citations: List[Dict[str, Any]] = Field(default_factory=list)


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
    """503 SHADOW_FEATURE_DISABLED when EVIDENCE_CITATION_MODE not v2_shadow."""
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


@router.get(
    "/documents/{document_id}/evidence",
    response_model=EvidenceListResponse,
    summary="List evidence spans for a document (admin-only, V2 shadow)",
)
async def list_evidence_spans(
    document_id: str,
    page: Optional[int] = Query(default=None, ge=1),
    _admin: Any = Depends(admin_only),
) -> Any:
    """G4A: DTO-conformant evidence spans. G4 serves empty (real
    per-document evidence = G5/G6). 503 when flag off."""
    _require_shadow_enabled()
    return EvidenceListResponse(evidence_spans=[])


@router.get(
    "/documents/{document_id}/citations",
    response_model=CitationListResponse,
    summary="List citations for a document (admin-only, V2 shadow)",
)
async def list_citations(
    document_id: str,
    page: Optional[int] = Query(default=None, ge=1),
    _admin: Any = Depends(admin_only),
) -> Any:
    """G4A: DTO-conformant citations. G4 serves empty. 503 when flag off."""
    _require_shadow_enabled()
    return CitationListResponse(citations=[])


@router.post(
    "/documents/{document_id}/citations/validate",
    response_model=CitationValidationResultDTO,
    summary="Validate citations against evidence (admin-only, V2 shadow)",
)
async def validate_citations(
    document_id: str,
    body: ValidateCitationsRequest,
    _admin: Any = Depends(admin_only),
) -> Any:
    """G4A: validate citations. No evidence available in G4 -> abstain
    (status no_evidence, no fake citation keys). 503 when flag off."""
    _require_shadow_enabled()
    total = len(body.citations)
    return CitationValidationResultDTO(
        status="no_evidence",
        abstain=True,
        abstain_reason="no_evidence_backed_citations",
        details=[],
        verified_count=0,
        total_count=total,
    )


@router.get(
    "/documents/{document_id}/pages",
    response_model=PageListResponse,
    summary="List page image URLs for a document (admin-only, V2 shadow)",
)
async def list_pages(
    document_id: str,
    _admin: Any = Depends(admin_only),
) -> Any:
    """G4A: page image URLs. G4 serves empty (real rendering = G5/G6).
    503 when flag off."""
    _require_shadow_enabled()
    return PageListResponse(pages=[])


@router.get(
    "/documents/{document_id}/pages/{page_number}/image",
    response_model=DocumentPageDTO,
    summary="Fetch a rendered page image (admin-only, V2 shadow)",
)
async def get_page_image(
    document_id: str,
    page_number: int,
    _admin: Any = Depends(admin_only),
) -> Any:
    """G4A: page rendering not available in G4 (real rendering = G5/G6).
    503 with structured reason when flag on; 503 SHADOW_FEATURE_DISABLED
    when flag off."""
    _require_shadow_enabled()
    raise HTTPException(
        status_code=503,
        detail={
            "detail": "PAGE_RENDERING_NOT_AVAILABLE_IN_G4",
            "document_id": document_id,
            "page_number": page_number,
        },
    )
