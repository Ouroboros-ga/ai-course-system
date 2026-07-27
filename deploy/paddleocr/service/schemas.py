"""Pydantic schemas for the standalone PaddleOCR HTTP service.

Stable JSON contract consumed by the main backend's ``PaddleOcrHttpAdapter``.
Never change field names without bumping ``provider_version`` and updating the
backend adapter; the backend treats this JSON as a versioned contract.

See docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §6 Step 2.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class OcrBlock(BaseModel):
    """A single recognized text block on a page."""
    text: str = Field(..., description="识别出的文本")
    bbox: List[float] = Field(
        ..., description="[x0, y0, x1, y1] 归一化坐标 0..1（相对页面宽高）",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="识别置信度 0..1")
    kind: str = Field("text", description="text|table|formula|figure_caption")


class OcrPage(BaseModel):
    """OCR result for one page."""
    page: int = Field(..., ge=1, description="1-based 页码")
    blocks: List[OcrBlock] = Field(default_factory=list)


class OcrResponse(BaseModel):
    """Stable top-level OCR response."""
    pages: List[OcrPage] = Field(default_factory=list)
    provider_version: str = Field(..., description="PaddleOCR provider 版本，如 paddleocr-2.7")
    model_hash: str = Field(..., description="所用模型文件 SHA256 摘要（前 16 位）")
    duration_ms: int = Field(0, description="本次识别耗时（毫秒）")


class HealthResponse(BaseModel):
    """``GET /health`` response."""
    status: str = Field("ok")
    provider_version: str = Field(...)
    model_hash: str = Field(...)
    gpu: bool = Field(False, description="是否使用 GPU 推理")


class OcrRequest(BaseModel):
    """``POST /v1/ocr`` request: a single image (base64)."""
    image_b64: str = Field(..., description="base64 编码的图片字节")
    lang: str = Field("ch", description="语言，如 ch / en / chinese_cht")
    page: int = Field(1, ge=1, description="该图片对应的页码（仅用于回填 page 字段）")


class OcrPdfRequest(BaseModel):
    """``POST /v1/ocr/pdf`` request: a PDF (base64)."""
    pdf_b64: str = Field(..., description="base64 编码的 PDF 字节")
    lang: str = Field("ch")
    pages: Optional[List[int]] = Field(
        None, description="指定页码列表；None 表示全部页（受 max_pages 限制）",
    )
    max_pages: int = Field(50, ge=1, le=200)
