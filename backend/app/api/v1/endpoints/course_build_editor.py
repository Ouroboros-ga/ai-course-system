"""Step 5-8: editable course outline, scripts, proposals, mapping and publish.

This router is deliberately small and demo-oriented.  It writes only draft
versions; published outline/script data is immutable and exposed read-only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.core.time_utils import utcnow_aware
from app.core.config import settings
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    CoursePptMapping,
    OutlineLifecycleStatus,
    OutlineNodeType,
    PatchOperation,
    PatchProposal,
    PatchProposalOperation,
    PatchProposalStatus,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.course_build_model import BuildStepName, BuildStepStatus, CourseBuildStep, CourseCorpusSnapshot, MaterialStatus, SourceMaterial
from app.models.document_parse_model import ParsePipeline, StaleStrategy
from app.models.document_parse_model import DocumentBlock, EvidenceSpan, EvidenceSpanStatus
from app.models.graph_production_model import CourseEvidenceRecord, EvidenceStatus
from app.models.database import get_session
from app.services.course_access_service import require_course_permission
from app.services.course_build_service import course_release_service, quality_gate_service, source_material_service
from app.services.course_corpus_service import course_corpus_service
from app.services.document_parse_service import document_parse_service
from app.services.object_storage import get_object_storage
from app.services.task_service import TaskCreateRequest, task_service
from app.platform.tasks.worker import local_task_worker
from app.models.database import session_factory
from app.models.resource_model import ResourceItem, ResourceLifecycleStatus, ResourceVisibility
from app.services.ppt_generation_service import ppt_generation_service
from app.schemas.controlled_prep import ControlledPrepInput, TeachingStyleConfig
from app.services.controlled_prep_workflow import controlled_prep_workflow

router = APIRouter()
logger = logging.getLogger(__name__)


class OutlineNodeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    node_type: OutlineNodeType = OutlineNodeType.KNOWLEDGE_POINT
    parent_node_id: Optional[str] = None
    order_index: int = Field(default=0, ge=0)
    page_range: Optional[str] = Field(default=None, max_length=64)


class OutlineNodeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    node_type: Optional[OutlineNodeType] = None
    parent_node_id: Optional[str] = None
    order_index: Optional[int] = Field(default=None, ge=0)
    page_range: Optional[str] = Field(default=None, max_length=64)


class ReorderRequest(BaseModel):
    node_ids: list[str] = Field(min_length=1)


class ScriptUpdate(BaseModel):
    content: Optional[str] = Field(default=None, max_length=200_000)
    style: Optional[str] = Field(default=None, max_length=64)


class ProposalOperationInput(BaseModel):
    operation: PatchOperation = PatchOperation.REPLACE
    target: str = Field(min_length=1, max_length=300)
    before: str = ""
    after: str = ""
    reason: str = ""
    evidence_refs: Optional[list[str]] = None
    external_ref: Optional[str] = None


class ProposalCreate(BaseModel):
    tool_name: str = Field(default="OutlineProposalTool", max_length=64)
    policy_version: str = Field(default="course-build-agent/1.0", max_length=32)
    reason: str = Field(default="", max_length=2000)
    operations: list[ProposalOperationInput] = Field(min_length=1)


class ProposalDecision(BaseModel):
    accepted: bool


class PptMappingUpdate(BaseModel):
    page_range: Optional[str] = Field(default=None, max_length=64)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    locked: Optional[bool] = None


class PptGenerateRequest(BaseModel):
    template_id: Optional[str] = Field(default=None, max_length=128)
    search: bool = False


class ControlledPrepRequest(BaseModel):
    """Input for one controlled preparation run.

    Evidence text is resolved server-side from course-scoped records. This
    prevents callers from smuggling arbitrary text into an auditable proposal.
    """

    source_text: str = Field(min_length=1, max_length=200_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=500)
    course_positioning: str = Field(default="", max_length=2_000)
    style: TeachingStyleConfig = Field(default_factory=TeachingStyleConfig)
    candidate_id: Optional[str] = Field(default=None, max_length=100)
    existing_outline_ids: dict[str, str] = Field(default_factory=dict)
    existing_script_ids: dict[str, str] = Field(default_factory=dict)


class PrepAgentCommandRequest(BaseModel):
    """Natural-language instruction for the teacher-facing preparation agent."""

    instruction: str = Field(min_length=2, max_length=8_000)
    outline_node_id: Optional[str] = Field(default=None, max_length=100)


class LegacyReleasePublishRequest(BaseModel):
    """Compatibility payload for the editor's one-click release action."""

    quality_gate_run_id: Optional[str] = Field(default=None, max_length=100)


def _mark_build_step(session: Session, course_id: int, step_name: BuildStepName, status: BuildStepStatus, actor_id: int, output_ref: str = "") -> None:
    step = session.exec(select(CourseBuildStep).where(
        CourseBuildStep.course_id == course_id,
        CourseBuildStep.step_name == step_name,
    )).first()
    if not step:
        step = CourseBuildStep(course_id=course_id, step_name=step_name)
    step.status = status
    step.output_ref = output_ref
    step.updated_at = utcnow_aware()
    session.add(step)


def _draft_outline(session: Session, course_id: int) -> CourseOutlineVersion | None:
    return session.exec(
        select(CourseOutlineVersion)
        .where(CourseOutlineVersion.course_id == course_id)
        .where(CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT)
        .order_by(CourseOutlineVersion.version.desc())
    ).first()


def _published_outline(session: Session, course_id: int) -> CourseOutlineVersion | None:
    return session.exec(
        select(CourseOutlineVersion)
        .where(CourseOutlineVersion.course_id == course_id)
        .where(CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.PUBLISHED)
        .order_by(CourseOutlineVersion.version.desc())
    ).first()


def _ensure_draft_outline(session: Session, course_id: int, user_id: int) -> CourseOutlineVersion:
    draft = _draft_outline(session, course_id)
    if draft:
        return draft
    published = _published_outline(session, course_id)
    latest = session.exec(
        select(CourseOutlineVersion).where(CourseOutlineVersion.course_id == course_id)
        .order_by(CourseOutlineVersion.version.desc())
    ).first()
    draft = CourseOutlineVersion(
        course_id=course_id,
        version=(latest.version + 1) if latest else 1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        source_parse_run_id=published.source_parse_run_id if published else None,
        created_by=user_id,
    )
    session.add(draft)
    session.flush()
    if published:
        nodes = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.outline_version_id == published.outline_version_id,
        )).all()
        id_map: dict[str, str] = {}
        for old in sorted(nodes, key=lambda n: n.order_index):
            new = CourseOutlineNode(
                outline_version_id=draft.outline_version_id,
                course_id=course_id,
                parent_node_id=id_map.get(old.parent_node_id),
                node_type=old.node_type,
                title=old.title,
                order_index=old.order_index,
                knowledge_graph_node_id=old.knowledge_graph_node_id,
                source_block_refs=old.source_block_refs,
                page_range=old.page_range,
                generation_reason=old.generation_reason,
                confidence=old.confidence,
                content_hash=old.content_hash,
            )
            session.add(new)
            session.flush()
            id_map[old.outline_node_id] = new.outline_node_id
        mappings = session.exec(select(CoursePptMapping).where(
            CoursePptMapping.course_id == course_id,
            CoursePptMapping.status == "published",
        )).all()
        for old_mapping in mappings:
            new_outline_id = id_map.get(old_mapping.outline_node_id)
            if not new_outline_id:
                continue
            session.add(CoursePptMapping(
                course_id=course_id,
                outline_node_id=new_outline_id,
                material_version_id=old_mapping.material_version_id,
                page_start=old_mapping.page_start,
                page_end=old_mapping.page_end,
                page_refs=old_mapping.page_refs,
                confidence=old_mapping.confidence,
                source_block_refs=old_mapping.source_block_refs,
                status="draft",
                teacher_locked=old_mapping.teacher_locked,
                created_by=user_id,
            ))
        # Keep the script aligned with the copied outline so the next draft is
        # editable without mutating the published script.
        published_script = session.exec(select(TeachingScriptVersion).where(
            TeachingScriptVersion.course_id == course_id,
            TeachingScriptVersion.outline_version_id == published.outline_version_id,
        ).order_by(TeachingScriptVersion.version.desc())).first()
        if published_script:
            new_script = TeachingScriptVersion(
                course_id=course_id,
                outline_version_id=draft.outline_version_id,
                version=published_script.version + 1,
                lifecycle_status=OutlineLifecycleStatus.DRAFT,
                source_parse_run_id=published_script.source_parse_run_id,
                created_by=user_id,
            )
            session.add(new_script)
            session.flush()
            script_nodes = session.exec(select(TeachingScriptNode).where(
                TeachingScriptNode.script_version_id == published_script.script_version_id,
            )).all()
            for old_script in script_nodes:
                new_outline_id = id_map.get(old_script.outline_node_id)
                if not new_outline_id:
                    continue
                session.add(TeachingScriptNode(
                    script_version_id=new_script.script_version_id,
                    course_id=course_id,
                    outline_node_id=new_outline_id,
                    content=old_script.content,
                    style=old_script.style,
                    evidence_refs=old_script.evidence_refs,
                    source_block_refs=old_script.source_block_refs,
                    content_hash=old_script.content_hash,
                ))
    return draft


def _ensure_draft_script(session: Session, outline: CourseOutlineVersion, user_id: int) -> TeachingScriptVersion:
    script = session.exec(
        select(TeachingScriptVersion)
        .where(TeachingScriptVersion.course_id == outline.course_id)
        .where(TeachingScriptVersion.outline_version_id == outline.outline_version_id)
        .order_by(TeachingScriptVersion.version.desc())
    ).first()
    if script:
        return script
    script = TeachingScriptVersion(
        course_id=outline.course_id,
        outline_version_id=outline.outline_version_id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        source_parse_run_id=outline.source_parse_run_id,
        created_by=user_id,
    )
    session.add(script)
    session.flush()
    return script


def _mark_teacher_edited(version: CourseOutlineVersion | TeachingScriptVersion) -> None:
    """Record teacher intent so an initial draft can never be replaced later."""
    if version.generation_source == "agent_initial_generation" and version.review_status == "pending":
        version.review_status = "teacher_edited"


def _outline_tree_views(nodes: list[CourseOutlineNode]) -> tuple[list[CourseOutlineNode], dict[str, dict[str, Any]]]:
    """Return one canonical display order/label for every build surface.

    ``outline_node_id`` remains the durable cross-version reference.  Teachers
    see a label derived from the current outline tree, so renaming or moving a
    node immediately updates scripts and PPT mapping without duplicating titles
    into those tables.
    """
    children: dict[str | None, list[CourseOutlineNode]] = {}
    for node in nodes:
        children.setdefault(node.parent_node_id, []).append(node)
    for group in children.values():
        group.sort(key=lambda item: (item.order_index, item.created_at, item.outline_node_id))

    ordered: list[CourseOutlineNode] = []
    views: dict[str, dict[str, Any]] = {}

    def walk(parent_id: str | None, numeric_path: tuple[int, ...], breadcrumb: list[str], depth: int) -> None:
        type_counts: dict[OutlineNodeType, int] = {}
        for node in children.get(parent_id, []):
            type_counts[node.node_type] = type_counts.get(node.node_type, 0) + 1
            index = type_counts[node.node_type]
            if node.node_type == OutlineNodeType.CHAPTER:
                child_path = (index,)
                number = f"第{index}章"
            elif node.node_type == OutlineNodeType.SECTION:
                child_path = numeric_path + (index,) if numeric_path else (index,)
                number = ".".join(str(value) for value in child_path) if numeric_path else f"第{index}节"
            elif node.node_type == OutlineNodeType.KNOWLEDGE_POINT:
                child_path = numeric_path + (index,) if numeric_path else (index,)
                number = ".".join(str(value) for value in child_path)
            elif node.node_type == OutlineNodeType.EXAMPLE:
                child_path = numeric_path
                number = f"例 {index}"
            else:
                child_path = numeric_path
                number = f"练习 {index}"
            label = f"{number} {node.title}".strip()
            node_breadcrumb = [*breadcrumb, label]
            views[node.outline_node_id] = {
                "display_number": number,
                "display_label": label,
                "breadcrumb": node_breadcrumb,
                "depth": depth,
            }
            ordered.append(node)
            walk(node.outline_node_id, child_path, node_breadcrumb, depth + 1)

    walk(None, (), [], 0)
    # A malformed legacy tree may point to a missing parent. Keep it visible
    # and label it predictably instead of making data disappear from review.
    for node in nodes:
        if node.outline_node_id not in views:
            views[node.outline_node_id] = {
                "display_number": "未归类",
                "display_label": f"未归类 {node.title}",
                "breadcrumb": [f"未归类 {node.title}"],
                "depth": 0,
            }
            ordered.append(node)
    return ordered, views


def _outline_node_view(node: CourseOutlineNode, display: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "outline_node_id": node.outline_node_id,
        "outline_version_id": node.outline_version_id,
        "course_id": node.course_id,
        "parent_node_id": node.parent_node_id,
        "node_type": node.node_type.value,
        "title": node.title,
        "order_index": node.order_index,
        "page_range": node.page_range,
        "source_block_refs": node.source_block_refs or [],
        "generation_reason": node.generation_reason,
        "confidence": node.confidence,
        "locked": node.locked_by is not None,
        "locked_by": node.locked_by,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        **(display or {}),
    }


def _script_node_view(
    node: TeachingScriptNode,
    *,
    outline_view: dict[str, Any] | None = None,
    ppt_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    view = {
        "script_node_id": node.script_node_id,
        "outline_node_id": node.outline_node_id,
        "course_id": node.course_id,
        "content": node.content,
        "style": node.style,
        "evidence_refs": node.evidence_refs or [],
        "source_block_refs": node.source_block_refs or [],
        "locked": node.locked_by is not None,
        "locked_by": node.locked_by,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
    }
    if outline_view is not None:
        view["outline_node"] = outline_view
        view["outline_title"] = outline_view["title"]
        view["display_number"] = outline_view.get("display_number")
        view["display_label"] = outline_view.get("display_label")
        view["breadcrumb"] = outline_view.get("breadcrumb", [])
    if ppt_mapping is not None:
        view["ppt_mapping"] = ppt_mapping
    return view


def _ppt_mapping_view(mapping: CoursePptMapping) -> dict[str, Any]:
    return {
        "mapping_id": mapping.mapping_id,
        "course_id": mapping.course_id,
        "outline_node_id": mapping.outline_node_id,
        "material_version_id": mapping.material_version_id,
        "page_start": mapping.page_start,
        "page_end": mapping.page_end,
        "page_refs": mapping.page_refs or [],
        "page_range": f"{mapping.page_start}-{mapping.page_end}" if mapping.page_start != mapping.page_end else str(mapping.page_start),
        "confidence": mapping.confidence,
        "source_block_refs": mapping.source_block_refs or [],
        "status": mapping.status,
        "teacher_locked": mapping.teacher_locked,
        "updated_at": mapping.updated_at.isoformat() if mapping.updated_at else None,
    }


@router.get("/course/{course_id}/outline")
async def get_outline(course_id: int, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.view")
    version = _draft_outline(session, course_id) or _published_outline(session, course_id)
    if not version:
        return unified_response(200, "课程目录尚未生成", {"version": None, "nodes": []})
    nodes = list(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == version.outline_version_id,
    )).all())
    ordered_nodes, displays = _outline_tree_views(nodes)
    return unified_response(200, "获取课程目录成功", {
        "version": {
            "outline_version_id": version.outline_version_id,
            "version": version.version,
            "status": version.lifecycle_status.value,
            "generation_source": version.generation_source,
            "review_status": version.review_status,
        },
        "nodes": [_outline_node_view(n, displays[n.outline_node_id]) for n in ordered_nodes],
        "editable": version.lifecycle_status == OutlineLifecycleStatus.DRAFT,
    })


@router.post("/course/{course_id}/outline/nodes")
async def create_outline_node(course_id: int, payload: OutlineNodeCreate, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.structure.edit")
    version = _ensure_draft_outline(session, course_id, context.user_id)
    if payload.parent_node_id:
        parent = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.outline_node_id == payload.parent_node_id,
            CourseOutlineNode.outline_version_id == version.outline_version_id,
        )).first()
        if not parent:
            raise HTTPException(400, "父节点不属于当前草稿目录")
    node = CourseOutlineNode(
        outline_version_id=version.outline_version_id, course_id=course_id,
        parent_node_id=payload.parent_node_id, node_type=payload.node_type,
        title=payload.title.strip(), order_index=payload.order_index,
        page_range=payload.page_range, generation_reason="teacher_edit",
    )
    _mark_teacher_edited(version)
    session.add(version)
    session.add(node); session.commit(); session.refresh(node)
    return unified_response(201, "目录节点已创建", _outline_node_view(node))


@router.patch("/course/{course_id}/outline/nodes/{node_id}")
async def update_outline_node(course_id: int, node_id: str, payload: OutlineNodeUpdate, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.structure.edit")
    node = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_node_id == node_id, CourseOutlineNode.course_id == course_id,
    )).first()
    if not node:
        raise HTTPException(404, "目录节点不存在")
    version = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.outline_version_id == node.outline_version_id,
    )).first()
    if not version or version.lifecycle_status != OutlineLifecycleStatus.DRAFT:
        raise HTTPException(409, "已发布目录不可直接编辑")
    if node.locked_by is not None and node.locked_by != context.user_id:
        raise HTTPException(409, "节点已被教师锁定")
    if payload.parent_node_id is not None:
        if payload.parent_node_id == node_id:
            raise HTTPException(400, "节点不能成为自己的父节点")
        parent = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.outline_node_id == payload.parent_node_id,
            CourseOutlineNode.outline_version_id == node.outline_version_id,
        )).first()
        if not parent:
            raise HTTPException(400, "父节点不属于当前草稿目录")
        node.parent_node_id = payload.parent_node_id
    if payload.title is not None: node.title = payload.title.strip()
    if payload.node_type is not None: node.node_type = payload.node_type
    if payload.order_index is not None: node.order_index = payload.order_index
    if payload.page_range is not None: node.page_range = payload.page_range
    _mark_teacher_edited(version)
    session.add(version)
    node.updated_at = utcnow_aware(); session.add(node); session.commit(); session.refresh(node)
    return unified_response(200, "目录节点已更新", _outline_node_view(node))


@router.post("/course/{course_id}/outline/reorder")
async def reorder_outline(course_id: int, payload: ReorderRequest, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.structure.edit")
    version = _ensure_draft_outline(session, course_id, context.user_id)
    nodes = session.exec(select(CourseOutlineNode).where(CourseOutlineNode.outline_version_id == version.outline_version_id)).all()
    by_id = {n.outline_node_id: n for n in nodes}
    if set(payload.node_ids) != set(by_id):
        raise HTTPException(400, "排序列表必须包含当前草稿的全部节点")
    for index, node_id in enumerate(payload.node_ids):
        by_id[node_id].order_index = index; by_id[node_id].updated_at = utcnow_aware(); session.add(by_id[node_id])
    _mark_teacher_edited(version)
    session.add(version)
    session.commit()
    return unified_response(200, "目录顺序已保存", {"node_ids": payload.node_ids})


@router.post("/course/{course_id}/outline/nodes/{node_id}/lock")
async def lock_outline_node(course_id: int, node_id: str, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.structure.edit")
    node = session.exec(select(CourseOutlineNode).where(CourseOutlineNode.outline_node_id == node_id, CourseOutlineNode.course_id == course_id)).first()
    if not node: raise HTTPException(404, "目录节点不存在")
    version = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.outline_version_id == node.outline_version_id,
    )).first()
    if version:
        _mark_teacher_edited(version); session.add(version)
    node.locked_by = context.user_id; node.locked_at = utcnow_aware(); session.add(node); session.commit()
    return unified_response(200, "目录节点已锁定", _outline_node_view(node))


@router.post("/course/{course_id}/outline/nodes/{node_id}/unlock")
async def unlock_outline_node(course_id: int, node_id: str, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.structure.edit")
    node = session.exec(select(CourseOutlineNode).where(CourseOutlineNode.outline_node_id == node_id, CourseOutlineNode.course_id == course_id)).first()
    if not node: raise HTTPException(404, "目录节点不存在")
    node.locked_by = None; node.locked_at = None; session.add(node); session.commit()
    return unified_response(200, "目录节点已解锁", _outline_node_view(node))


@router.delete("/course/{course_id}/outline/nodes/{node_id}")
async def delete_outline_node(course_id: int, node_id: str, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.structure.edit")
    node = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_node_id == node_id, CourseOutlineNode.course_id == course_id,
    )).first()
    if not node:
        raise HTTPException(404, "目录节点不存在")
    version = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.outline_version_id == node.outline_version_id,
    )).first()
    if not version or version.lifecycle_status != OutlineLifecycleStatus.DRAFT:
        raise HTTPException(409, "已发布目录不可直接编辑")
    if node.locked_by is not None and node.locked_by != context.user_id:
        raise HTTPException(409, "节点已被教师锁定")
    children = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
        CourseOutlineNode.outline_version_id == node.outline_version_id,
        CourseOutlineNode.parent_node_id == node.outline_node_id,
    )).all()
    if children:
        raise HTTPException(409, "请先处理子节点；删除父节点会使讲稿与 PPT 映射失去归属")
    version_id = node.outline_version_id
    mappings = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course_id,
        CoursePptMapping.outline_node_id == node_id,
        CoursePptMapping.status == "draft",
    )).all()
    for mapping in mappings:
        mapping.status = "stale"
        mapping.updated_by = context.user_id
        mapping.updated_at = utcnow_aware()
        session.add(mapping)
    session.delete(node)
    # 重新整理剩余节点顺序，避免 order_index 出现空洞
    remaining = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == version_id,
    ).order_by(CourseOutlineNode.order_index)).all()
    for index, n in enumerate(remaining):
        n.order_index = index; n.updated_at = utcnow_aware(); session.add(n)
    _mark_teacher_edited(version)
    session.add(version)
    session.commit()
    return unified_response(200, "目录节点已删除", {"outline_node_id": node_id})


@router.get("/course/{course_id}/scripts")
async def get_scripts(course_id: int, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.view")
    outline = _draft_outline(session, course_id) or _published_outline(session, course_id)
    if not outline: return unified_response(200, "讲稿尚未生成", {"version": None, "items": []})
    script = session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.course_id == course_id,
        TeachingScriptVersion.outline_version_id == outline.outline_version_id,
    ).order_by(TeachingScriptVersion.version.desc())).first()
    if not script: return unified_response(200, "讲稿尚未生成", {"version": None, "items": []})
    outline_nodes = list(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == outline.outline_version_id,
    )).all())
    ordered_outline, displays = _outline_tree_views(outline_nodes)
    outline_by_id = {node.outline_node_id: node for node in ordered_outline}
    mappings = list(session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course_id,
        CoursePptMapping.outline_node_id.in_(list(outline_by_id)),
        CoursePptMapping.status == "draft",
    )).all()) if outline_by_id else []
    mapping_by_node = {item.outline_node_id: _ppt_mapping_view(item) for item in mappings}
    script_nodes = list(session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.script_version_id == script.script_version_id,
    )).all())
    nodes_by_outline = {node.outline_node_id: node for node in script_nodes}
    items = [
        _script_node_view(
            nodes_by_outline[outline_node.outline_node_id],
            outline_view=_outline_node_view(outline_node, displays[outline_node.outline_node_id]),
            ppt_mapping=mapping_by_node.get(outline_node.outline_node_id),
        )
        for outline_node in ordered_outline
        if outline_node.outline_node_id in nodes_by_outline
    ]
    return unified_response(200, "获取讲授脚本成功", {
        "version": {
            "script_version_id": script.script_version_id,
            "outline_version_id": outline.outline_version_id,
            "status": script.lifecycle_status.value,
            "generation_source": script.generation_source,
            "review_status": script.review_status,
        },
        "items": items,
        "editable": script.lifecycle_status == OutlineLifecycleStatus.DRAFT,
    })


@router.patch("/course/{course_id}/scripts/{script_node_id}")
async def update_script(course_id: int, script_node_id: str, payload: ScriptUpdate, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.script.edit")
    node = session.exec(select(TeachingScriptNode).where(TeachingScriptNode.script_node_id == script_node_id, TeachingScriptNode.course_id == course_id)).first()
    if not node: raise HTTPException(404, "讲稿节点不存在")
    version = session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.script_version_id == node.script_version_id,
    )).first()
    if not version or version.lifecycle_status != OutlineLifecycleStatus.DRAFT: raise HTTPException(409, "已发布讲稿不可直接编辑")
    if node.locked_by is not None and node.locked_by != context.user_id: raise HTTPException(409, "讲稿节点已锁定")
    if payload.content is not None: node.content = payload.content
    if payload.style is not None: node.style = payload.style
    _mark_teacher_edited(version)
    session.add(version)
    outline = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.outline_version_id == version.outline_version_id,
    )).first()
    if outline:
        _mark_teacher_edited(outline)
        session.add(outline)
    node.updated_at = utcnow_aware(); session.add(node); session.commit(); session.refresh(node)
    return unified_response(200, "讲稿已保存", _script_node_view(node))


@router.post("/course/{course_id}/controlled-prep/run")
async def run_controlled_prep(
    course_id: int,
    payload: ControlledPrepRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Run five structured stages and persist only a teacher-review proposal."""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    if len(payload.evidence_ids) != len(set(payload.evidence_ids)):
        raise HTTPException(422, "evidence_ids 不能重复")

    formal = session.exec(select(CourseEvidenceRecord).where(
        CourseEvidenceRecord.course_id == course_id,
        CourseEvidenceRecord.evidence_id.in_(payload.evidence_ids),
        CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
    )).all()
    formal_by_id = {item.evidence_id: item for item in formal}
    spans = session.exec(select(EvidenceSpan).where(
        EvidenceSpan.course_id == course_id,
        EvidenceSpan.span_id.in_(payload.evidence_ids),
        EvidenceSpan.status == EvidenceSpanStatus.CONFIRMED,
    )).all()
    span_by_id = {item.span_id: item for item in spans}
    missing = [item for item in payload.evidence_ids if item not in formal_by_id and item not in span_by_id]
    if missing:
        raise HTTPException(422, detail={"error_code": "INVALID_COURSE_EVIDENCE", "evidence_ids": missing})

    evidence = []
    for evidence_id in payload.evidence_ids:
        item = formal_by_id.get(evidence_id)
        if item:
            evidence.append({"evidence_id": item.evidence_id, "text": item.text_snippet, "page": item.page_number})
        else:
            span = span_by_id[evidence_id]
            evidence.append({"evidence_id": span.span_id, "text": span.text_snippet, "page": span.page_number, "block_id": span.block_id})

    request = ControlledPrepInput(
        source_text=payload.source_text,
        evidence=evidence,
        course_positioning=payload.course_positioning,
        style=payload.style,
    )
    try:
        result = await controlled_prep_workflow.run(
            request,
            candidate_id=payload.candidate_id,
            existing_outline_ids=payload.existing_outline_ids,
            existing_script_ids=payload.existing_script_ids,
        )
    except Exception as exc:
        logger.exception("Controlled prep failed for course %s", course_id)
        raise HTTPException(422, detail={"error_code": "CONTROLLED_PREP_FAILED", "message": "受控备课流水线执行失败，请检查输入参数或稍后重试"}) from exc

    proposal = result["proposal"]
    db_proposal = PatchProposal(
        course_id=course_id, tool_name=proposal.tool_name,
        policy_version=proposal.policy_version, reason=proposal.reason,
        created_by=context.user_id,
    )
    session.add(db_proposal)
    session.flush()
    for operation in proposal.operations:
        session.add(PatchProposalOperation(
            proposal_id=db_proposal.proposal_id, course_id=course_id,
            operation=PatchOperation(operation.operation), target=operation.target,
            before=operation.before, after=operation.after, reason=operation.reason,
            evidence_refs=operation.evidence_refs, external_ref=operation.external_ref,
            policy_version=proposal.policy_version,
        ))
    session.commit()
    return unified_response(201, "受控备课完成，提案等待教师审核", {
        "proposal_id": db_proposal.proposal_id,
        "status": db_proposal.status.value,
        "stages": {
            "evidence_segmenter": result["segments"].model_dump(),
            "outline_planner": result["outline"].model_dump(),
            "script_writer": [item.model_dump() for item in result["scripts"]],
            "evidence_verifier": [item.model_dump() for item in result["verifications"]],
            "patch_compiler": proposal.model_dump(),
        },
    })


@router.post("/course/{course_id}/prep-agent/commands")
async def run_prep_agent_command(
    course_id: int,
    payload: PrepAgentCommandRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Turn a teacher's natural-language request into a reviewable proposal.

    This is intentionally a compatibility-facade route.  It uses the existing
    PatchProposal persistence and decision endpoint, so it cannot double-write
    the outline/script records.
    """
    context = require_course_permission(session, current_user, course_id, "course.edit")
    from app.services.course_prep_agent_service import (
        CoursePrepAgentPlanningError,
        course_prep_agent_service,
    )

    try:
        result = await course_prep_agent_service.plan(
            session,
            course_id=course_id,
            instruction=payload.instruction,
            outline_node_id=payload.outline_node_id,
        )
    except CoursePrepAgentPlanningError as exc:
        raise HTTPException(
            502,
            detail={
                "error_code": "PREP_AGENT_LLM_INVALID_RESPONSE",
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"error_code": "PREP_AGENT_NO_EDITABLE_TARGET", "message": str(exc)}) from exc

    proposal = PatchProposal(
        course_id=course_id,
        tool_name="CoursePrepAgent",
        policy_version="course-prep-agent/1.0",
        reason=result.summary,
        created_by=context.user_id,
    )
    session.add(proposal)
    session.flush()
    operation_count = 0
    for item in result.operations:
        target_kind, target_id, field = item["target"].split(":", 2)
        before = ""
        if target_kind == "outline":
            target = session.exec(select(CourseOutlineNode).where(
                CourseOutlineNode.course_id == course_id,
                CourseOutlineNode.outline_node_id == target_id,
            )).first()
            if target is None or target.locked_by is not None:
                continue
            before = str(getattr(target, field, ""))
        else:
            target = session.exec(select(TeachingScriptNode).where(
                TeachingScriptNode.course_id == course_id,
                TeachingScriptNode.script_node_id == target_id,
            )).first()
            if target is None or target.locked_by is not None:
                continue
            before = str(getattr(target, field, ""))
        session.add(PatchProposalOperation(
            proposal_id=proposal.proposal_id,
            course_id=course_id,
            operation=PatchOperation.REPLACE,
            target=item["target"],
            before=before,
            after=item["after"],
            reason=item["reason"],
            evidence_refs=item["evidence_refs"],
            policy_version="course-prep-agent/1.0",
        ))
        operation_count += 1
    if operation_count == 0:
        session.rollback()
        raise HTTPException(409, "提案目标已在生成期间被锁定或删除，请刷新后重试")
    session.commit()
    return unified_response(201, "备课 Agent 已生成待教师审核的提案", {
        "proposal_id": proposal.proposal_id,
        "status": PatchProposalStatus.PENDING.value,
        "explanation": {
            "changed": [item["target"] for item in result.operations],
            "reason": result.summary,
            "evidence": result.evidence,
            "excluded_locked_targets": result.excluded_locked_targets,
            "planner": result.planner,
        },
    })


@router.get("/course/{course_id}/prep-agent/evidence/{node_id}")
async def get_prep_agent_node_evidence(
    course_id: int,
    node_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Expose source blocks for the evidence pane, scoped to the current course."""
    require_course_permission(session, current_user, course_id, "course.view")
    node = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
        CourseOutlineNode.outline_node_id == node_id,
    )).first()
    if node is None:
        raise HTTPException(404, "课程目录节点不存在")
    refs = list(node.source_block_refs or [])
    blocks = session.exec(select(DocumentBlock).where(
        DocumentBlock.course_id == course_id,
        DocumentBlock.block_id.in_(refs),
    ).order_by(DocumentBlock.page_or_slide, DocumentBlock.order_index)).all() if refs else []
    return unified_response(200, "获取原文证据成功", {
        "outline_node_id": node_id,
        "items": [{
            "block_id": block.block_id,
            "page": block.page_or_slide or block.page_number,
            "text": block.text,
            "confidence": block.confidence,
            "source_kind": block.source_kind,
        } for block in blocks],
    })


@router.post("/course/{course_id}/scripts/{script_node_id}/lock")
async def lock_script(course_id: int, script_node_id: str, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.script.edit")
    node = session.exec(select(TeachingScriptNode).where(TeachingScriptNode.script_node_id == script_node_id, TeachingScriptNode.course_id == course_id)).first()
    if not node: raise HTTPException(404, "讲稿节点不存在")
    node.locked_by = context.user_id; node.locked_at = utcnow_aware(); session.add(node); session.commit()
    return unified_response(200, "讲稿节点已锁定", _script_node_view(node))


@router.get("/course/{course_id}/proposals")
async def list_proposals(course_id: int, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.view")
    proposals = session.exec(select(PatchProposal).where(PatchProposal.course_id == course_id).order_by(PatchProposal.created_at.desc())).all()
    result = []
    for proposal in proposals:
        ops = session.exec(select(PatchProposalOperation).where(PatchProposalOperation.proposal_id == proposal.proposal_id).order_by(PatchProposalOperation.id)).all()
        result.append({"proposal_id": proposal.proposal_id, "tool_name": proposal.tool_name, "policy_version": proposal.policy_version, "status": proposal.status.value, "reason": proposal.reason, "created_at": proposal.created_at.isoformat(), "operations": [{"op_id": o.op_id, "operation": o.operation.value, "target": o.target, "before": o.before, "after": o.after, "reason": o.reason, "evidence_refs": o.evidence_refs or [], "external_ref": o.external_ref, "accepted": o.accepted} for o in ops]})
    return unified_response(200, "获取备课提案成功", {"items": result, "total": len(result)})


@router.post("/course/{course_id}/proposals")
async def create_proposal(course_id: int, payload: ProposalCreate, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.edit")
    proposal = PatchProposal(course_id=course_id, tool_name=payload.tool_name, policy_version=payload.policy_version, reason=payload.reason, created_by=context.user_id)
    session.add(proposal); session.flush()
    for item in payload.operations:
        session.add(PatchProposalOperation(proposal_id=proposal.proposal_id, course_id=course_id, operation=item.operation, target=item.target, before=item.before, after=item.after, reason=item.reason, evidence_refs=item.evidence_refs, external_ref=item.external_ref, policy_version=payload.policy_version))
    session.commit()
    return unified_response(201, "备课提案已创建，等待教师审核", {"proposal_id": proposal.proposal_id, "status": proposal.status.value})


def _filter_course_evidence_refs(session: Session, course_id: int, refs):
    """P1-B4: 只保留属于当前课程的证据引用，过滤跨课程引用并记录警告。

    refs 为 None/空时原样返回，保持与历史空值语义一致。
    """
    if not refs:
        return refs
    formal_ids = {item.evidence_id for item in session.exec(select(CourseEvidenceRecord).where(
        CourseEvidenceRecord.course_id == course_id,
        CourseEvidenceRecord.evidence_id.in_(refs),
    )).all()}
    span_ids = {item.span_id for item in session.exec(select(EvidenceSpan).where(
        EvidenceSpan.course_id == course_id,
        EvidenceSpan.span_id.in_(refs),
    )).all()}
    valid = formal_ids | span_ids
    filtered = [r for r in refs if r in valid]
    dropped = [r for r in refs if r not in valid]
    if dropped:
        logger.warning("P1-B4: 过滤掉不属于课程 %s 的 evidence_refs: %s", course_id, dropped)
    return filtered


def _apply_operation(session: Session, course_id: int, op: PatchProposalOperation, user_id: int) -> None:
    # P1-B4: 校验 evidence_refs 课程归属，过滤跨课程引用。
    op.evidence_refs = _filter_course_evidence_refs(session, course_id, op.evidence_refs)
    match = re.match(r"^(outline|script):([^:]+):(title|content|style)$", op.target)
    if not match: raise HTTPException(400, f"不支持的提案目标: {op.target}")
    kind, target_id, field = match.groups()
    if kind == "outline":
        if target_id == "new":
            try:
                payload = json.loads(op.after)
            except json.JSONDecodeError as exc:
                raise HTTPException(422, "新增目录节点的 after 不是有效 JSON") from exc
            # P1-B5: 幂等——先查询派生的 outline_node_id 是否已存在，若存在则跳过创建，
            # 避免重试时重复创建节点导致主键冲突。
            derived_node_id = payload.get("outline_node_id") or f"on_agent_{hashlib.sha256(op.after.encode()).hexdigest()[:16]}"
            outline = _ensure_draft_outline(session, course_id, user_id)
            existing = session.exec(select(CourseOutlineNode).where(
                CourseOutlineNode.outline_node_id == derived_node_id,
                CourseOutlineNode.course_id == course_id,
            )).first()
            if existing is not None:
                logger.info("P1-B5: outline_node_id %s 已存在，跳过重复创建", derived_node_id)
                return
            # S-B3: JSON 字段类型校验，缺失或类型错误返回 422 而非 500。
            try:
                parent_id = payload.get("parent_node_id")
                parent = session.exec(select(CourseOutlineNode).where(
                    CourseOutlineNode.outline_node_id == parent_id,
                    CourseOutlineNode.course_id == course_id,
                    CourseOutlineNode.outline_version_id == outline.outline_version_id,
                )).first() if parent_id else None
                session.add(CourseOutlineNode(
                    outline_node_id=derived_node_id,
                    outline_version_id=outline.outline_version_id,
                    course_id=course_id,
                    parent_node_id=parent.outline_node_id if parent else None,
                    node_type=OutlineNodeType(payload["node_type"]),
                    title=payload["title"],
                    order_index=int(payload.get("order_index", 0)),
                    source_block_refs=payload.get("source_block_refs") or op.evidence_refs,
                    generation_reason=op.reason,
                    confidence=1.0 if op.evidence_refs else 0.0,
                ))
            except (KeyError, ValueError, TypeError) as exc:
                raise HTTPException(422, detail={"error_code": "INVALID_NODE_PAYLOAD", "message": "新增目录节点的 JSON 字段缺失或类型不正确"}) from exc
            return
        target = session.exec(select(CourseOutlineNode).where(CourseOutlineNode.outline_node_id == target_id, CourseOutlineNode.course_id == course_id)).first()
        if not target: raise HTTPException(404, "提案目标目录节点不存在")
        version = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.outline_version_id == target.outline_version_id,
        )).first()
        if not version or version.lifecycle_status != OutlineLifecycleStatus.DRAFT: raise HTTPException(409, "提案目标不是草稿")
        if target.locked_by is not None: raise HTTPException(409, "提案目标目录节点已锁定")
        setattr(target, field, op.after); target.updated_at = utcnow_aware(); session.add(target)
    else:
        if target_id == "new":
            try:
                payload = json.loads(op.after)
            except json.JSONDecodeError as exc:
                raise HTTPException(422, "新增讲稿节点的 after 不是有效 JSON") from exc
            outline = _ensure_draft_outline(session, course_id, user_id)
            # S-B3: JSON 字段类型校验。
            try:
                outline_node = session.exec(select(CourseOutlineNode).where(
                    CourseOutlineNode.outline_node_id == payload.get("outline_node_id"),
                    CourseOutlineNode.course_id == course_id,
                    CourseOutlineNode.outline_version_id == outline.outline_version_id,
                )).first()
                if outline_node is None:
                    raise HTTPException(409, "新增讲稿缺少对应的草稿目录节点")
                script = _ensure_draft_script(session, outline, user_id)
                session.add(TeachingScriptNode(
                    script_version_id=script.script_version_id,
                    course_id=course_id,
                    outline_node_id=outline_node.outline_node_id,
                    content=payload.get("content", ""),
                    style=payload.get("style", ""),
                    evidence_refs=payload.get("evidence_refs") or op.evidence_refs,
                    source_block_refs=payload.get("evidence_refs") or op.evidence_refs,
                ))
            except (KeyError, ValueError, TypeError) as exc:
                raise HTTPException(422, detail={"error_code": "INVALID_NODE_PAYLOAD", "message": "新增讲稿节点的 JSON 字段缺失或类型不正确"}) from exc
            return
        target = session.exec(select(TeachingScriptNode).where(TeachingScriptNode.script_node_id == target_id, TeachingScriptNode.course_id == course_id)).first()
        if not target: raise HTTPException(404, "提案目标讲稿节点不存在")
        version = session.exec(select(TeachingScriptVersion).where(
            TeachingScriptVersion.script_version_id == target.script_version_id,
        )).first()
        if not version or version.lifecycle_status != OutlineLifecycleStatus.DRAFT: raise HTTPException(409, "提案目标不是草稿")
        if target.locked_by is not None: raise HTTPException(409, "提案目标讲稿节点已锁定")
        setattr(target, field, op.after); target.updated_at = utcnow_aware(); session.add(target)


@router.post("/course/{course_id}/proposals/{proposal_id}/decide")
async def decide_proposal(course_id: int, proposal_id: str, payload: ProposalDecision, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.edit")
    proposal = session.exec(select(PatchProposal).where(PatchProposal.proposal_id == proposal_id, PatchProposal.course_id == course_id)).first()
    if not proposal: raise HTTPException(404, "提案不存在")
    if proposal.status != PatchProposalStatus.PENDING: raise HTTPException(409, "提案已经处理")
    ops = session.exec(select(PatchProposalOperation).where(PatchProposalOperation.proposal_id == proposal_id).order_by(PatchProposalOperation.id)).all()
    if payload.accepted:
        for op in ops: _apply_operation(session, course_id, op, context.user_id); op.accepted = True; op.decided_at = utcnow_aware(); session.add(op)
        proposal.status = PatchProposalStatus.ACCEPTED
    else:
        for op in ops: op.accepted = False; op.decided_at = utcnow_aware(); session.add(op)
        proposal.status = PatchProposalStatus.REJECTED
    proposal.decided_by = context.user_id; proposal.decided_at = utcnow_aware(); session.add(proposal); session.commit()
    return unified_response(200, "提案已接受" if payload.accepted else "提案已拒绝", {"proposal_id": proposal_id, "status": proposal.status.value})


@router.get("/course/{course_id}/ppt-mapping")
async def get_ppt_mapping(course_id: int, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.view")
    outline = _draft_outline(session, course_id) or _published_outline(session, course_id)
    materials = session.exec(select(SourceMaterial).where(SourceMaterial.course_id == course_id)).all()
    has_ppt = any(m.material_type == "slide" for m in materials)
    nodes = list(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == outline.outline_version_id,
    )).all()) if outline else []
    ordered_nodes, displays = _outline_tree_views(nodes)
    current_node_ids = {node.outline_node_id for node in ordered_nodes}
    all_mappings = list(session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course_id,
    )).all())
    mappings = [item for item in all_mappings if item.outline_node_id in current_node_ids]
    stale_mappings = [item for item in all_mappings if item.outline_node_id not in current_node_ids]
    mapping_by_node = {item.outline_node_id: item for item in mappings}
    node_views = []
    for node in ordered_nodes:
        view = _outline_node_view(node, displays[node.outline_node_id])
        view["ppt_mapping"] = _ppt_mapping_view(mapping_by_node[node.outline_node_id]) if node.outline_node_id in mapping_by_node else None
        node_views.append(view)
    return unified_response(200, "获取 PPT 映射状态成功", {
        "has_ppt": has_ppt,
        "editable": bool(outline and outline.lifecycle_status == OutlineLifecycleStatus.DRAFT),
        "outline_version_id": outline.outline_version_id if outline else None,
        "nodes": node_views,
        "mappings": [_ppt_mapping_view(item) for item in mappings],
        "stale_mappings": [_ppt_mapping_view(item) for item in stale_mappings],
        "actions": {"upload_existing": True, "generate_ai": bool(nodes)},
    })


@router.patch("/course/{course_id}/ppt-mapping/{outline_node_id}")
async def update_ppt_mapping(course_id: int, outline_node_id: str, payload: PptMappingUpdate, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.mapping.edit")
    node = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_node_id == outline_node_id,
        CourseOutlineNode.course_id == course_id,
    )).first()
    if not node:
        raise HTTPException(404, "课程结构节点不存在")
    version = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.outline_version_id == node.outline_version_id,
    )).first()
    if not version or version.lifecycle_status != OutlineLifecycleStatus.DRAFT:
        raise HTTPException(409, "已发布课程结构不可直接编辑")
    if node.locked_by is not None and node.locked_by != context.user_id:
        raise HTTPException(409, "节点已被教师锁定")
    mapping = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course_id,
        CoursePptMapping.outline_node_id == outline_node_id,
        CoursePptMapping.status == "draft",
    )).first()
    if not mapping:
        mapping = CoursePptMapping(course_id=course_id, outline_node_id=outline_node_id, created_by=context.user_id)
    if payload.page_range is not None:
        raw = payload.page_range.strip()
        parts = raw.split("-", 1)
        if not all(part.strip().isdigit() for part in parts):
            raise HTTPException(400, "页码格式应为 1 或 1-3")
        mapping.page_start = max(1, int(parts[0].strip()))
        mapping.page_end = max(mapping.page_start, int(parts[-1].strip()))
        mapping.page_refs = list(range(mapping.page_start, mapping.page_end + 1))
    if payload.confidence is not None:
        mapping.confidence = payload.confidence
    if payload.locked is True:
        mapping.teacher_locked = True
    _mark_teacher_edited(version)
    session.add(version)
    mapping.updated_by = context.user_id
    mapping.updated_at = utcnow_aware()
    session.add(mapping)
    session.commit()
    session.refresh(mapping)
    view = _outline_node_view(node)
    view["ppt_mapping"] = _ppt_mapping_view(mapping)
    return unified_response(200, "PPT 映射已保存", view)


@router.post("/course/{course_id}/ppt/generate")
async def generate_course_ppt(course_id: int, payload: PptGenerateRequest, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    """Generate a PPT for the existing course, then re-enter the unified parser."""
    context = require_course_permission(session, current_user, course_id, "course.mapping.edit")
    if not settings.XFYUN_PPT_APP_ID or not settings.XFYUN_PPT_API_SECRET:
        raise HTTPException(status_code=503, detail={"error_code": "PPT_GENERATION_UNAVAILABLE", "message": "未配置科大讯飞 PPT 服务"})
    outline = _draft_outline(session, course_id)
    if not outline:
        raise HTTPException(409, "请先生成并确认课程结构")
    outline_nodes = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == outline.outline_version_id,
    ).order_by(CourseOutlineNode.order_index)).all()
    script = session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.course_id == course_id,
        TeachingScriptVersion.outline_version_id == outline.outline_version_id,
    ).order_by(TeachingScriptVersion.version.desc())).first()
    script_nodes = session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.script_version_id == script.script_version_id,
    )).all() if script else []
    script_by_outline = {item.outline_node_id: item.content for item in script_nodes}
    topic = (session.get(Course, course_id).title if session.get(Course, course_id) else f"课程 {course_id}")
    teaching_outline = "\n".join(f"- {node.title}: {script_by_outline.get(node.outline_node_id, '')}" for node in outline_nodes)
    result = await ppt_generation_service.generate_ppt(
        topic=topic,
        outline=teaching_outline,
        knowledge_points=[node.title for node in outline_nodes],
        template_id=payload.template_id,
        search=payload.search,
    )
    if result.status != "done" or not result.ppt_file_path or not os.path.exists(result.ppt_file_path):
        raise HTTPException(status_code=502, detail={"error_code": "PPT_GENERATION_FAILED", "message": result.error or "PPT 生成失败"})
    digest = hashlib.sha256()
    size = os.path.getsize(result.ppt_file_path)
    with open(result.ppt_file_path, "rb") as source:
        data = source.read()
    digest.update(data)
    object_key = f"course-source/course{course_id}/ppt_{digest.hexdigest()[:16]}/generated.pptx"
    from io import BytesIO
    get_object_storage().put(object_key, BytesIO(data), mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    material, version = source_material_service.create_material(
        session, course_id=course_id, name=os.path.basename(result.ppt_file_path), material_type="slide", source_kind="ai_generated",
        file_path=object_key, file_hash=digest.hexdigest(), file_size=size,
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", created_by=context.user_id,
    )
    task_view = task_service.create_task(session, TaskCreateRequest(
        task_type="document_parse", owner_user_id=context.user_id, course_id=course_id,
        input_summary=f"解析课程 {course_id} 的 AI PPT", input_payload={
            "course_id": course_id, "material_id": material.material_id, "material_version_id": version.version_id,
            "stale_strategy": StaleStrategy.MARK_STALE.value, "initiated_by": context.user_id,
        }, resource_links=[{"resource_kind": "course", "resource_id": str(course_id), "relation": "input"}],
    ))
    run = document_parse_service.create_run(session, course_id=course_id, material_id=material.material_id, material_version_id=version.version_id,
        document_id=None, task_id=task_view.task_id, pipeline=ParsePipeline.FULL, stale_strategy=StaleStrategy.MARK_STALE, initiated_by=context.user_id)
    version.parse_task_id = task_view.task_id
    version.parse_status = MaterialStatus.PARSING
    session.add(version)
    session.commit()
    if local_task_worker.has_handler("document_parse"):
        local_task_worker.submit(session_factory, task_view.task_id, {"course_id": course_id, "run_id": run.run_id, "material_id": material.material_id, "material_version_id": version.version_id, "stale_strategy": StaleStrategy.MARK_STALE.value, "initiated_by": context.user_id})
    return unified_response(202, "AI PPT 已生成并进入统一解析链", {"material_id": material.material_id, "material_version_id": version.version_id, "task_id": task_view.task_id, "run_id": run.run_id})


@router.post("/course/{course_id}/ppt/upload")
async def upload_existing_ppt(course_id: int, file: UploadFile = File(...), session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    """Attach an existing PPT/PPTX to this course and enqueue the unified parser."""
    context = require_course_permission(session, current_user, course_id, "course.mapping.edit")
    filename = (file.filename or "course.pptx").strip()
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"ppt", "pptx"}:
        raise HTTPException(400, "教学 PPT 映射只接受 PPT 或 PPTX")
    digest = hashlib.sha256(); total = 0
    with tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b") as staged:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk: break
            total += len(chunk)
            if total > 50 * 1024 * 1024: raise HTTPException(413, "PPT 文件超过 50MB")
            digest.update(chunk); staged.write(chunk)
        if total == 0: raise HTTPException(400, "不能上传空 PPT")
        object_key = f"course-source/course{course_id}/ppt_{digest.hexdigest()[:16]}/source.{suffix}"
        staged.seek(0); get_object_storage().put(object_key, staged, mime_type=file.content_type or "application/octet-stream")
    material, version = source_material_service.create_material(
        session, course_id=course_id, name=filename, material_type="slide", source_kind="upload",
        file_path=object_key, file_hash=digest.hexdigest(), file_size=total,
        mime_type=file.content_type or "application/octet-stream", created_by=context.user_id,
    )
    task_view = task_service.create_task(session, TaskCreateRequest(
        task_type="document_parse", owner_user_id=context.user_id, course_id=course_id,
        input_summary=f"解析课程 {course_id} 的教学 PPT {filename}", input_payload={
            "course_id": course_id, "material_id": material.material_id, "material_version_id": version.version_id,
            "stale_strategy": StaleStrategy.MARK_STALE.value, "initiated_by": context.user_id,
        }, resource_links=[{"resource_kind":"course","resource_id":str(course_id),"relation":"input"}],
    ))
    run = document_parse_service.create_run(session, course_id=course_id, material_id=material.material_id,
        material_version_id=version.version_id, document_id=None, task_id=task_view.task_id,
        pipeline=ParsePipeline.FULL, stale_strategy=StaleStrategy.MARK_STALE, initiated_by=context.user_id)
    version.parse_task_id = task_view.task_id; version.parse_status = MaterialStatus.PARSING
    _mark_build_step(session, course_id, BuildStepName.MATERIALS, BuildStepStatus.IN_PROGRESS, context.user_id, task_view.task_id)
    session.add(version); session.commit()
    if local_task_worker.has_handler("document_parse"):
        local_task_worker.submit(session_factory, task_view.task_id, {
            "course_id": course_id, "run_id": run.run_id, "material_id": material.material_id,
            "material_version_id": version.version_id, "stale_strategy": StaleStrategy.MARK_STALE.value,
            "initiated_by": context.user_id,
        })
    return unified_response(202, "PPT 已上传，正在重新解析并建立映射", {"material_id": material.material_id, "material_version_id": version.version_id, "task_id": task_view.task_id, "run_id": run.run_id})


@router.post("/course/{course_id}/publish")
async def publish_course_build(
    course_id: int,
    payload: LegacyReleasePublishRequest = LegacyReleasePublishRequest(),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "course.publish")
    course = session.get(Course, course_id)
    if not course: raise HTTPException(404, "课程不存在")
    outline = _draft_outline(session, course_id)
    if not outline: raise HTTPException(409, "请先生成并确认课程结构")
    scripts = session.exec(select(TeachingScriptVersion).where(TeachingScriptVersion.course_id == course_id, TeachingScriptVersion.outline_version_id == outline.outline_version_id).order_by(TeachingScriptVersion.version.desc())).first()
    if not scripts: raise HTTPException(409, "请先生成并确认讲授脚本")
    nodes = session.exec(select(CourseOutlineNode).where(CourseOutlineNode.outline_version_id == outline.outline_version_id).order_by(CourseOutlineNode.order_index)).all()
    script_nodes = session.exec(select(TeachingScriptNode).where(TeachingScriptNode.script_version_id == scripts.script_version_id)).all()
    release = course_release_service.create_release_draft(session, course_id=course_id, label="课程草稿发布", created_by=context.user_id)
    _mark_build_step(session, course_id, BuildStepName.STRUCTURE, BuildStepStatus.APPROVED, context.user_id, outline.outline_version_id)
    _mark_build_step(session, course_id, BuildStepName.SCRIPTS, BuildStepStatus.APPROVED, context.user_id, scripts.script_version_id)
    materials = source_material_service.list_materials(session, course_id=course_id)
    if materials and all(item.status == MaterialStatus.PARSED for item in materials):
        _mark_build_step(session, course_id, BuildStepName.MATERIALS, BuildStepStatus.APPROVED, context.user_id, str(len(materials)))
    _mark_build_step(session, course_id, BuildStepName.RELEASE, BuildStepStatus.IN_PROGRESS, context.user_id, release.release_id)
    session.flush()
    corpus = session.exec(select(CourseCorpusSnapshot).where(
        CourseCorpusSnapshot.course_id == course_id,
        CourseCorpusSnapshot.status == "ready",
    ).order_by(CourseCorpusSnapshot.created_at.desc())).first()
    if corpus is not None:
        # The gate below must inspect the same reviewed learner-retrieval set
        # that publish_release will bind to the CourseRelease.
        course_corpus_service.freeze_release_retrieval_snapshot(session, corpus=corpus)
    gate = (
        quality_gate_service.get_run(
            session, course_id=course_id, gate_run_id=payload.quality_gate_run_id,
        )
        if payload.quality_gate_run_id
        else quality_gate_service.run_checks(
            session, course_id=course_id, initiated_by=context.user_id,
            target_release_id=release.release_id,
        )
    )
    if not gate.passed:
        raise HTTPException(status_code=409, detail={"error_code": "QUALITY_GATE_FAILED", "message": "发布前质量检查未通过", "details": {"gate_run_id": gate.gate_run_id, "error_count": gate.error_count, "blocker_count": gate.blocker_count, "warning_count": gate.warning_count, "requires_warning_confirmation": gate.warning_count > 0 and gate.warning_override_at is None}})
    mappings = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course_id,
        CoursePptMapping.outline_node_id.in_([node.outline_node_id for node in nodes]),
        CoursePptMapping.status == "draft",
    )).all()
    mapping_snapshot = [_ppt_mapping_view(item) for item in mappings]
    release = course_release_service.publish_release(session, course_id=course_id, release_id=release.release_id, published_by=context.user_id, structure_snapshot={"outline_version_id": outline.outline_version_id, "nodes": [_outline_node_view(n) for n in nodes]}, scripts_snapshot={"script_version_id": scripts.script_version_id, "nodes": [_script_node_view(n) for n in script_nodes]}, page_mappings_snapshot={"items": mapping_snapshot}, run_quality_gate=False, quality_gate_run_id=gate.gate_run_id)
    resources = session.exec(select(ResourceItem).where(ResourceItem.course_id == course_id, ResourceItem.is_deleted == False)).all()  # noqa: E712
    for resource in resources:
        resource.lifecycle_status = ResourceLifecycleStatus.PUBLISHED
        resource.visibility = ResourceVisibility.COURSE_MEMBERS
        resource.updated_at = utcnow_aware()
        session.add(resource)
    for mapping in mappings:
        mapping.status = "published"
        mapping.updated_at = utcnow_aware()
        session.add(mapping)
    outline.lifecycle_status = OutlineLifecycleStatus.PUBLISHED; scripts.lifecycle_status = OutlineLifecycleStatus.PUBLISHED
    course.status = CourseStatus.PUBLISHED; course.updated_at = utcnow_aware(); session.add(outline); session.add(scripts); session.add(course); session.commit()
    return unified_response(200, "课程已发布", {"course_id": course_id, "release_id": release.release_id, "status": course.status.value})


@router.get("/course/{course_id}/published-content")
async def get_published_content(course_id: int, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.view")
    release = course_release_service.get_active_release(session, course_id=course_id)
    if not release:
        return unified_response(200, "课程尚无已发布内容", {"outline": [], "scripts": []})
    outline = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.course_id == course_id,
        CourseOutlineVersion.outline_version_id == release.outline_version_id,
    )).first()
    if not outline:
        raise HTTPException(409, "发布版本缺少课程结构，请回滚或重新发布")
    nodes = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == outline.outline_version_id,
    ).order_by(CourseOutlineNode.order_index)).all()
    script = session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.course_id == course_id,
        TeachingScriptVersion.script_version_id == release.script_version_id,
    )).first()
    scripts = session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.script_version_id == script.script_version_id,
    )).all() if script else []
    return unified_response(200, "获取已发布课程内容成功", {
        "release_id": release.release_id,
        "outline_version_id": outline.outline_version_id,
        "outline": [_outline_node_view(node) for node in nodes],
        "scripts": [_script_node_view(node) for node in scripts],
        "ppt_mappings": (release.page_mappings_snapshot or {}).get("items", []),
    })
@router.get("/course/{course_id}/published-learning-units")
async def get_published_learning_units(course_id: int, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.view")
    release = course_release_service.get_active_release(session, course_id=course_id)
    if not release:
        return unified_response(200, "课程暂无已发布内容", {"items": [], "total": 0})
    outline = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.course_id == course_id,
        CourseOutlineVersion.outline_version_id == release.outline_version_id,
    )).first()
    if not outline:
        raise HTTPException(409, "发布版本缺少课程结构，请回滚或重新发布")
    nodes = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == outline.outline_version_id,
    ).order_by(CourseOutlineNode.order_index)).all()
    script = session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.course_id == course_id,
        TeachingScriptVersion.script_version_id == release.script_version_id,
    )).first()
    scripts = session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.script_version_id == script.script_version_id,
    )).all() if script else []
    by_script = {item.outline_node_id: item for item in scripts}
    by_mapping = {item["outline_node_id"]: item for item in (release.page_mappings_snapshot or {}).get("items", [])}
    by_id = {item.outline_node_id: item for item in nodes}
    items = []
    for node in nodes:
        if node.node_type != OutlineNodeType.KNOWLEDGE_POINT:
            continue
        children = [item for item in nodes if item.parent_node_id == node.outline_node_id]
        items.append({
            "unit_id": node.outline_node_id,
            "section_id": node.parent_node_id,
            "knowledge_point": _outline_node_view(node),
            "script": _script_node_view(by_script[node.outline_node_id]) if node.outline_node_id in by_script else None,
            "ppt_mapping": by_mapping.get(node.outline_node_id),
            "examples": [_outline_node_view(item) for item in children if item.node_type == OutlineNodeType.EXAMPLE],
            "practice_suggestions": [_outline_node_view(item) for item in children if item.node_type == OutlineNodeType.PRACTICE_SUGGESTION],
            "section": _outline_node_view(by_id[node.parent_node_id]) if node.parent_node_id in by_id else None,
            "playable": True,
        })
    return unified_response(200, "获取学习单元成功", {"release_id": release.release_id, "outline_version_id": outline.outline_version_id, "items": items, "total": len(items)})
