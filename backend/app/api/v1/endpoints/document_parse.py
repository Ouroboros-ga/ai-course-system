"""阶段4 课程材料解析、Evidence、Citation 与图谱治理 API 路由。

路由前缀：
- /api/v1/graph/course/{course_id}/ingestions           创建解析任务
- /api/v1/graph/course/{course_id}/ingestions/{run_id}  查询解析运行
- /api/v1/graph/course/{course_id}/ingestions           列表
- /api/v1/graph/course/{course_id}/reparse              明确版本与 stale 策略的重解析
- /api/v1/graph/course/{course_id}/evidence-spans       候选证据片段列表
- /api/v1/graph/course/{course_id}/evidence-spans/{span_id}/confirm   教师确认证据
- /api/v1/graph/course/{course_id}/evidence-spans/{span_id}/reject    教师拒绝证据
- /api/v1/graph/course/{course_id}/candidate-batches    图谱候选批次列表

facade:
- /api/v1/facade/course/{course_id}/knowledge?node_id=  知识空间首屏
- /api/v1/facade/course/{course_id}/health              课程健康度摘要

约束：
- 课程 A 的 Evidence、节点、Citation 永不出现在课程 B
- AI 抽取的候选证据未经教师确认不进入学生可见 Citation
- 重解析/删除后历史引用返回 stale/orphaned，不静默指向新内容
- 图谱不可用时正常问答降级；不返回 503 拒绝回答
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import (
    reject_resource_not_found,
    reject_validation_failed,
    unified_response,
)
from app.core.security import get_current_user
from app.core.time_utils import utcnow_aware
from app.models.course_build_model import (
    CourseRelease,
    ReleaseStatus,
    SourceMaterial,
    SourceMaterialVersion,
)
from app.models.database import get_session
from app.models.document_parse_model import (
    CandidateBatchStatus,
    CitationStatus,
    DocumentIRVersion,
    DocumentParseRun,
    EvidenceAnchor,
    EvidenceRenderAsset,
    EvidenceCitation,
    EvidenceSpan,
    EvidenceSpanStatus,
    GraphCandidateBatch,
    RetrievalChunk,
    ParsePipeline,
    ParseRunStatus,
    StaleStrategy,
)
from app.models.graph_production_model import (
    CourseEvidenceRecord,
    GraphSnapshotRecord,
    SnapshotStatus,
)
from app.models.agent_governance_model import AgentActionProposal
from app.services.course_access_service import require_course_permission, resolve_course_access
from app.services.document_parse_service import (
    document_parse_service,
    graph_candidate_service,
    graph_release_link_service,
)
from app.services.course_build_service import (
    course_build_service,
    course_release_service,
    source_material_service,
)


# ---------------------------------------------------------------------------
# 路由器：解析流水线（注册到 /api/v1/graph 前缀下）
# ---------------------------------------------------------------------------


document_parse_router = APIRouter()


# ---------------------------------------------------------------------------
# 请求体 schema
# ---------------------------------------------------------------------------


class IngestionCreateRequest(BaseModel):
    """创建解析任务请求体"""

    material_id: str = Field(..., min_length=1, max_length=200,
                             description="关联 SourceMaterial.material_id")
    material_version_id: Optional[str] = Field(None, max_length=200,
                                               description="指定材料版本ID；不传则使用 current_version_id")
    document_id: Optional[str] = Field(None, max_length=200,
                                       description="已有 DocumentArtifact.document_id；可空")
    pipeline: ParsePipeline = Field(default=ParsePipeline.FULL,
                                    description="解析流水线类型")
    stale_strategy: StaleStrategy = Field(default=StaleStrategy.MARK_STALE,
                                          description="重解析时旧证据处理策略")


class ReparseRequest(BaseModel):
    """重解析请求体：明确版本、影响范围与 stale 策略"""

    material_id: str = Field(..., min_length=1, max_length=200)
    material_version_id: Optional[str] = Field(None, max_length=200,
                                               description="指定版本；不传则使用 current_version_id")
    pipeline: ParsePipeline = Field(default=ParsePipeline.FULL)
    stale_strategy: StaleStrategy = Field(default=StaleStrategy.MARK_STALE)


class HighQualityOcrReparseRequest(BaseModel):
    """An auditable teacher-agent proposal for a narrowly scoped OCR reparse."""

    material_id: str = Field(..., min_length=1, max_length=200)
    material_version_id: Optional[str] = Field(None, max_length=200)
    pages: list[int] = Field(..., min_length=1, max_length=200)
    agent_action_id: str = Field(..., min_length=1, max_length=200)
    stale_strategy: StaleStrategy = Field(default=StaleStrategy.MARK_STALE)


class EvidenceSpanConfirmRequest(BaseModel):
    """教师确认候选证据"""

    source_file: str = Field(default="", max_length=500)
    source_type: str = Field(default="document",
                             description="ppt/textbook/handout/lesson_plan/document")
    node_id: Optional[int] = Field(None, description="关联知识点ID")
    identity_node_key: Optional[str] = Field(
        None, max_length=200, description="关联课程知识节点的稳定 node_key"
    )


class EvidenceSpanRejectRequest(BaseModel):
    """教师拒绝候选证据"""

    reject_reason: str = Field(default="", max_length=500)


class CanonicalRetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    run_id: Optional[str] = Field(default=None, max_length=200)
    top_k: int = Field(default=5, ge=1, le=20)


# ---------------------------------------------------------------------------
# 序列化 helpers
# ---------------------------------------------------------------------------


def _serialize_run(run: DocumentParseRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "course_id": run.course_id,
        "material_id": run.material_id,
        "material_version_id": run.material_version_id,
        "document_id": run.document_id,
        "task_id": run.task_id,
        "prev_run_id": run.prev_run_id,
        "pipeline": run.pipeline.value,
        "status": run.status.value,
        "stale_strategy": run.stale_strategy.value,
        "affected_evidence_count": run.affected_evidence_count,
        "reparse_applied": run.reparse_applied,
        "parse_profile": run.parse_profile,
        "reparse_scope": run.reparse_scope,
        "block_count": run.block_count,
        "evidence_span_count": run.evidence_span_count,
        "graph_candidate_count": run.graph_candidate_count,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "initiated_by": run.initiated_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def _serialize_span(span: EvidenceSpan) -> dict[str, Any]:
    return {
        "span_id": span.span_id,
        "course_id": span.course_id,
        "run_id": span.run_id,
        "ir_version_id": span.ir_version_id,
        "block_id": span.block_id,
        "document_id": span.document_id,
        "page_number": span.page_number,
        "text_snippet": span.text_snippet,
        "char_start": span.char_start,
        "char_end": span.char_end,
        "bbox": span.bbox,
        "content_hash": span.content_hash,
        "status": span.status.value,
        "confirmed_by": span.confirmed_by,
        "confirmed_at": span.confirmed_at.isoformat() if span.confirmed_at else None,
        "rejected_by": span.rejected_by,
        "rejected_at": span.rejected_at.isoformat() if span.rejected_at else None,
        "reject_reason": span.reject_reason,
        "stale_reason": span.stale_reason,
        "stale_at": span.stale_at.isoformat() if span.stale_at else None,
        "linked_node_ids": list(span.linked_node_ids or []),
        "linked_evidence_id": span.linked_evidence_id,
        "created_at": span.created_at.isoformat() if span.created_at else None,
        "updated_at": span.updated_at.isoformat() if span.updated_at else None,
    }


def _serialize_anchor(anchor: EvidenceAnchor) -> dict[str, Any]:
    return {
        "anchor_id": anchor.anchor_id,
        "ir_version_id": anchor.ir_version_id,
        "run_id": anchor.run_id,
        "document_id": anchor.document_id,
        "unit_id": anchor.unit_id,
        "block_id": anchor.block_id,
        "page_or_slide": anchor.page_or_slide,
        "char_start": anchor.char_start,
        "char_end": anchor.char_end,
        "text": anchor.text,
        "content_hash": anchor.content_hash,
        "bbox": anchor.bbox,
        "provenance": anchor.provenance,
        "status": anchor.status,
    }


def _serialize_ir_version(version: DocumentIRVersion) -> dict[str, Any]:
    return {
        "ir_version_id": version.ir_version_id,
        "document_id": version.document_id,
        "schema_version": version.schema_version,
        "quality_verdict": version.quality_verdict,
        "parse_outcome": version.parse_outcome,
        "needs_review": version.needs_review,
        "warning_count": version.warning_count,
        "prev_ir_version_id": version.prev_ir_version_id,
    }


def _serialize_citation(
    cit: EvidenceCitation,
    *,
    student_view: bool = False,
    render_url: Optional[str] = None,
) -> dict[str, Any]:
    """序列化 Citation。

    学生视图不暴露 evidence_id 与 span_id（内部追溯用）；只暴露学生可见字段。
    """
    data = {
        "citation_id": cit.citation_id,
        "course_id": cit.course_id,
        "run_id": cit.run_id,
        "document_id": cit.document_id,
        "node_id": cit.node_id,
        "source_file": cit.source_file,
        "source_type": cit.source_type,
        "page_number": cit.page_number,
        "page_range": cit.page_range,
        "bbox": cit.bbox,
        "source_anchor_ids": list(cit.source_anchor_ids or []),
        "text_snippet": cit.text_snippet,
        "char_start": cit.char_start,
        "char_end": cit.char_end,
        "version": cit.version,
        "status": cit.status.value,
        "stale_reason": cit.stale_reason,
        "stale_at": cit.stale_at.isoformat() if cit.stale_at else None,
        "student_visible": cit.student_visible,
        "created_at": cit.created_at.isoformat() if cit.created_at else None,
        "updated_at": cit.updated_at.isoformat() if cit.updated_at else None,
        "render_url": render_url,
    }
    if not student_view:
        data["evidence_id"] = cit.evidence_id
        data["span_id"] = cit.span_id
    return data


def _serialize_batch(
    batch: GraphCandidateBatch,
    *,
    review_payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload = review_payload or {}
    return {
        "batch_id": batch.batch_id,
        "course_id": batch.course_id,
        "parse_run_id": batch.parse_run_id,
        "task_id": batch.task_id,
        "prev_batch_id": batch.prev_batch_id,
        "status": batch.status.value,
        "node_candidate_count": payload.get("node_candidate_count", batch.node_candidate_count),
        "relation_candidate_count": payload.get("relation_candidate_count", batch.relation_candidate_count),
        "node_candidates": payload.get("node_candidates", batch.node_candidates),
        "relation_candidates": payload.get("relation_candidates", batch.relation_candidates),
        "accepted_count": batch.accepted_count,
        "rejected_count": batch.rejected_count,
        "needs_review_count": batch.needs_review_count,
        "snapshot_id": batch.snapshot_id,
        "model_version": batch.model_version,
        "error_code": batch.error_code,
        "error_message": batch.error_message,
        "initiated_by": batch.initiated_by,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


# ---------------------------------------------------------------------------
# 解析任务创建与查询
# ---------------------------------------------------------------------------


@document_parse_router.post("/course/{course_id}/ingestions")
async def create_ingestion(
    course_id: int,
    payload: IngestionCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """对课程材料创建 OCR/DocumentIR/Evidence/候选图谱解析任务。

    - 仅教师（course.edit）可创建
    - 同一 material_version 不允许并发 pending/running 运行
    - 返回 202 + run_id + task_id（异步执行；后续通过 GET /ingestions/{run_id} 或 /tasks/{task_id} 查询状态）
    - 解析本身由统一任务中心异步执行（worker 注册 document_parse handler）
    """
    context = require_course_permission(session, current_user, course_id, "course.edit")
    user_id = int(current_user["user_id"])

    # 校验材料归属本课程
    material = source_material_service.get_material(
        session, course_id=course_id, material_id=payload.material_id,
    )

    # 解析 material_version_id
    version_id = payload.material_version_id
    if not version_id:
        version_id = material.current_version_id
    if not version_id:
        reject_validation_failed(
            "材料尚未上传版本，无法解析",
            details={"material_id": payload.material_id},
        )

    # 校验版本归属
    version = session.exec(
        select(SourceMaterialVersion).where(
            SourceMaterialVersion.version_id == version_id,
            SourceMaterialVersion.course_id == course_id,
            SourceMaterialVersion.material_id == payload.material_id,
        )
    ).first()
    if version is None:
        reject_resource_not_found("材料版本不存在或不属于该课程")

    # 在统一任务中心创建 TaskRecord，确保解析任务可追踪、可取消、可重试
    from app.services.task_service import TaskCreateRequest, task_service
    task_view = task_service.create_task(session, TaskCreateRequest(
        task_type="document_parse",
        owner_user_id=user_id,
        course_id=course_id,
        input_summary=f"解析课程 {course_id} 材料 {payload.material_id} 版本 {version_id}",
        input_payload={
            "course_id": course_id,
            "material_id": payload.material_id,
            "material_version_id": version_id,
            "document_id": payload.document_id,
            "pipeline": payload.pipeline.value if hasattr(payload.pipeline, "value") else str(payload.pipeline),
            "stale_strategy": payload.stale_strategy.value if hasattr(payload.stale_strategy, "value") else str(payload.stale_strategy),
        },
        resource_links=[
            {"resource_kind": "course", "resource_id": str(course_id), "relation": "input"},
            {"resource_kind": "source_material", "resource_id": payload.material_id, "relation": "input"},
            {"resource_kind": "source_material_version", "resource_id": version_id, "relation": "input"},
            {"resource_kind": "document_parse_run", "resource_id": "pending", "relation": "output"},
        ],
    ))

    run = document_parse_service.create_run(
        session,
        course_id=course_id,
        material_id=payload.material_id,
        material_version_id=version_id,
        document_id=payload.document_id,
        task_id=task_view.task_id,
        pipeline=payload.pipeline,
        stale_strategy=payload.stale_strategy,
        initiated_by=user_id,
    )

    # 回填 parse_run_id 到 task resource_links（便于后续追踪）
    from app.models.task_model import TaskResourceLinkRecord
    session.add(TaskResourceLinkRecord(
        task_id=task_view.task_id,
        resource_kind="document_parse_run",
        resource_id=run.run_id,
        relation="output",
        created_at=utcnow_aware(),
    ))

    session.commit()
    session.refresh(run)

    # 触发 worker 异步执行（不阻塞 API 响应）
    # 若 worker 未注册 handler，任务会停留在 pending（前端可轮询 /tasks/{task_id}）
    # 若 worker 已注册 handler（main.py startup 调用 register_all_handlers），则异步执行
    try:
        from app.platform.tasks.worker import local_task_worker
        from app.platform.tasks.document_parse_queue import document_parse_queue
        from app.models.database import session_factory as _session_factory
        if local_task_worker.has_handler("document_parse"):
            document_parse_queue.submit(_session_factory, local_task_worker, task_view.task_id)
    except Exception:
        # worker 触发失败不影响任务记录创建；任务停留在 pending，前端可重试
        import logging
        logging.getLogger(__name__).warning(
            "Failed to submit document_parse task %s to worker; task stays pending",
            task_view.task_id,
            exc_info=True,
        )

    return unified_response(
        code=202,
        message="解析任务已创建",
        data={
            "run_id": run.run_id,
            "task_id": task_view.task_id,
            "status": run.status.value,
            "prev_run_id": run.prev_run_id,
            "affected_evidence_count": run.affected_evidence_count,
            "stale_strategy": run.stale_strategy.value,
        },
    )


@document_parse_router.get("/course/{course_id}/ingestions/{run_id}")
async def get_ingestion(
    course_id: int,
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """查询解析运行详情。"""
    require_course_permission(session, current_user, course_id, "course.view")
    run = session.exec(
        select(DocumentParseRun).where(
            DocumentParseRun.run_id == run_id,
            DocumentParseRun.course_id == course_id,
        )
    ).first()
    if run is None:
        reject_resource_not_found("解析运行不存在")
    return unified_response(
        code=200,
        message="获取解析运行成功",
        data={
            **_serialize_run(run),
            "canonical_ir": _serialize_ir_version(version) if (version := session.exec(
                select(DocumentIRVersion).where(DocumentIRVersion.ir_version_id == run.document_ir_version_id)
            ).first()) else None,
        },
    )


@document_parse_router.get("/course/{course_id}/ingestions")
async def list_ingestions(
    course_id: int,
    material_id: Optional[str] = Query(None, description="按材料过滤"),
    status: Optional[ParseRunStatus] = Query(None, description="按状态过滤"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出解析运行。"""
    require_course_permission(session, current_user, course_id, "course.view")
    runs = document_parse_service.list_runs(
        session,
        course_id=course_id,
        material_id=material_id,
        status=status,
    )
    return unified_response(
        code=200,
        message="获取解析运行列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_run(r) for r in runs],
            "total": len(runs),
        },
    )


@document_parse_router.post("/course/{course_id}/reparse")
async def reparse_material(
    course_id: int,
    payload: ReparseRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """明确版本、影响范围与 stale 策略的重解析。

    - 强制要求 stale_strategy，前端必须显式选择
    - 同一 material_version 不允许并发 pending/running
    - 旧证据按 stale_strategy 处理：mark_stale / orphan / delete
    - 返回 202 + run_id + affected_evidence_count
    """
    require_course_permission(session, current_user, course_id, "course.edit")
    user_id = int(current_user["user_id"])

    material = source_material_service.get_material(
        session, course_id=course_id, material_id=payload.material_id,
    )
    version_id = payload.material_version_id or material.current_version_id
    if not version_id:
        reject_validation_failed(
            "材料尚未上传版本，无法重解析",
            details={"material_id": payload.material_id},
        )
    version = session.exec(select(SourceMaterialVersion).where(
        SourceMaterialVersion.version_id == version_id,
        SourceMaterialVersion.course_id == course_id,
        SourceMaterialVersion.material_id == payload.material_id,
    )).first()
    if version is None:
        reject_resource_not_found("材料版本不存在或不属于指定材料")
    run = document_parse_service.create_run(
        session,
        course_id=course_id,
        material_id=payload.material_id,
        material_version_id=version_id,
        document_id=None,
        pipeline=payload.pipeline,
        stale_strategy=payload.stale_strategy,
        initiated_by=user_id,
    )

    from app.services.task_service import TaskCreateRequest, task_service
    task_view = task_service.create_task(session, TaskCreateRequest(
        task_type="document_parse",
        owner_user_id=user_id,
        course_id=course_id,
        input_summary=f"重解析课程 {course_id} 材料 {payload.material_id} 版本 {version_id}",
        input_payload={
            "course_id": course_id,
            "run_id": run.run_id,
            "material_id": payload.material_id,
            "material_version_id": version_id,
            "initiated_by": user_id,
            "pipeline": payload.pipeline.value if hasattr(payload.pipeline, "value") else str(payload.pipeline),
            "stale_strategy": payload.stale_strategy.value if hasattr(payload.stale_strategy, "value") else str(payload.stale_strategy),
        },
    ))
    run.task_id = task_view.task_id
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        from app.models.database import session_factory as _session_factory
        from app.platform.tasks.worker import local_task_worker
        from app.platform.tasks.document_parse_queue import document_parse_queue
        if local_task_worker.has_handler("document_parse"):
            document_parse_queue.submit(_session_factory, local_task_worker, task_view.task_id)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to submit reparse task %s", task_view.task_id, exc_info=True)

    return unified_response(
        code=202,
        message="重解析任务已创建",
        data={
            "run_id": run.run_id,
            "prev_run_id": run.prev_run_id,
            "affected_evidence_count": run.affected_evidence_count,
            "stale_strategy": run.stale_strategy.value,
            "status": run.status.value,
            "task_id": task_view.task_id,
        },
    )


@document_parse_router.get("/course/{course_id}/reparse/{run_id}/diff")
async def get_reparse_diff(
    course_id: int,
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Show the evidence replacement impact before a teacher applies it."""
    require_course_permission(session, current_user, course_id, "evidence.review")
    run = session.exec(select(DocumentParseRun).where(
        DocumentParseRun.course_id == course_id,
        DocumentParseRun.run_id == run_id,
    )).first()
    if run is None:
        reject_resource_not_found("解析运行不存在")
    if run.status not in (ParseRunStatus.SUCCEEDED, ParseRunStatus.PARTIAL_SUCCESS) or not run.prev_run_id:
        reject_validation_failed("仅已成功的重解析运行可生成差异")
    previous = session.exec(select(DocumentParseRun).where(
        DocumentParseRun.course_id == course_id,
        DocumentParseRun.run_id == run.prev_run_id,
    )).first()
    if previous is None or not previous.document_ir_version_id or not run.document_ir_version_id:
        reject_validation_failed("重解析缺少可比较的 Canonical DocumentIR 版本")
    old = session.exec(select(EvidenceAnchor).where(
        EvidenceAnchor.course_id == course_id,
        EvidenceAnchor.ir_version_id == previous.document_ir_version_id,
    )).all()
    new = session.exec(select(EvidenceAnchor).where(
        EvidenceAnchor.course_id == course_id,
        EvidenceAnchor.ir_version_id == run.document_ir_version_id,
    )).all()
    old_by_hash = {item.content_hash: item for item in old}
    new_by_hash = {item.content_hash: item for item in new}
    return unified_response(200, "获取重解析差异成功", {
        "run_id": run_id,
        "prev_run_id": run.prev_run_id,
        "stale_strategy": run.stale_strategy.value,
        "already_applied": run.reparse_applied,
        "added": [_serialize_anchor(item) for item in new if item.content_hash not in old_by_hash],
        "removed": [_serialize_anchor(item) for item in old if item.content_hash not in new_by_hash],
        "unchanged_count": len(set(old_by_hash).intersection(new_by_hash)),
    })


@document_parse_router.post("/course/{course_id}/reparse/high-quality-ocr")
async def request_high_quality_ocr_reparse(
    course_id: int,
    payload: HighQualityOcrReparseRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Queue an agent-proposed, page-scoped OCR reparse for teacher review.

    The caller must already hold course-edit permission.  ``agent_action_id``
    is persisted as provenance, while adoption stays a separate `/apply` step.
    """
    require_course_permission(session, current_user, course_id, "course.edit")
    user_id = int(current_user["user_id"])
    pages = sorted(set(payload.pages))
    if any(page < 1 for page in pages):
        reject_validation_failed("pages 必须是从 1 开始的页码/幻灯片序号")
    material = source_material_service.get_material(
        session, course_id=course_id, material_id=payload.material_id,
    )
    version_id = payload.material_version_id or material.current_version_id
    version = session.exec(select(SourceMaterialVersion).where(
        SourceMaterialVersion.version_id == version_id,
        SourceMaterialVersion.course_id == course_id,
        SourceMaterialVersion.material_id == payload.material_id,
    )).first() if version_id else None
    if version is None:
        reject_resource_not_found("材料版本不存在或不属于指定材料")
    proposal = session.exec(select(AgentActionProposal).where(
        AgentActionProposal.proposal_id == payload.agent_action_id,
        AgentActionProposal.course_id == course_id,
    )).first()
    if proposal is None:
        reject_resource_not_found("教师代理动作提案不存在或不属于该课程")
    if proposal.status != "approved" or proposal.proposal_type != "high_quality_ocr_reparse":
        reject_validation_failed("高质量 OCR 重解析需要已批准的对应教师代理提案")

    run = document_parse_service.create_run(
        session, course_id=course_id, material_id=payload.material_id,
        material_version_id=version_id, pipeline=ParsePipeline.FULL,
        stale_strategy=payload.stale_strategy, parse_profile="high_quality_ocr",
        reparse_scope={"pages": pages, "agent_action_id": payload.agent_action_id},
        initiated_by=user_id,
    )
    from app.services.task_service import TaskCreateRequest, task_service
    task = task_service.create_task(session, TaskCreateRequest(
        task_type="document_parse", owner_user_id=user_id, course_id=course_id,
        input_summary=f"高质量 OCR 重解析课程 {course_id} 材料 {payload.material_id} 页 {pages}",
        input_payload={
            "course_id": course_id, "run_id": run.run_id,
            "material_id": payload.material_id, "material_version_id": version_id,
            "pipeline": "full", "stale_strategy": payload.stale_strategy.value,
            "parse_profile": "high_quality_ocr", "pages": pages,
            "agent_action_id": payload.agent_action_id,
        },
    ))
    run.task_id = task.task_id
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        from app.models.database import session_factory as _session_factory
        from app.platform.tasks.worker import local_task_worker
        if local_task_worker.has_handler("document_parse"):
            local_task_worker.submit(_session_factory, task.task_id, {
                "course_id": course_id, "run_id": run.run_id,
                "material_id": payload.material_id, "material_version_id": version_id,
                "pipeline": "full", "stale_strategy": payload.stale_strategy.value,
                "parse_profile": "high_quality_ocr", "pages": pages,
                "agent_action_id": payload.agent_action_id,
            })
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to submit high-quality OCR task %s", task.task_id, exc_info=True)
    return unified_response(202, "高质量 OCR 重解析任务已创建，等待差异审核与显式采用", {
        "run_id": run.run_id, "task_id": task.task_id, "prev_run_id": run.prev_run_id,
        "parse_profile": run.parse_profile, "scope": run.reparse_scope,
        "adoption_required": True,
    })


@document_parse_router.post("/course/{course_id}/reparse/{run_id}/apply")
async def apply_reparse(
    course_id: int,
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Teacher confirmation point for replacing an earlier evidence version."""
    require_course_permission(session, current_user, course_id, "evidence.confirm")
    run = document_parse_service.apply_reparse(session, course_id=course_id, run_id=run_id)
    session.commit()
    session.refresh(run)
    return unified_response(200, "重解析差异已确认并应用", _serialize_run(run))


@document_parse_router.get("/course/{course_id}/document-ir/{run_id}/anchors")
async def list_canonical_anchors(
    course_id: int,
    run_id: str,
    page_or_slide: Optional[int] = Query(None, ge=1),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Evidence Viewer API backed by the immutable Canonical IR projection."""
    require_course_permission(session, current_user, course_id, "evidence.review")
    run = session.exec(select(DocumentParseRun).where(
        DocumentParseRun.course_id == course_id,
        DocumentParseRun.run_id == run_id,
    )).first()
    if run is None or not run.document_ir_version_id:
        reject_resource_not_found("Canonical DocumentIR 不存在")
    statement = select(EvidenceAnchor).where(
        EvidenceAnchor.course_id == course_id,
        EvidenceAnchor.ir_version_id == run.document_ir_version_id,
    ).order_by(EvidenceAnchor.page_or_slide, EvidenceAnchor.char_start)
    if page_or_slide is not None:
        statement = statement.where(EvidenceAnchor.page_or_slide == page_or_slide)
    anchors = list(session.exec(statement).all())
    return unified_response(200, "获取 Canonical Evidence Viewer 数据成功", {
        "run_id": run_id,
        "ir_version_id": run.document_ir_version_id,
        "page_assets": _canonical_page_assets(session, course_id, run_id, anchors),
        "items": [_serialize_anchor(item) for item in anchors],
        "total": len(anchors),
    })


def _canonical_page_assets(
    session: Session,
    course_id: int,
    run_id: str,
    anchors: list[EvidenceAnchor],
) -> list[dict[str, Any]]:
    """Expose page renders only through signed, course-scoped object URLs."""
    pages: dict[int, dict[str, Any]] = {}
    page_numbers = {anchor.page_or_slide for anchor in anchors if anchor.page_or_slide is not None}
    assets = list(session.exec(select(EvidenceRenderAsset).where(
        EvidenceRenderAsset.course_id == course_id,
        EvidenceRenderAsset.run_id == run_id,
        EvidenceRenderAsset.page_number.in_(page_numbers or {-1}),
    )).all())
    by_page = {asset.page_number: asset for asset in assets if asset.object_key}
    for anchor in anchors:
        if anchor.page_or_slide is None:
            continue
        asset = by_page.get(anchor.page_or_slide)
        pages.setdefault(anchor.page_or_slide, {
            "page_or_slide": anchor.page_or_slide,
            "anchor_count": 0,
            "rendition_url": f"/api/v1/graph/course/{course_id}/evidence-renders/{asset.asset_id}/content" if asset else None,
            "width": asset.width if asset else None,
            "height": asset.height if asset else None,
        })["anchor_count"] += 1
    return [pages[page] for page in sorted(pages)]


@document_parse_router.get("/course/{course_id}/evidence-renders/{asset_id}/content")
async def get_evidence_render_content(
    course_id: int,
    asset_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Read a persisted evidence page after course permission verification.

    Teachers may inspect any page render.  Students may only fetch a page that
    backs an active, student-visible Citation; this keeps the binary route
    course-scoped even though browsers cannot attach a Bearer header to an
    ``<img>`` element directly.
    """
    context = resolve_course_access(session, current_user, course_id)
    is_teacher = context.allows("evidence.review")
    if not is_teacher and not context.allows("course.citation.read"):
        require_course_permission(session, current_user, course_id, "evidence.review")
    asset = session.exec(select(EvidenceRenderAsset).where(
        EvidenceRenderAsset.asset_id == asset_id,
        EvidenceRenderAsset.course_id == course_id,
    )).first()
    if asset is None or not asset.object_key:
        reject_resource_not_found("Evidence 渲染资源不存在")
    if not is_teacher:
        citation = session.exec(select(EvidenceCitation).where(
            EvidenceCitation.course_id == course_id,
            EvidenceCitation.document_id == asset.document_id,
            EvidenceCitation.run_id == asset.run_id,
            EvidenceCitation.page_number == asset.page_number,
            EvidenceCitation.student_visible.is_(True),
            EvidenceCitation.status.in_([CitationStatus.EXACT, CitationStatus.APPROXIMATE]),
        )).first()
        if citation is None:
            raise HTTPException(status_code=403, detail="该原文页尚未绑定学生可读引用")
    try:
        from app.services.object_storage import LocalStorageProvider, get_object_storage
        storage = get_object_storage()
        if isinstance(storage, LocalStorageProvider):
            from pathlib import Path
            file_path = storage._safe_full_path(asset.object_key)
            if not Path(file_path).is_file():
                raise FileNotFoundError(asset.object_key)
            return FileResponse(file_path, media_type=asset.mime_type)
        return RedirectResponse(storage.sign_read_url(
            asset.object_key,
            expires_in=900,
            scope={"course_id": course_id, "user_id": current_user["user_id"], "purpose": "evidence_viewer"},
        ), status_code=307)
    except FileNotFoundError:
        reject_resource_not_found("Evidence 渲染文件不存在")


@document_parse_router.post("/course/{course_id}/document-ir/retrieval/query")
async def query_canonical_retrieval(
    course_id: int,
    payload: CanonicalRetrievalRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Teacher-workspace retrieval over candidate Canonical DocumentIR chunks.

    This route requires ``evidence.review`` and is deliberately distinct from
    learner QA, which resolves only the frozen retrieval manifest on the
    active CourseRelease.
    """
    require_course_permission(session, current_user, course_id, "evidence.review")
    ir_version_id = None
    if payload.run_id:
        requested = session.exec(select(DocumentParseRun).where(
            DocumentParseRun.course_id == course_id,
            DocumentParseRun.run_id == payload.run_id,
        )).first()
        if requested is None:
            reject_resource_not_found("解析运行不存在")
        ir_version_id = requested.document_ir_version_id
    if not ir_version_id:
        latest_run = session.exec(select(DocumentParseRun).where(
            DocumentParseRun.course_id == course_id,
            DocumentParseRun.document_ir_version_id.is_not(None),
        ).order_by(DocumentParseRun.finished_at.desc())).first()
        ir_version_id = latest_run.document_ir_version_id if latest_run else None
    if not ir_version_id:
        return unified_response(200, "尚无可检索的 Canonical DocumentIR", {"items": [], "total": 0})
    result_run = session.exec(select(DocumentParseRun).where(
        DocumentParseRun.course_id == course_id,
        DocumentParseRun.document_ir_version_id == ir_version_id,
    )).first()
    terms = [term.lower() for term in payload.query.split() if term.strip()]
    chunks = list(session.exec(select(RetrievalChunk).where(
        RetrievalChunk.course_id == course_id,
        RetrievalChunk.ir_version_id == ir_version_id,
        RetrievalChunk.status.in_(["draft", "candidate", "active"]),
    )).all())
    ranked = []
    for chunk in chunks:
        text = chunk.text.lower()
        score = sum(text.count(term) for term in terms)
        if score:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1].chunk_id))
    return unified_response(200, "Canonical 检索完成", {
        "run_id": result_run.run_id if result_run else None,
        "ir_version_id": ir_version_id,
        "items": [{
            "chunk_id": chunk.chunk_id, "score": score, "text": chunk.text,
            "document_id": chunk.document_id, "unit_id": chunk.unit_id,
            "block_ids": chunk.block_ids, "anchor_ids": chunk.anchor_ids,
        } for score, chunk in ranked[:payload.top_k]],
        "total": min(len(ranked), payload.top_k),
    })


# ---------------------------------------------------------------------------
# 候选证据片段审核
# ---------------------------------------------------------------------------


@document_parse_router.get("/course/{course_id}/evidence-spans")
async def list_evidence_spans(
    course_id: int,
    run_id: Optional[str] = Query(None, description="按解析运行过滤"),
    status: Optional[EvidenceSpanStatus] = Query(None, description="按状态过滤"),
    node_id: Optional[int] = Query(None, description="按知识点过滤"),
    include_history: bool = Query(False, description="包含未采用或已退役的历史 IR"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出候选证据片段（教师视图）。"""
    require_course_permission(session, current_user, course_id, "evidence.review")
    spans = document_parse_service.list_evidence_spans(
        session,
        course_id=course_id,
        run_id=run_id,
        status=status,
        node_id=node_id,
        include_history=include_history,
    )
    return unified_response(
        code=200,
        message="获取候选证据列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_span(s) for s in spans],
            "total": len(spans),
        },
    )


@document_parse_router.post("/course/{course_id}/evidence-spans/{span_id}/confirm")
async def confirm_evidence_span(
    course_id: int,
    span_id: str,
    payload: EvidenceSpanConfirmRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师确认候选证据：升级为正式 CourseEvidenceRecord + 学生可读 Citation。

    - 已 confirmed 的不可重复确认
    - rejected/orphaned 的不可再确认
    - 返回 span + formal_evidence + citation
    """
    context = require_course_permission(session, current_user, course_id, "evidence.confirm")
    user_id = int(current_user["user_id"])

    span, formal, citation = document_parse_service.confirm_evidence_span(
        session,
        course_id=course_id,
        span_id=span_id,
        confirmed_by=user_id,
        source_file=payload.source_file,
        source_type=payload.source_type,
        node_id=payload.node_id,
        identity_node_key=payload.identity_node_key,
    )
    session.commit()
    session.refresh(span)
    session.refresh(formal)
    session.refresh(citation)

    return unified_response(
        code=200,
        message="证据已确认并生成学生可读引用",
        data={
            "span": _serialize_span(span),
            "evidence": {
                "evidence_id": formal.evidence_id,
                "course_id": formal.course_id,
                "run_id": formal.run_id,
                "span_id": formal.span_id,
                "node_id": formal.node_id,
                "document_id": formal.document_id,
                "source_file": formal.source_file,
                "page_number": formal.page_number,
                "text_snippet": formal.text_snippet,
                "status": formal.status.value,
                "reviewed_by": formal.reviewed_by,
                "reviewed_at": formal.reviewed_at.isoformat() if formal.reviewed_at else None,
            },
            "citation": _serialize_citation(citation),
        },
    )


@document_parse_router.post("/course/{course_id}/evidence-spans/{span_id}/reject")
async def reject_evidence_span(
    course_id: int,
    span_id: str,
    payload: EvidenceSpanRejectRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师拒绝候选证据。"""
    require_course_permission(session, current_user, course_id, "evidence.review")
    user_id = int(current_user["user_id"])
    span = document_parse_service.reject_evidence_span(
        session,
        course_id=course_id,
        span_id=span_id,
        rejected_by=user_id,
        reject_reason=payload.reject_reason,
    )
    session.commit()
    session.refresh(span)
    return unified_response(
        code=200,
        message="证据已被拒绝",
        data=_serialize_span(span),
    )


# ---------------------------------------------------------------------------
# 学生可读 Citation 查询
# ---------------------------------------------------------------------------


@document_parse_router.get("/course/{course_id}/citations")
async def list_citations(
    course_id: int,
    node_id: Optional[int] = Query(None, description="按知识点过滤"),
    student_visible: Optional[bool] = Query(None, description="是否仅看学生可见"),
    include_stale: bool = Query(False, description="是否包含 stale/orphaned 引用"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """查询学生可读原文引用。

    - 学生默认仅看 student_visible=True 且 status in (exact, approximate)
    - 教师可看全部（include_stale=True 包含 source_updated/source_invalid）
    - 重解析/删除后历史引用返回 stale/orphaned 状态，不静默指向新内容
    """
    context = require_course_permission(session, current_user, course_id, "course.citation.read")
    is_teacher = context.allows("evidence.review")

    # 学生强制只看 student_visible 且不含 stale
    if not is_teacher:
        student_visible = True
        include_stale = False

    citations = document_parse_service.list_citations(
        session,
        course_id=course_id,
        node_id=node_id,
        student_visible=student_visible,
        include_stale=include_stale,
    )
    render_urls: dict[str, str] = {}
    for citation in citations:
        asset = session.exec(select(EvidenceRenderAsset).where(
            EvidenceRenderAsset.course_id == course_id,
            EvidenceRenderAsset.citation_id == citation.citation_id,
        )).first()
        if asset is None:
            asset = session.exec(select(EvidenceRenderAsset).where(
                EvidenceRenderAsset.course_id == course_id,
                EvidenceRenderAsset.document_id == citation.document_id,
                EvidenceRenderAsset.run_id == citation.run_id,
                EvidenceRenderAsset.page_number == citation.page_number,
                EvidenceRenderAsset.asset_type == "page_image",
            )).first()
        if asset is not None:
            render_urls[citation.citation_id] = (
                f"/api/v1/graph/course/{course_id}/evidence-renders/{asset.asset_id}/content"
            )
    return unified_response(
        code=200,
        message="获取原文引用列表成功",
        data={
            "course_id": course_id,
            "items": [
                _serialize_citation(
                    c,
                    student_view=not is_teacher,
                    render_url=render_urls.get(c.citation_id),
                )
                for c in citations
            ],
            "total": len(citations),
            "include_stale": include_stale,
        },
    )


# ---------------------------------------------------------------------------
# 图谱候选批次
# ---------------------------------------------------------------------------


@document_parse_router.get("/course/{course_id}/candidate-batches")
async def list_candidate_batches(
    course_id: int,
    status: Optional[CandidateBatchStatus] = Query(None, description="按状态过滤"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出图谱候选批次。"""
    require_course_permission(session, current_user, course_id, "knowledge.review")
    batches = graph_candidate_service.list_batches(
        session, course_id=course_id, status=status,
    )
    return unified_response(
        code=200,
        message="获取图谱候选批次列表成功",
        data={
            "course_id": course_id,
            "items": [
                _serialize_batch(
                    batch,
                    review_payload=graph_candidate_service.review_payload(session, batch=batch),
                )
                for batch in batches
            ],
            "total": len(batches),
        },
    )


# ---------------------------------------------------------------------------
# facade: 知识空间首屏 + 课程健康度
# ---------------------------------------------------------------------------


facade_knowledge_router = APIRouter()


@facade_knowledge_router.get("/course/{course_id}/knowledge")
async def get_knowledge_view(
    course_id: int,
    node_id: Optional[int] = Query(None, description="首屏聚焦的知识点ID"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """知识空间首屏聚合 ViewModel。

    前端首屏用的局部图、节点定义、相关 Evidence、学习位置、可见治理动作。
    跨课程严格隔离；学生只读已发布快照。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")
    is_teacher = context.allows("knowledge.review")

    # 已发布快照（学生与教师都可读）
    from app.services.graph_production_service import (
        get_active_snapshot,
        serialize_snapshot,
        get_evidence_for_node,
    )
    snapshot = get_active_snapshot(session, course_id)
    snapshot_view = serialize_snapshot(snapshot) if snapshot else None

    # 节点局部子图（如有 node_id）
    node_local: dict[str, Any] = {}
    if node_id is not None and snapshot is not None:
        nodes = snapshot.nodes or []
        relations = snapshot.relations or []
        node_ids_set = {str(node_id)}
        # 一跳邻居
        for rel in relations:
            src = str(rel.get("source") or rel.get("from") or "")
            tgt = str(rel.get("target") or rel.get("to") or "")
            if src == str(node_id):
                node_ids_set.add(tgt)
            if tgt == str(node_id):
                node_ids_set.add(src)
        local_nodes = [
            n for n in nodes
            if str(n.get("id") or n.get("node_id") or "") in node_ids_set
        ]
        local_relations = [
            r for r in relations
            if str(r.get("source") or r.get("from") or "") in node_ids_set
            and str(r.get("target") or r.get("to") or "") in node_ids_set
        ]
        node_local = {
            "focus_node_id": node_id,
            "nodes": local_nodes,
            "relations": local_relations,
        }

    # 节点相关 Evidence
    evidence_list: list[CourseEvidenceRecord] = []
    if node_id is not None:
        evidence_list = get_evidence_for_node(session, course_id, str(node_id))

    # 学生可读 Citation
    citations = document_parse_service.list_citations(
        session,
        course_id=course_id,
        node_id=node_id,
        student_visible=not is_teacher,
        include_stale=is_teacher,
    )

    # 教师视图：候选证据片段与图谱候选批次
    candidate_spans: list[EvidenceSpan] = []
    candidate_batches: list[GraphCandidateBatch] = []
    if is_teacher:
        candidate_spans = document_parse_service.list_evidence_spans(
            session, course_id=course_id, status=EvidenceSpanStatus.CANDIDATE,
        )
        candidate_batches = graph_candidate_service.list_batches(
            session, course_id=course_id,
        )

    return unified_response(
        code=200,
        message="获取知识空间首屏成功",
        data={
            "course_id": course_id,
            "snapshot": snapshot_view,
            "node_local": node_local,
            "evidence": [
                {
                    "evidence_id": e.evidence_id,
                    "document_id": e.document_id,
                    "source_file": e.source_file,
                    "page_number": e.page_number,
                    "text_snippet": e.text_snippet,
                    "status": e.status.value,
                }
                for e in evidence_list
            ],
            "citations": [
                _serialize_citation(c, student_view=not is_teacher)
                for c in citations
            ],
            "candidate_spans": [_serialize_span(s) for s in candidate_spans] if is_teacher else [],
            "candidate_batches": [
                _serialize_batch(
                    batch,
                    review_payload=graph_candidate_service.review_payload(session, batch=batch),
                )
                for batch in candidate_batches
            ] if is_teacher else [],
            "viewer_role": context.role.value if context.role else None,
            "can_review": is_teacher,
            "can_confirm_evidence": context.allows("evidence.confirm"),
        },
    )


@facade_knowledge_router.get("/course/{course_id}/health")
async def get_course_health_view(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课程健康度摘要：资料、映射、Evidence、图谱、媒体、发布质量门禁。

    返回每个维度的 available/experimental/pending/unavailable 状态与计数。
    不返回 503；图谱/Evidence 不可用时降级为 degraded 状态而非拒绝回答。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")
    is_teacher = context.allows("course.edit")

    # 资料
    materials = source_material_service.list_materials(session, course_id=course_id)
    materials_summary = {
        "status": "available" if materials else "pending",
        "total": len(materials),
    }

    # 解析运行
    runs = document_parse_service.list_runs(session, course_id=course_id)
    succeeded_runs = [r for r in runs if r.status in (
        ParseRunStatus.SUCCEEDED, ParseRunStatus.PARTIAL_SUCCESS,
    )]
    failed_runs = [r for r in runs if r.status == ParseRunStatus.FAILED]
    parse_summary = {
        "status": "available" if succeeded_runs else ("pending" if not runs else "degraded"),
        "total_runs": len(runs),
        "succeeded": len(succeeded_runs),
        "failed": len(failed_runs),
    }

    # Evidence
    evidence_records = session.exec(
        select(CourseEvidenceRecord).where(CourseEvidenceRecord.course_id == course_id)
    ).all()
    evidence_summary = {
        "status": "available" if evidence_records else "pending",
        "total": len(evidence_records),
    }

    # Citation
    citations = document_parse_service.list_citations(
        session, course_id=course_id, include_stale=False,
    )
    citation_summary = {
        "status": "available" if citations else "pending",
        "total": len(citations),
    }

    # 图谱快照
    from app.services.graph_production_service import get_active_snapshot, list_snapshots
    snapshot = get_active_snapshot(session, course_id)
    all_snapshots = list_snapshots(session, course_id)
    graph_summary = {
        "status": "available" if snapshot else "pending",
        "has_active": snapshot is not None,
        "total_snapshots": len(all_snapshots),
    }

    # 图谱候选批次
    batches = graph_candidate_service.list_batches(session, course_id=course_id)
    candidate_summary = {
        "status": "available" if batches else "pending",
        "total": len(batches),
    }

    # 发布
    releases = course_release_service.list_releases(session, course_id=course_id)
    active_release = course_release_service.get_active_release(session, course_id=course_id)
    release_summary = {
        "status": "available" if active_release else "pending",
        "total_releases": len(releases),
        "has_active": active_release is not None,
        "active_release_id": active_release.release_id if active_release else None,
    }

    # 图谱 ↔ release 关联
    release_links = graph_release_link_service.list_links(session, course_id=course_id)
    link_summary = {
        "status": "available" if release_links else "pending",
        "total": len(release_links),
    }

    # 整体健康度
    dimensions = [
        materials_summary, parse_summary, evidence_summary, citation_summary,
        graph_summary, candidate_summary, release_summary,
    ]
    available_count = sum(1 for d in dimensions if d["status"] == "available")
    overall = (
        "healthy" if available_count == len(dimensions)
        else "degraded" if available_count > 0
        else "pending"
    )

    return unified_response(
        code=200,
        message="获取课程健康度成功",
        data={
            "course_id": course_id,
            "overall": overall,
            "materials": materials_summary,
            "parse": parse_summary,
            "evidence": evidence_summary,
            "citations": citation_summary,
            "graph": graph_summary,
            "graph_candidates": candidate_summary,
            "release": release_summary,
            "graph_release_links": link_summary,
            "viewer_role": context.role.value if context.role else None,
            "can_view_health_detail": is_teacher,
        },
    )
