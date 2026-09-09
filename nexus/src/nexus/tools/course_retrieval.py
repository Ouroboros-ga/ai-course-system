"""M2 知识接入工具：课程资料检索 + CS 知识库检索。

设计文档 §18 链路：Nexus Tool → Existing Backend Capability → Structured Result。
- 数据不复制、KB 不重建：两工具调用 Backend 的 ``/api/v1/nexus-internal/*``
  只读端点（service token + 用户身份双重校验在 Backend 侧强制）；
- ``search_course_materials`` 的 course_id 来自代理层注入的请求作用域
  （request_scope），**不信任模型传参**；
- 未配置内部端点 / 不可达 / 无权限时 fail-closed，如实返回错误码，绝不假造
  检索结果（AGENTS.md §4.3）。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.tools import tool

from nexus.config import get_settings
from nexus.request_scope import current_course_id, current_user_id

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15.0
#: 工具结果回传模型的条目上限（展示层另有 300 字符截断，回源身份不受影响）。
_MAX_ITEMS = 8


def _settings_ready() -> tuple[str, str] | None:
    settings = get_settings()
    url = (settings.backend_internal_url or "").rstrip("/")
    token = settings.backend_internal_token or ""
    if not url or not token:
        return None
    return url, token


async def _call_internal(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """调用 Backend 内部检索端点；错误统一转结构化 dict（不抛给 Agent 循环）。"""
    ready = _settings_ready()
    if ready is None:
        return {
            "status": "unavailable",
            "code": "KNOWLEDGE_RETRIEVAL_UNCONFIGURED",
            "detail": "内部检索端点未配置，课程/CS 资料不可用；不得编造资料内容。",
            "items": [],
        }
    url, token = ready
    user_id = current_user_id()
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        **({"X-Nexus-User-Id": user_id} if user_id else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(f"{url}{path}", params=params, headers=headers)
    except Exception as error:  # noqa: BLE001 - 不可达 fail-closed
        logger.warning("nexus internal retrieval failed: %s", type(error).__name__)
        return {
            "status": "unavailable",
            "code": "KNOWLEDGE_RETRIEVAL_UNAVAILABLE",
            "detail": f"内部检索不可达（{type(error).__name__}）；不得编造资料内容。",
            "items": [],
        }
    if response.status_code == 403:
        return {
            "status": "rejected",
            "code": "COURSE_ACCESS_DENIED",
            "detail": "当前用户没有该课程的资料访问权限。",
            "items": [],
        }
    if response.status_code != 200:
        return {
            "status": "unavailable",
            "code": "KNOWLEDGE_RETRIEVAL_UNAVAILABLE",
            "detail": f"内部检索返回 HTTP {response.status_code}。",
            "items": [],
        }
    try:
        payload = response.json()
    except ValueError:
        return {
            "status": "unavailable",
            "code": "KNOWLEDGE_RETRIEVAL_UNAVAILABLE",
            "detail": "内部检索返回非 JSON 响应。",
            "items": [],
        }
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        items = []
    return {
        "status": "success",
        "authority": (data or {}).get("authority", ""),
        # 版本与降级随工具结果透传：模型/界面据此知道语料版本与可用通路
        "release_id": (data or {}).get("release_id", ""),
        "mode": (data or {}).get("mode", ""),
        "degraded_reasons": list((data or {}).get("degraded_reasons") or []),
        "items": items[:_MAX_ITEMS],
        "items_total": len(items),
        "items_truncated": max(0, len(items) - _MAX_ITEMS),
    }


def _course_scope() -> dict[str, Any]:
    course_id = current_course_id()
    if course_id is None:
        return {
            "status": "no_course_context",
            "code": "COURSE_CONTEXT_MISSING",
            "detail": (
                "本请求未绑定课程（会话未选择课程），课程资料检索不可用。"
                "如需课程资料，请让用户在会话中选择课程后再问。"
            ),
            "items": [],
        }
    return {"status": "ok", "course_id": course_id}


@tool
async def search_course_materials(query: str) -> dict[str, Any]:
    """检索当前绑定课程的教学资料（课件/讲义证据，经核实，含引用定位）。

    仅当会话绑定了课程时可用；course_id 由平台注入，模型传参不改变检索范围。
    返回的资料属"课程事实"，优先级高于公开网络资料，但必须与问题相关——
    不相关时如实说明没有找到相关课程资料，不得强行引用。
    """
    scope = _course_scope()
    if scope["status"] != "ok":
        return scope
    result = await _call_internal(
        "/api/v1/nexus-internal/course-evidence",
        {"course_id": scope["course_id"], "q": query},
    )
    if result.get("status") == "success":
        result["authority_label"] = "课程资料（经核实）"
        result["is_supplementary"] = False
        result["course_id"] = scope["course_id"]
    return result


@tool
async def search_cs_knowledge(query: str) -> dict[str, Any]:
    """检索 CS 语料参考（学科开放语料的原文段落，补充参考）。

    返回条目带 reference_id 与出处（标题/来源/许可/匹配方式），引用答案时
    必须核对原文引用；正文进入本工具结果供模型使用，界面展示可能截断，
    但回源入口（reference_id）不受展示截断影响。
    结果属"补充参考"（未经课程核实）：可追溯不等于正确，不得写成既定事实，
    不得标"教材级权威"；与问题无关时如实说明未找到相关条目。
    """
    result = await _call_internal("/api/v1/nexus-internal/cs-knowledge", {"q": query})
    if result.get("status") == "success":
        result["authority_label"] = "CS 语料参考（补充，需核对原文）"
        result["is_supplementary"] = True
        for item in result.get("items") or []:
            if isinstance(item, dict):
                item["is_supplementary"] = True
    return result
