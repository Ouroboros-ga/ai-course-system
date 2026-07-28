"""Course construction API for the versioned outline, teaching script and proposals.

This router is deliberately separate from the legacy ``CourseScript`` API.
It is the only write surface for the new course construction chain:

``DocumentParseRun -> draft outline/script -> teacher review -> published release``.

Every query carries ``course_id`` and is guarded by Course Access v1.  A
proposal is never applied by an agent directly: teachers decide it explicitly.
"""
from __future__ import annotations

import json
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.core.time_utils import utcnow_aware
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    OutlineNodeType,
    PatchOperation,
    PatchProposal,
    PatchProposalOperation,
    PatchProposalStatus,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.database import get_session
from app.services.course_access_service import require_course_permission


course_outline_router = APIRouter()


class OutlineNodeInput(BaseModel):
    parent_node_id: Optional[str] = None
    node_type: OutlineNodeType = OutlineNodeType.KNOWLEDGE_POINT
    title: str = Field(min_length=1, max_length=300)
    order_index: int = Field(default=0, ge=0)
    knowledge_graph_node_id: Optional[str] = Field(default=None, max_length=200)
    source_block_refs: list[str] = Field(default_factory=list, max_length=500)
    page_range: Optional[str] = Field(default=None, max_length=64)
    generation_reason: str = Field(default="", max_length=4000)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    content_hash: str = Field(default="", max_length=128)


class OutlineDraftRequest(BaseModel):
    """Optional explicit source version for a teacher-authored draft."""

    source_outline_version_id: Optional[str] = Field(default=None, max_length=200)


class OutlineNodePatch(BaseModel):
    parent_node_id: Optional[str] = None
    node_type: Optional[OutlineNodeType] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    order_index: Optional[int] = Field(default=None, ge=0)
    knowledge_graph_node_id: Optional[str] = Field(default=None, max_length=200)
    source_block_refs: Optional[list[str]] = Field(default=None, max_length=500)
    page_range: Optional[str] = Field(default=None, max_length=64)
    content_hash: Optional[str] = Field(default=None, max_length=128)
    lock: Optional[bool] = None


class ScriptNodeInput(BaseModel):
    outline_node_id: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=100_000)
    style: str = Field(default="", max_length=64)
    evidence_refs: list[str] = Field(default_factory=list, max_length=500)
    source_block_refs: list[str] = Field(default_factory=list, max_length=500)
    content_hash: str = Field(default="", max_length=128)


class ScriptNodePatch(BaseModel):
    content: Optional[str] = Field(default=None, max_length=100_000)
    style: Optional[str] = Field(default=None, max_length=64)
    evidence_refs: Optional[list[str]] = Field(default=None, max_length=500)
    source_block_refs: Optional[list[str]] = Field(default=None, max_length=500)
    content_hash: Optional[str] = Field(default=None, max_length=128)
    lock: Optional[bool] = None


class ProposalOperationInput(BaseModel):
    operation: PatchOperation
    # ``outline:<node_id>:title`` / ``script:<node_id>:content`` are the
    # supported replace targets.  ADD accepts ``outline:<version_id>:node``.
    target: str = Field(min_length=1, max_length=300)
    before: str = Field(default="", max_length=100_000)
    after: str = Field(default="", max_length=100_000)
    reason: str = Field(default="", max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=500)
    external_ref: Optional[str] = Field(default=None, max_length=300)
    policy_version: str = Field(default="", max_length=32)


class ProposalCreateRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=64)
    policy_version: str = Field(default="", max_length=32)
    reason: str = Field(default="", max_length=4000)
    operations: list[ProposalOperationInput] = Field(min_length=1, max_length=200)


class ProposalDecisionRequest(BaseModel):
    accepted_operation_ids: list[str] = Field(default_factory=list, max_length=200)
    reject_unselected: bool = True


def _outline_payload(version: CourseOutlineVersion, nodes: list[CourseOutlineNode]) -> dict[str, Any]:
    return {
        "outline_version_id": version.outline_version_id,
        "course_id": version.course_id,
        "version": version.version,
        "lifecycle_status": version.lifecycle_status.value,
        "source_parse_run_id": version.source_parse_run_id,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "nodes": [_node_payload(n) for n in nodes],
    }


def _node_payload(node: CourseOutlineNode) -> dict[str, Any]:
    return {
        "outline_node_id": node.outline_node_id,
        "outline_version_id": node.outline_version_id,
        "parent_node_id": node.parent_node_id,
        "node_type": node.node_type.value,
        "title": node.title,
        "order_index": node.order_index,
        "knowledge_graph_node_id": node.knowledge_graph_node_id,
        "source_block_refs": node.source_block_refs or [],
        "page_range": node.page_range,
        "generation_reason": node.generation_reason,
        "confidence": node.confidence,
        "content_hash": node.content_hash,
        "locked": node.locked_by is not None,
        "locked_by": node.locked_by,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
    }


def _script_payload(version: TeachingScriptVersion, nodes: list[TeachingScriptNode]) -> dict[str, Any]:
    return {
        "script_version_id": version.script_version_id,
        "course_id": version.course_id,
        "outline_version_id": version.outline_version_id,
        "version": version.version,
        "lifecycle_status": version.lifecycle_status.value,
        "source_parse_run_id": version.source_parse_run_id,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "nodes": [_script_node_payload(n) for n in nodes],
    }


def _script_node_payload(node: TeachingScriptNode) -> dict[str, Any]:
    return {
        "script_node_id": node.script_node_id,
        "script_version_id": node.script_version_id,
        "outline_node_id": node.outline_node_id,
        "content": node.content,
        "style": node.style,
        "evidence_refs": node.evidence_refs or [],
        "source_block_refs": node.source_block_refs or [],
        "content_hash": node.content_hash,
        "locked": node.locked_by is not None,
        "locked_by": node.locked_by,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
    }


def _proposal_payload(proposal: PatchProposal, ops: list[PatchProposalOperation]) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "course_id": proposal.course_id,
        "tool_name": proposal.tool_name,
        "policy_version": proposal.policy_version,
        "status": proposal.status.value,
        "reason": proposal.reason,
        "created_by": proposal.created_by,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "decided_by": proposal.decided_by,
        "decided_at": proposal.decided_at.isoformat() if proposal.decided_at else None,
        "operations": [
            {
                "op_id": op.op_id,
                "operation": op.operation.value,
                "target": op.target,
                "before": op.before,
                "after": op.after,
                "reason": op.reason,
                "evidence_refs": op.evidence_refs or [],
                "external_ref": op.external_ref,
                "policy_version": op.policy_version,
                "accepted": op.accepted,
                "decided_at": op.decided_at.isoformat() if op.decided_at else None,
            }
            for op in ops
        ],
    }


def _outline_nodes(session: Session, course_id: int, version_id: str) -> list[CourseOutlineNode]:
    return list(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
        CourseOutlineNode.outline_version_id == version_id,
    ).order_by(CourseOutlineNode.parent_node_id, CourseOutlineNode.order_index)).all())


def _script_nodes(session: Session, course_id: int, version_id: str) -> list[TeachingScriptNode]:
    return list(session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.course_id == course_id,
        TeachingScriptNode.script_version_id == version_id,
    ).order_by(TeachingScriptNode.created_at)).all())


def _require_draft_outline(session: Session, course_id: int, version_id: str) -> CourseOutlineVersion:
    version = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.course_id == course_id,
        CourseOutlineVersion.outline_version_id == version_id,
    )).first()
    if version is None:
        raise HTTPException(status_code=404, detail="课程结构版本不存在")
    if version.lifecycle_status != OutlineLifecycleStatus.DRAFT:
        raise HTTPException(status_code=409, detail="已发布课程结构不可直接编辑；请先创建草稿版本")
    return version


def _require_draft_script(session: Session, course_id: int, version_id: str) -> TeachingScriptVersion:
    version = session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.course_id == course_id,
        TeachingScriptVersion.script_version_id == version_id,
    )).first()
    if version is None:
        raise HTTPException(status_code=404, detail="讲授脚本版本不存在")
    if version.lifecycle_status != OutlineLifecycleStatus.DRAFT:
        raise HTTPException(status_code=409, detail="已发布讲稿不可直接编辑；请先创建草稿版本")
    return version


@course_outline_router.get("/course/{course_id}/outlines")
async def list_outlines(
    course_id: int,
    lifecycle_status: Optional[OutlineLifecycleStatus] = Query(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.view")
    statement = select(CourseOutlineVersion).where(CourseOutlineVersion.course_id == course_id)
    if lifecycle_status:
        statement = statement.where(CourseOutlineVersion.lifecycle_status == lifecycle_status)
    versions = list(session.exec(statement.order_by(CourseOutlineVersion.version.desc())).all())
    return unified_response(200, "获取课程结构版本成功", {
        "items": [_outline_payload(v, _outline_nodes(session, course_id, v.outline_version_id)) for v in versions],
    })


@course_outline_router.post("/course/{course_id}/outlines/drafts")
async def create_outline_draft(
    course_id: int,
    payload: Optional[OutlineDraftRequest] = None,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "course.structure.edit")
    source_outline_version_id = payload.source_outline_version_id if payload else None
    source = None
    if source_outline_version_id:
        source = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.course_id == course_id,
            CourseOutlineVersion.outline_version_id == source_outline_version_id,
        )).first()
    if source is None:
        source = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.course_id == course_id,
            CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.PUBLISHED,
        ).order_by(CourseOutlineVersion.version.desc())).first()
    max_version = session.exec(select(CourseOutlineVersion.version).where(
        CourseOutlineVersion.course_id == course_id,
    ).order_by(CourseOutlineVersion.version.desc())).first() or 0
    draft = CourseOutlineVersion(
        course_id=course_id, version=int(max_version) + 1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        source_parse_run_id=source.source_parse_run_id if source else None,
        created_by=context.user_id,
    )
    session.add(draft)
    session.flush()
    old_to_new: dict[str, str] = {}
    if source:
        for node in _outline_nodes(session, course_id, source.outline_version_id):
            clone = CourseOutlineNode(
                course_id=course_id, outline_version_id=draft.outline_version_id,
                parent_node_id=None, node_type=node.node_type, title=node.title,
                order_index=node.order_index, knowledge_graph_node_id=node.knowledge_graph_node_id,
                source_block_refs=node.source_block_refs, page_range=node.page_range,
                generation_reason="teacher draft cloned from published outline",
                confidence=node.confidence, content_hash=node.content_hash,
            )
            session.add(clone)
            session.flush()
            old_to_new[node.outline_node_id] = clone.outline_node_id
        for clone in _outline_nodes(session, course_id, draft.outline_version_id):
            # clone nodes retain insertion order matching source tree query.
            # Find the source by matching copied order/title; parent IDs are mapped in second pass.
            pass
        source_nodes = _outline_nodes(session, course_id, source.outline_version_id)
        draft_nodes = _outline_nodes(session, course_id, draft.outline_version_id)
        for old, clone in zip(source_nodes, draft_nodes):
            clone.parent_node_id = old_to_new.get(old.parent_node_id) if old.parent_node_id else None
            session.add(clone)
    session.commit()
    return unified_response(201, "已创建课程结构草稿", _outline_payload(draft, _outline_nodes(session, course_id, draft.outline_version_id)))


@course_outline_router.post("/course/{course_id}/outlines/{outline_version_id}/nodes")
async def add_outline_node(
    course_id: int,
    outline_version_id: str,
    payload: OutlineNodeInput,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.structure.edit")
    _require_draft_outline(session, course_id, outline_version_id)
    if payload.parent_node_id and not session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
        CourseOutlineNode.outline_version_id == outline_version_id,
        CourseOutlineNode.outline_node_id == payload.parent_node_id,
    )).first():
        raise HTTPException(status_code=422, detail="父结构节点不属于当前课程草稿")
    node = CourseOutlineNode(
        course_id=course_id, outline_version_id=outline_version_id,
        parent_node_id=payload.parent_node_id, node_type=payload.node_type,
        title=payload.title, order_index=payload.order_index,
        knowledge_graph_node_id=payload.knowledge_graph_node_id,
        source_block_refs=payload.source_block_refs, page_range=payload.page_range,
        generation_reason=payload.generation_reason, confidence=payload.confidence,
        content_hash=payload.content_hash,
    )
    session.add(node)
    session.commit()
    session.refresh(node)
    return unified_response(201, "课程结构节点已创建", _node_payload(node))


@course_outline_router.put("/course/{course_id}/outlines/{outline_version_id}/nodes/{outline_node_id}")
async def update_outline_node(
    course_id: int,
    outline_version_id: str,
    outline_node_id: str,
    payload: OutlineNodePatch,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "course.structure.edit")
    _require_draft_outline(session, course_id, outline_version_id)
    node = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
        CourseOutlineNode.outline_version_id == outline_version_id,
        CourseOutlineNode.outline_node_id == outline_node_id,
    )).first()
    if node is None:
        raise HTTPException(status_code=404, detail="课程结构节点不存在")
    if node.locked_by is not None and node.locked_by != context.user_id:
        raise HTTPException(status_code=409, detail="该节点已被教师锁定")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "lock":
            node.locked_by = context.user_id if value else None
            node.locked_at = utcnow_aware() if value else None
        else:
            setattr(node, field, value)
    node.updated_at = utcnow_aware()
    session.add(node)
    session.commit()
    return unified_response(200, "课程结构节点已更新", _node_payload(node))


@course_outline_router.post("/course/{course_id}/outlines/{outline_version_id}/publish")
async def publish_outline(
    course_id: int,
    outline_version_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.publish")
    draft = _require_draft_outline(session, course_id, outline_version_id)
    if not _outline_nodes(session, course_id, outline_version_id):
        raise HTTPException(status_code=422, detail="空课程结构不能发布")
    for old in session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.course_id == course_id,
        CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.PUBLISHED,
    )).all():
        old.lifecycle_status = OutlineLifecycleStatus.ARCHIVED
        session.add(old)
    draft.lifecycle_status = OutlineLifecycleStatus.PUBLISHED
    session.add(draft)
    session.commit()
    return unified_response(200, "课程结构已发布", _outline_payload(draft, _outline_nodes(session, course_id, outline_version_id)))


@course_outline_router.get("/course/{course_id}/scripts")
async def list_scripts(
    course_id: int,
    lifecycle_status: Optional[OutlineLifecycleStatus] = Query(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.view")
    statement = select(TeachingScriptVersion).where(TeachingScriptVersion.course_id == course_id)
    if lifecycle_status:
        statement = statement.where(TeachingScriptVersion.lifecycle_status == lifecycle_status)
    versions = list(session.exec(statement.order_by(TeachingScriptVersion.version.desc())).all())
    return unified_response(200, "获取讲授脚本版本成功", {
        "items": [_script_payload(v, _script_nodes(session, course_id, v.script_version_id)) for v in versions],
    })


@course_outline_router.post("/course/{course_id}/scripts/{script_version_id}/nodes")
async def add_script_node(
    course_id: int,
    script_version_id: str,
    payload: ScriptNodeInput,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.script.edit")
    version = _require_draft_script(session, course_id, script_version_id)
    if not session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
        CourseOutlineNode.outline_version_id == version.outline_version_id,
        CourseOutlineNode.outline_node_id == payload.outline_node_id,
    )).first():
        raise HTTPException(status_code=422, detail="讲稿必须绑定当前课程结构节点")
    node = TeachingScriptNode(
        course_id=course_id, script_version_id=script_version_id,
        outline_node_id=payload.outline_node_id, content=payload.content,
        style=payload.style, evidence_refs=payload.evidence_refs,
        source_block_refs=payload.source_block_refs, content_hash=payload.content_hash,
    )
    session.add(node)
    session.commit()
    return unified_response(201, "讲稿节点已创建", _script_node_payload(node))


@course_outline_router.put("/course/{course_id}/scripts/{script_version_id}/nodes/{script_node_id}")
async def update_script_node(
    course_id: int,
    script_version_id: str,
    script_node_id: str,
    payload: ScriptNodePatch,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "course.script.edit")
    _require_draft_script(session, course_id, script_version_id)
    node = session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.course_id == course_id,
        TeachingScriptNode.script_version_id == script_version_id,
        TeachingScriptNode.script_node_id == script_node_id,
    )).first()
    if node is None:
        raise HTTPException(status_code=404, detail="讲稿节点不存在")
    if node.locked_by is not None and node.locked_by != context.user_id:
        raise HTTPException(status_code=409, detail="该讲稿节点已被教师锁定")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "lock":
            node.locked_by = context.user_id if value else None
            node.locked_at = utcnow_aware() if value else None
        else:
            setattr(node, field, value)
    node.updated_at = utcnow_aware()
    session.add(node)
    session.commit()
    return unified_response(200, "讲稿节点已更新", _script_node_payload(node))


@course_outline_router.post("/course/{course_id}/scripts/{script_version_id}/publish")
async def publish_script(
    course_id: int,
    script_version_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.publish")
    draft = _require_draft_script(session, course_id, script_version_id)
    outline = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.course_id == course_id,
        CourseOutlineVersion.outline_version_id == draft.outline_version_id,
    )).first()
    if outline is None or outline.lifecycle_status != OutlineLifecycleStatus.PUBLISHED:
        raise HTTPException(status_code=409, detail="必须先发布对应课程结构，才能发布讲稿")
    for old in session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.course_id == course_id,
        TeachingScriptVersion.lifecycle_status == OutlineLifecycleStatus.PUBLISHED,
    )).all():
        old.lifecycle_status = OutlineLifecycleStatus.ARCHIVED
        session.add(old)
    draft.lifecycle_status = OutlineLifecycleStatus.PUBLISHED
    session.add(draft)
    session.commit()
    return unified_response(200, "讲授脚本已发布", _script_payload(draft, _script_nodes(session, course_id, script_version_id)))


@course_outline_router.get("/course/{course_id}/patch-proposals")
async def list_patch_proposals(
    course_id: int,
    status: Optional[PatchProposalStatus] = Query(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.view")
    statement = select(PatchProposal).where(PatchProposal.course_id == course_id)
    if status:
        statement = statement.where(PatchProposal.status == status)
    proposals = list(session.exec(statement.order_by(PatchProposal.created_at.desc())).all())
    return unified_response(200, "获取教师审核提案成功", {
        "items": [_proposal_payload(p, list(session.exec(select(PatchProposalOperation).where(
            PatchProposalOperation.course_id == course_id,
            PatchProposalOperation.proposal_id == p.proposal_id,
        )).all())) for p in proposals],
    })


@course_outline_router.post("/course/{course_id}/patch-proposals")
async def create_patch_proposal(
    course_id: int,
    payload: ProposalCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "course.edit")
    proposal = PatchProposal(
        course_id=course_id, tool_name=payload.tool_name,
        policy_version=payload.policy_version, reason=payload.reason,
        created_by=context.user_id,
    )
    session.add(proposal)
    session.flush()
    ops: list[PatchProposalOperation] = []
    for item in payload.operations:
        op = PatchProposalOperation(
            proposal_id=proposal.proposal_id, course_id=course_id,
            operation=item.operation, target=item.target, before=item.before,
            after=item.after, reason=item.reason, evidence_refs=item.evidence_refs,
            external_ref=item.external_ref, policy_version=item.policy_version or payload.policy_version,
        )
        session.add(op)
        ops.append(op)
    session.commit()
    return unified_response(201, "备课智能体提案已创建，等待教师审核", _proposal_payload(proposal, ops))


def _apply_proposal_operation(session: Session, course_id: int, op: PatchProposalOperation, teacher_id: int) -> None:
    """Apply a deliberately small, auditable proposal language.

    Unsupported operation shapes are rejected rather than attempting a broad
    JSON patch against course data.  This protects teacher locks and makes the
    green/red diff UI's accepted action match a concrete database mutation.
    """
    parts = op.target.split(":")
    if op.operation == PatchOperation.REPLACE and len(parts) == 3:
        domain, node_id, field = parts
        if domain == "outline" and field in {"title", "page_range"}:
            node = session.exec(select(CourseOutlineNode).where(
                CourseOutlineNode.course_id == course_id,
                CourseOutlineNode.outline_node_id == node_id,
            )).first()
            if node is None or node.locked_by is not None:
                raise HTTPException(status_code=409, detail="提案目标不存在或已锁定")
            _require_draft_outline(session, course_id, node.outline_version_id)
            setattr(node, field, op.after)
            node.updated_at = utcnow_aware()
            session.add(node)
            return
        if domain == "script" and field in {"content", "style"}:
            node = session.exec(select(TeachingScriptNode).where(
                TeachingScriptNode.course_id == course_id,
                TeachingScriptNode.script_node_id == node_id,
            )).first()
            if node is None or node.locked_by is not None:
                raise HTTPException(status_code=409, detail="提案目标不存在或已锁定")
            _require_draft_script(session, course_id, node.script_version_id)
            setattr(node, field, op.after)
            node.updated_at = utcnow_aware()
            session.add(node)
            return
    if op.operation == PatchOperation.ADD and len(parts) == 3 and parts[0] == "outline" and parts[2] == "node":
        version = _require_draft_outline(session, course_id, parts[1])
        try:
            data = json.loads(op.after)
            input_data = OutlineNodeInput.model_validate(data)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="新增结构提案的 after 必须是合法节点 JSON") from exc
        session.add(CourseOutlineNode(
            course_id=course_id, outline_version_id=version.outline_version_id,
            parent_node_id=input_data.parent_node_id, node_type=input_data.node_type,
            title=input_data.title, order_index=input_data.order_index,
            knowledge_graph_node_id=input_data.knowledge_graph_node_id,
            source_block_refs=input_data.source_block_refs, page_range=input_data.page_range,
            generation_reason=op.reason, confidence=input_data.confidence,
            content_hash=input_data.content_hash,
        ))
        return
    raise HTTPException(status_code=422, detail="不支持的提案操作；请改为受支持的结构/讲稿字段提案")


@course_outline_router.post("/course/{course_id}/patch-proposals/{proposal_id}/decide")
async def decide_patch_proposal(
    course_id: int,
    proposal_id: str,
    payload: ProposalDecisionRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "course.edit")
    proposal = session.exec(select(PatchProposal).where(
        PatchProposal.course_id == course_id,
        PatchProposal.proposal_id == proposal_id,
    )).first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="教师提案不存在")
    if proposal.status != PatchProposalStatus.PENDING:
        raise HTTPException(status_code=409, detail="该提案已经审核")
    ops = list(session.exec(select(PatchProposalOperation).where(
        PatchProposalOperation.course_id == course_id,
        PatchProposalOperation.proposal_id == proposal_id,
    )).all())
    wanted = set(payload.accepted_operation_ids)
    known = {op.op_id for op in ops}
    if not wanted.issubset(known):
        raise HTTPException(status_code=422, detail="存在不属于该提案的操作")
    for op in ops:
        if op.op_id in wanted:
            _apply_proposal_operation(session, course_id, op, context.user_id)
            op.accepted = True
        elif payload.reject_unselected:
            op.accepted = False
        op.decided_at = utcnow_aware()
        session.add(op)
    proposal.status = (
        PatchProposalStatus.ACCEPTED if wanted and len(wanted) == len(ops)
        else PatchProposalStatus.PARTIALLY_ACCEPTED if wanted
        else PatchProposalStatus.REJECTED
    )
    proposal.decided_by = context.user_id
    proposal.decided_at = utcnow_aware()
    session.add(proposal)
    session.commit()
    return unified_response(200, "教师提案审核完成", _proposal_payload(proposal, ops))
