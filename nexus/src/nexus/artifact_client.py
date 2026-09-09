"""M3/M4 共用：经 Backend 内部端点写 Artifact 的 HTTP 客户端。

write_artifact 工具与 M4 复现报告端点共用同一条写入链（service token +
用户身份），保证产物元数据/下载链路的单一实现。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from nexus.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT_S = 20.0


def _settings_ready() -> tuple[str, str] | None:
    settings = get_settings()
    url = (settings.backend_internal_url or "").rstrip("/")
    token = settings.backend_internal_token or ""
    if not url or not token:
        return None
    return url, token


def _error_detail(response: Any) -> str:
    """提取服务端错误明细（FastAPI 用 detail，内部信封用 message）。"""
    try:
        payload = response.json()
    except ValueError:
        return ""
    if isinstance(payload, dict):
        detail = payload.get("detail", payload.get("message", ""))
        if isinstance(detail, list):
            return "; ".join(str(getattr(item, "get", lambda *_: item)("msg", item))
                             if isinstance(item, dict) else str(item)
                             for item in detail)[:300]
        return str(detail or "")[:300]
    return ""


async def write_binary_artifact_via_backend(
    *, artifact_type: str, title: str, raw: bytes, user_id: str | None,
    run_id: str = "",
) -> dict[str, Any]:
    """写二进制产物（SR6 Word .docx）：字节经 base64 进内部端点。

    返回形态与 write_artifact_via_backend 一致（success＋artifact /
    unavailable＋code/detail）。空字节拒绝（不发送）。
    """
    import base64

    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return {
            "status": "unavailable",
            "code": "ARTIFACT_CONTENT_EMPTY",
            "detail": "二进制产物为空；不得声称文件已生成。",
        }
    ready = _settings_ready()
    if ready is None:
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": "产物存储未配置；不得声称文件已生成。",
        }
    url, token = ready
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        **({"X-Nexus-User-Id": user_id} if user_id else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.post(
                f"{url}/api/v1/nexus-internal/artifacts",
                json={
                    "artifact_type": artifact_type,
                    "title": title,
                    "content": "",
                    "content_b64": base64.b64encode(bytes(raw)).decode("ascii"),
                    **({"run_id": run_id} if run_id else {}),
                },
                headers=headers,
            )
    except Exception as error:  # noqa: BLE001 - fail-closed
        logger.warning("write_binary_artifact_via_backend failed: %s", type(error).__name__)
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": f"产物写入失败（{type(error).__name__}）；不得声称文件已生成。",
        }
    if response.status_code != 200:
        detail = _error_detail(response)
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": f"产物写入被拒（HTTP {response.status_code}）{detail}；不得声称文件已生成。",
        }
    try:
        data = response.json().get("data") or {}
    except ValueError:
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": "产物写入返回非 JSON 响应。",
        }
    artifact_id = str(data.get("artifact_id", ""))
    return {
        "status": "success",
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": data.get("artifact_type", artifact_type),
            "title": data.get("title", title),
            "size_bytes": data.get("size_bytes", 0),
            "download_path": f"/api/v1/nexus/artifacts/{artifact_id}/download",
        },
    }


async def write_artifact_via_backend(
    *, artifact_type: str, title: str, content: str, user_id: str | None,
    run_id: str = "",
) -> dict[str, Any]:
    """调用 Backend 内部写端点；返回统一形态：
    status=success + artifact{...}，或 status=unavailable + code/detail。"""
    ready = _settings_ready()
    if ready is None:
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": "产物存储未配置；不得声称文件已生成。",
        }
    url, token = ready
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        **({"X-Nexus-User-Id": user_id} if user_id else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.post(
                f"{url}/api/v1/nexus-internal/artifacts",
                json={
                    "artifact_type": artifact_type,
                    "title": title,
                    "content": content,
                    **({"run_id": run_id} if run_id else {}),
                },
                headers=headers,
            )
    except Exception as error:  # noqa: BLE001 - fail-closed
        logger.warning("write_artifact_via_backend failed: %s", type(error).__name__)
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": f"产物写入失败（{type(error).__name__}）；不得声称文件已生成。",
        }
    if response.status_code != 200:
        detail = _error_detail(response)
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": f"产物写入被拒（HTTP {response.status_code}）{detail}；不得声称文件已生成。",
        }
    try:
        data = response.json().get("data") or {}
    except ValueError:
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": "产物写入返回非 JSON 响应。",
        }
    artifact_id = str(data.get("artifact_id", ""))
    return {
        "status": "success",
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": data.get("artifact_type", artifact_type),
            "title": data.get("title", title),
            "size_bytes": data.get("size_bytes", 0),
            "download_path": f"/api/v1/nexus/artifacts/{artifact_id}/download",
        },
    }
