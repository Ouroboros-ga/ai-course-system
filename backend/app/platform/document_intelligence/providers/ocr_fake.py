"""OCR provider — capability contract and fake implementation.

This module defines the OCR provider capability contract.  Real OCR
integration (PaddleOCR, Tesseract, etc.) requires separate dependency
and hardware approval and cannot be installed during R2D1.

The fake OCR provider simulates OCR output for offline testing,
returning structured text detection and recognition results for
image-based pages.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..registry import (
    ParserCapabilities,
    ParserOutput,
    ParseTimeoutError,
    ParseUnavailableError,
)
from ..planner import ParsePlan
from ..source_artifact import SourceArtifact


# ---------------------------------------------------------------------------
# Check real OCR availability
# ---------------------------------------------------------------------------

try:
    import paddleocr  # noqa: F401
    HAS_PADDLE_OCR = False  # PaddleOCR needs separate hardware/dep approval
except ImportError:
    HAS_PADDLE_OCR = False


# ---------------------------------------------------------------------------
# Fake OCR provider
# ---------------------------------------------------------------------------


class OcrFakeProvider:
    """Fake OCR provider for offline testing.

    Simulates OCR text detection and recognition on image-based pages.
    Returns deterministic fake results — does NOT perform real OCR.

    Use this for:
    - Contract tests
    - Offline development
    - Pipeline integration testing

    Do NOT use for real OCR quality measurement.
    """

    name = "ocr-fake"
    version = "1.0.0-fake"
    capabilities = ParserCapabilities(
        supported_formats=("image", "pdf", "pptx"),
        supports_ocr=True,
        supports_coordinates=True,
        max_file_size_bytes=100 * 1024 * 1024,
        max_pages=100,
    )

    def __init__(self) -> None:
        self._real_available = HAS_PADDLE_OCR

    async def parse(
        self,
        source: SourceArtifact,
        plan: ParsePlan,
    ) -> ParserOutput:
        """Run fake OCR on a source artifact.

        Args:
            source: The source artifact (typically an image or image-heavy doc).
            plan: The parse plan (may specify target pages in enrichment config).

        Returns:
            Fake ParserOutput with OCR text blocks.

        Raises:
            ParseTimeoutError: If timeout exceeded.
        """
        timeout_ms = 300000
        if plan.steps:
            for step in plan.steps:
                if step.provider_name == self.name:
                    timeout_ms = step.timeout_ms

        start = time.perf_counter()

        # Determine which pages to process
        target_pages: List[int] = []
        for step in plan.steps:
            if step.provider_name == self.name:
                target_pages = step.config.get("pages", [1])
                break
        if not target_pages:
            target_pages = [1]

        # Simulate OCR processing delay
        import asyncio
        delay = min(len(target_pages) * 0.1, 1.0)
        await asyncio.sleep(delay)

        elapsed = (time.perf_counter() - start) * 1000
        if elapsed > timeout_ms:
            raise ParseTimeoutError(
                f"OCR fake parsing timed out after {timeout_ms}ms"
            )

        # Generate fake OCR page data
        pages: List[Dict[str, Any]] = []
        for page_no in target_pages:
            page = self._generate_fake_ocr_page(page_no)
            pages.append(page)

        return ParserOutput(
            provider=self.name,
            provider_version=self.version,
            pages=tuple(pages),
            metadata={
                "page_count": len(target_pages),
                "duration_ms": int(elapsed),
                "is_fake": True,
                "target_pages": target_pages,
            },
            warnings=["Using fake OCR provider — results are not real OCR output"],
        )

    def _generate_fake_ocr_page(self, page_no: int) -> Dict[str, Any]:
        """Generate a single page of fake OCR output."""
        return {
            "page_no": page_no,
            "width": 1.0,
            "height": 1.0,
            "coordinate_unit": "normalized",
            "text_blocks": [
                {
                    "bbox": [0.1, 0.1, 0.9, 0.2],
                    "text": f"Fake OCR detected text line 1 on page {page_no}",
                    "confidence": 0.85,
                },
                {
                    "bbox": [0.1, 0.3, 0.8, 0.4],
                    "text": f"Fake OCR detected text line 2 on page {page_no}",
                    "confidence": 0.92,
                },
            ],
            "tables": [],
            "formulas": [],
        }


# ---------------------------------------------------------------------------
# Real OCR provider (capability contract only)
# ---------------------------------------------------------------------------


class OcrProvider:
    """OCR provider — capability contract.

    This class defines the contract for a real OCR integration (PaddleOCR
    or alternative).  It is NOT implemented — it raises
    ``ParseUnavailableError`` until dependency and hardware approval is
    obtained.

    To activate:
    1. Get dependency + hardware approval for PaddleOCR (or alternative).
    2. Install paddleocr and its dependencies in the target environment.
    3. Implement the real ``parse`` method.
    4. Register ``OcrProvider`` instead of ``OcrFakeProvider``.
    """

    name = "paddleocr"
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supported_formats=("image", "pdf", "pptx"),
        supports_ocr=True,
        supports_tables=True,
        supports_formulas=True,
        supports_coordinates=True,
        requires_gpu=True,
        max_file_size_bytes=50 * 1024 * 1024,
        max_pages=50,
    )

    def __init__(self) -> None:
        self._available = HAS_PADDLE_OCR

    async def parse(
        self,
        source: SourceArtifact,
        plan: ParsePlan,
    ) -> ParserOutput:
        """Run OCR on a source artifact.

        Raises:
            ParseUnavailableError: Always — real OCR needs separate approval.
        """
        if not self._available:
            raise ParseUnavailableError(
                "Real OCR provider (PaddleOCR) is not available. "
                "PaddleOCR requires separate dependency and hardware approval. "
                "Use OcrFakeProvider for offline testing."
            )

        raise ParseUnavailableError(
            "Real OCR parse is not yet implemented. "
            "Use OcrFakeProvider for testing."
        )
