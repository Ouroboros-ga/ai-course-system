"""Step 2 - 统一课程建设九步实施计划：DocumentOcrPort / PaddleOcrHttpAdapter 测试。

覆盖关键不变式（无需真实 OCR 服务）：
- UnavailableOcrPort（PADDLEOCR_URL 为空时）每次调用都 fail-closed，
  error_code=OCR_SERVICE_UNAVAILABLE，绝不伪造输出。
- PaddleOcrHttpAdapter 在服务不可达时抛 OCR_SERVICE_UNAVAILABLE。
- PaddleOcrHttpAdapter 在服务返回 503 时抛 OCR_SERVICE_UNAVAILABLE（可重试）。
- PaddleOcrHttpAdapter 在服务返回 200 时正确解析稳定 JSON。

见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §6 Step 2。
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.platform.document_intelligence.ocr_port import (
    OcrUnavailable,
    PaddleOcrHttpAdapter,
    UnavailableOcrPort,
    _parse_ocr_response,
    reset_ocr_port,
)


# ---------------------------------------------------------------------------
# 1. UnavailableOcrPort 永远 fail-closed
# ---------------------------------------------------------------------------


def test_unavailable_port_fail_closed():
    """PADDLEOCR_URL 为空时，OCR 端口 fail-closed，绝不伪造输出。"""
    port = UnavailableOcrPort()
    assert port.is_available is False
    with pytest.raises(OcrUnavailable) as exc:
        port.ocr_image(b"\x89PNG fake")
    assert exc.value.error_code == "OCR_SERVICE_UNAVAILABLE"

    with pytest.raises(OcrUnavailable) as exc:
        port.ocr_pdf(b"%PDF-1.4 fake")
    assert exc.value.error_code == "OCR_SERVICE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# 2. PaddleOcrHttpAdapter：服务不可达 -> OCR_SERVICE_UNAVAILABLE
# ---------------------------------------------------------------------------


def test_adapter_service_unreachable_raises_ocr_service_unavailable():
    """HTTP 连接失败时映射为可重试的 fail-closed 错误码（OCR_SERVICE_UNAVAILABLE 或 OCR_TIMEOUT），
    不抛原始 httpx 异常，绝不伪造输出。"""
    # 指向一个必定不可达的端口；连接失败可能表现为 ConnectError 或超时
    adapter = PaddleOcrHttpAdapter("http://127.0.0.1:9", timeout_s=1.0)
    try:
        with pytest.raises(OcrUnavailable) as exc:
            adapter.ocr_image(b"\x89PNG fake")
        # 两种合法 fail-closed 错误码：服务不可达 -> OCR_SERVICE_UNAVAILABLE；
        # 若表现为超时 -> OCR_TIMEOUT。二者均可重试，都不伪造输出。
        assert exc.value.error_code in {"OCR_SERVICE_UNAVAILABLE", "OCR_TIMEOUT"}
    finally:
        adapter.close()


def test_adapter_health_returns_false_when_unreachable():
    """is_available 在服务不可达时返回 False（不抛异常）。"""
    adapter = PaddleOcrHttpAdapter("http://127.0.0.1:9", timeout_s=1.0)
    try:
        assert adapter.is_available is False
    finally:
        adapter.close()


# ---------------------------------------------------------------------------
# 3. PaddleOcrHttpAdapter：服务返回 503 -> OCR_SERVICE_UNAVAILABLE
# ---------------------------------------------------------------------------


def test_adapter_503_raises_ocr_service_unavailable():
    """服务 503（paddleocr 运行时未就绪）映射为 OCR_SERVICE_UNAVAILABLE。"""
    adapter = PaddleOcrHttpAdapter("http://ocr-fake.test", timeout_s=2.0)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(503, json={"error_code": "OCR_SERVICE_UNAVAILABLE", "detail": "down"})

    adapter._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=2.0)
    try:
        with pytest.raises(OcrUnavailable) as exc:
            adapter.ocr_image(b"\x89PNG fake")
        assert exc.value.error_code == "OCR_SERVICE_UNAVAILABLE"
        assert captured["path"] == "/v1/ocr"
    finally:
        adapter.close()


# ---------------------------------------------------------------------------
# 4. PaddleOcrHttpAdapter：200 成功路径正确解析稳定 JSON
# ---------------------------------------------------------------------------


def test_adapter_200_parses_stable_json():
    """服务返回稳定 JSON 时，适配器解析为 OcrResult，保留 bbox/confidence/provider_version。"""
    stable_json = {
        "pages": [
            {
                "page": 1,
                "blocks": [
                    {"text": "第一块文本", "bbox": [0.1, 0.2, 0.3, 0.4], "confidence": 0.98, "kind": "text"},
                    {"text": "表格块", "bbox": [0.0, 0.5, 1.0, 0.9], "confidence": 0.85, "kind": "table"},
                ],
            },
            {"page": 2, "blocks": [{"text": "第二页", "bbox": [0.0, 0.0, 0.5, 0.5], "confidence": 0.7}]},
        ],
        "provider_version": "paddleocr-2.7.3",
        "model_hash": "abc123def4567890",
        "duration_ms": 1234,
    }

    adapter = PaddleOcrHttpAdapter("http://ocr-fake.test", timeout_s=2.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=stable_json)

    adapter._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=2.0)
    try:
        result = adapter.ocr_image(b"\x89PNG fake")
        assert result.provider_version == "paddleocr-2.7.3"
        assert result.model_hash == "abc123def4567890"
        assert result.duration_ms == 1234
        assert len(result.pages) == 2
        assert result.pages[0].page == 1
        assert len(result.pages[0].blocks) == 2
        assert result.pages[0].blocks[0].text == "第一块文本"
        assert result.pages[0].blocks[0].confidence == pytest.approx(0.98)
        assert list(result.pages[0].blocks[0].bbox) == [0.1, 0.2, 0.3, 0.4]
        assert result.pages[0].blocks[1].kind == "table"
        assert result.pages[1].page == 2
    finally:
        adapter.close()


# ---------------------------------------------------------------------------
# 5. _parse_ocr_response 容错：缺字段不崩
# ---------------------------------------------------------------------------


def test_parse_response_tolerates_missing_fields():
    data = {"provider_version": "v1", "model_hash": "h", "pages": [{"page": 1}]}
    result = _parse_ocr_response(data)
    assert result.pages[0].blocks == []
    assert result.provider_version == "v1"


# ---------------------------------------------------------------------------
# 6. get_ocr_port 单例：PADDLEOCR_URL 为空时返回 UnavailableOcrPort
# ---------------------------------------------------------------------------


def test_get_ocr_port_returns_unavailable_when_url_empty(monkeypatch):
    """PADDLEOCR_URL 为空 -> get_ocr_port 返回 UnavailableOcrPort（fail-closed）。"""
    reset_ocr_port()
    monkeypatch.setattr("app.core.config.settings.PADDLEOCR_URL", "")
    from app.platform.document_intelligence.ocr_port import get_ocr_port
    port = get_ocr_port()
    assert isinstance(port, UnavailableOcrPort)
    assert port.is_available is False
    reset_ocr_port()
