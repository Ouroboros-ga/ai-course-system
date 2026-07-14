"""Document IR — the canonical intermediate representation for parsed documents.

All model types use frozen dataclasses for immutability.
Stable IDs (document_id, unit_id, block_id) are deterministic — they never
depend on timestamps, run IDs, status, errors, retries, or storage paths.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from ..contracts import (
    BoundingBox,
    CoordinateSpace,
    CURRENT_SCHEMA_VERSION,
    Polygon,
    ReadingOrder,
    SchemaVersion,
)
from ..source_artifact import SourceArtifact


# ---------------------------------------------------------------------------
# Block types
# ---------------------------------------------------------------------------


class BlockKind(str, Enum):
    """Discriminated union discriminator for blocks."""

    CONTENT = "content"
    TABLE = "table"
    FORMULA = "formula"


class BlockType(str, Enum):
    """Semantic type of a content block."""

    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    CODE = "code"
    QUOTE = "quote"
    TABLE = "table"
    FORMULA = "formula"
    IMAGE = "image"
    CHART = "chart"
    DIAGRAM = "diagram"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """Provenance record linking a block/unit back to a parser provider run."""

    artifact_id: str
    run_id: str
    parser_run_id: str
    provider: str
    raw_locator: str
    page_or_slide: Optional[int] = None
    bbox: Optional[BoundingBox] = None
    char_span: Optional[Tuple[int, int]] = None
    source_block_id: Optional[str] = None
    transform: Optional[str] = None
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        result: dict = {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "parser_run_id": self.parser_run_id,
            "provider": self.provider,
            "raw_locator": self.raw_locator,
        }
        if self.page_or_slide is not None:
            result["page_or_slide"] = self.page_or_slide
        if self.bbox is not None:
            result["bbox"] = self.bbox.to_dict()
        if self.char_span is not None:
            result["char_span"] = list(self.char_span)
        if self.source_block_id is not None:
            result["source_block_id"] = self.source_block_id
        if self.transform is not None:
            result["transform"] = self.transform
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "Provenance":
        bbox = None
        if "bbox" in d and d["bbox"] is not None:
            bbox = BoundingBox.from_dict(d["bbox"])
        char_span = None
        if "char_span" in d and d["char_span"] is not None:
            char_span = (int(d["char_span"][0]), int(d["char_span"][1]))
        return cls(
            artifact_id=d["artifact_id"],
            run_id=d["run_id"],
            parser_run_id=d["parser_run_id"],
            provider=d["provider"],
            raw_locator=d["raw_locator"],
            page_or_slide=d.get("page_or_slide"),
            bbox=bbox,
            char_span=char_span,
            source_block_id=d.get("source_block_id"),
            transform=d.get("transform"),
            confidence=d.get("confidence"),
        )


# ---------------------------------------------------------------------------
# ParserRun
# ---------------------------------------------------------------------------


class ParserRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ParserRun:
    """Record of one ParserProvider invocation.

    ``run_id`` and ``parser_run_id`` are execution identities — they must never
    participate in stable object IDs (document_id, unit_id, block_id, etc.).
    """

    run_id: str
    parser_run_id: str
    provider: str
    provider_version: str
    status: ParserRunStatus
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    input_artifact_id: Optional[str] = None
    raw_output_uri: Optional[str] = None
    raw_output_checksum: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    model_versions: Dict[str, str] = field(default_factory=dict)
    config_hash: Optional[str] = None
    warnings: List[ParseWarning] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    parent_parser_run_id: Optional[str] = None

    def to_dict(self) -> dict:
        result: dict = {
            "run_id": self.run_id,
            "parser_run_id": self.parser_run_id,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "status": self.status.value,
        }
        for attr in ("started_at", "finished_at"):
            val = getattr(self, attr)
            if val is not None:
                result[attr] = val.isoformat()
        for attr in ("duration_ms", "input_artifact_id", "raw_output_uri",
                     "raw_output_checksum", "error_code", "error_message",
                     "config_hash", "parent_parser_run_id"):
            val = getattr(self, attr)
            if val is not None:
                result[attr] = val
        if self.model_versions:
            result["model_versions"] = dict(self.model_versions)
        if self.warnings:
            result["warnings"] = [w.to_dict() for w in self.warnings]
        if self.metrics:
            result["metrics"] = dict(self.metrics)
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "ParserRun":
        warnings_list = [
            ParseWarning.from_dict(w) for w in d.get("warnings", [])
        ]
        return cls(
            run_id=d["run_id"],
            parser_run_id=d["parser_run_id"],
            provider=d["provider"],
            provider_version=d["provider_version"],
            status=ParserRunStatus(d["status"]),
            started_at=_parse_optional_dt(d, "started_at"),
            finished_at=_parse_optional_dt(d, "finished_at"),
            duration_ms=d.get("duration_ms"),
            input_artifact_id=d.get("input_artifact_id"),
            raw_output_uri=d.get("raw_output_uri"),
            raw_output_checksum=d.get("raw_output_checksum"),
            error_code=d.get("error_code"),
            error_message=d.get("error_message"),
            model_versions=d.get("model_versions", {}),
            config_hash=d.get("config_hash"),
            warnings=warnings_list,
            metrics=d.get("metrics", {}),
            parent_parser_run_id=d.get("parent_parser_run_id"),
        )


# ---------------------------------------------------------------------------
# ParseWarning
# ---------------------------------------------------------------------------


class WarningSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ParseWarning:
    """Non-fatal warning about parse quality."""

    code: str
    severity: WarningSeverity
    message: str
    run_id: Optional[str] = None
    parser_run_id: Optional[str] = None
    unit_id: Optional[str] = None
    block_id: Optional[str] = None
    recoverable: bool = True
    details_safe: Optional[str] = None

    def to_dict(self) -> dict:
        result: dict = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "recoverable": self.recoverable,
        }
        for attr in ("run_id", "parser_run_id", "unit_id", "block_id",
                     "details_safe"):
            val = getattr(self, attr)
            if val is not None:
                result[attr] = val
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "ParseWarning":
        return cls(
            code=d["code"],
            severity=WarningSeverity(d.get("severity", "warning")),
            message=d["message"],
            run_id=d.get("run_id"),
            parser_run_id=d.get("parser_run_id"),
            unit_id=d.get("unit_id"),
            block_id=d.get("block_id"),
            recoverable=d.get("recoverable", True),
            details_safe=d.get("details_safe"),
        )


# ---------------------------------------------------------------------------
# QualityReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityReport:
    """Document-level and per-unit quality metrics."""

    overall_score: Optional[float] = None
    text_coverage: Optional[float] = None
    reading_order_confidence: Optional[float] = None
    heading_confidence: Optional[float] = None
    ocr_ratio: Optional[float] = None
    formula_coverage: Optional[float] = None
    table_coverage: Optional[float] = None
    visual_coverage: Optional[float] = None
    duplicate_ratio: Optional[float] = None
    empty_unit_ratio: Optional[float] = None
    hard_failures: List[str] = field(default_factory=list)
    per_unit: List[dict] = field(default_factory=list)
    scorer_version: Optional[str] = None

    def to_dict(self) -> dict:
        result: dict = {}
        for attr in ("overall_score", "text_coverage",
                     "reading_order_confidence", "heading_confidence",
                     "ocr_ratio", "formula_coverage", "table_coverage",
                     "visual_coverage", "duplicate_ratio", "empty_unit_ratio",
                     "scorer_version"):
            val = getattr(self, attr)
            if val is not None:
                result[attr] = val
        if self.hard_failures:
            result["hard_failures"] = list(self.hard_failures)
        if self.per_unit:
            result["per_unit"] = list(self.per_unit)
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "QualityReport":
        return cls(
            overall_score=d.get("overall_score"),
            text_coverage=d.get("text_coverage"),
            reading_order_confidence=d.get("reading_order_confidence"),
            heading_confidence=d.get("heading_confidence"),
            ocr_ratio=d.get("ocr_ratio"),
            formula_coverage=d.get("formula_coverage"),
            table_coverage=d.get("table_coverage"),
            visual_coverage=d.get("visual_coverage"),
            duplicate_ratio=d.get("duplicate_ratio"),
            empty_unit_ratio=d.get("empty_unit_ratio"),
            hard_failures=d.get("hard_failures", []),
            per_unit=d.get("per_unit", []),
            scorer_version=d.get("scorer_version"),
        )


# ---------------------------------------------------------------------------
# VisualAsset
# ---------------------------------------------------------------------------


class AssetKind(str, Enum):
    IMAGE = "image"
    CHART = "chart"
    DIAGRAM = "diagram"
    PAGE_RENDER = "page_render"
    SLIDE_RENDER = "slide_render"


@dataclass(frozen=True)
class VisualAsset:
    """An image, chart, diagram, or rendered page/slide."""

    asset_id: str
    kind: AssetKind
    page_or_slide: Optional[int] = None
    bbox: Optional[BoundingBox] = None
    uri: Optional[str] = None
    sha256: Optional[str] = None
    mime: Optional[str] = None
    width: Optional[float] = None
    height: Optional[float] = None
    alt_text: Optional[str] = None
    visual_description: Optional[str] = None
    ocr_text: Optional[str] = None
    linked_block_ids: Tuple[str, ...] = field(default_factory=tuple)
    provider: Optional[str] = None
    confidence: Optional[float] = None
    provenance: Tuple[Provenance, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        result: dict = {
            "asset_id": self.asset_id,
            "kind": self.kind.value,
        }
        for attr in ("page_or_slide", "uri", "sha256", "mime",
                     "alt_text", "visual_description", "ocr_text",
                     "provider", "confidence"):
            val = getattr(self, attr)
            if val is not None:
                result[attr] = val
        for attr in ("width", "height"):
            val = getattr(self, attr)
            if val is not None:
                result[attr] = val
        if self.bbox is not None:
            result["bbox"] = self.bbox.to_dict()
        if self.linked_block_ids:
            result["linked_block_ids"] = list(self.linked_block_ids)
        if self.provenance:
            result["provenance"] = [p.to_dict() for p in self.provenance]
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "VisualAsset":
        bbox = BoundingBox.from_dict(d["bbox"]) if "bbox" in d and d["bbox"] is not None else None
        linked = tuple(d.get("linked_block_ids", []))
        prov = tuple(
            Provenance.from_dict(p) for p in d.get("provenance", [])
        )
        return cls(
            asset_id=d["asset_id"],
            kind=AssetKind(d["kind"]),
            page_or_slide=d.get("page_or_slide"),
            bbox=bbox,
            uri=d.get("uri"),
            sha256=d.get("sha256"),
            mime=d.get("mime"),
            width=d.get("width"),
            height=d.get("height"),
            alt_text=d.get("alt_text"),
            visual_description=d.get("visual_description"),
            ocr_text=d.get("ocr_text"),
            linked_block_ids=linked,
            provider=d.get("provider"),
            confidence=d.get("confidence"),
            provenance=prov,
        )


# ---------------------------------------------------------------------------
# Block union (discriminated by ``kind``)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentBlock:
    """A text content block (paragraph, heading, list item, etc.)."""

    kind: str = BlockKind.CONTENT.value
    block_id: str = ""
    page_or_slide: Optional[int] = None
    bbox: Optional[BoundingBox] = None
    reading_order: Optional[int] = None
    block_type: str = BlockType.PARAGRAPH.value
    text: Optional[str] = None
    ocr_text: Optional[str] = None
    heading_level: Optional[int] = None
    language: Optional[str] = None
    style_hints: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[str] = None
    child_ids: Tuple[str, ...] = field(default_factory=tuple)
    confidence: Optional[float] = None
    provider: Optional[str] = None
    provenance: Tuple[Provenance, ...] = field(default_factory=tuple)
    raw_result_ref: Optional[str] = None
    visual_description: Optional[str] = None
    warnings: Tuple[ParseWarning, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return _block_to_dict(self, extra_fields=[
            "text", "ocr_text", "heading_level", "language",
            "visual_description",
        ])

    @classmethod
    def from_dict(cls, d: dict) -> "ContentBlock":
        return _block_from_dict(cls, d, extra_fields=[
            "text", "ocr_text", "heading_level", "language",
            "visual_description",
        ])


@dataclass(frozen=True)
class TableBlock:
    """A table block with structured cell data."""

    kind: str = BlockKind.TABLE.value
    block_id: str = ""
    page_or_slide: Optional[int] = None
    bbox: Optional[BoundingBox] = None
    reading_order: Optional[int] = None
    block_type: str = BlockType.TABLE.value
    rows: Optional[int] = None
    columns: Optional[int] = None
    cells: Tuple["TableCell", ...] = field(default_factory=tuple)
    html: Optional[str] = None
    markdown: Optional[str] = None
    caption_block_id: Optional[str] = None
    continued_from: Optional[str] = None
    continued_to: Optional[str] = None
    text: Optional[str] = None
    confidence: Optional[float] = None
    provider: Optional[str] = None
    provenance: Tuple[Provenance, ...] = field(default_factory=tuple)
    raw_result_ref: Optional[str] = None
    warnings: Tuple[ParseWarning, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        result = _block_to_dict(self, extra_fields=[
            "rows", "columns", "html", "markdown", "caption_block_id",
            "continued_from", "continued_to", "text",
        ])
        if self.cells:
            result["cells"] = [c.to_dict() for c in self.cells]
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "TableBlock":
        cells = tuple(
            TableCell.from_dict(c) for c in d.get("cells", [])
        )
        obj = _block_from_dict(cls, d, extra_fields=[
            "rows", "columns", "html", "markdown", "caption_block_id",
            "continued_from", "continued_to", "text",
        ])
        # Replace default cells tuple
        object.__setattr__(obj, "cells", cells)
        return obj


@dataclass(frozen=True)
class TableCell:
    """A single cell in a TableBlock."""

    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: Optional[str] = None
    bbox: Optional[BoundingBox] = None
    header: bool = False
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        result: dict = {
            "row": self.row,
            "col": self.col,
            "row_span": self.row_span,
            "col_span": self.col_span,
            "header": self.header,
        }
        if self.text is not None:
            result["text"] = self.text
        if self.bbox is not None:
            result["bbox"] = self.bbox.to_dict()
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "TableCell":
        bbox = BoundingBox.from_dict(d["bbox"]) if "bbox" in d and d["bbox"] is not None else None
        return cls(
            row=d["row"],
            col=d["col"],
            row_span=d.get("row_span", 1),
            col_span=d.get("col_span", 1),
            text=d.get("text"),
            bbox=bbox,
            header=d.get("header", False),
            confidence=d.get("confidence"),
        )


@dataclass(frozen=True)
class FormulaBlock:
    """A formula/math block."""

    kind: str = BlockKind.FORMULA.value
    block_id: str = ""
    page_or_slide: Optional[int] = None
    bbox: Optional[BoundingBox] = None
    reading_order: Optional[int] = None
    block_type: str = BlockType.FORMULA.value
    latex: Optional[str] = None
    normalized_latex: Optional[str] = None
    display_mode: bool = False
    source_text: Optional[str] = None
    symbol_mentions: Tuple[str, ...] = field(default_factory=tuple)
    recognition_confidence: Optional[float] = None
    image_asset_id: Optional[str] = None
    text: Optional[str] = None
    confidence: Optional[float] = None
    provider: Optional[str] = None
    provenance: Tuple[Provenance, ...] = field(default_factory=tuple)
    raw_result_ref: Optional[str] = None
    warnings: Tuple[ParseWarning, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        result = _block_to_dict(self, extra_fields=[
            "latex", "normalized_latex", "display_mode", "source_text",
            "image_asset_id", "text",
        ])
        if self.symbol_mentions:
            result["symbol_mentions"] = list(self.symbol_mentions)
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "FormulaBlock":
        obj = _block_from_dict(cls, d, extra_fields=[
            "latex", "normalized_latex", "display_mode", "source_text",
            "image_asset_id", "text",
        ])
        mentions = tuple(d.get("symbol_mentions", []))
        object.__setattr__(obj, "symbol_mentions", mentions)
        return obj


# ---------------------------------------------------------------------------
# Block union type
# ---------------------------------------------------------------------------

Block = Union[ContentBlock, TableBlock, FormulaBlock]


# ---------------------------------------------------------------------------
# DocumentUnit
# ---------------------------------------------------------------------------


class UnitType(str, Enum):
    PAGE = "page"
    SLIDE = "slide"
    SECTION = "section"
    SHEET = "sheet"


@dataclass(frozen=True)
class DocumentUnit:
    """A page, slide, section, or sheet within a document."""

    unit_id: str
    unit_type: UnitType
    index: int
    label: Optional[str] = None
    width: Optional[float] = None
    height: Optional[float] = None
    coordinate_unit: Optional[str] = None
    block_ids: Tuple[str, ...] = field(default_factory=tuple)
    reading_order: ReadingOrder = field(default_factory=ReadingOrder)
    notes_block_ids: Tuple[str, ...] = field(default_factory=tuple)
    asset_ids: Tuple[str, ...] = field(default_factory=tuple)
    quality: Optional[QualityReport] = None
    provenance: Tuple[Provenance, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        result: dict = {
            "unit_id": self.unit_id,
            "unit_type": self.unit_type.value,
            "index": self.index,
        }
        for attr in ("label", "width", "height", "coordinate_unit"):
            val = getattr(self, attr)
            if val is not None:
                result[attr] = val
        result["block_ids"] = list(self.block_ids)
        result["reading_order"] = self.reading_order.to_dict()
        if self.notes_block_ids:
            result["notes_block_ids"] = list(self.notes_block_ids)
        if self.asset_ids:
            result["asset_ids"] = list(self.asset_ids)
        if self.quality is not None:
            result["quality"] = self.quality.to_dict()
        if self.provenance:
            result["provenance"] = [p.to_dict() for p in self.provenance]
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentUnit":
        prov = tuple(
            Provenance.from_dict(p) for p in d.get("provenance", [])
        )
        quality = (
            QualityReport.from_dict(d["quality"])
            if "quality" in d and d["quality"] is not None
            else None
        )
        return cls(
            unit_id=d["unit_id"],
            unit_type=UnitType(d["unit_type"]),
            index=d["index"],
            label=d.get("label"),
            width=d.get("width"),
            height=d.get("height"),
            coordinate_unit=d.get("coordinate_unit"),
            block_ids=tuple(d.get("block_ids", [])),
            reading_order=ReadingOrder.from_dict(d.get("reading_order", [])),
            notes_block_ids=tuple(d.get("notes_block_ids", [])),
            asset_ids=tuple(d.get("asset_ids", [])),
            quality=quality,
            provenance=prov,
        )


# ---------------------------------------------------------------------------
# DocumentIR (top-level)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentIR:
    """Top-level canonical document intermediate representation.

    ``document_id`` is a deterministic stable ID that depends only on the source
    artifact ID, schema version, and normalization rules — never on execution
    metadata (run_id, timestamps, status, errors, retries).
    """

    schema_version: str = field(
        default_factory=lambda: CURRENT_SCHEMA_VERSION.serialize()
    )
    document_id: str = ""
    source_artifact: Optional[SourceArtifact] = None
    parser_runs: Tuple[ParserRun, ...] = field(default_factory=tuple)
    units: Tuple[DocumentUnit, ...] = field(default_factory=tuple)
    blocks: Tuple[Block, ...] = field(default_factory=tuple)
    assets: Tuple[VisualAsset, ...] = field(default_factory=tuple)
    quality: Optional[QualityReport] = None
    warnings: Tuple[ParseWarning, ...] = field(default_factory=tuple)
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        result: dict = {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
        }
        if self.source_artifact is not None:
            result["source_artifact"] = self.source_artifact.to_dict()
        if self.parser_runs:
            result["parser_runs"] = [r.to_dict() for r in self.parser_runs]
        result["units"] = [u.to_dict() for u in self.units]
        result["blocks"] = [block_to_dict(b) for b in self.blocks]
        if self.assets:
            result["assets"] = [a.to_dict() for a in self.assets]
        if self.quality is not None:
            result["quality"] = self.quality.to_dict()
        if self.warnings:
            result["warnings"] = [w.to_dict() for w in self.warnings]
        if self.created_at is not None:
            result["created_at"] = self.created_at.isoformat()
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentIR":
        schema_version = d.get("schema_version", CURRENT_SCHEMA_VERSION.serialize())
        source_artifact = (
            SourceArtifact.from_dict(d["source_artifact"])
            if "source_artifact" in d and d["source_artifact"] is not None
            else None
        )
        parser_runs = tuple(
            ParserRun.from_dict(r) for r in d.get("parser_runs", [])
        )
        units = tuple(
            DocumentUnit.from_dict(u) for u in d.get("units", [])
        )
        blocks = tuple(
            block_from_dict(b) for b in d.get("blocks", [])
        )
        assets = tuple(
            VisualAsset.from_dict(a) for a in d.get("assets", [])
        )
        quality = (
            QualityReport.from_dict(d["quality"])
            if "quality" in d and d["quality"] is not None
            else None
        )
        warnings = tuple(
            ParseWarning.from_dict(w) for w in d.get("warnings", [])
        )
        created_at = (
            datetime.fromisoformat(d["created_at"])
            if "created_at" in d and d["created_at"]
            else None
        )
        return cls(
            schema_version=schema_version,
            document_id=d.get("document_id", ""),
            source_artifact=source_artifact,
            parser_runs=parser_runs,
            units=units,
            blocks=blocks,
            assets=assets,
            quality=quality,
            warnings=warnings,
            created_at=created_at,
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_reference_integrity(doc: DocumentIR) -> List[str]:
    """Check that every block reference in units resolves to a top-level block.

    Returns a list of error messages (empty list means valid).
    """
    errors: List[str] = []
    block_ids = {b.block_id for b in doc.blocks}

    for unit in doc.units:
        for ref in list(unit.block_ids) + list(unit.reading_order.block_ids) + list(unit.notes_block_ids):
            if ref and ref not in block_ids:
                errors.append(
                    f"Unit {unit.unit_id}: block reference {ref!r} "
                    f"does not resolve to any top-level block"
                )
    # Check child_ids and parent_id (use getattr since not all block types have these)
    for block in doc.blocks:
        parent_id = getattr(block, "parent_id", None)
        if parent_id and parent_id not in block_ids:
            errors.append(
                f"Block {block.block_id}: parent_id {parent_id!r} "
                f"does not resolve to a top-level block"
            )
        for child in getattr(block, "child_ids", ()):
            if child and child not in block_ids:
                errors.append(
                    f"Block {block.block_id}: child_id {child!r} "
                    f"does not resolve to a top-level block"
                )
    # Check VisualAsset linked_block_ids
    for asset in doc.assets:
        for ref in asset.linked_block_ids:
            if ref and ref not in block_ids:
                errors.append(
                    f"Asset {asset.asset_id}: linked_block_id {ref!r} "
                    f"does not resolve to a top-level block"
                )
    # Check caption_block_id / continued_from / to in TableBlock
    for block in doc.blocks:
        if isinstance(block, TableBlock):
            for ref_name in ("caption_block_id", "continued_from", "continued_to"):
                ref = getattr(block, ref_name)
                if ref and ref not in block_ids:
                    errors.append(
                        f"TableBlock {block.block_id}: {ref_name} {ref!r} "
                        f"does not resolve to a top-level block"
                    )
    return errors


def validate_no_duplicate_ids(doc: DocumentIR) -> List[str]:
    """Check that no two blocks share the same block_id."""
    errors: List[str] = []
    seen: Dict[str, str] = {}
    for b in doc.blocks:
        if b.block_id in seen:
            errors.append(
                f"Duplicate block_id {b.block_id!r} "
                f"(first in block type {seen[b.block_id]})"
            )
        else:
            seen[b.block_id] = b.kind
    # Also check assets
    seen_assets: Dict[str, str] = {}
    for a in doc.assets:
        if a.asset_id in seen_assets:
            errors.append(f"Duplicate asset_id {a.asset_id!r}")
        else:
            seen_assets[a.asset_id] = a.kind.value
    # Check unit_ids
    seen_units: Dict[str, int] = {}
    for u in doc.units:
        if u.unit_id in seen_units:
            errors.append(f"Duplicate unit_id {u.unit_id!r}")
        else:
            seen_units[u.unit_id] = u.index
    return errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _block_to_dict(
    block: Block,
    extra_fields: Tuple[str, ...] = (),
) -> dict:
    """Serialize any block type to a dict."""
    result: dict = {
        "block_id": block.block_id,
        "kind": block.kind,
    }
    common_fields = (
        "page_or_slide", "reading_order", "block_type", "provider",
        "raw_result_ref", "confidence",
    )
    for attr in common_fields:
        val = getattr(block, attr, None)
        if val is not None:
            result[attr] = val
    for attr in extra_fields:
        val = getattr(block, attr, None)
        if val is not None:
            result[attr] = val
    if hasattr(block, "style_hints") and block.style_hints:  # type: ignore[union-attr]
        result["style_hints"] = dict(block.style_hints)  # type: ignore[union-attr]
    if block.bbox is not None:
        result["bbox"] = block.bbox.to_dict()
    if block.provenance:
        result["provenance"] = [p.to_dict() for p in block.provenance]
    if block.warnings:
        result["warnings"] = [w.to_dict() for w in block.warnings]
    if hasattr(block, "child_ids") and block.child_ids:  # type: ignore[union-attr]
        result["child_ids"] = list(block.child_ids)  # type: ignore[union-attr]
    if hasattr(block, "parent_id") and block.parent_id is not None:  # type: ignore[union-attr]
        result["parent_id"] = block.parent_id  # type: ignore[union-attr]
    return result


def _block_from_dict(
    cls: type,
    d: dict,
    extra_fields: Tuple[str, ...] = (),
):
    """Deserialize a block from dict."""
    bbox = BoundingBox.from_dict(d["bbox"]) if "bbox" in d and d["bbox"] is not None else None
    prov = tuple(Provenance.from_dict(p) for p in d.get("provenance", []))
    warnings = tuple(ParseWarning.from_dict(w) for w in d.get("warnings", []))

    kwargs: dict = {
        "block_id": d.get("block_id", ""),
        "page_or_slide": d.get("page_or_slide"),
        "bbox": bbox,
        "reading_order": d.get("reading_order"),
        "block_type": d.get("block_type", "paragraph"),
        "confidence": d.get("confidence"),
        "provider": d.get("provider"),
        "provenance": prov,
        "raw_result_ref": d.get("raw_result_ref"),
        "warnings": warnings,
    }

    for attr in extra_fields:
        if attr in d:
            kwargs[attr] = d[attr]

    if hasattr(cls, "style_hints"):
        kwargs["style_hints"] = d.get("style_hints", {})
    if hasattr(cls, "child_ids"):
        kwargs["child_ids"] = tuple(d.get("child_ids", []))
    if hasattr(cls, "parent_id"):
        kwargs["parent_id"] = d.get("parent_id")

    return cls(**kwargs)


def block_to_dict(block: Block) -> dict:
    """Serialize a discriminated block."""
    if isinstance(block, ContentBlock):
        return block.to_dict()
    elif isinstance(block, TableBlock):
        return block.to_dict()
    elif isinstance(block, FormulaBlock):
        return block.to_dict()
    else:
        raise TypeError(f"Unknown block type: {type(block).__name__}")


def block_from_dict(d: dict) -> Block:
    """Deserialize a discriminated block from dict."""
    kind = d.get("kind", "")
    if kind == BlockKind.CONTENT.value:
        return ContentBlock.from_dict(d)
    elif kind == BlockKind.TABLE.value:
        return TableBlock.from_dict(d)
    elif kind == BlockKind.FORMULA.value:
        return FormulaBlock.from_dict(d)
    else:
        raise ValueError(
            f"Unknown block kind {kind!r}. "
            f"Expected one of: {[k.value for k in BlockKind]}"
        )


def _parse_optional_dt(d: dict, key: str):
    raw = d.get(key)
    if raw:
        return datetime.fromisoformat(raw)
    return None


# ---------------------------------------------------------------------------
# Stable ID helpers
# ---------------------------------------------------------------------------


def compute_document_id(
    artifact_id: str,
    schema_version: str,
    normalization_version: str = "1",
) -> str:
    """Deterministic document ID from artifact + schema + normalization."""
    raw = f"{artifact_id}:sv{schema_version}:nv{normalization_version}"
    ns = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
    return f"doc_{uuid.uuid5(ns, raw).hex}"


def compute_unit_id(
    document_id: str,
    unit_type: str,
    index: int,
    normalization_version: str = "1",
) -> str:
    """Deterministic unit ID from document + type + index."""
    raw = f"{document_id}:ut{unit_type}:idx{index}:nv{normalization_version}"
    ns = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
    return f"unit_{uuid.uuid5(ns, raw).hex}"
