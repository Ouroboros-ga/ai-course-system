"""V1 compatibility adapter.

Maps known source data (text, pages/slides) from the existing V1 parse
result into a DocumentIR structure.  Missing coordinates, structure, or
provenance produce explicit warnings rather than invented values.

This adapter is limited to known V1 fields only and must never fabricate
bounding boxes, confidence scores, or provenance where none exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import CURRENT_SCHEMA_VERSION
from ..source_artifact import SourceArtifact
from .models import (
    Block,
    ContentBlock,
    DocumentIR,
    DocumentUnit,
    ParseWarning,
    Provenance,
    QualityReport,
    UnitType,
    WarningSeverity,
    compute_document_id,
    compute_unit_id,
)


@dataclass
class V1ParseResult:
    """Simplified representation of a V1 parse result.

    This is the adapter's input contract — it represents only the fields
    the adapter knows how to map.
    """

    pages: List["V1Page"] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class V1Page:
    """A single page/slide from V1 parsing."""

    index: int
    text: str
    label: Optional[str] = None
    width: Optional[float] = None
    height: Optional[float] = None


def adapt_v1_to_document_ir(
    v1_result: V1ParseResult,
    source_artifact: SourceArtifact,
    *,
    normalization_version: str = "1",
) -> DocumentIR:
    """Convert a V1 parse result into a DocumentIR.

    Missing coordinates, structure, and provenance produce explicit
    ``ParseWarning`` entries.  No bounding boxes, confidence scores, or
    provenance are invented.
    """
    warnings: List[ParseWarning] = []
    units: List[DocumentUnit] = []
    blocks: List[Block] = []

    # Compute document ID first (needed for stable unit IDs)
    doc_id = compute_document_id(
        artifact_id=source_artifact.artifact_id,
        schema_version=CURRENT_SCHEMA_VERSION.serialize(),
        normalization_version=normalization_version,
    )

    for page in v1_result.pages:
        unit_id = compute_unit_id(
            document_id=doc_id,
            unit_type="page",
            index=page.index,
            normalization_version=normalization_version,
        )

        # Create one ContentBlock per page with the full page text
        block_id = f"blk_v1_page_{page.index}"

        block = ContentBlock(
            block_id=block_id,
            page_or_slide=page.index,
            block_type="paragraph",
            text=page.text,
        )
        blocks.append(block)

        unit = DocumentUnit(
            unit_id=unit_id,
            unit_type=UnitType.PAGE,
            index=page.index,
            label=page.label,
            width=page.width,
            height=page.height,
            block_ids=(block_id,),
        )
        units.append(unit)

    # Add warnings for missing structure
    if not v1_result.pages:
        warnings.append(ParseWarning(
            code="V1_ADAPTER_EMPTY_PAGES",
            severity=WarningSeverity.WARNING,
            message="V1 parse result contains no pages; empty DocumentIR produced",
            recoverable=False,
        ))
    else:
        _add_structure_warnings(v1_result, warnings)

    quality = QualityReport(
        text_coverage=1.0 if v1_result.pages else 0.0,
        empty_unit_ratio=0.0 if v1_result.pages else 1.0,
        scorer_version="v1-adapter/1.0.0",
    )

    return DocumentIR(
        schema_version=CURRENT_SCHEMA_VERSION.serialize(),
        document_id=doc_id,
        source_artifact=source_artifact,
        units=tuple(units),
        blocks=tuple(blocks),
        quality=quality,
        warnings=tuple(warnings),
        created_at=datetime.now(timezone.utc),
    )


def _add_structure_warnings(
    v1_result: V1ParseResult,
    warnings: List[ParseWarning],
) -> None:
    """Add warnings for known structural gaps in V1 data."""
    for page in v1_result.pages:
        if page.width is None or page.height is None:
            warnings.append(ParseWarning(
                code="V1_ADAPTER_MISSING_PAGE_DIMENSIONS",
                severity=WarningSeverity.WARNING,
                message=(
                    f"Page {page.index}: missing width/height; "
                    f"cannot determine coordinate space"
                ),
                recoverable=True,
            ))
    # General warning about missing coordinates / structure
    warnings.append(ParseWarning(
        code="V1_ADAPTER_NO_BOUNDING_BOXES",
        severity=WarningSeverity.WARNING,
        message=(
            "V1 adapter does not produce bounding boxes; "
            "coordinates are unavailable for all blocks"
        ),
        recoverable=True,
    ))
    warnings.append(ParseWarning(
        code="V1_ADAPTER_NO_PROVENANCE",
        severity=WarningSeverity.WARNING,
        message=(
            "V1 adapter does not produce provenance records; "
            "parser run and provider information is unavailable"
        ),
        recoverable=True,
    ))
