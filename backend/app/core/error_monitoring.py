"""Error monitoring middleware.

批次0上线底座要求：建立错误监控--403、503、5xx、外部服务失败、跨课程拒绝、任务失败。

本中间件对每个 >= 400 的响应做结构化日志记录，并按错误类别分类计数。
不改变响应内容，仅观测。计数通过 ``app.state.error_monitor`` 暴露，可供
健康检查或运维端点读取。
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("error_monitor")

# Error categories tracked by the monitor.
CATEGORY_CROSS_COURSE_DENIAL = "cross_course_denial"
CATEGORY_AUTHORIZATION_403 = "authorization_403"
CATEGORY_SHADOW_DISABLED_503 = "shadow_disabled_503"
CATEGORY_EXTERNAL_SERVICE_503 = "external_service_503"
CATEGORY_SERVER_ERROR_5XX = "server_error_5xx"
CATEGORY_CLIENT_ERROR_4XX = "client_error_4xx"
CATEGORY_TASK_FAILURE = "task_failure"

# Heuristic error-code strings that indicate specific failure sources.
_SHADOW_CODES = {
    "SHADOW_FEATURE_DISABLED",
    "DEMO_SHADOW_DISABLED",
    "PAGE_RENDERING_NOT_AVAILABLE_IN_G4",
}
_EXTERNAL_SERVICE_CODES = {
    "TEACHING_AGENT_NOT_CONFIGURED",
    "TEACHING_LLM_UNAVAILABLE",
    "TEACHING_SERVICE_UNAVAILABLE",
}
_CROSS_COURSE_HINTS = ("课程权限不足", "平台权限不足")


class ErrorMonitor:
    """In-memory error counters, keyed by category."""

    def __init__(self) -> None:
        self.counts: Counter = Counter()

    def record(self, category: str) -> None:
        self.counts[category] += 1

    def snapshot(self) -> dict:
        return dict(self.counts)

    def reset(self) -> None:
        self.counts.clear()


# Module-level singleton so app.state and tests can read/reset it without
# reaching into the middleware stack.
monitor = ErrorMonitor()


def _classify(status_code: int, body: dict | None) -> str:
    """Classify an error response into a monitoring category.

    Handles both the unified_response envelope (``{"code","message","data"}``)
    and FastAPI's default ``{"detail": ...}`` format so the monitor works
    regardless of which exception handler produced the response.
    """
    if not isinstance(body, dict):
        body = {}

    message = str(body.get("message", ""))
    # ``data`` may carry a structured error_code (unified_response path),
    # ``detail`` may carry the same (FastAPI default path).
    detail = body.get("data")
    if detail is None:
        detail = body.get("detail")
    error_code = ""
    if isinstance(detail, dict):
        error_code = str(detail.get("code") or detail.get("detail") or "")
    elif isinstance(detail, str):
        message = message or detail

    if status_code == 403:
        if any(hint in message for hint in _CROSS_COURSE_HINTS):
            return CATEGORY_CROSS_COURSE_DENIAL
        return CATEGORY_AUTHORIZATION_403

    if status_code == 503:
        if any(code in error_code for code in _SHADOW_CODES):
            return CATEGORY_SHADOW_DISABLED_503
        if any(code in error_code for code in _EXTERNAL_SERVICE_CODES):
            return CATEGORY_EXTERNAL_SERVICE_503
        return CATEGORY_EXTERNAL_SERVICE_503

    if 500 <= status_code < 600:
        if "task" in message.lower() or "task" in error_code.lower():
            return CATEGORY_TASK_FAILURE
        return CATEGORY_SERVER_ERROR_5XX

    return CATEGORY_CLIENT_ERROR_4XX


async def _read_body(response: Response) -> bytes:
    body = b""
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        body += chunk
    return body


# P3 §四.1：流式响应 Content-Type 白名单。
# 这些类型的响应体不能一次性读取（会破坏 SSE / NDJSON / chunked 流式语义），
# 中间件遇到它们时只按状态码粗略分类计数，不消费 body，直接放行原始响应。
_STREAMING_CONTENT_TYPES = frozenset({
    "text/event-stream",
    "application/x-ndjson",
    "application/streaming",
    "text/plain; charset=utf-8 streaming",
})


def _is_streaming_response(response: Response) -> bool:
    """Detect SSE / NDJSON / streaming responses whose body must not be buffered."""
    content_type = response.headers.get("content-type", "")
    # 取主类型（忽略参数），小写比较
    main_type = content_type.split(";")[0].strip().lower()
    if main_type in _STREAMING_CONTENT_TYPES:
        return True
    # StreamingResponse 且未设置 media_type 时，headers 可能没有 content-type，
    # 但 starlette 会注入 transfer-encoding: chunked；此时也按流式处理。
    if isinstance(response, StreamingResponse) and "text/event-stream" in content_type:
        return True
    return False


class ErrorMonitoringMiddleware(BaseHTTPMiddleware):
    """Logs and counts error responses (status >= 400) with structured context."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if response.status_code < 400:
            return response

        # P3 §四.1：流式响应（SSE / NDJSON 等）不能一次性读取 body，
        # 否则会破坏流式语义。只按状态码粗略分类计数，放行原始响应。
        if _is_streaming_response(response):
            category = _classify(response.status_code, None)
            monitor.record(category)
            logger.warning(
                "error_monitor status=%s category=%s method=%s path=%s streaming=true",
                response.status_code,
                category,
                request.method,
                request.url.path,
                extra={
                    "status_code": response.status_code,
                    "category": category,
                    "method": request.method,
                    "path": request.url.path,
                    "error_code": "",
                    "streaming": True,
                },
            )
            return response

        # Read the response body to extract structured error_code (only for errors).
        body_bytes = await _read_body(response)
        body: dict | None = None
        try:
            body = json.loads(body_bytes) if body_bytes else None
        except Exception:
            body = None

        category = _classify(response.status_code, body)
        monitor.record(category)

        error_code = ""
        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, dict):
                error_code = str(data.get("code") or data.get("detail") or "")

        logger.warning(
            "error_monitor status=%s category=%s method=%s path=%s error_code=%s",
            response.status_code,
            category,
            request.method,
            request.url.path,
            error_code,
            extra={
                "status_code": response.status_code,
                "category": category,
                "method": request.method,
                "path": request.url.path,
                "error_code": error_code,
            },
        )

        # Re-wrap the consumed body into a fresh StreamingResponse so the client
        # still receives the full payload.
        return StreamingResponse(
            iter([body_bytes]),
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
