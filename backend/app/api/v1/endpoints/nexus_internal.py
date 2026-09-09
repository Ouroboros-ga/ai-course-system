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
from app.models.access_control_model import PlatformPermission
from app.models.database import get_session
from app.services.course_access_service import (
    require_platform_permission,
    resolve_course_access,
)
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
    session: Session = Depends(get_session),
):
    """CS 学科参考检索（只读；概念层兼容 + 语料层同版本，全补充参考）。

    - 服务凭据 + 用户身份 + ``platform.nexus.use`` 显式授权三重校验
      （停用用户 401、无授权 403；不读 ``User.role`` 兜底）；
    - 概念层（``search_nodes``，旧字段原样保留）与语料层
      （``CorpusSearchService`` 按已发布 head 版本）结果合并，
      顶层与每条均为 ``is_supplementary=True``；
    - 来源标签按来源/核验状态逐条标注，不再全标"教材级权威"。
    """
    _require_service_token(authorization)
    user_id = _require_user_identity(x_nexus_user_id)
    require_platform_permission(
        session, {"user_id": user_id}, PlatformPermission.NEXUS_USE)
    concept_items = await asyncio.to_thread(search_nodes, q, top_k)
    items: list[dict[str, Any]] = [
        {
            "result_type": "concept",
            "id": item.get("id"),
            "name": item.get("name"),
            "node_type": item.get("node_type"),
            "definition": item.get("definition"),
            "key_points": item.get("key_points", []),
            "example": item.get("example", ""),
            "aliases": item.get("aliases", []),
            "source": item.get("source"),
            "course": item.get("course"),
            "score": item.get("score"),
            "authority_label": "精编概念（书目来源）",
            "is_supplementary": True,
        }
        for item in concept_items
    ]
    corpus = await asyncio.to_thread(_search_corpus_release, q, top_k)
    items.extend(corpus["items"])
    return unified_response(
        code=200,
        message=f"CS 学科参考检索完成（概念 {len(concept_items)} 条 + 语料 {len(corpus['items'])} 条）",
        data={"authority": "cs_kb", "release_id": corpus["release_id"],
              "mode": corpus["mode"],
              "degraded_reasons": corpus["degraded_reasons"],
              "is_supplementary": True, "items": items},
    )


def _search_corpus_release(query: str, top_k: int) -> dict[str, Any]:
    """语料层检索（独立 session；无已发布版本/失败即空 + 降级原因）。"""
    from app.models.database import session_factory
    from app.platform.knowledge.corpus_embedding import HttpEmbedClient
    from app.services.discipline_knowledge.corpus_index import read_head
    from app.services.discipline_knowledge.corpus_search import (
        CorpusSearchService,
    )

    url = (settings.CORPUS_EMBEDDING_URL or "").strip()
    client = HttpEmbedClient(base_url=url) if url else None
    with session_factory() as session:
        try:
            if not read_head(session).get("release_id"):
                return {"release_id": "", "mode": "legacy",
                        "degraded_reasons": ["NO_PUBLISHED_RELEASE"], "items": []}
            result = CorpusSearchService().search(
                session, query, top_k=top_k, embed_client=client)
        except Exception as error:  # noqa: BLE001 - 语料层失败不影响概念层
            logger.warning("nexus cs corpus search failed: %s",
                           type(error).__name__)
            return {"release_id": "", "mode": "lexical",
                    "degraded_reasons": ["CORPUS_SEARCH_FAILED"], "items": []}
        # 全文进工具结果（模型上下文），展示截断由 Runtime 事件层处理，
        # 回源入口（reference_id）不受展示截断影响。
        items = []
        for row in result.get("results") or []:
            items.append({
                "result_type": "corpus_chunk",
                "chunk_id": row.get("chunk_id"),
                "reference_id": row.get("reference_id"),
                "title": row.get("title"),
                "text": row.get("context_text"),
                "snippet": row.get("snippet"),
                "doc_id": row.get("doc_id"),
                "section_path": row.get("section_path"),
                "source_kind": row.get("source_kind"),
                "source_url": row.get("source_url"),
                "license": row.get("license"),
                "matched_by": row.get("matched_by", []),
                "authority_label": _corpus_authority_label(
                    row.get("source_kind")),
                "is_supplementary": True,
            })
        return {"release_id": result.get("release_id") or "",
                "mode": result.get("mode") or "",
                "degraded_reasons": result.get("degraded_reasons") or [],
                "items": items}


def _corpus_authority_label(source_kind: Any) -> str:
    """按来源的诚实标签；未知来源原样返回，不全称教材。"""
    labels = {
        "textbook": "开放教材",
        "zhwiki": "维基百科（CC BY-SA）",
        "enwiki": "维基百科（CC BY-SA）",
        "rfc": "RFC（IETF）",
        "arxiv": "arXiv 论文（研究层）",
    }
    kind = str(source_kind or "").strip()
    if not kind:
        return "未知来源"
    return labels.get(kind, kind)


class NexusArtifactWriteRequest(BaseModel):
    """Runtime write_artifact → Backend 写入请求（M3-A，与工具侧同源校验）。

    NX-LB5：run_id 可选——报告链/工具写入时可关联运行，供 run 详情投影
    已授权产物引用。
    SR6：content_b64 可选——word 二进制经 base64 写入（content 须为空，
    走二进制分支；文本类型沿用 content）。
    """

    artifact_type: str = Field(min_length=1, max_length=16)
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(default="")
    content_b64: str = Field(default="", max_length=1024 * 1024)
    run_id: str = Field(default="", max_length=64)


class NexusReproJobRecordRequest(BaseModel):
    """Runtime run_reproduction → Backend 归属登记（M4-B1）。"""

    job_id: str = Field(min_length=4, max_length=32)
    preset_id: str = Field(default="", max_length=64)
    repo_url: str = Field(default="", max_length=300)


class NexusRunRecordRequest(BaseModel):
    """NX-E1：Runtime 执行成功后登记 run linkage（恢复查询依据）。

    NX-LB1 扩展：title/parent/proposal/config_snapshot/展示投影均为可选；
    老 Runtime 只发旧字段时照常登记（序号照分、展示名回退 preset_id）。
    T5：autonomous runs 无 Worker job（job_id 为空）：恢复/取消/备注走
    Runtime console/cancel 端点，不碰旧 Worker。
    """

    run_id: str = Field(min_length=4, max_length=64)
    session_id: str = Field(default="default", max_length=128)
    tool: str = Field(default="run_reproduction", max_length=64)
    preset_id: str = Field(default="", max_length=64)
    plan_hash: str = Field(default="", max_length=64)
    approval_id: str = Field(default="", max_length=64)
    job_id: str = Field(default="", max_length=64)
    status: str = Field(default="submitted", max_length=32)
    repo_url: str = Field(default="", max_length=300)
    title: str = Field(default="", max_length=120)
    parent_run_id: str = Field(default="", max_length=64)
    proposal_id: str = Field(default="", max_length=64)
    proposal_version: int = Field(default=0, ge=0)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    preset_display_name: str = Field(default="", max_length=120)
    paper_title: str = Field(default="", max_length=300)


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
        title=payload.title,
        parent_run_id=payload.parent_run_id,
        proposal_id=payload.proposal_id,
        proposal_version=payload.proposal_version,
        config_snapshot=payload.config_snapshot,
        preset_display_name=payload.preset_display_name,
        paper_title=payload.paper_title,
    )
    if run is None:
        # run_id 冲突且属他人：拒绝覆盖（正常 run_id=approval_id 全局唯一）。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="RUN_ID_CONFLICT")
    # NX-G2 集成修正（2026-09-06 线上验收）：run linkage 登记时同步写 M4 归属表
    # nexus_repro_jobs——审批执行路径上 Runtime 的 _record_job_ownership 因无聊天
    # 请求作用域（ContextVar 为空）静默失败，导致聊天发起的作业状态查询永久 404。
    # 幂等（ON CONFLICT DO NOTHING），与 Runtime 侧 /repro-jobs 登记互不冲突。
    if payload.job_id:
        from app.services import nexus_repro_job_service

        nexus_repro_job_service.record_job(
            session,
            job_id=payload.job_id,
            user_id=user_id,
            preset_id=payload.preset_id,
            repo_url=payload.repo_url,
        )
    return unified_response(code=200, message="run 已登记", data={"run_id": run["run_id"]})


@router.get("/repro-runs/by-job/{job_id}")
async def nexus_internal_run_by_job(
    job_id: str,
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    session: Session = Depends(get_session),
):
    """NX-LB2：按 job 反查本人的 run（含提案引用与冻结配置快照）。

    供报告链取 metric_policy/提案上下文；无 linkage（老作业/他人的）返回
    404，调用方回退 legacy preset 判定，不伪造基线。
    """
    from app.services import nexus_run_service

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    run = nexus_run_service.get_run_by_job(
        session, user_id=user_id, job_id=job_id.strip()[:64])
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RUN_NOT_FOUND")
    return unified_response(code=200, message="run linkage", data={
        "run_id": run["run_id"],
        "proposal_id": run["proposal_id"],
        "proposal_version": run["proposal_version"],
        "config_snapshot": run["config_snapshot"],
    })


@router.post("/artifacts")
async def nexus_internal_write_artifact(
    payload: NexusArtifactWriteRequest,
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    session: Session = Depends(get_session),
):
    """产物写入（M3）：对象存储 + Nexus 域元数据，一次成功才返回 artifact_id。

    SR6：word 类型走 content_b64 二进制分支（base64 非法/超限 422）。
    F6：pdf 同理走二进制分支（工具链真实编译字节）。
    """
    import base64

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    if payload.artifact_type in ("word", "pdf"):
        try:
            raw = base64.b64decode(payload.content_b64, validate=True)
        except Exception:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="ARTIFACT_CONTENT_INVALID")
        error = nexus_artifact_service.validate_binary_input(
            payload.artifact_type, payload.title, raw
        )
        if error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error)
        artifact = nexus_artifact_service.create_binary_artifact(
            session,
            user_id=user_id,
            artifact_type=payload.artifact_type,
            title=payload.title,
            data=raw,
            run_id=payload.run_id,
        )
        return unified_response(code=200, message="产物已写入", data=artifact)
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
        run_id=payload.run_id,
    )
    return unified_response(
        code=200,
        message="产物已写入",
        data=artifact,
    )


_INTERNAL_READ_MAX_BYTES = 512 * 1024


@router.get("/artifacts/{artifact_id}")
async def nexus_internal_read_artifact(
    artifact_id: str,
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    session: Session = Depends(get_session),
):
    """F5 产物读取（干净B消费冻结配方/补丁）：owner 校验＋有界返回。

    非 owner/不存在一律 404（列表不可见即不存在，防枚举）；超限截断并
    置 truncated（调用方不得把截断内容当完整配方）。二进制类型拒绝文本
    解读（415，不猜测）。
    """
    from app.services.object_storage import get_object_storage

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    artifact = nexus_artifact_service.get_owned_artifact(
        session, user_id=user_id, artifact_id=(artifact_id or "")[:64]
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="产物不存在")
    if str(artifact.get("artifact_type") or "") not in ("markdown", "json", "latex", "text"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="仅文本类产物可经内部端点读取")
    storage = get_object_storage()
    try:
        raw = storage.get(str(artifact.get("object_key") or ""))
    except Exception as error:  # noqa: BLE001 - fail-closed
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"对象读取失败（{type(error).__name__}）") from error
    truncated = len(raw) > _INTERNAL_READ_MAX_BYTES
    text = bytes(raw[:_INTERNAL_READ_MAX_BYTES]).decode("utf-8", errors="replace")
    return unified_response(code=200, message="ok", data={
        "artifact_id": artifact["artifact_id"],
        "artifact_type": artifact.get("artifact_type", ""),
        "title": artifact.get("title", ""),
        "size_bytes": artifact.get("size_bytes", 0),
        "sha256": artifact.get("sha256", ""),
        "content": text,
        "truncated": truncated,
    })


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


@router.get("/repro-runs/{run_id}")
async def nexus_internal_run_detail(
    run_id: str,
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    session: Session = Depends(get_session),
):
    """NX-LB2：按 run_id 读本人的 run 全行（含冻结配置快照）。

    供 Runtime 提案 parent 校验与 diff 取数；非 owner/不存在 → 404 不区分。
    """
    from app.services import nexus_run_service

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    run = nexus_run_service.get_owned_run(
        session, user_id=user_id, run_id=run_id.strip()[:64])
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RUN_NOT_FOUND")
    return unified_response(code=200, message="run", data=run)


# ---------------------------------------------------------------------------
# NX-LB4/LB5：运行操作（查询/取消/备注）的 Runtime 工具消费入口。
# 身份三重来源：service token + X-Nexus-User-Id（登录态注入）+
# X-Nexus-Session-Id（会话绑定）。归属校验同主代理链，跨会话引用一律拒绝。
# ---------------------------------------------------------------------------


def _internal_run_scope(
    session: Session, user_id: str, run_id: str, x_session_id: str | None,
) -> dict[str, Any]:
    """归属 + 会话绑定校验；失败按码抛 HTTPException（调用方透传给工具）。"""
    from app.services import nexus_run_service

    run = nexus_run_service.get_owned_run(
        session, user_id=user_id, run_id=(run_id or "").strip()[:64])
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RUN_NOT_FOUND")
    session_id = (x_session_id or "").strip()[:128]
    if not session_id or (run["session_id"] or "") != session_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="RUN_SESSION_MISMATCH")
    return run


@router.get("/runs/{run_id}/status")
async def nexus_internal_run_status(
    run_id: str,
    step_id: int | None = Query(default=None, ge=0),
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    x_nexus_session_id: str | None = Header(default=None, alias="X-Nexus-Session-Id"),
    session: Session = Depends(get_session),
):
    """NX-LB4：get_reproduction_run 工具的消费入口——有界状态投影。

    复用主代理链的 LB3 白名单投影（归属/脱敏/≤40 行 ≤8000 字符日志）；
    只读，不触发任何执行。
    """
    from app.api.v1.endpoints.nexus_proxy import _build_run_context

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    run = _internal_run_scope(session, user_id, run_id, x_nexus_session_id)
    context = await _build_run_context(
        session, {"user_id": user_id}, run["session_id"],
        {"run_id": run["run_id"], **({"step_id": step_id} if step_id is not None else {})},
    )
    return unified_response(code=200, message="run status", data=context)


class NexusInternalRunCancelRequest(BaseModel):
    """NX-LB4：内部取消（无 body 字段；保留给未来受限参数）。"""


@router.post("/runs/{run_id}/cancel")
async def nexus_internal_run_cancel(
    run_id: str,
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    x_nexus_session_id: str | None = Header(default=None, alias="X-Nexus-Session-Id"),
    session: Session = Depends(get_session),
):
    """NX-LB4：cancel_reproduction_run 工具的消费入口——授权门控取消。

    无有效一次性授权 → 200 confirmation_required（模型据此引导用户确认，
    授权由用户在登录态下经 /nexus/runs/{id}/cancel-grant 显式签发）；
    有授权 → 原子核销后走与用户取消代理相同的 Worker 取消核心。
    """
    from app.api.v1.endpoints.nexus_proxy import _worker_cancel
    from app.services import nexus_action_grant_service, nexus_run_service

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    run = _internal_run_scope(session, user_id, run_id, x_nexus_session_id)
    if run["status"] in nexus_run_service.TERMINAL_RUN_STATUSES:
        return unified_response(code=200, message="run 已终态", data={
            "run_id": run["run_id"], "status": run["status"],
            "already_terminal": True,
            "note": "运行已结束（无需也无法取消）；此为登记快照状态。",
        })
    from app.api.v1.endpoints.nexus_proxy import _run_provider, _runtime_cancel_run

    if _run_provider(run) == "autonomous" or not run["job_id"]:
        # 自主 run：无 Worker 作业，经 Runtime 取消（置旗＋操作取消＋回收确认）。
        grant = nexus_action_grant_service.consume_grant(
            session, user_id=user_id, run_id=run["run_id"], action="cancel_run")
        if grant is None:
            return unified_response(code=200, message="需要用户确认", data={
                "run_id": run["run_id"], "status": "confirmation_required",
                "code": "CANCEL_CONFIRMATION_REQUIRED",
                "detail": (
                    "取消是破坏性停止动作，需要用户本次明确确认。请向用户说明将取消"
                    "哪个运行，并请其在界面上确认取消（确认后服务端签发一次性授权）。"
                ),
            })
        try:
            result = await _runtime_cancel_run(run["run_id"], user_id)
        except HTTPException as error:
            raise error
        if result["status"] == "cancelled":
            try:
                nexus_run_service.update_run_status(
                    session, user_id=user_id, run_id=run["run_id"],
                    status="cancelled", detail="用户确认后取消")
            except Exception as error:  # noqa: BLE001
                logger.warning("run cancel snapshot writeback failed: %s", error)
        return unified_response(code=200, message="取消已受理", data={
            "run_id": run["run_id"], "status": result["status"],
            "already_terminal": result["already_terminal"],
        })
    grant = nexus_action_grant_service.consume_grant(
        session, user_id=user_id, run_id=run["run_id"], action="cancel_run")
    if grant is None:
        return unified_response(code=200, message="需要用户确认", data={
            "run_id": run["run_id"], "status": "confirmation_required",
            "code": "CANCEL_CONFIRMATION_REQUIRED",
            "detail": (
                "取消是破坏性停止动作，需要用户本次明确确认。请向用户说明将取消"
                "哪个运行，并请其在界面上确认取消（确认后服务端签发一次性授权）。"
            ),
        })
    result = await _worker_cancel(run["job_id"])
    # best-effort 回写快照（终态由列表合并路径权威化，此处只加速可见性）。
    if result["status"] == "cancelled":
        try:
            nexus_run_service.update_run_status(
                session, user_id=user_id, run_id=run["run_id"],
                status="cancelled", detail="用户确认后取消")
        except Exception as error:  # noqa: BLE001
            logger.warning("run cancel snapshot writeback failed: %s", error)
    return unified_response(code=200, message="取消已受理", data={
        "run_id": run["run_id"], "job_id": run["job_id"],
        "status": result["status"], "already_terminal": result["already_terminal"],
    })


class NexusInternalRunNoteRequest(BaseModel):
    """NX-LB5：Agent 运行备注写入（author_kind 服务端强制 agent）。"""

    content: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(default="", max_length=64)


@router.post("/runs/{run_id}/notes")
async def nexus_internal_run_note_create(
    run_id: str,
    payload: NexusInternalRunNoteRequest,
    authorization: str | None = Header(default=None),
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
    x_nexus_session_id: str | None = Header(default=None, alias="X-Nexus-Session-Id"),
    session: Session = Depends(get_session),
):
    """NX-LB5：add_reproduction_note 工具的消费入口（备注标记为 Agent 解释/建议）。"""
    from app.services import nexus_run_service

    _require_service_token(authorization)
    user_id = str(_require_user_identity(x_nexus_user_id))
    run = _internal_run_scope(session, user_id, run_id, x_nexus_session_id)
    try:
        note = nexus_run_service.add_run_note(
            session, user_id=user_id, run_id=run["run_id"], content=payload.content,
            author_kind="agent", request_id=payload.request_id,
        )
    except nexus_run_service.NoteError as error:
        code_status = {"RUN_NOT_FOUND": 404, "NOTE_CONTENT_INVALID": 422}
        raise HTTPException(
            status_code=code_status.get(error.code, 422), detail=error.code) from error
    return unified_response(code=200, message="note added", data=note)
