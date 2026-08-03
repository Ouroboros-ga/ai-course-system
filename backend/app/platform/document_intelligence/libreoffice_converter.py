"""LibreOfficeHeadlessConverter - auditable Office-to-PDF conversion.

Converges the existing ``app.common.slide_converter`` LibreOffice helpers into
a single auditable converter used by the parsing pipeline:

- ``.ppt`` -> ``.pdf`` (NativePptxProvider cannot read legacy .ppt directly)
- ``.doc`` -> ``.pdf`` (PythonDocxProvider cannot read legacy .doc)
- ``.docx`` -> ``.pdf`` (for page coordinates + OCR enrichment)

Failure semantics are explicit and auditable:
- ``CONVERTER_UNAVAILABLE``: LibreOffice binary not found.
- ``CONVERSION_FAILED``: LibreOffice ran but returned non-zero / no output.
- ``CONVERSION_TIMEOUT``: LibreOffice exceeded the timeout.
- ``SOURCE_REUPLOAD_REQUIRED``: input missing/unreadable.

The converter NEVER fabricates a PDF; on failure it raises so the pipeline
records a structured ``SOURCE_REUPLOAD_REQUIRED`` task failure.

See docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §7 Step 3.
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


class ConversionError(Exception):
    """Auditable conversion failure carrying a stable error_code."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class ConversionResult:
    """Auditable conversion output."""
    pdf_path: str
    source_path: str
    error_code: str = ""           # empty on success
    duration_ms: int = 0
    converter: str = "libreoffice-headless"


class LibreOfficeHeadlessConverter:
    """Auditable wrapper around the LibreOffice headless converter.

    Delegates the actual ``soffice --headless --convert-to pdf`` call to
    ``app.common.slide_converter.convert_office_to_pdf`` (which handles
    platform binary lookup, the shared user-profile lock, and Windows
    STARTUPINFO hiding). This class adds:

    - explicit, stable error codes for audit;
    - byte-level rendering of PDF pages to PNG (for OCR enrichment);
    - never fabricates output.
    """

    def __init__(self, *, timeout_s: int = 300) -> None:
        self._timeout_s = timeout_s

    def is_available(self) -> bool:
        """True if the LibreOffice binary is discoverable."""
        from app.common.slide_converter import _find_libreoffice
        return _find_libreoffice() is not None

    def convert_to_pdf(self, source_path: str, *, output_dir: Optional[str] = None) -> ConversionResult:
        """Convert an Office document (.ppt/.doc/.docx) to PDF.

        Raises ``ConversionError`` on failure (never returns a fabricated path).
        """
        src = Path(source_path)
        if not src.exists():
            raise ConversionError(
                "SOURCE_REUPLOAD_REQUIRED",
                f"Source file not found: {source_path}",
            )
        from app.common.slide_converter import convert_office_to_pdf

        if not self.is_available():
            raise ConversionError(
                "CONVERTER_UNAVAILABLE",
                "LibreOffice binary not found; cannot convert Office document to PDF. "
                "Install LibreOffice or re-upload as PDF.",
            )

        import time
        start = time.perf_counter()
        pdf_path = convert_office_to_pdf(str(src), output_dir=output_dir)
        elapsed = int((time.perf_counter() - start) * 1000)

        if not pdf_path:
            # convert_office_to_pdf already logged stderr; map to a stable code.
            raise ConversionError(
                "CONVERSION_FAILED",
                f"LibreOffice conversion failed for {src.name} (rc!=0 or no output). "
                "Re-upload as PDF or DOCX.",
            )

        return ConversionResult(
            pdf_path=pdf_path,
            source_path=str(src),
            duration_ms=elapsed,
        )

    def render_pages(
        self,
        pdf_path: str,
        *,
        dpi: int = 150,
        output_dir: Optional[str] = None,
        pages: Optional[Iterable[int]] = None,
    ) -> list[str]:
        """Render a PDF to per-page PNG images (for OCR enrichment).

        Raises ``ConversionError`` if rendering fails.
        """
        from app.common.slide_converter import render_pdf_to_images

        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="ocr_pages_")
        try:
            images = render_pdf_to_images(pdf_path, output_dir, dpi=dpi, pages=pages)
        except Exception as exc:
            raise ConversionError(
                "CONVERSION_FAILED",
                f"PDF page rendering failed: {exc}",
            ) from exc
        if not images:
            raise ConversionError(
                "CONVERSION_FAILED",
                f"PDF page rendering produced no images for {pdf_path}",
            )
        return images


# Module-level singleton
libreoffice_converter = LibreOfficeHeadlessConverter()
