"""Nexus AI Runtime 反向代理（S1 双轨期，CodeNexus 转型）。

本模块是**纯透传层**，不含任何 Agent 逻辑：Nexus Runtime 运行在独立 Python
环境的独立进程（``nexus/``，deepagents + langgraph 1.x），与本后端只经 HTTP/SSE
通信（AGENTS.md §4.1.9）。前端统一走本后端的 ``/api/v1/nexus/*``，因此复用既有
JWT 鉴权与签名中间件，无需为 Nexus 单开公网端口。

设计约束：
- **不重实现**：上游返回什么就透传什么，不改写 Nexus 的响应体语义。
- **fail-closed**：Runtime 未配置或不可达时返回 503 + 明确错误码，不伪造回答
  （AGENTS.md 禁止静默成功）。
- **身份不外泄凭据**：不把用户 JWT 转发给 Runtime；用户身份以 ``X-Nexus-User-*``
  头透传，后端到 Runtime 之间用内部服务令牌 ``NEXUS_RUNTIME_API_KEY``。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import reject, unified_response
from app.core.security import get_current_user
from app.models.access_control_model import PlatformPermission
from app.models.database import get_session
from app.services.course_access_service import require_platform_permission

logger = logging.getLogger(__name__)

router = APIRouter()

# 错误码：前端据此给出准确的恢复提示，不做文案解析。
ERROR_NOT_CONFIGURED = "NEXUS_RUNTIME_NOT_CONFIGURED"
ERROR_UNAVAILABLE = "NEXUS_RUNTIME_UNAVAILABLE"
ERROR_TIMEOUT = "NEXUS_RUNTIME_TIMEOUT"
ERROR_FORBIDDEN = "NEXUS_PERMISSION_DENIED"


async def require_nexus_use(
    session=Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Nexus AI 使用权门控：``platform.nexus.use``（或 ``platform.admin``）。

    Nexus 是课程外全局入口，不绑定课程上下文，因此不走 course-scoped 的
    ``course_permission`` 链，而走平台权限解析（仅读
    ``platform_permission_assignments`` 显式授权，不依赖 ``User.role`` 推断）。
    """
    try:
        require_platform_permission(session, current_user, PlatformPermission.NEXUS_USE)
    except HTTPException as error:
        if error.status_code != status.HTTP_403_FORBIDDEN:
            raise
        reject(403, ERROR_FORBIDDEN, "尚未获得 Nexus AI 使用权限，请联系平台管理员开通")
    return current_user

# 上游响应中不可透传的逐跳头（由本后端的 ASGI 服务器重新决定）。
_HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class NexusChatRequest(BaseModel):
    """与 ``nexus.main.ChatRequest`` 保持同构；上限一致以便提前拒绝超长输入。

    M1-B1（D2）：mode 与 context 不再被本层 pydantic 静默丢弃——
    ``model_dump()`` 全量透传到 Runtime，由 Runtime 白名单归一 mode。
    """

    message: str = Field(min_length=1, max_length=10_000)
    session_id: str = Field(default="default", max_length=128)
    mode: str | None = Field(default=None, max_length=32)
    context: dict[str, Any] | None = Field(default=None)


def _runtime_base_url() -> str:
    return (settings.NEXUS_RUNTIME_URL or "").rstrip("/")


def _upstream_headers(current_user: dict | None, request: Request) -> dict[str, str]:
    """构造到 Runtime 的请求头：内部服务令牌 + 用户身份 + 转发链。"""
    headers: dict[str, str] = {"Accept": "application/json"}
    if settings.NEXUS_RUNTIME_API_KEY:
        headers["Authorization"] = f"Bearer {settings.NEXUS_RUNTIME_API_KEY}"
    if current_user:
        user_id = current_user.get("user_id")
        if user_id is not None:
            headers["X-Nexus-User-Id"] = str(user_id)
        role = current_user.get("role")
        if role:
            headers["X-Nexus-User-Role"] = str(role)
    if request.client and request.client.host:
        headers["X-Forwarded-For"] = request.client.host
    headers["X-Forwarded-Proto"] = request.url.scheme
    host = request.headers.get("host")
    if host:
        headers["X-Forwarded-Host"] = host
    return headers


def _not_configured() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=unified_response(
            code=503,
            message="Nexus AI 运行时未配置，暂不可用",
            data={"error_code": ERROR_NOT_CONFIGURED},
        ),
    )


def _unavailable(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=unified_response(
            code=503,
            message="Nexus AI 运行时不可达，请稍后重试",
            data={"error_code": ERROR_UNAVAILABLE, "detail": detail},
        ),
    )


def _timeout(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content=unified_response(
            code=504,
            message="Nexus AI 运行时响应超时",
            data={"error_code": ERROR_TIMEOUT, "detail": detail},
        ),
    )


def _passthrough(response: httpx.Response) -> JSONResponse:
    """透传上游 JSON 响应；上游返回非 JSON 时如实报告，不猜测内容。"""
    try:
        payload: Any = response.json()
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=unified_response(
                code=502,
                message="Nexus AI 运行时返回了非 JSON 响应",
                data={
                    "error_code": ERROR_UNAVAILABLE,
                    "upstream_status": response.status_code,
                    "body_preview": response.text[:200],
                },
            ),
        )
    return JSONResponse(status_code=response.status_code, content=payload)


@router.get("/health")
async def nexus_health(
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """透传 Nexus Runtime 的 ``/health``（含 llm/searxng/repro_worker 配置状态）。"""
    base = _runtime_base_url()
    if not base:
        return _not_configured()

    timeout = httpx.Timeout(
        settings.NEXUS_RUNTIME_TIMEOUT_S,
        connect=settings.NEXUS_RUNTIME_CONNECT_TIMEOUT_S,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base}/health", headers=_upstream_headers(current_user, request)
            )
    except httpx.TimeoutException as error:
        logger.warning("Nexus runtime health timeout: %s", error)
        return _timeout(str(error))
    except httpx.HTTPError as error:
        logger.warning("Nexus runtime health unreachable: %s", error)
        return _unavailable(str(error))
    return _passthrough(response)


@router.post("/chat")
async def nexus_chat(
    payload: NexusChatRequest,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """非流式对话：等待 Agent 循环结束后一次性返回最终答复与工具事件。"""
    base = _runtime_base_url()
    if not base:
        return _not_configured()

    timeout = httpx.Timeout(
        settings.NEXUS_RUNTIME_TIMEOUT_S,
        connect=settings.NEXUS_RUNTIME_CONNECT_TIMEOUT_S,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base}/api/v1/nexus/chat",
                json=payload.model_dump(),
                headers=_upstream_headers(current_user, request),
            )
    except httpx.TimeoutException as error:
        logger.warning("Nexus runtime chat timeout: %s", error)
        return _timeout(str(error))
    except httpx.HTTPError as error:
        logger.warning("Nexus runtime chat unreachable: %s", error)
        return _unavailable(str(error))
    return _passthrough(response)


@router.get("/sessions")
async def nexus_sessions(
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """会话列表透传（P1-C2）：归属由 X-Nexus-User-Id 决定，本层只做门控与转发。"""
    base = _runtime_base_url()
    if not base:
        return _not_configured()

    timeout = httpx.Timeout(
        settings.NEXUS_RUNTIME_TIMEOUT_S,
        connect=settings.NEXUS_RUNTIME_CONNECT_TIMEOUT_S,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base}/api/v1/nexus/sessions",
                headers=_upstream_headers(current_user, request),
            )
    except httpx.TimeoutException as error:
        logger.warning("Nexus runtime sessions timeout: %s", error)
        return _timeout(str(error))
    except httpx.HTTPError as error:
        logger.warning("Nexus runtime sessions unreachable: %s", error)
        return _unavailable(str(error))
    return _passthrough(response)


@router.get("/sessions/{session_id}/messages")
async def nexus_session_messages(
    session_id: str,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """单会话历史透传（P1-C2/C3）：Runtime 侧按用户命名空间隔离。"""
    base = _runtime_base_url()
    if not base:
        return _not_configured()

    timeout = httpx.Timeout(
        settings.NEXUS_RUNTIME_TIMEOUT_S,
        connect=settings.NEXUS_RUNTIME_CONNECT_TIMEOUT_S,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base}/api/v1/nexus/sessions/{session_id}/messages",
                headers=_upstream_headers(current_user, request),
            )
    except httpx.TimeoutException as error:
        logger.warning("Nexus runtime session messages timeout: %s", error)
        return _timeout(str(error))
    except httpx.HTTPError as error:
        logger.warning("Nexus runtime session messages unreachable: %s", error)
        return _unavailable(str(error))
    return _passthrough(response)


@router.post("/chat/stream")
async def nexus_chat_stream(
    payload: NexusChatRequest,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """流式对话：逐块转发上游 SSE（token / tool_call / tool_result / done）。

    读超时单独放宽到 ``NEXUS_RUNTIME_STREAM_READ_TIMEOUT_S``：Agent 在多轮工具
    循环中可能长时间不产出 token，用非流式的 60s 会误杀正常长任务。
    """
    base = _runtime_base_url()
    if not base:
        return _not_configured()

    timeout = httpx.Timeout(
        settings.NEXUS_RUNTIME_STREAM_READ_TIMEOUT_S,
        connect=settings.NEXUS_RUNTIME_CONNECT_TIMEOUT_S,
    )
    headers = _upstream_headers(current_user, request)
    headers["Accept"] = "text/event-stream"

    client = httpx.AsyncClient(timeout=timeout)
    stream_ctx = client.stream(
        "POST",
        f"{base}/api/v1/nexus/chat/stream",
        json=payload.model_dump(),
        headers=headers,
    )
    try:
        upstream = await stream_ctx.__aenter__()
    except httpx.TimeoutException as error:
        await client.aclose()
        logger.warning("Nexus runtime stream timeout: %s", error)
        return _timeout(str(error))
    except httpx.HTTPError as error:
        await client.aclose()
        logger.warning("Nexus runtime stream unreachable: %s", error)
        return _unavailable(str(error))

    if upstream.status_code >= 400:
        # 上游在建流阶段就失败（如 503 LLM_NOT_CONFIGURED）：读完错误体按普通
        # JSON 透传，让前端拿到确定的错误码，而不是一个空的 SSE 流。
        await upstream.aread()
        await stream_ctx.__aexit__(None, None, None)
        await client.aclose()
        return _passthrough(upstream)

    async def relay():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await stream_ctx.__aexit__(None, None, None)
            await client.aclose()

    passthrough_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS
    }
    passthrough_headers.setdefault("Cache-Control", "no-cache")
    # 关闭 Nginx 缓冲，否则 SSE 会被攒成一整块再下发。
    passthrough_headers["X-Accel-Buffering"] = "no"

    return StreamingResponse(
        relay(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "text/event-stream"),
        headers=passthrough_headers,
    )
