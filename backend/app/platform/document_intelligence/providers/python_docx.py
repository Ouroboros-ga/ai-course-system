"""PythonDocx parser provider.

Wraps ``python-docx`` to extract paragraphs, headings, and tables, producing
a ``ParserOutput`` compatible with the DocumentIR mapper.

This provider extracts the semantic structure (paragraphs, headings, tables)
but does NOT produce page coordinates on its own -- DOCX has no inherent
pagination. For page coordinates + OCR of embedded images, the pipeline
converts the DOCX to PDF via ``LibreOfficeHeadlessConverter`` and runs the
PDF + PaddleOCR chain (see planner._plan_docx).

If python-docx is not installed, ``parse`` raises ``ParseUnavailableError``;
it never fabricates output.

See docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §7 Step 3.
"""
from __future__ import annotations

import io
import time
from typing import Any, Dict, List, Tuple

from ..registry import (
    ParserCapabilities,
    ParserOutput,
    ParseUnavailableError,
)
from ..planner import ParsePlan
from ..source_artifact import SourceArtifact

try:
    import docx as _docx  # python-docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False
    _docx = None  # type: ignore


class PythonDocxProvider:
    """Parser provider for DOCX files using python-docx."""

    name = "python-docx"
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supported_formats=("docx",),
        supports_tables=True,
        supports_ocr=False,
        supports_notes=False,
        supports_reading_order=True,
        supports_heading_detection=True,
        supports_visual_assets=False,
        supports_coordinates=False,
        requires_gpu=False,
        max_file_size_bytes=50 * 1024 * 1024,
        max_pages=500,
    )

    def __init__(self) -> None:
        self._available = HAS_DOCX

    @property
    def is_real(self) -> bool:
        return True

    async def parse(self, source: SourceArtifact, plan: ParsePlan) -> ParserOutput:
        if not self._available:
            raise ParseUnavailableError(
                "python-docx is not available. Install with: pip install python-docx"
            )
        start = time.perf_counter()

        data = self._get_source_data(source)
        if data is None:
            raise ParseUnavailableError(
                "Source artifact has no accessible data for DOCX parsing"
            )

        try:
            document = _docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise ParseUnavailableError(
                f"python-docx failed to open document: {exc}"
            ) from exc

        pages: List[Dict[str, Any]] = []
        # DOCX has no native pagination; emit a single "page" of semantic blocks
        # so the IR mapper produces ordered text blocks. Page coordinates come
        # from the PDF conversion in the pipeline (Step 3 combo chain).
        text_blocks: List[Dict[str, Any]] = []
        order = 0
        for para in document.paragraphs:
            text = (para.text or "").strip()
            if not text:
                continue
            style_name = (para.style.name or "").lower() if para.style else ""
            if "heading" in style_name or "title" in style_name:
                kind = "heading"
                heading_level = next((int(ch) for ch in style_name if ch.isdigit()), 1)
            else:
                kind = "text"
                heading_level = None
            text_blocks.append({
                "text": text,
                "bbox": None,           # DOCX has no page coordinates
                "confidence": 1.0,
                "kind": kind,
                "heading_level": heading_level,
                "style_hints": {"style_name": style_name},
                "order_index": order,
            })
            order += 1

        # Tables: flatten cells as text blocks
        table_count = 0
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    text = (cell.text or "").strip()
                    if text:
                        text_blocks.append({
                            "text": text,
                            "bbox": None,
                            "confidence": 1.0,
                            "kind": "table_cell",
                            "order_index": order,
                        })
                        order += 1
            table_count += 1

        pages.append({
            "page_no": 1,
            "slide_index": 1,
            "text_blocks": text_blocks,
            "tables": [],
            "formulas": [],
            "width": 1.0,
            "height": 1.0,
            "coordinate_unit": "none",
        })

        elapsed = (time.perf_counter() - start) * 1000
        return ParserOutput(
            provider=self.name,
            provider_version=self.version,
            pages=tuple(pages),
            metadata={
                "page_count": 1,
                "duration_ms": int(elapsed),
                "is_fake": False,
                "docx_engine": "python-docx",
                "paragraph_count": order,
                "table_count": table_count,
            },
            warnings=[],
        )

    @staticmethod
    def _get_source_data(source: SourceArtifact) -> Any:
        if not source.uri:
            return None
        try:
            from app.services.object_storage import get_object_storage
            return get_object_storage().get(source.uri)
        except FileNotFoundError:
            return None
        except Exception:
            return None


def map_docx_output_to_ir(
    output: ParserOutput,
    source: SourceArtifact,
    run_id: str,
    parser_run_id: str,
    normalization_version: str = "1",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Map python-docx ParserOutput to DocumentIR block dicts.

    Reuses the OCR mapper shape (text_blocks with bbox/text/confidence/kind)
    so the pipeline reconciler treats DOCX blocks uniformly.
    """
    from app.platform.document_intelligence.providers.ocr_provider import map_ocr_output_to_ir
    return map_ocr_output_to_ir(output, source, run_id, parser_run_id, normalization_version)
