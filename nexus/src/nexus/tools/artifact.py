"""M3 Artifact 工具：把真实文件写入对象存储（经 Backend 内部端点）。

设计文档 Phase 4 原则：不要模型输出"以下是 Word 文档内容"，要真实文件。
- 工具只接受 markdown / latex 文本对象（P0）；成功后返回 artifact_id 与
  下载路径（前端经 Backend JWT 路由下载）；
- 未配置内部端点 / 失败时 fail-closed 返回 ARTIFACT_UNAVAILABLE，
  绝不假造"文件已生成"（AGENTS.md §4.3 诚实性）。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.tools import tool

from nexus.config import get_settings
from nexus.request_scope import current_user_id

logger = logging.getLogger(__name__)

_TIMEOUT_S = 20.0


def _settings_ready() -> tuple[str, str] | None:
    settings = get_settings()
    url = (settings.backend_internal_url or "").rstrip("/")
    token = settings.backend_internal_token or ""
    if not url or not token:
        return None
    return url, token


@tool
async def write_artifact(artifact_type: str, title: str, content: str) -> dict[str, Any]:
    """把整理成果写成真实文件（Artifact），供用户下载。

    参数：
    - artifact_type：仅支持 "markdown"（研究报告、笔记、总结）或
      "latex"（论文/公式类内容）；
    - title：产物标题（将用作下载文件名，<=120 字符）；
    - content：完整正文（纯文本，<=512KB）。

    成功返回 artifact_id 与下载路径；失败如实返回错误（不得声称文件已生成）。
    输出长报告时优先调用本工具落成文件，再在对话中给出摘要。
    """
    ready = _settings_ready()
    if ready is None:
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": "产物存储未配置；不得声称文件已生成。",
        }
    url, token = ready
    user_id = current_user_id()
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        **({"X-Nexus-User-Id": user_id} if user_id else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.post(
                f"{url}/api/v1/nexus-internal/artifacts",
                json={"artifact_type": artifact_type, "title": title, "content": content},
                headers=headers,
            )
    except Exception as error:  # noqa: BLE001 - fail-closed
        logger.warning("write_artifact failed: %s", type(error).__name__)
        return {
            "status": "unavailable",
            "code": "ARTIFACT_UNAVAILABLE",
            "detail": f"产物写入失败（{type(error).__name__}）；不得声称文件已生成。",
        }
    if response.status_code != 200:
        try:
            detail = response.json().get("message", "")
        except ValueError:
            detail = ""
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
    artifact = {
        "artifact_id": data.get("artifact_id", ""),
        "artifact_type": data.get("artifact_type", artifact_type),
        "title": data.get("title", title),
        "size_bytes": data.get("size_bytes", 0),
        "download_path": f"/api/v1/nexus/artifacts/{data.get('artifact_id', '')}/download",
    }
    return {
        "status": "success",
        "artifact": artifact,
        "detail": "文件已真实写入存储，用户可在产物面板下载。",
    }
