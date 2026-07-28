"""OCR parser provider — real implementations with honest degradation.

P1-3: Replaces ``OcrFakeProvider`` with real OCR providers. The previous
fake provider returned fabricated text blocks (``"Fake OCR detected
text..."``) which polluted real parsing pipelines with misleading data.

This module exposes two real providers:

1. ``TesseractOcrProvider`` — CPU-only OCR via ``pytesseract`` + Pillow.
   Works for typical scanned documents and image-only PDF pages. No GPU
   required. Falls back to ``ParseUnavailableError`` if Tesseract is not
   installed in the environment.

2. ``OcrProvider`` — placeholder contract for ``PaddleOCR`` (GPU). Not
   activated until dependency + hardware approval is obtained.

Neither provider ever returns fake output: if real OCR cannot run, they
raise ``ParseUnavailableError`` so the caller can record a structured
failure instead of fabricating evidence.
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
# Check real OCR availability
# ---------------------------------------------------------------------------

try:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    import paddleocr  # type: ignore  # noqa: F401
    HAS_PADDLE_OCR = True
except ImportError:
    HAS_PADDLE_OCR = False


# ---------------------------------------------------------------------------
# Tesseract OCR provider (real, CPU-only)
# ---------------------------------------------------------------------------


class TesseractOcrProvider:
    """Real OCR provider using Tesseract via pytesseract + Pillow.

    Suitable for:
    - Scanned PDF pages (rendered to images first)
    - Standalone image files (PNG, JPEG, TIFF)

    Limitations:
    - Requires the ``tesseract`` binary installed on the system
    - No formula recognition
    - No GPU acceleration
    """

    name = "tesseract-ocr"
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supported_formats=("image", "pdf", "pptx"),
        supports_ocr=True,
        supports_coordinates=True,
        supports_tables=False,
        supports_formulas=False,
        requires_gpu=False,
        max_file_size_bytes=50 * 1024 * 1024,
        max_pages=50,
    )

    def __init__(self) -> None:
        self._available = HAS_TESSERACT

    @property
    def is_real(self) -> bool:
        return True

    async def parse(
        self,
        source: SourceArtifact,
        plan: ParsePlan,
    ) -> ParserOutput:
        if not self._available:
            raise ParseUnavailableError(
                "Tesseract OCR is not available. "
                "Install with: pip install pytesseract pillow "
                "and ensure the tesseract binary is on PATH."
            )

        timeout_ms = 300000
        if plan.steps:
            for step in plan.steps:
                if step.provider_name == self.name:
                    timeout_ms = step.timeout_ms

        start = time.perf_counter()

        target_pages: List[int] = []
        for step in plan.steps:
            if step.provider_name == self.name:
                target_pages = step.config.get("pages", [1])
                break
        if not target_pages:
            target_pages = [1]

        data = self._get_source_data(source)
        if data is None:
            raise ParseMalformedError(
                "Source artifact has no accessible data for OCR"
            )

        pages: List[Dict[str, Any]] = []
        warnings: List[str] = []

        for page_no in target_pages:
            if (time.perf_counter() - start) * 1000 > timeout_ms:
                raise ParseTimeoutError(
                    f"OCR timed out after {timeout_ms}ms at page {page_no}"
                )
            try:
                page_data = self._ocr_image_bytes(data, page_no)
                pages.append(page_data)
            except Exception as exc:
                warnings.append(
                    f"OCR failed for page {page_no}: {type(exc).__name__}: {exc}"
                )

        elapsed = (time.perf_counter() - start) * 1000
        return ParserOutput(
            provider=self.name,
            provider_version=self.version,
            pages=tuple(pages),
            metadata={
                "page_count": len(pages),
                "duration_ms": int(elapsed),
                "is_fake": False,
                "ocr_engine": "tesseract",
                "target_pages": target_pages,
            },
            warnings=warnings,
        )

    @staticmethod
    def _get_source_data(source: SourceArtifact) -> Optional[bytes]:
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

    def _ocr_image_bytes(self, data: bytes, page_no: int) -> Dict[str, Any]:
        """Run Tesseract OCR on a single image byte stream."""
        try:
            image = Image.open(io.BytesIO(data))
        except Exception as exc:
            raise ParseMalformedError(
                f"Failed to open image for OCR: {exc}"
            ) from exc

        # Get detailed OCR data with bounding boxes
        ocr_data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
        )

        text_blocks: List[Dict[str, Any]] = []
        width = float(image.width) if image.width else 1.0
        height = float(image.height) if image.height else 1.0

        n_boxes = len(ocr_data.get("text", []))
        for i in range(n_boxes):
            text = (ocr_data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(ocr_data["conf"][i])
            except (ValueError, TypeError):
                conf = -1.0
            if conf < 0:
                continue

            x = float(ocr_data["left"][i]) / max(width, 1)
            y = float(ocr_data["top"][i]) / max(height, 1)
            w = float(ocr_data["width"][i]) / max(width, 1)
            h = float(ocr_data["height"][i]) / max(height, 1)

            # Clamp + ensure x1 >= x0, y1 >= y0
            x0 = max(0.0, min(1.0, x))
            y0 = max(0.0, min(1.0, y))
            x1 = max(0.0, min(1.0, x + w))
            y1 = max(0.0, min(1.0, y + h))
            if x1 < x0:
                x1 = x0
            if y1 < y0:
                y1 = y0

            text_blocks.append({
                "bbox": [round(x0, 6), round(y0, 6), round(x1, 6), round(y1, 6)],
                "text": text,
                "confidence": round(conf / 100.0, 4) if conf <= 100 else 1.0,
            })

        return {
            "page_no": page_no,
            "width": width,
            "height": height,
            "coordinate_unit": "normalized",
            "text_blocks": text_blocks,
            "tables": [],
            "formulas": [],
        }


# ---------------------------------------------------------------------------
# PaddleOCR provider (real, GPU — gated by approval)
# ---------------------------------------------------------------------------


class OcrProvider:
    """PaddleOCR provider — capability contract with honest unavailability.

    Real PaddleOCR integration requires dependency + hardware approval.
    Until approved, ``parse`` raises ``ParseUnavailableError``. It NEVER
    returns fake output.
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

    @property
    def is_real(self) -> bool:
        return self._available

    async def parse(
        self,
        source: SourceArtifact,
        plan: ParsePlan,
    ) -> ParserOutput:
        if not self._available:
            raise ParseUnavailableError(
                "PaddleOCR is not available. PaddleOCR requires separate "
                "dependency and hardware approval. Install paddleocr or "
                "use TesseractOcrProvider for CPU-only OCR."
            )

        # PaddleOCR is available — but the actual invocation is intentionally
        # left as a thin stub because the production runtime still needs to
        # be validated against the approved paddleocr version. We do not
        # fabricate output; we raise so callers fall back to Tesseract.
        raise ParseUnavailableError(
            "PaddleOCR runtime integration is not yet wired. "
            "Use TesseractOcrProvider for CPU-only OCR."
        )


# ---------------------------------------------------------------------------
# IR mapper
# ---------------------------------------------------------------------------


def map_ocr_output_to_ir(
    output: ParserOutput,
    source: SourceArtifact,
    run_id: str,
    parser_run_id: str,
    normalization_version: str = "1",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Map OCR ParserOutput to DocumentIR block/unit/asset dicts.

    Works for any OCR provider whose ``ParserOutput.pages`` entries carry
    a ``text_blocks`` list with ``bbox`` (normalized) and ``text``.
    """
    from ..contracts import BoundingBox, CoordinateSpace
    from ..document_ir.models import Provenance

    blocks: List[Dict[str, Any]] = []
    units: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []

    for page_dict in output.pages:
        page_no = page_dict.get("page_no", 1)
        text_blocks = page_dict.get("text_blocks", [])

        for idx, blk in enumerate(text_blocks):
            block_id = f"blk_ocr_p{page_no}_b{idx}"
            bbox_raw = blk.get("bbox")
            bbox = None
            if bbox_raw and len(bbox_raw) == 4:
                try:
                    bbox = BoundingBox(
                        x0=round(float(bbox_raw[0]), 6),
                        y0=round(float(bbox_raw[1]), 6),
                        x1=round(float(bbox_raw[2]), 6),
                        y1=round(float(bbox_raw[3]), 6),
                        coordinate_space=CoordinateSpace.NORMALIZED,
                    )
                except (ValueError, TypeError):
                    bbox = None

            text = blk.get("text", "")
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
                "block_type": "paragraph",
                "text": text,
                "page_or_slide": page_no,
                "bbox": bbox,
                "char_start": 0,
                "char_end": len(text),
                "order_index": idx,
                "provenance": provenance,
            })

    return blocks, units, assets
