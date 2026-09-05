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
    # NX-A1：本次对话引用的附件 id（≤5）。本层逐个验 owner 并原子绑定到
    # session 后才透传；Runtime 侧只读执行上下文，不再信任模型传参。
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


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


def _require_attachments(
    session, current_user: dict, session_id: str, attachment_ids: list[str]
) -> list[str]:
    """NX-A1：对话引用附件的验主 + 原子绑定（执行前完成，不依赖 Runtime）。

    - 每个 id 验 owner（非 owner/不存在 → 404，不区分）；
    - 未绑定 → 绑定到本 session；已绑他会话 → 403；
    - 不可用状态（failed/expired/deleted）→ 422。
    返回清洗后的 id 列表（去重保序），由调用方透传给 Runtime。
    """
    from app.services import nexus_attachment_service
    from app.services.nexus_attachment_parse import AttachmentParseError

    user_id = _artifact_user_id(current_user)
    session_id = (session_id or "").strip()[:128] or "default"
    clean: list[str] = []
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
    return clean


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
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """非流式对话：等待 Agent 循环结束后一次性返回最终答复与工具事件。"""
    _require_valid_mode(payload.mode)
    payload.attachment_ids = _require_attachments(
        session, current_user, payload.session_id, payload.attachment_ids
    )
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
_LOG_TAIL_MAX = 300
_STEP_MAX = 10


def _worker_base() -> str:
    return (settings.REPRO_WORKER_URL or "").rstrip("/")


def _trim_job_record(record: dict) -> dict:
    """裁剪 Worker 记录为前端展示形态：短日志摘要 + 阶段切片，不回传全文。"""
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
    }
    for step in (record.get("steps_result") or [])[:_STEP_MAX]:
        trimmed["steps_result"].append({
            "command": str(step.get("command") or "")[:160],
            "exit_code": step.get("exit_code"),
            "timed_out": step.get("timed_out"),
            "duration_s": step.get("duration_s"),
            "log_tail": str(step.get("log_tail") or "")[-_LOG_TAIL_MAX:],
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
    Runtime 侧同一核销核心；幂等语义由上游保证（重试返回原 job）。"""
    return await _proxy_json(
        request,
        current_user,
        "POST",
        "/api/v1/nexus/repro/execute",
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
# ---------------------------------------------------------------------------


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


def _merge_run_live(run: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    """run 快照 + 实时态合并：live 缺失 → stale 快照 + honest note。"""
    merged = dict(run)
    if live is None:
        merged["live"] = {"status": "stale", "note": "执行器不可达，显示登记快照"}
        return merged
    if live.get("missing"):
        merged["live"] = {
            "status": "unknown",
            "note": "执行器无此作业（可能已重启），不可恢复执行，只能查看登记快照",
        }
        return merged
    merged["live"] = {
        "status": live.get("status", "unknown"),
        "preset_id": live.get("preset_id", run["preset_id"]),
        "started_at": live.get("started_at"),
        "finished_at": live.get("finished_at"),
        "code": live.get("code"),
        "detail": live.get("detail"),
    }
    return merged


@router.get("/runs")
async def nexus_runs_list(
    session_id: str = "",
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """某会话我的 runs（含实时态合并）：恢复查询入口，不触发任何执行。"""
    from app.services import nexus_run_service

    runs = nexus_run_service.list_session_runs(
        session, user_id=_artifact_user_id(current_user), session_id=session_id.strip()[:128]
    )
    items = []
    for run in runs:
        live = await _live_job_status(run["job_id"]) if run["job_id"] else None
        items.append(_merge_run_live(run, live))
    return JSONResponse(status_code=status.HTTP_200_OK, content={"items": items})


@router.get("/runs/{run_id}")
async def nexus_run_detail(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_nexus_use),
):
    """单个 run 详情（含实时态合并）；非 owner/不存在 → 404。"""
    from app.services import nexus_run_service

    run = nexus_run_service.get_owned_run(
        session, user_id=_artifact_user_id(current_user), run_id=run_id.strip()[:64]
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run 不存在")
    live = await _live_job_status(run["job_id"]) if run["job_id"] else None
    return JSONResponse(
        status_code=status.HTTP_200_OK, content=_merge_run_live(run, live)
    )


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
    payload.attachment_ids = _require_attachments(
        session, current_user, payload.session_id, payload.attachment_ids
    )
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
