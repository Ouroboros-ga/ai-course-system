"""Standalone PaddleOCR HTTP service.

Runs in its own container with paddleocr/paddlepaddle installed. The main
backend never imports paddleocr; it calls this service over HTTP via
``PaddleOcrHttpAdapter`` (backend/app/platform/document_intelligence/ocr_port.py).

Endpoints:
- GET  /health        -> service + runtime readiness
- POST /v1/ocr        -> OCR a single image (base64)
- POST /v1/ocr/pdf     -> OCR a PDF (base64), page-aware

If the paddleocr runtime is unavailable, /health returns 503 and the OCR
endpoints return 503 with a structured error. We NEVER fabricate OCR output.

See docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §6 Step 2.
"""
from __future__ import annotations

import base64
import logging
import os
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from provider import PaddleRuntime
from schemas import HealthResponse, OcrPdfRequest, OcrRequest, OcrResponse, OcrPage, OcrBlock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("paddleocr-service")

app = FastAPI(
    title="PaddleOCR Service",
    description="独立 OCR 服务，主后端通过 DocumentOcrPort 调用",
    version="1.0.0",
)

MAX_PAGES = int(os.getenv("PADDLEOCR_MAX_PAGES", "50"))
REQUEST_TIMEOUT_S = int(os.getenv("PADDLEOCR_REQUEST_TIMEOUT_S", "300"))


@app.get("/health")
async def health() -> JSONResponse:
    """Runtime readiness. 503 if paddleocr not importable."""
    if not PaddleRuntime.available:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "provider_version": PaddleRuntime.version,
                "model_hash": PaddleRuntime.model_hash,
                "gpu": PaddleRuntime.uses_gpu,
                "error": "paddleocr runtime not importable",
            },
        )
    return JSONResponse(
        status_code=200,
        content=HealthResponse(
            status="ok",
            provider_version=PaddleRuntime.version,
            model_hash=PaddleRuntime.model_hash,
            gpu=PaddleRuntime.uses_gpu,
        ).model_dump(),
    )


@app.post("/v1/ocr", response_model=OcrResponse)
async def ocr_image(req: OcrRequest) -> JSONResponse:
    """OCR a single base64-encoded image."""
    if not PaddleRuntime.available:
        return _unavailable()
    start = time.perf_counter()
    try:
        image_bytes = base64.b64decode(req.image_b64)
        blocks = PaddleRuntime.ocr_image(image_bytes, lang=req.lang)
    except Exception as exc:
        logger.exception("ocr_image failed")
        return JSONResponse(
            status_code=500,
            content={"error_code": "OCR_FAILED", "detail": str(exc)[:300]},
        )
    elapsed = int((time.perf_counter() - start) * 1000)
    return JSONResponse(
        status_code=200,
        content=OcrResponse(
            pages=[OcrPage(page=req.page, blocks=blocks)],
            provider_version=PaddleRuntime.version,
            model_hash=PaddleRuntime.model_hash,
            duration_ms=elapsed,
        ).model_dump(),
    )


@app.post("/v1/ocr/pdf", response_model=OcrResponse)
async def ocr_pdf(req: OcrPdfRequest) -> JSONResponse:
    """OCR a base64-encoded PDF, page-aware."""
    if not PaddleRuntime.available:
        return _unavailable()
    start = time.perf_counter()
    try:
        pdf_bytes = base64.b64decode(req.pdf_b64)
        max_pages = min(req.max_pages, MAX_PAGES)
        pages = PaddleRuntime.ocr_pdf(
            pdf_bytes, lang=req.lang, pages=req.pages, max_pages=max_pages,
        )
    except Exception as exc:
        logger.exception("ocr_pdf failed")
        return JSONResponse(
            status_code=500,
            content={"error_code": "OCR_FAILED", "detail": str(exc)[:300]},
        )
    elapsed = int((time.perf_counter() - start) * 1000)
    return JSONResponse(
        status_code=200,
        content=OcrResponse(
            pages=pages,
            provider_version=PaddleRuntime.version,
            model_hash=PaddleRuntime.model_hash,
            duration_ms=elapsed,
        ).model_dump(),
    )


def _unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error_code": "OCR_SERVICE_UNAVAILABLE",
            "detail": "paddleocr runtime not available; install paddleocr in the service container",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("PADDLEOCR_HOST", "0.0.0.0"),
        port=int(os.getenv("PADDLEOCR_PORT", "8090")),
        workers=int(os.getenv("PADDLEOCR_WORKERS", "1")),
    )
