"""DocumentOcrPort - the protocol the main backend uses to call OCR.

PaddleOCR runs in a **standalone service** (deploy/paddleocr/). The main backend
never imports paddleocr; it calls the service over HTTP via ``PaddleOcrHttpAdapter``.

This module defines:
- ``DocumentOcrPort`` (Protocol): the stable interface.
- ``PaddleOcrHttpAdapter``: real HTTP client calling the standalone service.
- ``UnavailableOcrPort``: fail-closed fallback that raises ``OcrUnavailable``
  on every call (used when no OCR backend is configured).

Honest degradation: when the OCR service is unreachable, adapters raise
``OcrUnavailable`` (mapped to error_code ``OCR_SERVICE_UNAVAILABLE`` at the
pipeline level). We NEVER fabricate OCR output.

See docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §6 Step 2.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stable result types (mirrors deploy/paddleocr/service/schemas.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OcrBlock:
    text: str
    bbox: Sequence[float]  # [x0, y0, x1, y1] normalized 0..1
    confidence: float
    kind: str = "text"


@dataclass(frozen=True)
class OcrPageResult:
    page: int
    blocks: List[OcrBlock]


@dataclass(frozen=True)
class OcrResult:
    pages: List[OcrPageResult]
    provider_version: str
    model_hash: str
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OcrUnavailable(Exception):
    """OCR service unavailable or returned an error. Never fabricate output.

    ``error_code`` is stable for the pipeline to map to a task failure:
    - OCR_SERVICE_UNAVAILABLE: service down / 503 / network
    - OCR_FAILED: service up but recognition failed (500)
    - OCR_TIMEOUT: request exceeded timeout
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


# ---------------------------------------------------------------------------
# Port (Protocol)
# ---------------------------------------------------------------------------


@runtime_checkable
class DocumentOcrPort(Protocol):
    """Stable OCR interface consumed by the parsing pipeline."""

    @property
    def is_available(self) -> bool: ...

    def ocr_image(self, image_bytes: bytes, *, lang: str = "ch", page: int = 1) -> OcrResult: ...

    def ocr_pdf(
        self,
        pdf_bytes: bytes,
        *,
        lang: str = "ch",
        pages: Optional[Sequence[int]] = None,
        max_pages: int = 50,
    ) -> OcrResult: ...


# ---------------------------------------------------------------------------
# Real HTTP adapter
# ---------------------------------------------------------------------------


class PaddleOcrHttpAdapter:
    """HTTP client for the standalone PaddleOCR service.

    Reads ``PADDLEOCR_URL`` (default http://127.0.0.1:8090) and
    ``PADDLEOCR_REQUIRED_FOR_PDF`` from settings. When the service is
    unreachable, ``is_available`` is False and OCR calls raise
    ``OcrUnavailable(OCR_SERVICE_UNAVAILABLE)``.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 300.0,
        required_for_pdf: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._required_for_pdf = required_for_pdf
        self._client: Optional[httpx.Client] = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def required_for_pdf(self) -> bool:
        return self._required_for_pdf

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout_s)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    @property
    def is_available(self) -> bool:
        """Probe /health once (cheap). Cached per process via module singleton."""
        try:
            resp = self._get_client().get(f"{self._base_url}/health", timeout=5.0)
            return resp.status_code == 200 and resp.json().get("status") == "ok"
        except Exception:
            return False

    def ocr_image(self, image_bytes: bytes, *, lang: str = "ch", page: int = 1) -> OcrResult:
        payload = {
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
            "lang": lang,
            "page": page,
        }
        return self._post("/v1/ocr", payload)

    def ocr_pdf(
        self,
        pdf_bytes: bytes,
        *,
        lang: str = "ch",
        pages: Optional[Sequence[int]] = None,
        max_pages: int = 50,
    ) -> OcrResult:
        payload = {
            "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
            "lang": lang,
            "pages": list(pages) if pages is not None else None,
            "max_pages": max_pages,
        }
        return self._post("/v1/ocr/pdf", payload)

    def _post(self, path: str, payload: dict) -> OcrResult:
        url = f"{self._base_url}{path}"
        try:
            resp = self._get_client().post(url, json=payload, timeout=self._timeout_s)
        except httpx.TimeoutException as exc:
            raise OcrUnavailable(
                "OCR_TIMEOUT",
                f"OCR service timed out after {self._timeout_s}s: {exc}",
            ) from exc
        except Exception as exc:
            raise OcrUnavailable(
                "OCR_SERVICE_UNAVAILABLE",
                f"OCR service unreachable at {self._base_url}: {exc}",
            ) from exc

        if resp.status_code == 503:
            raise OcrUnavailable(
                "OCR_SERVICE_UNAVAILABLE",
                f"OCR service unavailable (503): {resp.text[:200]}",
            )
        if resp.status_code >= 500:
            raise OcrUnavailable(
                "OCR_FAILED",
                f"OCR service error {resp.status_code}: {resp.text[:200]}",
            )
        if resp.status_code != 200:
            raise OcrUnavailable(
                "OCR_FAILED",
                f"OCR service returned {resp.status_code}: {resp.text[:200]}",
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise OcrUnavailable("OCR_FAILED", f"OCR service returned non-JSON: {exc}") from exc

        return _parse_ocr_response(data)


def _parse_ocr_response(data: dict) -> OcrResult:
    pages: List[OcrPageResult] = []
    for p in data.get("pages", []):
        blocks = [
            OcrBlock(
                text=b.get("text", ""),
                bbox=b.get("bbox", [0, 0, 0, 0]),
                confidence=float(b.get("confidence", 0.0)),
                kind=b.get("kind", "text"),
            )
            for b in p.get("blocks", [])
        ]
        pages.append(OcrPageResult(page=int(p.get("page", 1)), blocks=blocks))
    return OcrResult(
        pages=pages,
        provider_version=data.get("provider_version", "unknown"),
        model_hash=data.get("model_hash", "unknown"),
        duration_ms=int(data.get("duration_ms", 0)),
    )


# ---------------------------------------------------------------------------
# Fail-closed fallback (no OCR configured)
# ---------------------------------------------------------------------------


class UnavailableOcrPort:
    """Used when no OCR service is configured. Always fails closed."""

    @property
    def is_available(self) -> bool:
        return False

    def ocr_image(self, image_bytes: bytes, *, lang: str = "ch", page: int = 1) -> OcrResult:
        raise OcrUnavailable(
            "OCR_SERVICE_UNAVAILABLE",
            "No OCR service configured (PADDLEOCR_URL empty). OCR-requiring tasks fail closed.",
        )

    def ocr_pdf(
        self,
        pdf_bytes: bytes,
        *,
        lang: str = "ch",
        pages: Optional[Sequence[int]] = None,
        max_pages: int = 50,
    ) -> OcrResult:
        raise OcrUnavailable(
            "OCR_SERVICE_UNAVAILABLE",
            "No OCR service configured (PADDLEOCR_URL empty). OCR-requiring tasks fail closed.",
        )


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_OCR_PORT: Optional[DocumentOcrPort] = None


def get_ocr_port() -> DocumentOcrPort:
    """Return the process-wide OCR port singleton.

    Configured from settings on first call. If ``PADDLEOCR_URL`` is empty,
    returns ``UnavailableOcrPort`` (fail-closed); OCR-requiring tasks will
    fail with ``OCR_SERVICE_UNAVAILABLE`` and be retryable once OCR is up.
    """
    global _OCR_PORT
    if _OCR_PORT is not None:
        return _OCR_PORT
    from app.core.config import settings
    base_url = (settings.PADDLEOCR_URL or "").strip()
    if not base_url:
        logger.info("PADDLEOCR_URL empty; OCR port is fail-closed UnavailableOcrPort")
        _OCR_PORT = UnavailableOcrPort()
        return _OCR_PORT
    _OCR_PORT = PaddleOcrHttpAdapter(
        base_url=base_url,
        timeout_s=float(getattr(settings, "PADDLEOCR_TIMEOUT_S", 300)),
        required_for_pdf=bool(getattr(settings, "PADDLEOCR_REQUIRED_FOR_PDF", True)),
    )
    logger.info("OCR port = PaddleOcrHttpAdapter(%s)", base_url)
    return _OCR_PORT


def reset_ocr_port() -> None:
    """Test helper: drop the cached singleton so config changes take effect."""
    global _OCR_PORT
    if isinstance(_OCR_PORT, PaddleOcrHttpAdapter):
        _OCR_PORT.close()
    _OCR_PORT = None
