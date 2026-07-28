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

        # Extract words with positions for reading order
        try:
            words = page.extract_words(
                use_text_flow=True,
                keep_blank_chars=False,
                extra_attrs=["size", "fontname"],
            )
        except Exception:
            words = []

        # Group words into lines by approximate y-coordinate
        if words:
            lines: Dict[float, List[Dict[str, Any]]] = {}
            for w in words:
                # Round y to nearest 3px to group words on same line
                y_key = round(float(w.get("top", 0)) / 3) * 3
                lines.setdefault(y_key, []).append(w)

            for y_key in sorted(lines.keys()):
                line_words = sorted(lines[y_key], key=lambda w: float(w.get("x0", 0)))
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
                    "font_size": avg_size,
                })

        # Extract tables
        try:
            raw_tables = page.extract_tables()
            for tbl in raw_tables:
                if not tbl:
                    continue
                rows = len(tbl)
                cols = max(len(r) for r in tbl) if tbl else 0
                cells = tuple(
                    tuple(str(c) if c is not None else "" for c in row)
                    for row in tbl
                )
                tables.append({
                    "rows": rows,
                    "columns": cols,
                    "cells": cells,
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
    from ..document_ir.models import Provenance

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
            provenance = Provenance(
                artifact_id=source.artifact_id,
                run_id=run_id,
                parser_run_id=parser_run_id,
                provider=output.provider,
                raw_locator=f"pages/{page_no}/tables/{tidx}",
                page_or_slide=page_no,
                confidence=1.0,
            )
            blocks.append({
                "block_id": block_id,
                "block_type": "table",
                "text": table_text,
                "page_or_slide": page_no,
                "bbox": None,
                "char_start": 0,
                "char_end": len(table_text),
                "order_index": len(text_blocks) + tidx,
                "provenance": provenance,
            })

    return blocks, units, assets
