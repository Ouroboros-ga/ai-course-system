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
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

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
    NX-G1（v1.3 A1）：本层先做同样的严格校验（别名表镜像
    ``nexus.agent``，两进程不共享 Python 环境故不能 import），未知 mode
    在触达 Runtime（启动模型/SSE）前以 400 INVALID_NEXUS_MODE 拒绝。
    模型网关 P0：model 只透传不校验——可选模型清单是动态服务端配置，
    唯一真相源在 Runtime（/health models）；本层硬编码只会漂移。
    未知模型由 Runtime 以 400 INVALID_NEXUS_MODEL 拒绝并原样透传。
    """

    message: str = Field(min_length=1, max_length=10_000)
    session_id: str = Field(default="default", max_length=128)
    mode: str | None = Field(default=None, max_length=32)
    context: dict[str, Any] | None = Field(default=None)
    model: str | None = Field(default=None, max_length=64)
    # T2 Research Ask/Auto（前端规格 §2.1）：ask|auto，只在 Research 展示。
    # 本层只做未知值 400 拒绝（两模式一致），缺字段透传由 Runtime 默认 Ask；
    # General 兼容合法值但不产生执行授权（Runtime 执行核裁决）。
    research_execution_mode: str | None = Field(default=None, max_length=16)
    # NX-A1：本次对话引用的附件 id（≤5）。本层逐个验 owner 并原子绑定到
    # session 后才透传；Runtime 侧只读执行上下文，不再信任模型传参。
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    # 附件元数据清单（Backend 验主+绑定后构建，Runtime 注入模型上下文）。
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=5)
    # NX-LB3：请求幂等键。Runtime 以 (user, session, client_request_id) 去重：
    # 重试不重复调用模型/工具；不同请求竞争同一会话写者时 409 SESSION_BUSY。
    client_request_id: str = Field(default="", max_length=64)


def _reject_unknown_fields(model: type[BaseModel], payload: Any) -> None:
    """NX-LB4/回归修复：写入类接口拒绝未声明字段（422），但容忍签名键。

    前端 request.js 会把 time/enc 注入 POST/PATCH body（签名中间件契约），
    因此不能用 pydantic extra=forbid（会把签名键一起 422，线上 E2E 实证）。
    本助手保留同等防护：除声明字段与 {time, enc} 外的任何字段一律 422。
    """
    if not isinstance(payload, dict):
        return
    known = set(model.model_fields) | {"time", "enc"}
    unknown = sorted(set(payload) - known)
    if unknown:
        reject(422, "REQUEST_FIELD_UNKNOWN",
               f"不接受未声明字段：{', '.join(unknown[:10])}")


# NX-G1：mode 别名表镜像（见 NexusChatRequest 注释；与 nexus.agent 保持同构，
# 改动时两边同步）。None 缺字段→general；未知（含空串/空白）→ 400。
_NEXUS_GENERAL_ALIASES = frozenset({"general", "nexus_general"})
_NEXUS_RESEARCH_ALIASES = frozenset({"research", "nexus_research"})


def _require_valid_mode(raw: str | None) -> str:
    """校验请求 mode；非法值 reject 400 INVALID_NEXUS_MODE。"""
    if raw is None:
        return "general"
    cleaned = raw.strip().lower() if isinstance(raw, str) else ""
    if cleaned in _NEXUS_GENERAL_ALIASES:
        return "general"
    if cleaned in _NEXUS_RESEARCH_ALIASES:
        return "research"
    reject(400, "INVALID_NEXUS_MODE", f"未知的 Nexus 模式：{raw!r}（仅支持 general/research）")


# T2：执行模式别名镜像（与 nexus.execution_mode 同构，两进程不共享 Python
# 环境故不能 import；改动时两边同步）。未知值两模式一致 400。
_NEXUS_EXECUTION_MODES = frozenset({"ask", "auto"})


def _require_valid_execution_mode(raw: str | None) -> str | None:
    """校验 research_execution_mode；未知值 reject 400（缺字段→None 透传）。"""
    if raw is None:
        return None
    cleaned = raw.strip().lower() if isinstance(raw, str) else ""
    if cleaned in _NEXUS_EXECUTION_MODES:
        return cleaned
    reject(400, "INVALID_RESEARCH_EXECUTION_MODE",
           f"未知的执行模式：{raw!r}（仅支持 ask/auto）")


def _require_attachments(
    session, current_user: dict, session_id: str, attachment_ids: list[str]
) -> tuple[list[str], list[dict]]:
    """NX-A1：对话引用附件的验主 + 原子绑定（执行前完成，不依赖 Runtime）。

    - 每个 id 验 owner（非 owner/不存在 → 404，不区分）；
    - 未绑定 → 绑定到本 session；已绑他会话 → 403；
    - 不可用状态（failed/expired/deleted）→ 422。
    返回 (清洗后的 id 列表, 附件元数据清单)。清单随 payload 透传给 Runtime
    注入模型上下文——模型必须知道附件 id 才能调用 read_attachment
    （2026-09-06 线上验收：只透传 id 时模型无从得知附件存在）。
    """
    from app.services import nexus_attachment_service
    from app.services.nexus_attachment_parse import AttachmentParseError

    user_id = _artifact_user_id(current_user)
    session_id = (session_id or "").strip()[:128] or "default"
    clean: list[str] = []
    manifest: list[dict] = []
    for raw in attachment_ids or []:
        aid = (raw or "").strip()[:16]
        if not aid or aid in clean:
            continue
        row = nexus_attachment_service.get_owned_attachment(
            session, user_id=user_id, attachment_id=aid
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
        try:
            nexus_attachment_service.bind_session(
                session, user_id=user_id, attachment_id=aid, session_id=session_id
            )
        except AttachmentParseError as error:
            if error.code == "ATTACHMENT_SESSION_MISMATCH":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail=error.code
                ) from error
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error.code
            ) from error
        clean.append(aid)
        manifest.append({
            "attachment_id": row["attachment_id"],
            "filename": row["filename"],
            "mime": row["mime"],
            "size_bytes": row["size_bytes"],
            "ocr": (row.get("stats") or {}).get("ocr", ""),
            "vision": (row.get("stats") or {}).get("vision", ""),
        })
    return clean, manifest


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


# ---------------------------------------------------------------------------
# NX-LB3：会话内运行引用（context.run_ref）→ 服务端白名单投影。
# 客户端只提交 run/step 标识；日志、退出码、指标等执行事实一律由本层从
# 归属校验后的 Worker 记录生成——客户端提交的任何"执行结果"不被采信。
# ---------------------------------------------------------------------------

_RUN_CTX_LOG_LINES = 40
_RUN_CTX_LOG_CHARS = 8000


def _bounded_log_tail(text: Any) -> dict[str, Any]:
    """有界日志切片（最近 ≤40 行且 ≤8000 字符）＋真实行数/截断标记。"""
    raw = _sanitize_log(text, limit=_RUN_CTX_LOG_CHARS * 100)
    all_lines = raw.splitlines()
    truncated = len(all_lines) > _RUN_CTX_LOG_LINES
    shown = all_lines[-_RUN_CTX_LOG_LINES:] if truncated else all_lines
    body = "\n".join(shown)
    if len(body) > _RUN_CTX_LOG_CHARS:
        body = body[-_RUN_CTX_LOG_CHARS:]
        truncated = True
    return {"text": body, "lines": len(shown), "total_lines": len(all_lines),
            "truncated": truncated}


def _resolve_run_ref(session, current_user: dict, session_id: str, run_ref: Any) -> tuple[dict, int | None]:
    """归属三重校验：本人（404 不区分）→ 同会话（403）→ step 标识（422）。"""
    from app.services import nexus_run_service

    if not isinstance(run_ref, dict) or not str(run_ref.get("run_id") or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="RUN_REF_INVALID")
    run_id = str(run_ref["run_id"]).strip()[:64]
    step_id: int | None = None
    step_raw = run_ref.get("step_id")
    if step_raw is not None and str(step_raw).strip() != "":
        try:
            step_id = int(step_raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="STEP_NOT_FOUND") from exc
        if step_id < 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="STEP_NOT_FOUND")
    run = nexus_run_service.get_owned_run(
        session, user_id=_artifact_user_id(current_user), run_id=run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RUN_NOT_FOUND")
    if (run["session_id"] or "") != session_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="RUN_SESSION_MISMATCH")
    return run, step_id


async def _build_run_context(
    session, current_user: dict, session_id: str, run_ref: Any
) -> dict[str, Any]:
    """生成注入聊天上下文的运行快照白名单投影（有界、脱敏、无凭据/路径）。"""
    run, step_id = _resolve_run_ref(session, current_user, session_id, run_ref)
    if _run_provider(run) == "autonomous":
        return await _build_autonomous_run_context(
            session, current_user, run, step_id)
    live = await _live_job_status(run["job_id"]) if run["job_id"] else None
    merged = _merge_run_live(run, live)
    live_view = merged.get("live") or {}
    context: dict[str, Any] = {
        "run_id": run["run_id"],
        "run_number": run["run_number"],
        "display_title": run["display_title"],
        "preset_id": run["preset_id"],
        "paper_title": run["paper_title"],
        "status": live_view.get("status", "unknown"),
        "status_source": merged.get("status_source"),
        "stale": merged.get("stale"),
        "observed_at": merged.get("observed_at"),
        "note": str(live_view.get("note") or ""),
        "code": live_view.get("code"),
        "detail": live_view.get("detail"),
    }
    steps: list[dict[str, Any]] = []
    if live and not live.get("missing"):
        context["stage_events"] = _trim_job_record(live).get("stage_events", [])
        context["current_step"] = live.get("current_step")
        for idx, step in enumerate((live.get("steps_result") or [])[:_STEP_MAX]):
            steps.append({
                "index": idx,
                "command": str(step.get("command") or "")[:160],
                "exit_code": step.get("exit_code"),
                "timed_out": step.get("timed_out"),
                "duration_s": step.get("duration_s"),
                "log": _bounded_log_tail(step.get("log_tail")),
            })
    if step_id is not None:
        if step_id >= len(steps):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="STEP_NOT_FOUND")
        context["step_ref"] = step_id
        context["steps"] = [steps[step_id]]
    else:
        context["steps"] = steps
    return context


async def _build_autonomous_run_context(
    session, current_user: dict, run: dict[str, Any], step_id: int | None,
) -> dict[str, Any]:
    """自主 run 的聊天上下文投影：attempt 即步骤（编号/命令摘要/退出码/日志尾）。

    状态取 Runtime console（running/reconciling/终态）；Runtime 失联回落
    登记快照并标 stale，不伪造执行事实。step_id 索引 attempts（越界 422）。
    """
    console = await _runtime_console_snapshot(
        run["run_id"], _artifact_user_id(current_user))
    attempts = (console or {}).get("attempts", []) if console else []
    console_status = (console or {}).get("console_status", "unknown") if console else "unknown"
    steps: list[dict[str, Any]] = []
    for idx, attempt in enumerate(attempts[:_STEP_MAX]):
        steps.append({
            "index": idx,
            "attempt_no": attempt.get("attempt_no", idx + 1),
            "command": str(attempt.get("command_summary") or "")[:160],
            "exit_code": attempt.get("exit_code"),
            "timed_out": None,
            "duration_s": attempt.get("duration_s"),
            "log": _bounded_log_tail(attempt.get("log_tail")),
        })
    if step_id is not None:
        if step_id >= len(steps):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="STEP_NOT_FOUND")
        picked = [steps[step_id]]
    else:
        picked = steps
    return {
        "run_id": run["run_id"],
        "run_number": run["run_number"],
        "display_title": run["display_title"],
        "preset_id": run["preset_id"],
        "provider": "autonomous",
        "paper_title": run["paper_title"],
        "status": console_status,
        "status_source": "live" if console else "snapshot",
        "stale": console is None,
        "observed_at": None,
        "note": ("" if console
                 else "执行器不可达，显示登记快照"),
        "code": None,
        "detail": (console or {}).get("detail", ""),
        "steps": picked,
    }


async def _inject_run_context(payload: NexusChatRequest, session, current_user: dict) -> None:
    """把客户端 run_ref 替换为服务端白名单投影（客户端提交的执行事实不透传）。

    run_ref 缺省（None）时保留 context 其余键原样（如 course_id）；客户端
    自带的 run_context 键一律丢弃，投影只由本层生成。
    """
    context = dict(payload.context or {})
    run_ref = context.pop("run_ref", None)
    context.pop("run_context", None)
    if run_ref is not None:
        context["run_context"] = await _build_run_context(
            session, current_user, payload.session_id, run_ref)
    payload.context = context or None


@router.post("/chat")
async def nexus_chat(
    payload: NexusChatRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """非流式对话：等待 Agent 循环结束后一次性返回最终答复与工具事件。"""
    _require_valid_mode(payload.mode)
    _require_valid_execution_mode(payload.research_execution_mode)
    payload.attachment_ids, payload.attachments = _require_attachments(
        session, current_user, payload.session_id, payload.attachment_ids
    )
    await _inject_run_context(payload, session, current_user)
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


class NexusExecutionModeBody(BaseModel):
    research_execution_mode: str = Field(min_length=1, max_length=16)


@router.put("/sessions/{session_id}/execution-mode")
async def nexus_session_execution_mode_save(
    session_id: str,
    payload: NexusExecutionModeBody,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """T2：保存用户明确选择的 Research 执行模式（Ask/Auto；未知值 400）。"""
    _require_valid_execution_mode(payload.research_execution_mode)
    return await _proxy_json(
        request, current_user, "PUT",
        f"/api/v1/nexus/sessions/{session_id}/execution-mode",
        body=payload.model_dump(),
    )


@router.get("/sessions/{session_id}/execution-mode")
async def nexus_session_execution_mode_get(
    session_id: str,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """T2：读取服务端会话偏好（无记录默认 Ask；纯读取）。"""
    return await _proxy_json(
        request, current_user, "GET",
        f"/api/v1/nexus/sessions/{session_id}/execution-mode",
    )


@router.get("/plan/{session_id}")
async def nexus_plan_snapshot(
    session_id: str,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """NX-H1 计划快照反代：鉴权/身份注入与 messages 同链（require_nexus_use
    + 反代注入用户身份，Runtime 侧 thread_for 命名空间隔离）。只读投影，
    不触发执行。"""
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
                f"{base}/api/v1/nexus/plan/{session_id}",
                headers=_upstream_headers(current_user, request),
            )
    except httpx.TimeoutException as error:
        logger.warning("Nexus runtime plan snapshot timeout: %s", error)
        return _timeout(str(error))
    except httpx.HTTPError as error:
        logger.warning("Nexus runtime plan snapshot unreachable: %s", error)
        return _unavailable(str(error))
    return _passthrough(response)


# ---------------------------------------------------------------------------
# M3 Artifact：Backend 原生路由（非透传）——元数据在 nexus_checkpoints
# schema（P1 验收后 ai_course_app 可读写），文件字节经对象存储直出，
# 不穿过 Runtime 进程（偏离计划 M3-B2 原文，理由见计划文档偏离记录）。
# ---------------------------------------------------------------------------


def _artifact_user_id(current_user: dict) -> str:
    return str(current_user.get("user_id"))


@router.get("/artifacts")
async def nexus_artifacts_list(
    limit: int = 50,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """当前用户产物列表（M3-B2，owner 过滤）。

    与其余 /api/v1/nexus/* 路由一致返回裸 JSON（无 code/message 信封），
    前端 allowFlatResponse 消费。
    """
    from app.services import nexus_artifact_service

    items = nexus_artifact_service.list_artifacts(
        session, user_id=_artifact_user_id(current_user), limit=limit
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"items": items},
    )


@router.get("/artifacts/{artifact_id}/download")
async def nexus_artifact_download(
    artifact_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """产物下载（M3-B2）：owner 校验后经对象存储直出文件。非 owner 返回 404
    （列表不可见即不存在，防枚举探测）。"""
    from app.services import nexus_artifact_service
    from fastapi.responses import FileResponse
    from app.services.object_storage import get_object_storage

    artifact = nexus_artifact_service.get_owned_artifact(
        session, user_id=_artifact_user_id(current_user), artifact_id=artifact_id
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产物不存在")
    storage = get_object_storage()
    try:
        path = storage._safe_full_path(artifact["object_key"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="object_key 不安全") from exc
    mime, filename = nexus_artifact_service.mime_and_filename(artifact)
    return FileResponse(path=path, media_type=mime, filename=filename)


# ---------------------------------------------------------------------------
# M4：复现体验闭环——job 状态查询代理 + 报告生成代理
# 归属鉴权（发起人）由 nexus_repro_jobs 域表裁决；Worker 本体不暴露公网。
# ---------------------------------------------------------------------------

# 日志摘要上限：只展示操作状态与安全日志摘要（计划 §8 M4-F1）。
_LOG_TAIL_MAX = 2000
_STEP_MAX = 10
_STAGE_EVENTS_MAX = 60
# NX-E2：日志控制符清洗；审查 F2（2026-09-07）补齐真实脱敏——仅删控制字符
# 不等于脱敏，凭据类内容必须在进入外发/持久化路径前遮蔽。
_LOG_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# ANSI 转义序列：CSI / OSC（含终止符；未终止的 OSC 不吞正文）/ 其余 C1。
# 必须在控制符删除**之前**执行，否则 ESC 被删后序列残骸（如 [0;31m）会留在日志里。
_LOG_ANSI_ESCAPE = re.compile(
    r"\x1b(?:"
    r"\[[0-9;?<>=!]*[ -/]*[@-~]"
    r"|\][^\x07\x1b]{0,256}(?:\x07|\x1b\\)"
    r"|[@-Z\\-_]"
    r")"
)
_LOG_URL_USERINFO = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)([^\s/@:]+):([^\s/@]+)@")
_LOG_URL_USER = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)([^\s/@]+)@")
_LOG_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/_\-]{8,}")
_LOG_AUTH_HEADER = re.compile(r"(?i)\b(authorization|proxy-authorization|cookie)(\s*[:=]\s*)[^\n]{0,512}")
# 键值型密钥：token 用 (?!s) 排除复数 tokens（训练日志常见计数指标），\b 排除
# token_xxx/max_token 等复合词；值需 ≥4 连续非空白字符，普通指标不受影响。
_LOG_KV_SECRET = re.compile(
    r"(?i)\b(api[-_]?key|apikey|access[-_]?token|auth[-_]?token|secret[-_]?key|"
    r"client[-_]?secret|private[-_]?key|passphrase|password|passwd|pwd|secret|token)(?!s)"
    r"(\s*[:=]\s*)([\"']?)[^\s\"',;]{4,}"
)
_LOG_KNOWN_TOKEN = re.compile(
    r"(?i)\b(sk-[a-z0-9]{16,}|gh[pousrn]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|"
    r"hf_[a-z0-9]{20,}|xox[baprs]-[a-z0-9-]{10,}|akia[0-9a-z]{16}|"
    r"eyJ[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}\.[a-z0-9_-]{5,})"
)


def _redact_secrets(text: str) -> str:
    """遮蔽凭据类内容与 ANSI 转义序列。

    Worker 侧（deploy/repro-worker/worker.py `_redact_secrets`）为同源独立
    实现——独立容器不共享代码，模式修改须两处同步。
    """
    text = _LOG_ANSI_ESCAPE.sub("", text)
    text = _LOG_BEARER.sub("Bearer ***", text)
    text = _LOG_AUTH_HEADER.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    text = _LOG_KV_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}***", text)
    text = _LOG_KNOWN_TOKEN.sub("***", text)
    text = _LOG_URL_USERINFO.sub(r"\1***:***@", text)
    return _LOG_URL_USER.sub(r"\1***@", text)


def _sanitize_log(text: Any, limit: int = _LOG_TAIL_MAX) -> str:
    # 先脱敏（ANSI 正则依赖完整转义序列），再删残留控制符，最后截尾。
    cleaned = _redact_secrets(str(text or ""))
    cleaned = _LOG_CONTROL_CHARS.sub("", cleaned)
    return cleaned[-limit:]


# F1：Worker cancel 端点可能返回的状态词；缺失/未知一律 502，不默认 cancelling。
_CANCEL_KNOWN_STATUSES = {"cancelling", "cancelled", "succeeded", "failed", "rejected"}


def _worker_base() -> str:
    return (settings.REPRO_WORKER_URL or "").rstrip("/")


def _trim_job_record(record: dict) -> dict:
    """裁剪 Worker 记录为前端展示形态：短日志摘要 + 阶段切片，不回传全文。

    NX-E2：透传 stage_events（真实边界事件，封顶 _STAGE_EVENTS_MAX）与
    live_log_tail（运行中当前步骤增量日志）；所有日志经控制符清洗与限长。
    """
    trimmed = {
        "job_id": record.get("job_id"),
        "status": record.get("status"),
        "preset_id": record.get("preset_id"),
        "repo_url": record.get("repo_url"),
        "requested_license": record.get("requested_license"),
        "license_checks": record.get("license_checks"),
        "seed_used": record.get("seed_used"),
        "submitted_at": record.get("submitted_at"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "code": record.get("code"),
        "detail": record.get("detail"),
        "steps_result": [],
        "artifacts": record.get("artifacts") or [],
        "stage_events": [],
        "current_step": record.get("current_step"),
        "live_log_tail": _sanitize_log(record.get("live_log_tail")),
    }
    for event in (record.get("stage_events") or [])[-_STAGE_EVENTS_MAX:]:
        trimmed["stage_events"].append({
            "seq": event.get("seq"),
            "stage": str(event.get("stage") or "")[:32],
            "status": str(event.get("status") or "")[:32],
            "note": str(event.get("note") or "")[:200] or None,
            "time": event.get("time"),
        })
    for step in (record.get("steps_result") or [])[:_STEP_MAX]:
        trimmed["steps_result"].append({
            "command": str(step.get("command") or "")[:160],
            "exit_code": step.get("exit_code"),
            "timed_out": step.get("timed_out"),
            "duration_s": step.get("duration_s"),
            "log_tail": _sanitize_log(step.get("log_tail")),
        })
    return trimmed


def _owned_job_or_404(session, current_user: dict, job_id: str) -> dict:
    from app.services import nexus_repro_job_service

    job = nexus_repro_job_service.get_owned_job(
        session, job_id=job_id, user_id=_artifact_user_id(current_user)
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="复现作业不存在")
    return job


@router.get("/repro/jobs/{job_id}")
async def nexus_repro_job_status(
    job_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """作业状态查询（M4-B1）：发起人鉴权后代理 Worker 记录（裁剪版）。"""
    _owned_job_or_404(session, current_user, job_id)
    base = _worker_base()
    if not base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="REPRO_WORKER_NOT_CONFIGURED"
        )
    timeout = httpx.Timeout(15.0, connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base}/jobs/{job_id}",
                headers={"Authorization": f"Bearer {settings.REPRO_WORKER_TOKEN}"}
                if settings.REPRO_WORKER_TOKEN
                else {},
            )
    except httpx.HTTPError as error:
        logger.warning("repro worker unreachable: %s", error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="REPRO_WORKER_UNAVAILABLE"
        ) from error
    if response.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="复现作业不存在")
    try:
        record = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Worker 返回非 JSON"
        ) from exc
    return JSONResponse(status_code=200, content=_trim_job_record(record))


async def _worker_cancel(job_id: str) -> dict[str, Any]:
    """Worker 取消核心（NX-E3 代理与 NX-LB4 内部取消共用）。

    审查 F1 语义保留：任何**非成功**响应如实上抛；成功响应校验作业身份
    与已知状态词。取消语义（幂等/竞争终态）仍由 Worker 裁决。
    """
    base = _worker_base()
    if not base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="REPRO_WORKER_NOT_CONFIGURED"
        )
    timeout = httpx.Timeout(15.0, connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base}/jobs/{job_id}/cancel",
                headers={"Authorization": f"Bearer {settings.REPRO_WORKER_TOKEN}"}
                if settings.REPRO_WORKER_TOKEN
                else {},
            )
    except httpx.HTTPError as error:
        logger.warning("repro worker cancel unreachable: %s", error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="REPRO_WORKER_UNAVAILABLE"
        ) from error
    if response.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="复现作业不存在")
    if response.status_code != 200:
        logger.warning(
            "repro worker cancel http %s for job %s", response.status_code, job_id
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="REPRO_CANCEL_UPSTREAM_ERROR"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Worker 返回非 JSON"
        ) from exc
    if not isinstance(payload, dict) or payload.get("job_id") != job_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="REPRO_CANCEL_IDENTITY_MISMATCH"
        )
    cancel_status = payload.get("status")
    if cancel_status not in _CANCEL_KNOWN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="REPRO_CANCEL_UNKNOWN_STATUS"
        )
    return {"status": cancel_status,
            "already_terminal": bool(payload.get("already_terminal"))}


@router.post("/repro/jobs/{job_id}/cancel")
async def nexus_repro_job_cancel(
    job_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """NX-E3 取消代理：发起人鉴权（归属 = nexus_runs 登记）后转发 Worker。

    审查 F1（2026-09-07）：本层对 Worker 的任何**非成功**响应如实上抛——
    404 透传、401/5xx/非 JSON 一律 502，绝不把上游失败包装成"已接受取消"。
    """
    _owned_job_or_404(session, current_user, job_id)
    result = await _worker_cancel(job_id)
    return JSONResponse(status_code=200, content={
        "job_id": job_id,
        "status": result["status"],
        "already_terminal": result["already_terminal"],
    })


@router.post("/repro/jobs/{job_id}/report")
async def nexus_repro_job_report(
    job_id: str,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """报告生成代理（M4-B3）：确定性判定在 Runtime（预设期望指标所在地），
    本层只做发起人鉴权与用户身份透传，LLM 不参与 PASS/FAIL。"""
    _owned_job_or_404(session, current_user, job_id)
    base = _runtime_base_url()
    if not base:
        return _not_configured()
    timeout = httpx.Timeout(settings.NEXUS_RUNTIME_TIMEOUT_S, connect=settings.NEXUS_RUNTIME_CONNECT_TIMEOUT_S)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base}/api/v1/nexus/repro/jobs/{job_id}/report",
                headers=_upstream_headers(current_user, request),
            )
    except httpx.TimeoutException as error:
        logger.warning("repro report timeout: %s", error)
        return _timeout(str(error))
    except httpx.HTTPError as error:
        logger.warning("repro report unreachable: %s", error)
        return _unavailable(str(error))
    return _passthrough(response)


# ---------------------------------------------------------------------------
# NX-G2：执行审批代理——批准/查询走 Runtime 审批存储，身份由本层门控注入。
# 本层不解析票据语义：批准是否有效由 Runtime 原子核销裁决，此处只做
# require_nexus_use 门控与用户身份透传（跨用户/过期/篡改由上游按码拒绝）。
# ---------------------------------------------------------------------------


class NexusApprovalDecision(BaseModel):
    decision: str = Field(default="approved", max_length=16)


class NexusApprovalExecute(BaseModel):
    approval_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(default="default", max_length=128)
    # T2 Ask/Auto 执行门：启动须 Research+Auto+本人批准（Runtime 执行核裁决，
    # 本层透传；未知值 400；缺字段时旧 preset 票据兼容，自主票据 fail-closed）。
    mode: str | None = Field(default=None, max_length=32)
    research_execution_mode: str | None = Field(default=None, max_length=16)


async def _proxy_json(
    request: Request,
    current_user: dict,
    method: str,
    upstream_path: str,
    body: dict | None = None,
):
    """通用 JSON 透传（审批端点族）：fail-closed + 上游语义原样返回。"""
    base = _runtime_base_url()
    if not base:
        return _not_configured()
    timeout = httpx.Timeout(
        settings.NEXUS_RUNTIME_TIMEOUT_S, connect=settings.NEXUS_RUNTIME_CONNECT_TIMEOUT_S
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                f"{base}{upstream_path}",
                json=body,
                headers=_upstream_headers(current_user, request),
            )
    except httpx.TimeoutException as error:
        logger.warning("Nexus approval proxy timeout: %s", error)
        return _timeout(str(error))
    except httpx.HTTPError as error:
        logger.warning("Nexus approval proxy unreachable: %s", error)
        return _unavailable(str(error))
    return _passthrough(response)


@router.get("/approvals")
async def nexus_approvals_list(
    request: Request,
    session_id: str = "",
    status: str = "pending",
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB2：审批待办恢复（输入框浮窗用）：本人的待办＋提案摘要。

    查询串原样透传（session_id/status），语义由 Runtime 裁决；
    status 非法由上游 422。
    """
    from urllib.parse import urlencode

    query = urlencode({
        "session_id": (session_id or "").strip()[:128],
        "status": (status or "pending").strip()[:16],
    })
    return await _proxy_json(
        request, current_user, "GET", f"/api/v1/nexus/approvals?{query}"
    )


@router.get("/approvals/{approval_id}")
async def nexus_approval_status(
    approval_id: str,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """审批状态查询代理（NX-G2）：本人查询，跨用户上游 404。"""
    return await _proxy_json(
        request, current_user, "GET", f"/api/v1/nexus/approvals/{approval_id}"
    )


@router.post("/approvals/{approval_id}/decide")
async def nexus_approval_decide(
    approval_id: str,
    payload: NexusApprovalDecision,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """批准/拒绝代理（NX-G2）：决定动作本人发起，上游原子转换。"""
    return await _proxy_json(
        request,
        current_user,
        "POST",
        f"/api/v1/nexus/approvals/{approval_id}/decide",
        body=payload.model_dump(),
    )


@router.post("/repro/execute")
async def nexus_repro_execute(
    payload: NexusApprovalExecute,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """手工执行代理（NX-G2）：凭已批准票据提交 Worker，与聊天工具共用
    Runtime 侧同一核销核心；幂等语义由上游保证（重试返回原 job）。
    T2：mode/research_execution_mode 透传执行门（未知值 400）。
    修复 A3：显式 Ask 在此直接拒绝（与 Runtime 同码），零转发零提交——
    后端与工具两侧各自校验；未显式传值仍交 Runtime 按会话偏好裁决。"""
    mode = _require_valid_mode(payload.mode)
    execution_mode = _require_valid_execution_mode(payload.research_execution_mode)
    if mode == "research" and execution_mode is not None and execution_mode != "auto":
        reject(403, "EXPERIMENT_EXECUTION_DISABLED",
               "Research Ask 模式不执行实验（仅 Auto 可执行）。")
    return await _proxy_json(
        request,
        current_user,
        "POST",
        "/api/v1/nexus/repro/execute",
        body=payload.model_dump(),
    )


@router.get("/repro/presets")
async def nexus_repro_presets(
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB1：可见 preset 投影（display/论文/仓库/环境/参数schema/预算/指标）。

    Backend 经内部 HTTP 查询 Runtime，不跨 Python 环境 import preset；
    只读，无凭据、内部路径、任意命令入口。
    """
    return await _proxy_json(
        request, current_user, "GET", "/api/v1/nexus/repro/presets"
    )


class NexusProposalCreate(BaseModel):
    """NX-LB2 提案创建（字段与 Runtime ProposalCreate 同构，原样透传）。

    T2：kind 缺省 preset；kind=autonomous_experiment 时消费 scope，
    preset_id 可空。
    """

    preset_id: str = Field(default="", max_length=64)
    session_id: str = Field(default="default", max_length=128)
    parent_run_id: str = Field(default="", max_length=64)
    objective: str = Field(default="", max_length=500)
    parameters: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    client_request_id: str = Field(default="", max_length=64)
    kind: str = Field(default="preset", max_length=32)
    scope: dict[str, Any] | None = Field(default=None)


class NexusProposalPatch(BaseModel):
    """NX-LB2 提案修改。

    extra=allow：签名键 time/enc 随 body 进来（前端 request.js 契约），
    未声明字段由 _reject_unknown_fields 422；转发上游时排除全部 extras
    （Runtime 侧 extra=forbid 仍兜底）。
    """

    expected_version: int = Field(ge=1)
    objective: str | None = Field(default=None, max_length=500)
    parameters: dict[str, Any] | None = None
    # T2：自主提案改 scope（preset 提案传 scope 由 Runtime 422）。
    scope: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


class NexusProposalRequestApproval(BaseModel):
    expected_version: int = Field(ge=1)


@router.post("/repro/proposals")
async def nexus_proposal_create(
    payload: NexusProposalCreate,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB2：建结构化提案草案（不执行；client_request_id 幂等）。"""
    return await _proxy_json(
        request, current_user, "POST", "/api/v1/nexus/repro/proposals",
        body=payload.model_dump(),
    )


@router.get("/repro/proposals/{proposal_id}")
async def nexus_proposal_detail(
    proposal_id: str,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB2：提案完整方案＋校验结果＋与父运行/上一版本的 diff。"""
    return await _proxy_json(
        request, current_user, "GET",
        f"/api/v1/nexus/repro/proposals/{proposal_id}",
    )


@router.patch("/repro/proposals/{proposal_id}")
async def nexus_proposal_patch(
    proposal_id: str,
    payload: NexusProposalPatch,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB2：改提案（乐观锁；仅 draft；旧批准随 hash 失效）。"""
    _reject_unknown_fields(NexusProposalPatch, payload.model_dump())
    return await _proxy_json(
        request, current_user, "PATCH",
        f"/api/v1/nexus/repro/proposals/{proposal_id}",
        body=payload.model_dump(exclude_none=True,
                                exclude=set(payload.model_extra or {})),
    )


@router.post("/repro/proposals/{proposal_id}/request-approval")
async def nexus_proposal_request_approval(
    proposal_id: str,
    payload: NexusProposalRequestApproval,
    request: Request,
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB2：pin 住版本+hash 生成/复用审批（不直接执行）。"""
    return await _proxy_json(
        request, current_user, "POST",
        f"/api/v1/nexus/repro/proposals/{proposal_id}/request-approval",
        body=payload.model_dump(),
    )


# ---------------------------------------------------------------------------
# NX-A1：附件入口（Backend 原生路由，非透传）——上传/状态/删除/鉴权下载。
# 元数据进 nexus_checkpoints.nexus_attachments，字节进对象存储；
# 内容永不进入课程知识域，只进会话上下文（经 chat attachment_ids 绑定）。
# ---------------------------------------------------------------------------


def _attachment_public(row: dict[str, Any]) -> dict[str, Any]:
    """公开投影：不含 object_key/parsed_key 等内部定位（防越权拼装）。"""
    return {
        "attachment_id": row["attachment_id"],
        "filename": row["filename"],
        "ext": row["ext"],
        "mime": row["mime"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "session_id": row["session_id"],
        "status": row["status"],
        "error_code": row["error_code"],
        "error_detail": row["error_detail"],
        "stats": row["stats"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
        "download_path": f"/api/v1/nexus/attachments/{row['attachment_id']}/download",
    }


@router.post("/attachments")
async def nexus_attachment_upload(
    file: UploadFile = File(...),
    session_id: str = Form(default=""),
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """上传附件（multipart）：校验→配额→解析→ready/partial/failed 同步返回。

    八格式：pdf/docx/jpg/jpeg/png/xlsx/pptx/ppt/doc。DOC/PPT 无 LibreOffice
    时如实 failed（CONVERT_UNAVAILABLE），目标保留。解析失败同样落库 failed
    行（错误码明确），不抛 500——调用方可凭错误码决定重试/删除/换格式。
    """
    import asyncio

    from app.services import nexus_attachment_service
    from app.services.nexus_attachment_parse import AttachmentParseError

    try:
        content = await file.read()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ATTACHMENT_READ_FAILED"
        ) from error
    if len(content) == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="ATTACHMENT_EMPTY")
    try:
        # 解析预算内为秒级；仍放线程池，避免阻塞事件循环。
        row = await asyncio.to_thread(
            nexus_attachment_service.submit_attachment,
            session,
            user_id=_artifact_user_id(current_user),
            filename=file.filename or "attachment",
            data=content,
            session_id=(session_id or "").strip()[:128],
        )
    except AttachmentParseError as error:
        code_to_status = {
            "ATTACHMENT_TYPE_UNSUPPORTED": 422,
            "ATTACHMENT_EMPTY": 422,
            "ATTACHMENT_TOO_LARGE": 413,
            "ATTACHMENT_QUOTA_FILES": 429,
            "ATTACHMENT_QUOTA_BYTES": 429,
        }
        raise HTTPException(
            status_code=code_to_status.get(error.code, 422), detail=error.code
        ) from error
    return JSONResponse(status_code=200, content=_attachment_public(row))


@router.get("/attachments")
async def nexus_attachment_list(
    session_id: str = "",
    limit: int = 50,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """我的附件列表（更新时间倒序；可按会话过滤未绑定+本会话）。"""
    from app.services import nexus_attachment_service

    items = nexus_attachment_service.list_attachments(
        session, user_id=_artifact_user_id(current_user),
        session_id=session_id.strip()[:128] or None, limit=limit,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"items": [_attachment_public(r) for r in items]},
    )


@router.get("/attachments/{attachment_id}")
async def nexus_attachment_detail(
    attachment_id: str,
    include_blocks: bool = False,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """附件元数据；include_blocks=1 附带预算内解析 blocks（文本预览用）。"""
    from app.services import nexus_attachment_service
    from app.services.nexus_attachment_parse import AttachmentParseError

    row = nexus_attachment_service.get_owned_attachment(
        session, user_id=_artifact_user_id(current_user), attachment_id=attachment_id
    )
    if row is None or row["status"] == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
    public = _attachment_public(row)
    if include_blocks:
        try:
            public["content"] = nexus_attachment_service.load_parsed_blocks(
                session, user_id=_artifact_user_id(current_user),
                attachment_id=attachment_id,
            )
        except AttachmentParseError as error:
            public["content"] = {"error_code": error.code, "blocks": []}
    return JSONResponse(status_code=status.HTTP_200_OK, content=public)


@router.get("/attachments/{attachment_id}/download")
async def nexus_attachment_download(
    attachment_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """原文件下载（owner 校验；非 owner/不存在/已删/过期一律 404）。"""
    from app.services import nexus_attachment_service
    from app.services.object_storage import get_object_storage
    from fastapi.responses import FileResponse

    row = nexus_attachment_service.get_owned_attachment(
        session, user_id=_artifact_user_id(current_user), attachment_id=attachment_id
    )
    if row is None or row["status"] in ("deleted", "expired"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
    storage = get_object_storage()
    try:
        path = storage._safe_full_path(row["object_key"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="object_key 不安全") from exc
    return FileResponse(path=path, media_type=row["mime"], filename=row["filename"])


@router.delete("/attachments/{attachment_id}")
async def nexus_attachment_delete(
    attachment_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """删除附件：立即撤销读取并尽力清对象；幂等（重复删返回 deleted=true）。"""
    from app.services import nexus_attachment_service

    deleted = nexus_attachment_service.delete_attachment(
        session, user_id=_artifact_user_id(current_user), attachment_id=attachment_id
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
    return JSONResponse(status_code=status.HTTP_200_OK, content={"deleted": True})


class NexusAttachmentBind(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


@router.post("/attachments/{attachment_id}/bind")
async def nexus_attachment_bind(
    attachment_id: str,
    payload: NexusAttachmentBind,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """绑定会话（未绑定→绑定；同会话→幂等；他会话→403）。"""
    from app.services import nexus_attachment_service
    from app.services.nexus_attachment_parse import AttachmentParseError

    try:
        row = nexus_attachment_service.bind_session(
            session, user_id=_artifact_user_id(current_user),
            attachment_id=attachment_id, session_id=payload.session_id.strip(),
        )
    except AttachmentParseError as error:
        status_map = {
            "ATTACHMENT_NOT_FOUND": 404,
            "ATTACHMENT_SESSION_MISMATCH": 403,
            "ATTACHMENT_UNAVAILABLE": 422,
        }
        raise HTTPException(
            status_code=status_map.get(error.code, 422), detail=error.code
        ) from error
    return JSONResponse(status_code=status.HTTP_200_OK, content=_attachment_public(row))


# ---------------------------------------------------------------------------
# NX-E1：run 恢复查询——owner/session/run/job 关联 + Worker 实时态合并。
# 前端刷新/换设备后凭此恢复轮询，绝不重新提交。Worker 无此 job（重启丢内存）
# 或不可达时回落快照并标 stale/unknown，不伪造终态。
# NX-LB1：有界并发批量读取＋整体截止；终态行消费已保存快照（不反复问 Worker）；
# 列表分页（cursor/limit/total）；重命名（乐观锁）；未知数量单列不冒充 0。
# ---------------------------------------------------------------------------

_RUNS_LIVE_CONCURRENCY = 4
_RUNS_LIVE_DEADLINE_S = 10.0


async def _live_job_status(job_id: str) -> dict[str, Any] | None:
    """直问 Worker 取实时态；任何失败返回 None（调用方回落快照）。"""
    base = _worker_base()
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            response = await client.get(
                f"{base}/jobs/{job_id}",
                headers={"Authorization": f"Bearer {settings.REPRO_WORKER_TOKEN}"}
                if settings.REPRO_WORKER_TOKEN
                else {},
            )
    except httpx.HTTPError as error:
        logger.warning("repro worker live status unreachable: %s", error)
        return None
    if response.status_code == 404:
        return {"status": "unknown", "missing": True}
    try:
        return response.json()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# T5：执行 provider 分派（preset Worker vs 自主实验）。
# - preset：既有 Worker 实时态合并（job_id 维度）；
# - autonomous：Backend nexus_runs 只存归属投影，实时态（attempt/状态/日志）
#   经 Runtime console 端点读取；取消经 Runtime cancel 端点。前端绝不直连
#   控制服务。provider 标识与 preset job 命名空间不碰撞（run_id=approval_id
#   全局唯一，两类共用同一 run 表行格式）。
# ---------------------------------------------------------------------------

_AUTONOMOUS_TOOL = "autonomous_experiment"


def _run_provider(run: dict[str, Any]) -> str:
    """run 的执行 provider：autonomous（自主实验）或 preset（旧 Worker）。"""
    if (run.get("tool") or "") == _AUTONOMOUS_TOOL:
        return "autonomous"
    if not (run.get("job_id") or "") and (run.get("proposal_id") or ""):
        return "autonomous"
    return "preset"


async def _runtime_console_snapshot(run_id: str, user_id: Any) -> dict[str, Any] | None:
    """读 Runtime 自主 run 控制台快照；任何失败返回 None（调用方回落快照）。"""
    base = _runtime_base_url()
    if not base:
        return None
    headers = {"Accept": "application/json"}
    if settings.NEXUS_RUNTIME_API_KEY:
        headers["Authorization"] = f"Bearer {settings.NEXUS_RUNTIME_API_KEY}"
    headers["X-Nexus-User-Id"] = str(user_id)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            response = await client.get(
                f"{base}/api/v1/nexus/repro/runs/{run_id}/console",
                headers=headers,
            )
    except httpx.HTTPError as error:
        logger.warning("nexus runtime console unreachable for run %s: %s", run_id, error)
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    snapshot = (payload or {}).get("snapshot")
    return snapshot if isinstance(snapshot, dict) else None


async def _runtime_cancel_run(run_id: str, user_id: Any) -> dict[str, Any]:
    """经 Runtime 取消自主 run（置旗＋操作取消＋回收确认）。

    成功返回 {status, already_terminal}；Runtime 明确拒绝/不可达按码上抛，
    绝不把失败包装成"已取消"。
    """
    base = _runtime_base_url()
    if not base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="NEXUS_RUNTIME_NOT_CONFIGURED"
        )
    headers = {"Accept": "application/json"}
    if settings.NEXUS_RUNTIME_API_KEY:
        headers["Authorization"] = f"Bearer {settings.NEXUS_RUNTIME_API_KEY}"
    headers["X-Nexus-User-Id"] = str(user_id)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.post(
                f"{base}/api/v1/nexus/repro/runs/{run_id}/cancel",
                headers=headers,
            )
    except httpx.HTTPError as error:
        logger.warning("nexus runtime cancel unreachable for run %s: %s", run_id, error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="RUNTIME_CANCEL_UNAVAILABLE"
        ) from error
    if response.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    if response.status_code == 503:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="RUNTIME_CANCEL_UNAVAILABLE"
        )
    if response.status_code != 200:
        logger.warning("nexus runtime cancel http %s for run %s", response.status_code, run_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="RUNTIME_CANCEL_UPSTREAM_ERROR"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Runtime 返回非 JSON"
        ) from exc
    if not isinstance(payload, dict) or payload.get("run_id") != run_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="RUNTIME_CANCEL_IDENTITY_MISMATCH"
        )
    return {"status": payload.get("status", "unknown"),
            "already_terminal": bool(payload.get("already_terminal"))}


def _merge_run_console(
    run: dict[str, Any], console: dict[str, Any],
    observed_at: float | None = None,
) -> dict[str, Any]:
    """自主 run 快照 + Runtime console 合并。

    console_status=reconciling 是显式展示（执行器失联但运行未终止），
    stale=False（这是新鲜的对账结论，不是过期快照）；attempt 投影
    （编号/命令摘要/时长/日志尾/退出码/结果）直接透出供工作台渲染。
    """
    import time as _time

    merged = dict(run)
    now = observed_at if observed_at is not None else _time.time()
    merged["provider"] = "autonomous"
    merged["observed_at"] = now
    merged["config_status"] = _config_status(run)
    merged["attempt_no"] = console.get("attempt_no", merged.get("attempt_no", 0))
    merged["attempts"] = console.get("attempts", [])
    # SR6：干净B结论直通（只读投影；""=未验证/verifying=运行中）。
    merged["clean_status"] = console.get("clean_status", "")
    merged["clean_note"] = console.get("clean_note", "")
    console_status = console.get("console_status", "unknown")
    merged["live"] = {
        "status": console_status,
        "attempt_no": console.get("attempt_no", 0),
        "attempts": console.get("attempts", []),
        "active_operation": console.get("active_operation", ""),
        "detail": console.get("detail", ""),
        "note": ("执行器不可达，显示登记快照；运行未终止，恢复后继续"
                 if console_status == "reconciling" else ""),
        # F2：恢复状态直通（""=未恢复过；UI 只读展示，不分支新枚举）。
        "recovery_status": console.get("recovery_status", ""),
        "completion_reason": console.get("completion_reason", ""),
    }
    merged["status_source"] = "live"
    merged["stale"] = False
    return merged


def _merge_run_live(
    run: dict[str, Any], live: dict[str, Any] | None,
    observed_at: float | None = None,
) -> dict[str, Any]:
    """run 快照 + 实时态合并：live 缺失 → stale 快照 + honest note。

    status_source 标记每个 run 的状态来源（live|snapshot），observed_at 为
    本次合并时间（epoch 秒）；stale=true 表示显示的不是当前事实。
    config_status 标记冻结配置可恢复性：frozen（快照齐全）/
    preset-defaults（老直批运行，参数即预设默认，可重建）/
    unavailable（无快照又无已知预设，不倒灌当前 preset 伪装历史）。
    """
    import time as _time

    merged = dict(run)
    now = observed_at if observed_at is not None else _time.time()
    merged["observed_at"] = now
    merged["config_status"] = _config_status(run)
    if live is None:
        merged["live"] = {"status": "stale", "note": "执行器不可达，显示登记快照"}
        merged["status_source"] = "snapshot"
        merged["stale"] = True
        return merged
    if live.get("missing"):
        merged["live"] = {
            "status": "unknown",
            "note": "执行器无此作业（可能已重启），不可恢复执行，只能查看登记快照",
        }
        merged["status_source"] = "snapshot"
        merged["stale"] = True
        return merged
    merged["live"] = {
        "status": live.get("status", "unknown"),
        "preset_id": live.get("preset_id", run["preset_id"]),
        "started_at": live.get("started_at"),
        "finished_at": live.get("finished_at"),
        "code": live.get("code"),
        "detail": live.get("detail"),
        # NX-E2/E3：恢复视图同样需要阶段事件与当前步骤（只读投影，经 _trim 同源裁剪）。
        "stage_events": _trim_job_record(live).get("stage_events", []),
        "current_step": live.get("current_step"),
    }
    merged["status_source"] = "live"
    merged["stale"] = False
    return merged


def _config_status(run: dict[str, Any]) -> str:
    """冻结配置可恢复性（展示层计算，不改存储）。

    - frozen：config_snapshot 非空（LB1 后 runs / 提案执行）；
    - preset-defaults：老直批运行（无快照），执行即预设默认参数，可重建；
    - unavailable：无快照又无 preset 指向——不从当前 preset 倒灌成历史事实。
    """
    if run.get("config_snapshot"):
        return "frozen"
    if (run.get("preset_id") or "").strip():
        return "preset-defaults"
    return "unavailable"


async def _merge_runs_live(
    runs: list[dict[str, Any]],
    session: Session | None = None,
) -> list[dict[str, Any]]:
    """批量合并实时态：有界并发（4）＋整体截止（10s）。

    终态快照行（succeeded/failed/rejected/cancelled）不再问执行器，直接消费
    快照；超时/失败的行回落 stale 快照——部分失联不能阻塞整个会话列表。
    T5：自主 run 走 Runtime console 分支（attempt 投影＋reconciling 语义）；
    session 传入时做终态快照回写（best-effort）。
    """
    import asyncio
    import time as _time

    from app.services import nexus_run_service

    semaphore = asyncio.Semaphore(_RUNS_LIVE_CONCURRENCY)
    now = _time.time()

    async def _one(run: dict[str, Any]) -> dict[str, Any]:
        if run.get("status") in nexus_run_service.TERMINAL_RUN_STATUSES:
            return _merge_run_live(run, None, observed_at=now) | {
                "status_source": "snapshot",
                "stale": False,
                "provider": _run_provider(run),
                "live": {"status": run.get("status", "unknown"),
                         "note": "终态快照，不再轮询执行器"},
            }
        if _run_provider(run) == "autonomous":
            console = await _runtime_console_snapshot(run["run_id"], run["user_id"])
            if console is None:
                return _merge_run_live(run, None, observed_at=now) | {
                    "provider": "autonomous"}
            merged = _merge_run_console(run, console, observed_at=now)
            # 终态快照回写（best-effort）：Runtime 已终态且与快照不一致时更新。
            console_status = console.get("status")
            if (session is not None
                    and console_status in nexus_run_service.TERMINAL_RUN_STATUSES
                    and console_status != run.get("status")):
                try:
                    nexus_run_service.update_run_status(
                        session, user_id=run["user_id"],
                        run_id=run["run_id"], status=console_status,
                        detail=str(console.get("detail") or "")[:300],
                    )
                except Exception as error:  # noqa: BLE001
                    logger.warning("autonomous run snapshot writeback failed: %s", error)
            return merged
        async with semaphore:
            live = await _live_job_status(run["job_id"]) if run["job_id"] else None
        merged = _merge_run_live(run, live, observed_at=now)
        merged["provider"] = "preset"
        return merged

    try:
        async with asyncio.timeout(_RUNS_LIVE_DEADLINE_S):
            return await asyncio.gather(*(_one(run) for run in runs))
    except TimeoutError:
        logger.warning("runs live merge deadline exceeded, fallback to snapshots")
        return [_merge_run_live(run, None, observed_at=now) for run in runs]


@router.get("/runs")
async def nexus_runs_list(
    session_id: str = "",
    cursor: str = "",
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB1：某会话我的 runs 分页（含实时态合并）：恢复查询入口，不触发任何执行。

    返回 {items, next_cursor, total}；total 为真实 COUNT（未知数量单列，
    失败时抛 503 而不返回 0 冒充）。旧 items 字段全保留（老客户端兼容）。
    """
    from app.services import nexus_run_service

    page = nexus_run_service.list_session_runs_page(
        session, user_id=_artifact_user_id(current_user),
        session_id=session_id.strip()[:128], limit=limit, cursor=cursor.strip()[:128],
    )
    items = await _merge_runs_live(page["items"], session)
    # 终态快照回写（best-effort）：live 为终态且与快照不一致时更新，
    # 下次列表直接消费快照；失败只记日志。
    for run, merged in zip(page["items"], items):
        live_status = (merged.get("live") or {}).get("status")
        if (merged.get("status_source") == "live"
                and live_status in nexus_run_service.TERMINAL_RUN_STATUSES
                and live_status != run.get("status")):
            try:
                nexus_run_service.update_run_status(
                    session, user_id=_artifact_user_id(current_user),
                    run_id=run["run_id"], status=live_status,
                    detail=str((merged.get("live") or {}).get("detail") or "")[:300],
                )
            except Exception as error:  # noqa: BLE001
                logger.warning("run snapshot writeback failed: %s", error)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"items": items, "next_cursor": page["next_cursor"], "total": page["total"]},
    )


@router.get("/runs/{run_id}")
async def nexus_run_detail(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """单个 run 详情（含实时态合并；新字段 display_title/run_number/version/
    parent/proposal/config_snapshot；老字段保留）。非 owner/不存在 → 404。"""
    from app.services import nexus_artifact_service, nexus_run_service

    run = nexus_run_service.get_owned_run(
        session, user_id=_artifact_user_id(current_user), run_id=run_id.strip()[:64]
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    merged = (await _merge_runs_live([run], session))[0]
    # NX-LB5：已授权 Artifact 引用（可下载）；Worker 工作目录文件清单不是
    # 下载链接，不经此字段暴露。
    merged["artifacts"] = nexus_artifact_service.list_run_artifacts(
        session, user_id=_artifact_user_id(current_user), run_id=run["run_id"])
    return JSONResponse(status_code=status.HTTP_200_OK, content=merged)


class NexusRunCancelGrant(BaseModel):
    """NX-LB4：取消授权签发请求（本人＋同会话；一次性、短有效期）。"""

    session_id: str = Field(min_length=1, max_length=128)

    model_config = {"extra": "allow"}


@router.post("/runs/{run_id}/cancel-grant")
async def nexus_run_cancel_grant(
    run_id: str,
    payload: NexusRunCancelGrant,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB4：为"取消该运行"签发一次性授权（用户显式确认动作）。

    授权绑定 (user, run, action=cancel_run)＋会话＋TTL（默认 300s）；
    Agent 的 cancel_reproduction_run 工具经内部端点核销后才会真正取消。
    模型参数无法伪造授权——grant 只由本端点（登录态）签发。
    """
    from app.services import nexus_action_grant_service, nexus_run_service

    _reject_unknown_fields(NexusRunCancelGrant, payload.model_dump())
    run = nexus_run_service.get_owned_run(
        session, user_id=_artifact_user_id(current_user), run_id=run_id.strip()[:64]
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    if (run["session_id"] or "") != payload.session_id.strip()[:128]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="RUN_SESSION_MISMATCH")
    grant = nexus_action_grant_service.create_grant(
        session, user_id=_artifact_user_id(current_user),
        session_id=payload.session_id.strip()[:128], run_id=run["run_id"],
        action="cancel_run",
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=grant)


class NexusRunNoteCreate(BaseModel):
    """NX-LB5：追加运行备注（request_id 幂等；content ≤4000 字符）。"""

    content: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(default="", max_length=64)

    model_config = {"extra": "allow"}


@router.post("/runs/{run_id}/notes")
async def nexus_run_note_create(
    run_id: str,
    payload: NexusRunNoteCreate,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB5：本人给运行追加备注（author_kind 固定 user，不由客户端指定）。"""
    from app.services import nexus_run_service

    _reject_unknown_fields(NexusRunNoteCreate, payload.model_dump())
    try:
        note = nexus_run_service.add_run_note(
            session, user_id=_artifact_user_id(current_user),
            run_id=run_id.strip()[:64], content=payload.content,
            author_kind="user", request_id=payload.request_id,
        )
    except nexus_run_service.NoteError as error:
        if error.code == "RUN_NOT_FOUND":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="run 不存在") from error
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=error.code) from error
    return JSONResponse(status_code=status.HTTP_200_OK, content=note)


@router.get("/runs/{run_id}/notes")
async def nexus_run_note_list(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB5：某 run 的备注列表（owner 校验；升序；Agent 备注标 author=agent）。"""
    from app.services import nexus_run_service

    items = nexus_run_service.list_run_notes(
        session, user_id=_artifact_user_id(current_user), run_id=run_id.strip()[:64])
    return JSONResponse(status_code=status.HTTP_200_OK, content={"items": items})


@router.post("/runs/{run_id}/report")
async def nexus_run_report(
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """T6：自主 run 报告＋配方生成代理（确定性拼装，不经 LLM）。

    本人终态（succeeded/failed）run 才可生成；产物经 Artifact 链写入并关联
    本 run，可下载；落盘后回收可变工作区。归属校验先行（非本人 404），
    判定语义由 Runtime 原样返回（透传体，无信封改写）。
    """
    from app.services import nexus_run_service

    run = nexus_run_service.get_owned_run(
        session, user_id=_artifact_user_id(current_user), run_id=run_id.strip()[:64]
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    return await _proxy_json(
        request, current_user, "POST",
        f"/api/v1/nexus/repro/runs/{run['run_id']}/report",
    )


class NexusRunCleanVerify(BaseModel):
    """SR6 干净B验证代理体重：只透传执行模式（未知值 400，由门裁决）。

    extra=allow：容忍签名键 time/enc；未声明字段由 _reject_unknown_fields
    422；转发上游时只带声明字段（Runtime 侧 extra=forbid 仍兜底）。
    """

    research_execution_mode: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "allow"}


@router.post("/runs/{run_id}/formats")
async def nexus_run_formats(
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """SR6：自主 run 正式格式产物（Word .docx＋LaTeX .tex）代理。

    本人终态 run 才可生成；内容与 T6 Markdown 同源同版本；纯渲染不碰
    沙箱。归属校验先行（非本人 404），判定语义由 Runtime 原样返回。
    """
    from app.services import nexus_run_service

    run = nexus_run_service.get_owned_run(
        session, user_id=_artifact_user_id(current_user), run_id=run_id.strip()[:64]
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    return await _proxy_json(
        request, current_user, "POST",
        f"/api/v1/nexus/repro/runs/{run['run_id']}/formats",
    )


@router.post("/runs/{run_id}/clean-verify")
async def nexus_run_clean_verify(
    run_id: str,
    payload: NexusRunCleanVerify,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """SR6：自主 run 干净B验证代理（全新沙箱重放冻结配方）。

    重放调用实验沙箱——未知模式 400，非 Auto 403（Ask 禁止，门在 Runtime
    再验）。归属校验先行（非本人 404），判定语义由 Runtime 原样返回。
    """
    from app.services import nexus_run_service

    _require_valid_execution_mode(payload.research_execution_mode)
    _reject_unknown_fields(NexusRunCleanVerify, payload.model_dump())
    run = nexus_run_service.get_owned_run(
        session, user_id=_artifact_user_id(current_user), run_id=run_id.strip()[:64]
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    return await _proxy_json(
        request, current_user, "POST",
        f"/api/v1/nexus/repro/runs/{run['run_id']}/clean-verify",
        body={"research_execution_mode": payload.research_execution_mode},
    )


class NexusRunResume(BaseModel):
    """F2 恢复认领代理体：只透传执行模式（未知值 400，由门裁决）。

    extra=allow：容忍签名键 time/enc；未声明字段由 _reject_unknown_fields
    422；转发上游时只带声明字段（Runtime 侧 extra=forbid 仍兜底）。
    """

    research_execution_mode: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "allow"}


@router.post("/runs/{run_id}/resume")
async def nexus_run_resume(
    run_id: str,
    payload: NexusRunResume,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """F2：认领 running run 并对账在途意图后继续（恢复入口代理）。

    只查不交地对账，需继续时 Runtime 后台调度图执行；未知模式 400，
    非 Auto 403（Ask 禁止，门在 Runtime 再验）。归属校验先行（非本人
    404），判定语义由 Runtime 原样返回。
    """
    from app.services import nexus_run_service

    _require_valid_execution_mode(payload.research_execution_mode)
    _reject_unknown_fields(NexusRunResume, payload.model_dump())
    run = nexus_run_service.get_owned_run(
        session, user_id=_artifact_user_id(current_user), run_id=run_id.strip()[:64]
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    return await _proxy_json(
        request, current_user, "POST",
        f"/api/v1/nexus/repro/runs/{run['run_id']}/resume",
        body={"research_execution_mode": payload.research_execution_mode},
    )


class NexusRunRename(BaseModel):
    """NX-LB1 重命名：仅 title（null/空串恢复默认名）＋ expected_version。

    extra=allow：容忍签名键 time/enc；未声明字段（配置/状态/owner 等）
    由 _reject_unknown_fields 422。
    """

    title: str | None = Field(default=None, max_length=120)
    expected_version: int = Field(ge=0)

    model_config = {"extra": "allow"}


@router.patch("/runs/{run_id}")
async def nexus_run_rename(
    run_id: str,
    payload: NexusRunRename,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """NX-LB1：重命名运行（乐观锁；不改变执行 hash 或配置）。"""
    from app.services import nexus_run_service

    _reject_unknown_fields(NexusRunRename, payload.model_dump())
    try:
        row = nexus_run_service.rename_run(
            session, user_id=_artifact_user_id(current_user),
            run_id=run_id.strip()[:64], title=payload.title,
            expected_version=payload.expected_version,
        )
    except nexus_run_service._VersionConflict as error:
        reject(409, "RUN_VERSION_CONFLICT", "运行已被修改，请刷新后重试",
               details={"current_version": error.current_version})
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    merged = (await _merge_runs_live([row], session))[0]
    return JSONResponse(status_code=status.HTTP_200_OK, content=merged)


@router.post("/runs/{run_id}/cancel")
async def nexus_run_cancel(
    run_id: str,
    payload: NexusRunCancelGrant,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """T5：用户直接取消运行（本人＋同会话；登录态即授权，不经过 grant）。

    - preset（有 job_id）：沿用 Worker 取消核心（与作业取消同语义）；
    - autonomous：经 Runtime 取消（置旗＋操作取消＋回收确认），终态
      cancelled 才返回成功；控制不可达 → 503，不伪装取消。
    模型排错时终止自己的卡住命令走 operation 级取消，不调本端点（不触发
    “取消整个实验”的第二次确认语义由调用方保证：本端点只响应用户手势）。
    """
    from app.services import nexus_run_service

    _reject_unknown_fields(NexusRunCancelGrant, payload.model_dump())
    run = nexus_run_service.get_owned_run(
        session, user_id=_artifact_user_id(current_user), run_id=run_id.strip()[:64]
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    if (run["session_id"] or "") != payload.session_id.strip()[:128]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="RUN_SESSION_MISMATCH")
    if run["status"] in nexus_run_service.TERMINAL_RUN_STATUSES:
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "run_id": run["run_id"], "status": run["status"],
            "already_terminal": True,
        })
    if _run_provider(run) == "autonomous" or not run["job_id"]:
        result = await _runtime_cancel_run(
            run["run_id"], _artifact_user_id(current_user))
        if result["status"] == "cancelled":
            try:
                nexus_run_service.update_run_status(
                    session, user_id=_artifact_user_id(current_user),
                    run_id=run["run_id"], status="cancelled",
                    detail="用户取消，进程已回收确认")
            except Exception as error:  # noqa: BLE001
                logger.warning("autonomous run cancel snapshot writeback failed: %s", error)
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "run_id": run["run_id"], "status": result["status"],
            "already_terminal": result["already_terminal"],
        })
    result = await _worker_cancel(run["job_id"])
    if result["status"] == "cancelled":
        try:
            nexus_run_service.update_run_status(
                session, user_id=_artifact_user_id(current_user),
                run_id=run["run_id"], status="cancelled", detail="用户取消")
        except Exception as error:  # noqa: BLE001
            logger.warning("run cancel snapshot writeback failed: %s", error)
    return JSONResponse(status_code=status.HTTP_200_OK, content={
        "run_id": run["run_id"], "job_id": run["job_id"],
        "status": result["status"], "already_terminal": result["already_terminal"],
    })


@router.post("/chat/stream")
async def nexus_chat_stream(
    payload: NexusChatRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """流式对话：逐块转发上游 SSE（token / tool_call / tool_result / done）。

    读超时单独放宽到 ``NEXUS_RUNTIME_STREAM_READ_TIMEOUT_S``：Agent 在多轮工具
    循环中可能长时间不产出 token，用非流式的 60s 会误杀正常长任务。
    """
    _require_valid_mode(payload.mode)
    _require_valid_execution_mode(payload.research_execution_mode)
    payload.attachment_ids, payload.attachments = _require_attachments(
        session, current_user, payload.session_id, payload.attachment_ids
    )
    await _inject_run_context(payload, session, current_user)
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
