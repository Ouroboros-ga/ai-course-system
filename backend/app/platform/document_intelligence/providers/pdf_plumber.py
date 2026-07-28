"""Real PDF parser provider based on pdfplumber.

P1-3: Replaces DoclingFakeProvider for PDF parsing with a real CPU-only
implementation. Extracts text, tables, and page metadata from PDF files
using pdfplumber (no GPU required, no external service calls).

Capabilities:
- Text extraction with page-level granularity
- Table detection (rows/columns)
- Page coordinates (normalized)
- Reading order (top-to-bottom, left-to-right)

Limitations (explicitly declared):
- No OCR (scanned PDFs need OcrProvider)
- No formula recognition
- No image extraction
"""
from __future__ import annotations

import io
import time
from typing import Any, Dict, List, Optional, Tuple

from ..registry import (
    ParserCapabilities,
    ParserOutput,
    ParseTimeoutError,
    ParseUnavailableError,
    ParseMalformedError,
)
from ..planner import ParsePlan
from ..source_artifact import SourceArtifact


# ---------------------------------------------------------------------------
# Check pdfplumber availability
# ---------------------------------------------------------------------------

try:
    import pdfplumber  # type: ignore
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


# ---------------------------------------------------------------------------
# Real PDF parser provider
# ---------------------------------------------------------------------------


class PdfPlumberProvider:
    """Real PDF parser provider using pdfplumber.

    This provider performs actual PDF text and table extraction. It does
    NOT perform OCR — for scanned PDFs, use OcrProvider after this one.

    The provider is CPU-only and has no external service dependencies,
    making it suitable for production use without GPU or network access.
    """

    name = "pdf-plumber"
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supported_formats=("pdf",),
        supports_tables=True,
        supports_reading_order=True,
        supports_heading_detection=True,
        supports_coordinates=True,
        supports_provenance=True,
        max_file_size_bytes=200 * 1024 * 1024,
        max_pages=500,
    )

    def __init__(self) -> None:
        self._available = HAS_PDFPLUMBER

    @property
    def is_real(self) -> bool:
        """Return True — this is a real provider, not a fake."""
        return True

    async def parse(
        self,
        source: SourceArtifact,
        plan: ParsePlan,
    ) -> ParserOutput:
        """Parse a PDF source artifact using pdfplumber.

        Args:
            source: The source artifact (must be PDF format).
            plan: The parse plan with configuration.

        Returns:
            ParserOutput with page-level text and table data.

        Raises:
            ParseUnavailableError: If pdfplumber is not installed.
            ParseMalformedError: If the file cannot be opened as a PDF.
            ParseTimeoutError: If parsing exceeds the configured timeout.
        """
        if not self._available:
            raise ParseUnavailableError(
                "pdfplumber is not installed. "
                "Install with: pip install pdfplumber"
            )

        timeout_ms = 180000  # 3 minutes default
        if plan.steps:
            primary = plan.primary_step
            if primary:
                timeout_ms = primary.timeout_ms

        start = time.perf_counter()

        data = self._get_source_data(source)
        if data is None:
            raise ParseMalformedError(
                "Source artifact has no accessible data"
            )

        try:
            pdf = pdfplumber.open(io.BytesIO(data))
        except Exception as exc:
            raise ParseMalformedError(
                f"Failed to open PDF: {exc}"
            ) from exc

        pages: List[Dict[str, Any]] = []
        warnings: List[str] = []

        try:
            for page_no, page in enumerate(pdf.pages, start=1):
                if (time.perf_counter() - start) * 1000 > timeout_ms:
                    raise ParseTimeoutError(
                        f"PDF parsing timed out after {timeout_ms}ms "
                        f"at page {page_no}/{len(pdf.pages)}"
                    )

                page_data = self._extract_page(page, page_no)
                pages.append(page_data)

                if not (page.width and page.height):
                    warnings.append(f"page {page_no} has no dimensions")
        finally:
            pdf.close()

        elapsed = (time.perf_counter() - start) * 1000
        return ParserOutput(
            provider=self.name,
            provider_version=self.version,
            pages=tuple(pages),
            metadata={
                "page_count": len(pages),
                "duration_ms": int(elapsed),
                "is_fake": False,
                "parser": "pdfplumber",
            },
            warnings=warnings,
        )

    @staticmethod
    def _get_source_data(source: SourceArtifact) -> Optional[bytes]:
        """从 SourceArtifact 读取源数据。

        通过 source.uri（即 object_key）从对象存储读取文件内容。
        若 uri 为空，回退到 None（测试场景可由调用方直接注入数据）。
        """
        if source.data is not None:
            return source.data
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

    def _extract_page(self, page: Any, page_no: int) -> Dict[str, Any]:
        """Extract text and tables from a single pdfplumber page."""
        width = float(page.width) if page.width else 1.0
        height = float(page.height) if page.height else 1.0

        text_blocks: List[Dict[str, Any]] = []
        tables: List[Dict[str, Any]] = []

        # Extract visual words, then resolve reading order separately.  The
        # PDF text stream is often wrong for multi-column course material.
        try:
            words = page.extract_words(
                use_text_flow=False,
                keep_blank_chars=False,
                extra_attrs=["size", "fontname"],
            )
        except Exception:
            words = []

        if words:
            for line_words in self._resolve_lines(words, width=width, height=height):
                text = " ".join(str(w.get("text", "")) for w in line_words).strip()
                if not text:
                    continue

                # Compute bbox from word positions (normalized)
                x0 = min(float(w.get("x0", 0)) for w in line_words) / max(width, 1)
                y0 = min(float(w.get("top", 0)) for w in line_words) / max(height, 1)
                x1 = max(float(w.get("x1", 0)) for w in line_words) / max(width, 1)
                y1 = max(float(w.get("bottom", 0)) for w in line_words) / max(height, 1)

                # Clamp to [0, 1] to satisfy BoundingBox NORMALIZED constraint
                x0 = max(0.0, min(1.0, x0))
                y0 = max(0.0, min(1.0, y0))
                x1 = max(0.0, min(1.0, x1))
                y1 = max(0.0, min(1.0, y1))
                if x1 < x0:
                    x1 = x0
                if y1 < y0:
                    y1 = y0

                # Detect heading by font size
                avg_size = sum(float(w.get("size", 12)) for w in line_words) / len(line_words)
                is_heading = avg_size >= 16

                text_blocks.append({
                    "bbox": [round(x0, 6), round(y0, 6), round(x1, 6), round(y1, 6)],
                    "text": text,
                    "confidence": 1.0,  # pdfplumber extracts real text
                "is_heading": is_heading,
                    "heading_level": 1 if is_heading else None,
                    "font_size": avg_size,
                })

        # Extract tables with their detected geometry. ``extract_tables`` only
        # returns strings, so prefer the Table objects when this pdfplumber
        # version exposes them. Coordinates let evidence cite the actual table
        # rather than a flattened tab-delimited surrogate.
        try:
            raw_tables = page.find_tables()
            for table in raw_tables:
                extracted = table.extract()
                if not extracted:
                    continue
                rows = len(extracted)
                cols = max(len(row) for row in extracted) if extracted else 0
                cells = tuple(
                    tuple(str(cell) if cell is not None else "" for cell in row)
                    for row in extracted
                )
                x0, top, x1, bottom = table.bbox
                table_bbox = [
                    round(max(0.0, min(1.0, x0 / width)), 6),
                    round(max(0.0, min(1.0, top / height)), 6),
                    round(max(0.0, min(1.0, x1 / width)), 6),
                    round(max(0.0, min(1.0, bottom / height)), 6),
                ]
                row_cells = getattr(table, "rows", ())
                cell_bboxes = []
                for row in row_cells:
                    cell_bboxes.append([
                        ([
                            round(max(0.0, min(1.0, cell[0] / width)), 6),
                            round(max(0.0, min(1.0, cell[1] / height)), 6),
                            round(max(0.0, min(1.0, cell[2] / width)), 6),
                            round(max(0.0, min(1.0, cell[3] / height)), 6),
                        ] if cell is not None else None)
                        for cell in row.cells
                    ])
                tables.append({
                    "rows": rows,
                    "columns": cols,
                    "cells": cells,
                    "bbox": table_bbox,
                    "cell_bboxes": cell_bboxes,
                })
        except Exception:
            # Older pdfplumber releases do not expose Table geometry. Retain
            # text and mark the missing structure explicitly for review.
            try:
                for raw_table in page.extract_tables():
                    if not raw_table:
                        continue
                    tables.append({
                        "rows": len(raw_table),
                        "columns": max(len(row) for row in raw_table),
                        "cells": tuple(
                            tuple(str(cell) if cell is not None else "" for cell in row)
                            for row in raw_table
                        ),
                        "structure_unresolved": True,
                    })
            except Exception:
                pass

        return {
            "page_no": page_no,
            "width": width,
            "height": height,
            "coordinate_unit": "pixel",
            "text_blocks": text_blocks,
            "tables": tables,
            "formulas": [],
        }

    @staticmethod
    def _resolve_lines(words: List[Dict[str, Any]], *, width: float, height: float) -> List[List[Dict[str, Any]]]:
        """Group visually aligned words and read columns left-to-right.

        This deliberately avoids fixed pixel buckets.  It uses each word's
        vertical overlap and font-size-derived tolerance, then detects a
        durable horizontal whitespace gap as a column separator.
        """
        ordered = sorted(words, key=lambda word: (float(word.get("top", 0)), float(word.get("x0", 0))))
        lines: List[List[Dict[str, Any]]] = []
        for word in ordered:
            top, bottom = float(word.get("top", 0)), float(word.get("bottom", 0))
            size = max(float(word.get("size", 10) or 10), 1.0)
            target = None
            for line in reversed(lines):
                first = line[0]
                line_top, line_bottom = float(first.get("top", 0)), float(first.get("bottom", 0))
                overlap = max(0.0, min(bottom, line_bottom) - max(top, line_top))
                minimum_height = max(min(bottom - top, line_bottom - line_top), 1.0)
                baseline_gap = abs(top - line_top)
                if overlap / minimum_height >= 0.60 or baseline_gap <= max(size * 0.45, 1.5):
                    target = line
                    break
            if target is None:
                lines.append([word])
            else:
                target.append(word)
        for line in lines:
            line.sort(key=lambda word: float(word.get("x0", 0)))

        line_boxes = [
            (min(float(word.get("x0", 0)) for word in line), max(float(word.get("x1", 0)) for word in line), line)
            for line in lines
        ]
        # A gap spanning most lines indicates a column boundary.  The resolver
        # intentionally handles the common two-column case conservatively.
        candidates: List[float] = []
        for left, right, _line in line_boxes:
            candidates.extend((left, right))
        split = None
        if candidates:
            midpoint = width / 2.0
            near_mid = sorted(candidates, key=lambda value: abs(value - midpoint))[:4]
            for boundary in near_mid:
                left_lines = sum(1 for left, right, _ in line_boxes if right <= boundary)
                right_lines = sum(1 for left, right, _ in line_boxes if left >= boundary)
                if left_lines >= 2 and right_lines >= 2:
                    split = boundary
                    break
        if split is None:
            return [line for _, _, line in sorted(line_boxes, key=lambda item: (float(item[2][0].get("top", 0)), item[0]))]
        left_column = [item for item in line_boxes if item[1] <= split]
        right_column = [item for item in line_boxes if item[0] >= split]
        spanning = [item for item in line_boxes if item not in left_column and item not in right_column]
        key = lambda item: float(item[2][0].get("top", 0))
        return [line for _, _, line in sorted(spanning, key=key) + sorted(left_column, key=key) + sorted(right_column, key=key)]


# ---------------------------------------------------------------------------
# IR mapper
# ---------------------------------------------------------------------------


def map_pdf_plumber_output_to_ir(
    output: ParserOutput,
    source: SourceArtifact,
    run_id: str,
    parser_run_id: str,
    normalization_version: str = "1",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Map pdfplumber ParserOutput to DocumentIR block/unit/asset dicts.

    Returns:
        Tuple of (blocks, units, assets) as dicts ready for DocumentIR
        construction. The blocks list carries keys consumed by
        ``document_parse_pipeline.run_parse_pipeline``:
        ``block_type``, ``text``, ``page_or_slide``, ``bbox``.
    """
    from ..contracts import BoundingBox, CoordinateSpace
    from ..document_ir.models import (
        ParseWarning, Provenance, TableBlock, TableCell, WarningSeverity,
    )

    blocks: List[Dict[str, Any]] = []
    units: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []

    for page_dict in output.pages:
        page_no = page_dict["page_no"]

        text_blocks = page_dict.get("text_blocks", [])
        for idx, blk in enumerate(text_blocks):
            block_id = f"blk_pdf_p{page_no}_b{idx}"
            bbox_raw = blk.get("bbox")
            bbox = None
            if bbox_raw and len(bbox_raw) == 4:
                try:
                    bbox = BoundingBox(
                        x0=round(bbox_raw[0], 6),
                        y0=round(bbox_raw[1], 6),
                        x1=round(bbox_raw[2], 6),
                        y1=round(bbox_raw[3], 6),
                        coordinate_space=CoordinateSpace.NORMALIZED,
                    )
                except ValueError:
                    bbox = None

            text = blk.get("text", "")
            is_heading = blk.get("is_heading", False)
            block_type = "heading" if is_heading else "paragraph"

            provenance = Provenance(
                artifact_id=source.artifact_id,
                run_id=run_id,
                parser_run_id=parser_run_id,
                provider=output.provider,
                raw_locator=f"pages/{page_no}/blocks/{idx}",
                page_or_slide=page_no,
                bbox=bbox,
                confidence=blk.get("confidence"),
            )

            blocks.append({
                "block_id": block_id,
                "block_type": block_type,
                "text": text,
                "page_or_slide": page_no,
                "bbox": bbox,
                "char_start": 0,
                "char_end": len(text),
                "order_index": idx,
                "provenance": provenance,
            })

        # Tables as block entries
        tables = page_dict.get("tables", [])
        for tidx, tbl in enumerate(tables):
            cells = tbl.get("cells", [])
            table_text = "\n".join("\t".join(row) for row in cells)
            if not table_text.strip():
                continue
            block_id = f"blk_pdf_p{page_no}_t{tidx}"
            bbox_raw = tbl.get("bbox")
            bbox = None
            if bbox_raw and len(bbox_raw) == 4:
                try:
                    bbox = BoundingBox(
                        x0=round(bbox_raw[0], 6), y0=round(bbox_raw[1], 6),
                        x1=round(bbox_raw[2], 6), y1=round(bbox_raw[3], 6),
                        coordinate_space=CoordinateSpace.NORMALIZED,
                    )
                except ValueError:
                    bbox = None
            cell_bboxes = tbl.get("cell_bboxes") or []
            structured_cells = []
            for row_index, row in enumerate(cells):
                for col_index, cell_text in enumerate(row):
                    raw_cell_bbox = (
                        cell_bboxes[row_index][col_index]
                        if row_index < len(cell_bboxes)
                        and col_index < len(cell_bboxes[row_index])
                        else None
                    )
                    try:
                        cell_bbox = BoundingBox(
                            x0=raw_cell_bbox[0], y0=raw_cell_bbox[1],
                            x1=raw_cell_bbox[2], y1=raw_cell_bbox[3],
                            coordinate_space=CoordinateSpace.NORMALIZED,
                        ) if raw_cell_bbox else None
                    except ValueError:
                        cell_bbox = None
                    structured_cells.append(TableCell(
                        row=row_index, col=col_index, text=cell_text,
                        bbox=cell_bbox, header=row_index == 0,
                    ))
            warnings = ()
            if tbl.get("structure_unresolved") or bbox is None:
                warnings = (ParseWarning(
                    code="TABLE_STRUCTURE_UNRESOLVED",
                    severity=WarningSeverity.WARNING,
                    message="PDF table cells were extracted without reliable geometry",
                    run_id=run_id,
                ),)
            provenance = Provenance(
                artifact_id=source.artifact_id,
                run_id=run_id,
                parser_run_id=parser_run_id,
                provider=output.provider,
                raw_locator=f"pages/{page_no}/tables/{tidx}",
                page_or_slide=page_no,
                bbox=bbox,
                confidence=1.0,
            )
            blocks.append(TableBlock(
                block_id=block_id,
                page_or_slide=page_no,
                bbox=bbox,
                reading_order=len(text_blocks) + tidx,
                rows=tbl.get("rows"),
                columns=tbl.get("columns"),
                cells=tuple(structured_cells),
                text=table_text,
                provider=output.provider,
                provenance=(provenance,),
                raw_result_ref=f"artifact://{parser_run_id}/raw.json#/pages/{page_no}/tables/{tidx}",
                warnings=warnings,
            ).to_dict())

    return blocks, units, assets
