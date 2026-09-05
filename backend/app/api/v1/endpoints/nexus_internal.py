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
