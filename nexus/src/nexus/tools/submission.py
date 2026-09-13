"""NX-CT1 代码伴学工具：读取本次对话绑定的本人提交快照。

设计（照抄 M2 课程检索链路 §18）：
- Nexus Tool → Backend ``/api/v1/nexus-internal/submission`` 只读端点 →
  Structured Result；数据不复制、不重建；
- course_id/run_id 来自代理层投影注入的请求作用域（request_scope），
  **不信任模型传参**——本工具刻意无参数，模型无法指定读哪次提交；
- 未绑定 / 未配置 / 不可达 / 无权限时 fail-closed，如实返回错误码，
  绝不假造代码与判题结果（AGENTS.md §4.3）。

红线：快照只含归属三元组命中的本人行；用例输入/期望输出不在
Backend 投影内，本工具更接触不到；结果标记 ``is_supplementary``，
不写掌握度/课程事实/图谱（AGENTS.md §4.1.5）。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.tools import tool

from nexus.config import get_settings
from nexus.request_scope import current_submission, current_user_id

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15.0


def _settings_ready() -> tuple[str, str] | None:
    settings = get_settings()
    url = (settings.backend_internal_url or "").rstrip("/")
    token = settings.backend_internal_token or ""
    if not url or not token:
        return None
    return url, token


@tool
async def read_my_submission() -> dict[str, Any]:
    """读取当前代码伴学绑定的本人提交快照（源码+判题+产物尾部，有界）。

    无参数：读哪次提交由服务端绑定决定。未绑定时返回
    SUBMISSION_NOT_BOUND 并指引从提交页重新进入，不编造内容。
    """
    bound = current_submission()
    if bound is None:
        return {
            "status": "no_submission_context",
            "code": "SUBMISSION_NOT_BOUND",
            "detail": (
                "本次对话未绑定代码提交：请从题目/提交页点击「问代码伴学」"
                "重新进入，或先提交一次代码再回来提问；不得编造提交内容。"
            ),
        }
    ready = _settings_ready()
    if ready is None:
        return {
            "status": "unavailable",
            "code": "SUBMISSION_RETRIEVAL_UNCONFIGURED",
            "detail": "内部提交快照端点未配置；不得编造提交内容。",
        }
    url, token = ready
    course_id, run_id = bound
    user_id = current_user_id()
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        **({"X-Nexus-User-Id": user_id} if user_id else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(
                f"{url}/api/v1/nexus-internal/submission",
                params={"course_id": course_id, "run_id": run_id},
                headers=headers,
            )
    except Exception as error:  # noqa: BLE001 - 不可达 fail-closed
        logger.warning("nexus submission snapshot failed: %s", type(error).__name__)
        return {
            "status": "unavailable",
            "code": "SUBMISSION_RETRIEVAL_UNAVAILABLE",
            "detail": f"提交快照不可达（{type(error).__name__}）；不得编造提交内容。",
        }
    if response.status_code == 403:
        return {
            "status": "rejected",
            "code": "SUBMISSION_ACCESS_DENIED",
            "detail": "当前用户没有该课程的提交访问权限。",
        }
    if response.status_code == 404:
        return {
            "status": "rejected",
            "code": "SUBMISSION_NOT_FOUND",
            "detail": "绑定的提交不存在或不属于当前用户；不得编造提交内容。",
        }
    if response.status_code != 200:
        return {
            "status": "unavailable",
            "code": "SUBMISSION_RETRIEVAL_UNAVAILABLE",
            "detail": f"提交快照返回 HTTP {response.status_code}。",
        }
    try:
        payload = response.json()
    except ValueError:
        return {
            "status": "unavailable",
            "code": "SUBMISSION_RETRIEVAL_UNAVAILABLE",
            "detail": "提交快照返回非 JSON 响应。",
        }
    data = payload.get("data") if isinstance(payload, dict) else None
    submission = (data or {}).get("submission")
    if not isinstance(submission, dict):
        return {
            "status": "unavailable",
            "code": "SUBMISSION_RETRIEVAL_UNAVAILABLE",
            "detail": "提交快照缺少 submission 字段。",
        }
    submission.setdefault("is_supplementary", True)
    return {
        "status": "success",
        "authority": (data or {}).get("authority", "oj_submission"),
        "is_supplementary": True,
        "submission": submission,
    }
