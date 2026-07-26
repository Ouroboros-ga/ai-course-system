"""Native PPTX parser provider.

Wraps python-pptx to extract slide structure, text, tables, notes, and images,
producing a ParserOutput compatible with the DocumentIR mapper.

This provider uses the existing python-pptx library (same dependency as the
read-only ``common/ppt_parser.py::PPTParser``) but produces structured output
for the DocumentIR pipeline rather than the old V1 container types.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..registry import (
    ParserCapabilities,
    ParserOutput,
    ParseError,
    ParseTimeoutError,
    ParseUnavailableError,
    ParseMalformedError,
)
from ..planner import ParsePlan
from ..source_artifact import SourceArtifact


# ---------------------------------------------------------------------------
# Check python-pptx availability
# ---------------------------------------------------------------------------

try:
    from pptx import Presentation as _PptxPresentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE as _MSO_SHAPE_TYPE

    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False
    _PptxPresentation = None  # type: ignore
    _MSO_SHAPE_TYPE = None    # type: ignore


# ---------------------------------------------------------------------------
# Slide data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlideShape:
    """A shape extracted from a PPTX slide."""

    shape_id: int
    shape_name: str
    shape_type: int
    text: Optional[str] = None
    bbox_emu: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h in EMU
    has_table: bool = False
    is_title: bool = False
    is_picture: bool = False
    is_group: bool = False
    raw_data: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SlideTable:
    """A table extracted from a PPTX slide."""

    rows: int
    columns: int
    cells: Tuple[Tuple[str, ...], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SlideData:
    """All data extracted from a single PPTX slide."""

    slide_index: int
    title: Optional[str] = None
    shapes: Tuple[SlideShape, ...] = field(default_factory=tuple)
    tables: Tuple[SlideTable, ...] = field(default_factory=tuple)
    notes: Optional[str] = None
    width_emu: int = 0
    height_emu: int = 0
    slide_layout: Optional[str] = None


# ---------------------------------------------------------------------------
# Parser provider
# ---------------------------------------------------------------------------


class NativePptxProvider:
    """Parser provider for native PPTX files using python-pptx.

    This provider extracts slide-level structure, text content, tables,
    notes, and shape metadata.  It does NOT perform OCR, formula recognition,
    or image analysis — those are enrichment steps.
    """

    name = "native-pptx"
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supported_formats=("pptx",),
        supports_tables=True,
        supports_notes=True,
        supports_reading_order=True,
        supports_coordinates=True,
        supports_visual_assets=True,
        supports_provenance=True,
        max_file_size_bytes=200 * 1024 * 1024,
        max_pages=200,
    )

    def __init__(self) -> None:
        if not HAS_PPTX:
            self._available = False
        else:
            self._available = True

    async def parse(
        self,
        source: SourceArtifact,
        plan: ParsePlan,
    ) -> ParserOutput:
        """Parse a PPTX source artifact.

        Args:
            source: The source artifact (must be PPTX format).
            plan: The parse plan with configuration.

        Returns:
            ParserOutput with slide data.

        Raises:
            ParseUnavailableError: If python-pptx is not installed.
            ParseMalformedError: If the file cannot be opened as a PPTX.
            ParseTimeoutError: If parsing exceeds the configured timeout.
        """
        if not self._available:
            raise ParseUnavailableError(
                "python-pptx is not installed. "
                "Install with: pip install python-pptx"
            )

        timeout_ms = 120000
        if plan.steps:
            primary = plan.primary_step
            if primary:
                timeout_ms = primary.timeout_ms

        start = time.perf_counter()

        # Source data must be accessible
        data = self._get_source_data(source)
        if data is None:
            raise ParseMalformedError(
                "Source artifact has no accessible data"
            )

        try:
            prs = _PptxPresentation(io.BytesIO(data))
        except Exception as exc:
            raise ParseMalformedError(
                f"Failed to open PPTX: {exc}"
            ) from exc

        slides: List[SlideData] = []
        slide_width = prs.slide_width or 0
        slide_height = prs.slide_height or 0

        for i, pptx_slide in enumerate(prs.slides):
            if (time.perf_counter() - start) * 1000 > timeout_ms:
                raise ParseTimeoutError(
                    f"PPTX parsing timed out after {timeout_ms}ms "
                    f"at slide {i + 1}/{len(prs.slides)}"
                )

            slide_data = self._extract_slide(pptx_slide, i + 1,
                                             slide_width, slide_height)
            slides.append(slide_data)

        duration_ms = int((time.perf_counter() - start) * 1000)

        # Build pages tuple for ParserOutput
        pages: List[Dict[str, Any]] = []
        for slide in slides:
            pages.append(self._slide_to_page_dict(slide))

        return ParserOutput(
            provider=self.name,
            provider_version=self.version,
            pages=tuple(pages),
            metadata={
                "slide_count": len(slides),
                "slide_width_emu": slide_width,
                "slide_height_emu": slide_height,
                "duration_ms": duration_ms,
            },
        )

    def _extract_slide(
        self,
        pptx_slide: Any,
        index: int,
        slide_width: int,
        slide_height: int,
    ) -> SlideData:
        """Extract all data from a single PPTX slide."""
        title: Optional[str] = None
        shapes: List[SlideShape] = []
        tables: List[SlideTable] = []
        notes: Optional[str] = None

        # Get slide title
        if pptx_slide.shapes.title:
            title_text = pptx_slide.shapes.title.text
            if title_text:
                title = title_text.strip()

        # Extract shapes
        for shape in pptx_slide.shapes:
            shape_type = int(shape.shape_type) if hasattr(shape, "shape_type") else 0
            is_title = (shape == pptx_slide.shapes.title) if pptx_slide.shapes.title else False

            # Extract text
            shape_text: Optional[str] = None
            if hasattr(shape, "text") and shape.text:
                shape_text = shape.text.strip()

            # Extract bounding box (EMU coordinates)
            bbox = None
            if hasattr(shape, "left") and hasattr(shape, "top"):
                left = int(getattr(shape, "left", 0))
                top = int(getattr(shape, "top", 0))
                width = int(getattr(shape, "width", 0))
                height = int(getattr(shape, "height", 0))
                bbox = (left, top, width, height)

            # Check for table
            has_table = False
            if hasattr(shape, "has_table") and shape.has_table:
                has_table = True
                table = shape.table
                rows_data: List[Tuple[str, ...]] = []
                for row in table.rows:
                    cells = tuple(cell.text.strip() for cell in row.cells)
                    rows_data.append(cells)
                tables.append(SlideTable(
                    rows=len(table.rows),
                    columns=len(table.columns),
                    cells=tuple(rows_data),
                ))

            # Check for picture
            is_picture = False
            try:
                is_picture = (shape_type == 13)  # MSO_SHAPE_TYPE.PICTURE
            except Exception:
                pass

            is_group = (shape_type == 6)  # MSO_SHAPE_TYPE.GROUP

            shapes.append(SlideShape(
                shape_id=int(shape.shape_id) if hasattr(shape, "shape_id") else 0,
                shape_name=str(getattr(shape, "name", "")),
                shape_type=shape_type,
                text=shape_text,
                bbox_emu=bbox,
                has_table=has_table,
                is_title=is_title,
                is_picture=is_picture,
                is_group=is_group,
            ))

        # Extract notes
        if pptx_slide.has_notes_slide:
            notes_slide = pptx_slide.notes_slide
            if notes_slide.notes_text_frame:
                notes_text = notes_slide.notes_text_frame.text
                if notes_text:
                    notes = notes_text.strip()

        return SlideData(
            slide_index=index,
            title=title,
            shapes=tuple(shapes),
            tables=tuple(tables),
            notes=notes,
            width_emu=slide_width,
            height_emu=slide_height,
            slide_layout=str(getattr(pptx_slide, "slide_layout", None)),
        )

    def _slide_to_page_dict(self, slide: SlideData) -> Dict[str, Any]:
        """Convert a SlideData to a dict for ParserOutput pages."""
        shape_dicts: List[Dict[str, Any]] = []
        for shape in slide.shapes:
            sd: Dict[str, Any] = {
                "shape_id": shape.shape_id,
                "shape_name": shape.shape_name,
                "shape_type": shape.shape_type,
                "is_title": shape.is_title,
                "is_picture": shape.is_picture,
                "is_group": shape.is_group,
            }
            if shape.text is not None:
                sd["text"] = shape.text
            if shape.bbox_emu is not None:
                sd["bbox_emu"] = list(shape.bbox_emu)
            if shape.has_table:
                sd["has_table"] = True
            shape_dicts.append(sd)

        table_dicts: List[Dict[str, Any]] = []
        for table in slide.tables:
            td: Dict[str, Any] = {
                "rows": table.rows,
                "columns": table.columns,
                "cells": [list(row) for row in table.cells],
            }
            table_dicts.append(td)

        result: Dict[str, Any] = {
            "slide_index": slide.slide_index,
            "title": slide.title or "",
            "shapes": shape_dicts,
            "tables": table_dicts,
            "width_emu": slide.width_emu,
            "height_emu": slide.height_emu,
        }
        if slide.notes:
            result["notes"] = slide.notes
        if slide.slide_layout:
            result["slide_layout"] = slide.slide_layout

        return result

    @staticmethod
    def _get_source_data(source: SourceArtifact) -> Optional[bytes]:
        """从 SourceArtifact 读取源数据。

        P0-4：通过 source.uri（即 object_key）从对象存储读取文件内容。
        若 uri 为空，回退到 None（测试场景可由调用方直接注入数据）。
        """
        if not source.uri:
            return None
        try:
            from app.services.object_storage import get_object_storage
            storage = get_object_storage()
            return storage.get(source.uri)
        except FileNotFoundError:
            return None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# IR mapper
# ---------------------------------------------------------------------------


def map_pptx_output_to_ir(
    output: ParserOutput,
    source: SourceArtifact,
    run_id: str,
    parser_run_id: str,
    normalization_version: str = "1",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Map native-pptx ParserOutput to DocumentIR block/unit/asset dicts.

    Args:
        output: The ParserOutput from NativePptxProvider.
        source: The source artifact.
        run_id: The pipeline run ID.
        parser_run_id: The parser run ID.
        normalization_version: Normalization version for stable IDs.

    Returns:
        Tuple of (blocks, units, assets) as dicts ready for DocumentIR construction.
    """
    from ..contracts import CURRENT_SCHEMA_VERSION
    from ..document_ir.models import (
        compute_document_id, compute_unit_id,
        ContentBlock, DocumentUnit, Provenance, UnitType,
        AssetKind, VisualAsset,
    )

    doc_id = compute_document_id(
        artifact_id=source.artifact_id,
        schema_version=CURRENT_SCHEMA_VERSION.serialize(),
        normalization_version=normalization_version,
    )

    blocks: List[Dict[str, Any]] = []
    units: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []
    page_blocks: Dict[int, List[str]] = {}

    slide_width = output.metadata.get("slide_width_emu", 0)
    slide_height = output.metadata.get("slide_height_emu", 0)

    for page_dict in output.pages:
        slide_index = page_dict["slide_index"]
        unit_id = compute_unit_id(
            document_id=doc_id,
            unit_type="slide",
            index=slide_index,
            normalization_version=normalization_version,
        )
        block_ids: List[str] = []

        shapes = page_dict.get("shapes", [])
        for shape in shapes:
            block_id = f"blk_pptx_s{slide_index}_sh{shape['shape_id']}"

            # Build bounding box
            bbox = None
            bbox_emu = shape.get("bbox_emu")
            if bbox_emu and slide_width > 0 and slide_height > 0:
                from ..contracts import BoundingBox, CoordinateSpace
                left, top, w, h = bbox_emu
                x0 = left / slide_width
                y0 = top / slide_height
                x1 = (left + w) / slide_width
                y1 = (top + h) / slide_height
                try:
                    bbox = BoundingBox(
                        x0=round(x0, 6),
                        y0=round(y0, 6),
                        x1=round(x1, 6),
                        y1=round(y1, 6),
                        coordinate_space=CoordinateSpace.NORMALIZED,
                    )
                except ValueError:
                    bbox = None

            # Determine block type
            text = shape.get("text", "")
            block_type = "paragraph"
            heading_level = None
            if shape.get("is_title"):
                block_type = "heading"
                heading_level = 1
            elif not text:
                block_type = "image" if shape.get("is_picture") else "unknown"

            provenance = Provenance(
                artifact_id=source.artifact_id,
                run_id=run_id,
                parser_run_id=parser_run_id,
                provider="native-pptx",
                raw_locator=f"slides/{slide_index}/shapes/{shape['shape_id']}",
                page_or_slide=slide_index,
                bbox=bbox,
                confidence=1.0,
            )

            block = ContentBlock(
                block_id=block_id,
                page_or_slide=slide_index,
                bbox=bbox,
                reading_order=len(block_ids) + 1,
                block_type=block_type,
                heading_level=heading_level,
                text=text or None,
                provider="native-pptx",
                provenance=(provenance,),
                raw_result_ref=f"artifact://{parser_run_id}/raw.json"
                              f"#/slides/{slide_index}/shapes/{shape['shape_id']}",
            )
            blocks.append(block.to_dict())
            block_ids.append(block_id)

        # Handle tables
        for t_idx, table in enumerate(page_dict.get("tables", [])):
            block_id = f"blk_pptx_s{slide_index}_t{t_idx}"
            from ..document_ir.models import TableBlock, TableCell

            cells: List[Dict[str, Any]] = []
            for r_idx, row in enumerate(table.get("cells", [])):
                for c_idx, cell_text in enumerate(row):
                    cells.append(TableCell(
                        row=r_idx,
                        col=c_idx,
                        text=cell_text,
                    ).to_dict())

            table_provenance = Provenance(
                artifact_id=source.artifact_id,
                run_id=run_id,
                parser_run_id=parser_run_id,
                provider="native-pptx",
                raw_locator=f"slides/{slide_index}/tables/{t_idx}",
                page_or_slide=slide_index,
            )

            table_block = TableBlock(
                block_id=block_id,
                page_or_slide=slide_index,
                reading_order=len(block_ids) + 1,
                rows=table.get("rows", 0),
                columns=table.get("columns", 0),
                cells=tuple(
                    TableCell(r, c, text=cell)
                    for r, row in enumerate(table.get("cells", []))
                    for c, cell in enumerate(row)
                ),
                provider="native-pptx",
                provenance=(table_provenance,),
            )
            blocks.append(table_block.to_dict())
            block_ids.append(block_id)

        # Create unit
        unit = DocumentUnit(
            unit_id=unit_id,
            unit_type=UnitType.SLIDE,
            index=slide_index,
            label=page_dict.get("title") or None,
            width=slide_width / 914400 if slide_width else None,  # EMU to inches
            height=slide_height / 914400 if slide_height else None,
            coordinate_unit="inch",
            block_ids=tuple(block_ids),
            provenance=(
                Provenance(
                    artifact_id=source.artifact_id,
                    run_id=run_id,
                    parser_run_id=parser_run_id,
                    provider="native-pptx",
                    raw_locator=f"slides/{slide_index}",
                    page_or_slide=slide_index,
                ),
            ),
        )
        units.append(unit.to_dict())
        page_blocks[slide_index] = block_ids

        # Add slide render asset placeholder
        if slide_width and slide_height:
            asset = VisualAsset(
                asset_id=f"asset_pptx_slide_{slide_index}",
                kind=AssetKind.SLIDE_RENDER,
                page_or_slide=slide_index,
                width=slide_width / 914400,
                height=slide_height / 914400,
                linked_block_ids=tuple(block_ids),
                provider="native-pptx",
            )
            assets.append(asset.to_dict())

    return blocks, units, assets
