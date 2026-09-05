"""Nexus 内部检索端点（M2 知识接入，CodeNexus P2）。

职责：给独立进程的 Nexus Runtime 提供课程资料与 CS 知识库的结构化检索，
**不复制知识、不重建 KB**（设计文档 §18：Nexus Tool → Existing Backend
Capability → Structured Result）。

安全边界（AGENTS.md §4.1.6 / P2 计划 §六）：
- 双重校验：内部服务令牌（``NEXUS_INTERNAL_TOKEN``，fail-closed：未配置即 503）
  + ``X-Nexus-User-Id`` 用户身份；课程检索以**该用户身份**经
  ``course_access_service.resolve_course_access`` 校验，不绕过 Course Access v1；
- 端点只读：不写任何业务数据；结果为结构化 items（来源/标题/正文摘要/引用），
  不返回原始文件。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.config import settings
from app.core.exceptions import unified_response
from app.models.database import get_session
from app.services.course_access_service import resolve_course_access
from app.services import nexus_artifact_service
from app.platform.knowledge.discipline_kb import search_nodes
from app.platform.knowledge.sql_lance_provider import SqlLanceCourseKnowledgeProvider

logger = logging.getLogger(__name__)

router = APIRouter()

_ERROR_NOT_CONFIGURED = "NEXUS_INTERNAL_NOT_CONFIGURED"
_ERROR_UNAUTHORIZED = "NEXUS_INTERNAL_UNAUTHORIZED"
_ERROR_FORBIDDEN = "NEXUS_INTERNAL_FORBIDDEN"

_EVIDENCE_TEXT_MAX = 600
_TOP_K_MAX = 8


def _require_service_token(authorization: str | None) -> None:
    """fail-closed：令牌未配置一律 503；配置后不匹配 401。"""
    token = (settings.NEXUS_INTERNAL_TOKEN or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ERROR_NOT_CONFIGURED,
        )
    if authorization != f"Bearer {token}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_ERROR_UNAUTHORIZED,
        )


def _require_user_identity(x_nexus_user_id: str | None) -> int:
    if not x_nexus_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NEXUS_INTERNAL_USER_REQUIRED",
        )
    try:
        return int(str(x_nexus_user_id).strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NEXUS_INTERNAL_USER_INVALID",
        ) from exc


def _course_allowed(session: Session, user_id: int, course_id: int) -> bool:
    """Course Access v1 门控：与 TeachingAgent 同一能力位（knowledge.view +
    course.citation.read），不引入任何 User.role 兜底。"""
    try:
        access = resolve_course_access(session, {"user_id": user_id}, course_id)
    except HTTPException:
        return False
    return bool(
        access.allows("knowledge.view") and access.allows("course.citation.read")
    )


def _provider() -> SqlLanceCourseKnowledgeProvider:
    return SqlLanceCourseKnowledgeProvider()


@router.get("/course-evidence")
async def nexus_internal_course_evidence(
    request: Request,
    course_id: int = Query(..., ge=1),
    q: str = Query(..., min_length=1, max_length=200),
    top_k: int = Query(default=5, ge=1, le=_TOP_K_MAX),
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    session: Session = Depends(get_session),
):
    """课程资料证据检索（course-scoped，向量/关键词经活跃知识包）。"""
    _require_service_token(authorization)
    user_id = _require_user_identity(x_nexus_user_id)
    if not _course_allowed(session, user_id, course_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_ERROR_FORBIDDEN,
        )
    result = await asyncio.to_thread(_provider().search_evidence, course_id, q, top_k=top_k)
    items: list[dict[str, Any]] = []
    if result is not None:
        for item in result.items:
            if not item.evidence_ids or not item.citation_ids:
                continue
            items.append(
                {
                    "evidence_id": item.evidence_ids[0],
                    "resource_id": item.document_id,
                    "page": item.page_number,
                    "text": (item.content or "")[:_EVIDENCE_TEXT_MAX],
                    "node_key": item.node_key,
                    "knowledge_node_id": item.knowledge_node_id,
                    "citation_ids": list(item.citation_ids)[:4],
                    "bundle_id": result.bundle.bundle_id,
                    "graph_snapshot_id": result.bundle.graph_snapshot_id,
                }
            )
    return unified_response(
        code=200,
        message=f"课程资料检索完成（{len(items)} 条）",
        data={"authority": "course", "course_id": course_id, "items": items},
    )


@router.get("/cs-knowledge")
async def nexus_internal_cs_knowledge(
    q: str = Query(..., min_length=1, max_length=200),
    top_k: int = Query(default=5, ge=1, le=10),
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
):
    """CS 学科知识库检索（只读，权威来源随条目返回）。"""
    _require_service_token(authorization)
    _require_user_identity(x_nexus_user_id)
    results = await asyncio.to_thread(search_nodes, q, top_k)
    return unified_response(
        code=200,
        message=f"CS 知识库检索完成（{len(results)} 条）",
        data={"authority": "cs_kb", "items": results},
    )


class NexusArtifactWriteRequest(BaseModel):
    """Runtime write_artifact → Backend 写入请求（M3-A，与工具侧同源校验）。"""

    artifact_type: str = Field(min_length=1, max_length=16)
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)


class NexusReproJobRecordRequest(BaseModel):
    """Runtime run_reproduction → Backend 归属登记（M4-B1）。"""

    job_id: str = Field(min_length=4, max_length=32)
    preset_id: str = Field(default="", max_length=64)
    repo_url: str = Field(default="", max_length=300)


class NexusRunRecordRequest(BaseModel):
    """NX-E1：Runtime 执行成功后登记 run linkage（恢复查询依据）。"""

    run_id: str = Field(min_length=4, max_length=64)
    session_id: str = Field(default="default", max_length=128)
    tool: str = Field(default="run_reproduction", max_length=64)
    preset_id: str = Field(default="", max_length=64)
    plan_hash: str = Field(default="", max_length=64)
    approval_id: str = Field(default="", max_length=64)
    job_id: str = Field(min_length=4, max_length=64)
    status: str = Field(default="submitted", max_length=32)


@router.post("/repro-jobs")
async def nexus_internal_record_repro_job(
    payload: NexusReproJobRecordRequest,
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    session: Session = Depends(get_session),
):
    """复现作业归属登记：之后该 job 的状态查询/报告生成按发起人鉴权。"""
    from app.services import nexus_repro_job_service

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    nexus_repro_job_service.record_job(
        session,
        job_id=payload.job_id,
        user_id=user_id,
        preset_id=payload.preset_id,
        repo_url=payload.repo_url,
    )
    return unified_response(code=200, message="作业归属已登记", data={"job_id": payload.job_id})


@router.post("/repro-runs")
async def nexus_internal_record_repro_run(
    payload: NexusRunRecordRequest,
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    session: Session = Depends(get_session),
):
    """NX-E1 run linkage 登记：执行成功后由 Runtime/代理登记，供恢复查询。"""
    from app.services import nexus_run_service

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    run = nexus_run_service.record_run(
        session,
        run_id=payload.run_id,
        user_id=user_id,
        session_id=payload.session_id,
        tool=payload.tool,
        preset_id=payload.preset_id,
        plan_hash=payload.plan_hash,
        approval_id=payload.approval_id,
        job_id=payload.job_id,
        status=payload.status,
    )
    if run is None:
        # run_id 冲突且属他人：拒绝覆盖（正常 run_id=approval_id 全局唯一）。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="RUN_ID_CONFLICT")
    return unified_response(code=200, message="run 已登记", data={"run_id": run["run_id"]})


@router.post("/artifacts")
async def nexus_internal_write_artifact(
    payload: NexusArtifactWriteRequest,
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    session: Session = Depends(get_session),
):
    """产物写入（M3）：对象存储 + Nexus 域元数据，一次成功才返回 artifact_id。"""
    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    error = nexus_artifact_service.validate_artifact_input(
        payload.artifact_type, payload.title, payload.content
    )
    if error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error)
    artifact = nexus_artifact_service.create_artifact(
        session,
        user_id=user_id,
        artifact_type=payload.artifact_type,
        title=payload.title,
        content=payload.content,
    )
    return unified_response(
        code=200,
        message="产物已写入",
        data=artifact,
    )


@router.get("/attachments/{attachment_id}/content")
async def nexus_internal_attachment_content(
    attachment_id: str,
    locator: str = Query(default="", max_length=64),
    max_chars: int = Query(default=24000, ge=1000, le=60000),
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    x_nexus_session_id: str | None = Header(default=None, alias="X-Nexus-Session-Id"),
    session: Session = Depends(get_session),
):
    """NX-A1 Runtime 工具消费入口：owner + 会话绑定双重校验后返回解析 blocks。

    附件必须已绑定到请求会话（绑定发生在 chat 发送时）；未绑定/他会话一律
    拒绝——模型传参不能越权读他人文件。只返回文本 blocks，不含原图字节。
    """
    from app.services import nexus_attachment_service
    from app.services.nexus_attachment_parse import AttachmentParseError

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    session_id = (x_nexus_session_id or "").strip()[:128]
    try:
        row = nexus_attachment_service.get_owned_attachment(
            session, user_id=user_id, attachment_id=attachment_id.strip()[:16]
        )
        if row is None:
            raise AttachmentParseError("ATTACHMENT_NOT_FOUND", "附件不存在")
        if not session_id or row["session_id"] != session_id:
            raise AttachmentParseError("ATTACHMENT_SESSION_MISMATCH", "附件未绑定到当前会话")
        content = nexus_attachment_service.load_parsed_blocks(
            session, user_id=user_id, attachment_id=row["attachment_id"],
            max_chars=max_chars, locator=locator.strip(),
        )
    except AttachmentParseError as error:
        code_to_status = {
            "ATTACHMENT_NOT_FOUND": 404,
            "ATTACHMENT_SESSION_MISMATCH": 403,
            "ATTACHMENT_LOCATOR_NOT_FOUND": 422,
        }
        raise HTTPException(
            status_code=code_to_status.get(error.code, 422), detail=error.code
        ) from error
    return unified_response(code=200, message="附件内容", data=content)
