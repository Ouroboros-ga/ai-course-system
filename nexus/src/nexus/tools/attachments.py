"""NX-A1 附件消费工具：会话绑定的用户资料读取。

安全边界：
- attachment_id 来自请求作用域（request_scope，随 chat attachment_ids 由
  Backend 验主+绑定后注入），**不是模型可编造的访问凭证**；
- Backend 内部端点做 owner + 会话绑定双重校验；此处只透传身份，不做授权裁决；
- 内容视为资料（supplementary），不写课程 KB/LearningEvidence/Course Graph；
- 图片只消费文本 blocks（OCR 回填）+ 元数据；无视觉模型，不冒充看图。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.tools import tool

from nexus.config import get_settings
from nexus.request_scope import current_attachments, current_user_id

logger = logging.getLogger(__name__)

_TIME_OUT_S = 20.0


def _settings_ready() -> tuple[str, str] | None:
    settings = get_settings()
    url = (settings.backend_internal_url or "").rstrip("/")
    token = settings.backend_internal_token or ""
    if not url or not token:
        return None
    return url, token


@tool
async def read_attachment(attachment_id: str, locator: str = "") -> dict[str, Any]:
    """读取本次对话绑定的附件内容（用户上传的真实资料）。

    参数：
    - attachment_id：附件 id（仅本次对话绑定的可用；未绑定/他人文件会被拒绝）；
    - locator：精读定位（页 p3 / 幻灯片 slide2 / 表 sheet:Sheet1 / 段 para5），
      为空返回开头预算内全文。

    返回 blocks（每块自带 locator，引用时必须使用原文 locator，不得编页码）。
    图片返回文字与尺寸元数据；无 OCR/无视觉时如实标注。
    """
    from nexus.request_scope import current_session_id

    aid = (attachment_id or "").strip()[:16]
    if not aid:
        return {"status": "rejected", "code": "ATTACHMENT_ID_INVALID",
                "detail": "附件 id 为空。", "items": []}
    allowed = set(current_attachments())
    if allowed and aid not in allowed:
        return {"status": "rejected", "code": "ATTACHMENT_NOT_IN_SCOPE",
                "detail": "该附件未绑定到本次对话，不得读取。", "items": []}
    ready = _settings_ready()
    if ready is None:
        return {"status": "unavailable", "code": "ATTACHMENT_UNAVAILABLE",
                "detail": "附件服务未配置；不得编造文件内容。", "items": []}
    url, token = ready
    user_id = current_user_id()
    session_id = current_session_id()
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        **({"X-Nexus-User-Id": user_id} if user_id else {}),
        **({"X-Nexus-Session-Id": session_id} if session_id else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIME_OUT_S) as client:
            response = await client.get(
                f"{url}/api/v1/nexus-internal/attachments/{aid}/content",
                params={"locator": (locator or "").strip()[:64]},
                headers=headers,
            )
    except Exception as error:  # noqa: BLE001
        logger.warning("read_attachment unreachable: %s", type(error).__name__)
        return {"status": "unavailable", "code": "ATTACHMENT_UNAVAILABLE",
                "detail": f"附件服务不可达（{type(error).__name__}）。", "items": []}
    if response.status_code == 403:
        return {"status": "rejected", "code": "ATTACHMENT_SESSION_MISMATCH",
                "detail": "附件未绑定到本次对话，不得读取。", "items": []}
    if response.status_code == 404:
        return {"status": "rejected", "code": "ATTACHMENT_NOT_FOUND",
                "detail": "附件不存在。", "items": []}
    if response.status_code != 200:
        return {"status": "unavailable", "code": "ATTACHMENT_UNAVAILABLE",
                "detail": f"附件读取被拒（HTTP {response.status_code}）。", "items": []}
    try:
        data = response.json().get("data") or {}
    except ValueError:
        return {"status": "unavailable", "code": "ATTACHMENT_UNAVAILABLE",
                "detail": "附件服务返回非 JSON。", "items": []}
    blocks = data.get("blocks", [])
    return {
        "status": "success",
        "filename": data.get("filename", ""),
        "kind": data.get("kind", ""),
        "attachment_status": data.get("status", ""),
        "truncated": bool(data.get("truncated")),
        "items": blocks,
        "is_supplementary": True,
    }
