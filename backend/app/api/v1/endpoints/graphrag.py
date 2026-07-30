"""Course knowledge Bundle governance and learner read APIs."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.core.config import settings
from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session, session_factory
from app.models.document_parse_model import EvidenceAnchor
from app.models.knowledge_bundle_model import (
    CourseKnowledgeActivation,
    CourseKnowledgeBundle,
    CourseKnowledgeHead,
    CourseVectorIndex,
    GraphRagRun,
)
from app.platform.knowledge.sql_lance_provider import SqlLanceCourseKnowledgeProvider
from app.platform.knowledge.embedding import EmbeddingConfigurationError
from app.platform.knowledge.lancedb_provider import VectorIndexError
from app.platform.tasks.worker import local_task_worker
from app.platform.tasks.knowledge_build_queue import knowledge_build_queue
from app.services.course_access_service import require_course_permission
from app.services.graph_production_service import diff_snapshots
from app.services.knowledge_bundle_service import (
    KnowledgeBundleError,
    knowledge_bundle_service,
)

router = APIRouter(tags=["GraphRAG Knowledge Bundle"])


def _success(data: Any, *, code: int = 200, message: str = "操作成功"):
    return unified_response(code=code, message=message, data=data)


class RegenerateRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "reason": "先修关系方向需要重新抽取",
        "instructions": "区分定义、原理、应用和先修关系",
        "relation_profile": ["PREREQUISITE_OF", "PART_OF", "APPLIES_TO"],
        "preserve_existing_node_identity": True,
    }})

    reason: str = Field(min_length=1, max_length=1000, description="必填的重新生成原因")
    instructions: str = Field(default="", max_length=8000, description="传给抽取策略的教师反馈")
    source_scope: dict[str, Any] = Field(default_factory=dict, description="可选文档和页码范围")
    required_concepts: list[str] = Field(default_factory=list, max_length=100)
    forbidden_concepts: list[str] = Field(default_factory=list, max_length=100)
    relation_profile: list[str] = Field(default_factory=list, max_length=20)
    preserve_existing_node_identity: bool = Field(
        default=True,
        description="仅允许复用稳定 kn_* 身份，不复用 GraphRAG UUID",
    )
    parent_run_id: str | None = Field(default=None, description="可选的父运行审计 ID")


class RefineRequest(BaseModel):
    """Deterministically rebuild stable identities from existing paid artifacts."""

    model_config = ConfigDict(json_schema_extra={"example": {
        "parent_run_id": "grr_bc3348e4c9924ab9b5dabbc66b8d88c1",
        "reason": "收紧身份映射并过滤模型占位实体",
        "identity_policy": "strict-title-anchor/1.0",
        "filter_placeholders": True,
    }})

    parent_run_id: str = Field(
        min_length=5,
        max_length=100,
        description="已有完整 Parquet 和 typed relationships 的父运行",
    )
    reason: str = Field(min_length=1, max_length=1000, description="精炼原因，写入审计记录")
    identity_policy: str = Field(
        default="strict-title-anchor/1.0",
        description="确定性身份策略；当前只支持严格标题与来源重叠策略",
    )
    filter_placeholders: bool = Field(
        default=True,
        description="必须启用，过滤 NONE、IMAGE<n> 等占位实体",
    )


class ApproveRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "run_id": "grr_example",
        "label": "课程知识图谱严格映射版",
    }})

    run_id: str = Field(min_length=5, max_length=100, description="待审批 GraphRAG/精炼运行 ID")
    label: str = Field(default="", max_length=240, description="快照和 Bundle 展示标签")


class BootstrapRequest(BaseModel):
    confirm_existing_snapshot: bool


def _actor(current_user: dict) -> int:
    return int(current_user["user_id"])


def _error(exc: KnowledgeBundleError) -> HTTPException:
    not_found = {
        "GRAPHRAG_RUN_NOT_FOUND", "KNOWLEDGE_BUNDLE_NOT_FOUND",
        "GRAPH_SNAPSHOT_NOT_FOUND", "VECTOR_INDEX_NOT_FOUND",
    }
    validation = {
        "REGENERATION_REASON_REQUIRED", "GRAPH_INPUT_EMPTY",
        "EVIDENCE_CLOSURE_FAILED", "GRAPH_OUTPUT_INVALID",
        "REFINEMENT_REASON_REQUIRED", "IDENTITY_POLICY_UNSUPPORTED",
        "PLACEHOLDER_FILTER_REQUIRED", "GRAPH_INPUT_MANIFEST_MISMATCH",
        "GRAPH_QUALITY_GATE_FAILED", "IDENTITY_AMBIGUOUS",
    }
    unavailable = {"GRAPH_ARTIFACTS_NOT_FOUND", "TYPED_RELATIONSHIPS_NOT_FOUND"}
    code = (
        404 if exc.code in not_found
        else 422 if exc.code in validation
        else 424 if exc.code in unavailable
        else 409
    )
    return HTTPException(
        status_code=code,
        detail={"error_code": exc.code, "message": str(exc)},
    )


def _submit(task: dict) -> None:
    task_id = str(task.get("task_id") or "")
    if not task_id:
        return
    knowledge_build_queue.submit(session_factory, local_task_worker, task_id)


@router.get(
    "/course/{course_id}/knowledge-bundle/draft",
    summary="获取教师侧最新图谱草稿和 Evidence 预览",
    description="只返回本课程最新 GraphRAG/精炼运行；草稿不会被学生、推荐或助教读取。",
)
async def get_draft(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.review")
    require_course_permission(session, current_user, course_id, "evidence.review")
    run = session.exec(select(GraphRagRun).where(
        GraphRagRun.course_id == course_id,
    ).order_by(GraphRagRun.created_at.desc())).first()
    if run is None:
        return _success(None, message="暂无 GraphRAG 草稿")
    data = knowledge_bundle_service.serialize_run(run)
    anchor_ids = {
        str(anchor_id)
        for item in [*(data.get("nodes") or []), *(data.get("relations") or [])]
        for anchor_id in item.get("source_anchor_ids") or []
    }
    anchors = session.exec(select(EvidenceAnchor).where(
        EvidenceAnchor.course_id == course_id,
        EvidenceAnchor.anchor_id.in_(sorted(anchor_ids)),
    )).all() if anchor_ids else []
    preview_by_id = {
        anchor.anchor_id: {
            "anchor_id": anchor.anchor_id,
            "run_id": anchor.run_id,
            "document_id": anchor.document_id,
            "page_number": anchor.page_or_slide,
            "text_snippet": anchor.text,
            "bbox": anchor.bbox,
            "status": anchor.status,
        }
        for anchor in anchors
    }
    for item in [*(data.get("nodes") or []), *(data.get("relations") or [])]:
        item["evidence_previews"] = [
            preview_by_id[anchor_id]
            for anchor_id in item.get("source_anchor_ids") or []
            if anchor_id in preview_by_id
        ]
    return _success(data, message="获取 GraphRAG 草稿成功")


@router.post(
    "/course/{course_id}/knowledge-bundle/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交一次新的付费 GraphRAG 抽取",
    description=(
        "从 Canonical DocumentIR 创建新的语义抽取任务。该操作可能调用配置的 "
        "Completion Provider；相同输入、配置和教师反馈会复用未完成草稿。"
    ),
)
async def regenerate(
    course_id: int,
    payload: RegenerateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.review")
    try:
        run, task = knowledge_bundle_service.request_regeneration(
            session,
            course_id=course_id,
            actor_user_id=_actor(current_user),
            reason=payload.reason,
            instructions=payload.instructions,
            source_scope={
                **payload.source_scope,
                "required_concepts": payload.required_concepts,
                "forbidden_concepts": payload.forbidden_concepts,
                "preserve_existing_node_identity": payload.preserve_existing_node_identity,
            },
            relation_profile=payload.relation_profile,
            parent_run_id=payload.parent_run_id,
        )
    except KnowledgeBundleError as exc:
        raise _error(exc) from exc
    _submit(task)
    return _success(
        {"run": knowledge_bundle_service.serialize_run(run), "task": task},
        code=202,
        message="GraphRAG 重新生成任务已提交",
    )


@router.post(
    "/course/{course_id}/knowledge-bundle/refine",
    status_code=status.HTTP_201_CREATED,
    summary="使用既有产物创建零模型调用的严格精炼草稿",
    description=(
        "读取父运行已经落盘的 GraphRAG Parquet 与 typed_relationships.json，"
        "重新执行占位实体过滤、严格 kn_* 身份对齐、关系去自环和去重。"
        "该接口不调用 Completion、Embedding 或关系分类模型，也不会自动批准或激活。"
    ),
)
async def refine(
    course_id: int,
    payload: RefineRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.review")
    try:
        run = knowledge_bundle_service.refine_existing_run(
            session,
            course_id=course_id,
            parent_run_id=payload.parent_run_id,
            actor_user_id=_actor(current_user),
            reason=payload.reason,
            identity_policy=payload.identity_policy,
            filter_placeholders=payload.filter_placeholders,
        )
    except KnowledgeBundleError as exc:
        raise _error(exc) from exc
    return _success(
        {
            "run": knowledge_bundle_service.serialize_run(run),
            "model_calls": 0,
            "approval_required": True,
            "activation_pending": False,
        },
        code=201,
        message="严格精炼草稿已生成，未调用模型，等待教师整图审批",
    )


@router.post(
    "/course/{course_id}/knowledge-bundle/approve",
    status_code=status.HTTP_202_ACCEPTED,
    summary="批准整图并异步构建索引",
    description=(
        "批准会闭合 Evidence/Citation、冻结 GraphSnapshot 与 RetrievalSnapshot，"
        "然后提交 LanceDB 构建任务。批准不等于激活；索引校验成功后才原子切换 Head。"
    ),
)
async def approve(
    course_id: int,
    payload: ApproveRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.edit")
    require_course_permission(session, current_user, course_id, "evidence.confirm")
    try:
        bundle, task = knowledge_bundle_service.approve_draft(
            session,
            course_id=course_id,
            run_id=payload.run_id,
            actor_user_id=_actor(current_user),
            label=payload.label,
        )
    except KnowledgeBundleError as exc:
        raise _error(exc) from exc
    _submit(task)
    return _success({
        "bundle": knowledge_bundle_service.serialize_bundle(bundle),
        "task": task,
        "activation_pending": True,
    }, code=202, message="整图已批准，正在构建向量索引")


@router.post(
    "/course/{course_id}/knowledge-bundle/bootstrap",
    status_code=status.HTTP_202_ACCEPTED,
    summary="从既有正式快照创建兼容 Bootstrap Bundle",
    description="仅用于迁移；不会重新抽取语义关系，索引校验成功后才激活。",
)
async def bootstrap(
    course_id: int,
    payload: BootstrapRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.edit")
    if not payload.confirm_existing_snapshot:
        raise HTTPException(status_code=422, detail="必须明确确认现有正式快照")
    try:
        bundle, task = knowledge_bundle_service.bootstrap_existing_snapshot(
            session, course_id=course_id, actor_user_id=_actor(current_user)
        )
    except KnowledgeBundleError as exc:
        raise _error(exc) from exc
    _submit(task)
    return _success({
        "bundle": knowledge_bundle_service.serialize_bundle(bundle),
        "task": task,
    }, code=202, message="Bootstrap Bundle 构建任务已提交")


@router.get(
    "/course/{course_id}/knowledge-bundle/status",
    summary="获取抽取、精炼、索引和服务就绪状态",
    description="返回最新运行、最新 Bundle、Active Head 和向量索引计数，不返回密钥。",
)
async def bundle_status(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.version.view")
    latest_run = session.exec(select(GraphRagRun).where(
        GraphRagRun.course_id == course_id,
    ).order_by(GraphRagRun.created_at.desc())).first()
    latest_bundle = session.exec(select(CourseKnowledgeBundle).where(
        CourseKnowledgeBundle.course_id == course_id,
    ).order_by(CourseKnowledgeBundle.version.desc())).first()
    head = session.exec(select(CourseKnowledgeHead).where(
        CourseKnowledgeHead.course_id == course_id,
    )).first()
    vector = None
    if latest_bundle and latest_bundle.vector_index_id:
        vector = session.exec(select(CourseVectorIndex).where(
            CourseVectorIndex.vector_index_id == latest_bundle.vector_index_id,
        )).first()
    completion_configured = all((
        settings.GRAPHRAG_COMPLETION_PROVIDER,
        settings.GRAPHRAG_COMPLETION_MODEL,
        settings.GRAPHRAG_COMPLETION_API_BASE,
        settings.GRAPHRAG_COMPLETION_API_KEY,
    ))
    embedding_provider = settings.GRAPHRAG_EMBEDDING_PROVIDER.strip().lower()
    embedding_configured = bool(
        settings.GRAPHRAG_EMBEDDING_PROVIDER
        and settings.GRAPHRAG_EMBEDDING_MODEL
        and (
            settings.GRAPHRAG_EMBEDDING_LOCAL_PATH
            if embedding_provider in {"local_bge", "bge-local", "local"}
            else (
                settings.GRAPHRAG_EMBEDDING_API_BASE
                and settings.GRAPHRAG_EMBEDDING_API_KEY
            )
        )
    )
    return _success({
        "runtime": {
            "knowledge_bundle_enabled": settings.KNOWLEDGE_BUNDLE_ENABLED,
            "graphrag_enabled": settings.GRAPHRAG_ENABLED,
            "completion_configured": completion_configured,
            "embedding_configured": embedding_configured,
            "isolated_worker_configured": bool(settings.GRAPHRAG_WORKER_PYTHON),
            "extraction_ready": bool(
                settings.KNOWLEDGE_BUNDLE_ENABLED
                and settings.GRAPHRAG_ENABLED
                and completion_configured
                and embedding_configured
            ),
            "refinement_ready": bool(settings.KNOWLEDGE_BUNDLE_ENABLED),
            "serving_ready": bool(head and head.active_bundle_id),
            "ready": bool(
                settings.KNOWLEDGE_BUNDLE_ENABLED
                and settings.GRAPHRAG_ENABLED
                and completion_configured
                and embedding_configured
            ),
        },
        "active_bundle_id": head.active_bundle_id if head else None,
        "lock_version": head.lock_version if head else 0,
        "latest_run": knowledge_bundle_service.serialize_run(latest_run) if latest_run else None,
        "latest_bundle": (
            knowledge_bundle_service.serialize_bundle(latest_bundle)
            if latest_bundle else None
        ),
        "vector_index": {
            "vector_index_id": vector.vector_index_id,
            "status": vector.status.value,
            "vector_dimension": vector.vector_dimension,
            "text_unit_row_count": vector.text_unit_row_count,
            "entity_row_count": vector.entity_row_count,
            "evidence_row_count": vector.evidence_row_count,
            "error_code": vector.error_code,
            "error_message": vector.error_message,
        } if vector else None,
    }, message="获取知识包状态成功")


@router.get(
    "/course/{course_id}/knowledge-bundles",
    summary="列出不可变知识包版本",
    description="历史 Bundle 和 LanceDB 目录保留；is_active 由 CourseKnowledgeHead 决定。",
)
async def list_bundles(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.version.view")
    bundles = session.exec(select(CourseKnowledgeBundle).where(
        CourseKnowledgeBundle.course_id == course_id,
    ).order_by(CourseKnowledgeBundle.version.desc())).all()
    head = session.exec(select(CourseKnowledgeHead).where(
        CourseKnowledgeHead.course_id == course_id,
    )).first()
    return _success([{
        **knowledge_bundle_service.serialize_bundle(bundle),
        "is_active": bool(head and head.active_bundle_id == bundle.bundle_id),
    } for bundle in bundles], message="获取知识包版本成功")


@router.get(
    "/course/{course_id}/knowledge-bundles/diff",
    summary="比较两个 Bundle 的图谱快照",
    description="返回节点与关系的 added/removed/modified 差异，不修改激活指针。",
)
async def bundle_diff(
    course_id: int,
    from_bundle_id: str = Query(...),
    to_bundle_id: str = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.version.view")
    bundles = session.exec(select(CourseKnowledgeBundle).where(
        CourseKnowledgeBundle.course_id == course_id,
        CourseKnowledgeBundle.bundle_id.in_([from_bundle_id, to_bundle_id]),
    )).all()
    by_id = {bundle.bundle_id: bundle for bundle in bundles}
    if from_bundle_id not in by_id or to_bundle_id not in by_id:
        raise HTTPException(status_code=404, detail="Bundle 不存在")
    return _success(diff_snapshots(
        session,
        course_id,
        by_id[from_bundle_id].graph_snapshot_id,
        by_id[to_bundle_id].graph_snapshot_id,
    ), message="知识包版本对比成功")


@router.get(
    "/course/{course_id}/knowledge-bundles/{bundle_id}",
    summary="获取指定 Bundle 及激活审计",
)
async def get_bundle(
    course_id: int,
    bundle_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.version.view")
    bundle = session.exec(select(CourseKnowledgeBundle).where(
        CourseKnowledgeBundle.course_id == course_id,
        CourseKnowledgeBundle.bundle_id == bundle_id,
    )).first()
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle 不存在")
    activations = session.exec(select(CourseKnowledgeActivation).where(
        CourseKnowledgeActivation.course_id == course_id,
        CourseKnowledgeActivation.bundle_id == bundle_id,
    ).order_by(CourseKnowledgeActivation.created_at.desc())).all()
    return _success({
        **knowledge_bundle_service.serialize_bundle(bundle),
        "activations": [{
            "activation_id": item.activation_id,
            "action": item.action,
            "previous_bundle_id": item.previous_bundle_id,
            "actor_user_id": item.actor_user_id,
            "created_at": item.created_at.isoformat(),
        } for item in activations],
    }, message="获取知识包详情成功")


@router.post(
    "/course/{course_id}/knowledge-bundles/{bundle_id}/rollback",
    summary="原子回滚到历史 READY Bundle",
    description="只切换 Active Head 并新增 Activation；不删除当前或历史 LanceDB。",
)
async def rollback_bundle(
    course_id: int,
    bundle_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.edit")
    try:
        bundle = knowledge_bundle_service.activate_bundle(
            session,
            course_id=course_id,
            bundle_id=bundle_id,
            actor_user_id=_actor(current_user),
            action="rollback",
        )
    except KnowledgeBundleError as exc:
        raise _error(exc) from exc
    return _success(
        knowledge_bundle_service.serialize_bundle(bundle),
        message="知识包已原子切换",
    )


@router.get(
    "/course/{course_id}/knowledge-bundle/active",
    summary="获取当前学生可消费的 Active Bundle",
    description="仅返回 READY 且被 Head 指向的知识包；构建中草稿严格不可见。",
)
async def active_bundle(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.view")
    bundle = knowledge_bundle_service.get_active_bundle(session, course_id)
    return _success(
        knowledge_bundle_service.serialize_bundle(bundle) if bundle else None,
        message="获取当前知识包成功",
    )


@router.get(
    "/course/{course_id}/knowledge-bundle/graph",
    summary="读取当前 Active Bundle 的完整正式图谱",
    description="节点只使用稳定 kn_* 身份，并携带 GraphSnapshot/Bundle 版本信息。",
)
async def active_graph(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.view")
    graph = SqlLanceCourseKnowledgeProvider().get_graph(course_id)
    return _success(asdict(graph) if graph else None, message="获取学生图谱成功")


@router.get(
    "/course/{course_id}/knowledge-bundle/nodes/{node_key}",
    summary="读取正式节点、邻居和 Citation",
    description="node_key 必须是 kn_*；GraphRAG UUID 不属于产品接口。",
)
async def active_node(
    course_id: int,
    node_key: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.view")
    require_course_permission(session, current_user, course_id, "course.citation.read")
    if not node_key.startswith("kn_"):
        raise HTTPException(status_code=422, detail="节点必须使用正式 kn_* 身份")
    provider = SqlLanceCourseKnowledgeProvider()
    node = provider.get_node(course_id, node_key)
    if node is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    citations = provider.get_citations(course_id, node_key=node_key)
    return _success(
        {**asdict(node), "citations": list(citations)},
        message="获取知识节点成功",
    )


@router.get(
    "/course/{course_id}/knowledge-bundle/search",
    summary="在当前课程 Active Bundle 中检索原文证据",
    description=(
        "查询固定课程独立 LanceDB，结果必须 Citation 闭合；索引不可用时失败关闭，"
        "不会回退到候选 Chunk 或其他课程。"
    ),
)
async def active_search(
    course_id: int,
    q: str = Query(..., min_length=1, max_length=1000),
    top_k: int = Query(6, ge=1, le=20),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "knowledge.view")
    require_course_permission(session, current_user, course_id, "course.citation.read")
    try:
        result = SqlLanceCourseKnowledgeProvider().search_evidence(
            course_id, q, top_k=top_k
        )
    except (EmbeddingConfigurationError, VectorIndexError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": getattr(exc, "code", "KNOWLEDGE_SEARCH_UNAVAILABLE"),
                "message": "当前知识包检索暂不可用",
            },
        ) from exc
    return _success(
        asdict(result) if result else None,
        message="课程知识检索成功",
    )
