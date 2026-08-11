"""Step 5-8: editable course outline, scripts, proposals, mapping and publish.

This router is deliberately small and demo-oriented.  It writes only draft
versions; published outline/script data is immutable and exposed read-only.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
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
    CourseScriptCoverageIssue,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.course_build_model import BuildStepName, BuildStepStatus, CourseBuildStep, CourseCorpusSnapshot, MaterialStatus, SourceMaterial, SourceMaterialVersion
from app.models.media_release_model import MediaRelease
from app.models.document_parse_model import ParsePipeline, StaleStrategy
from app.models.document_parse_model import (
    DocumentBlock,
    EvidenceRenderAsset,
    EvidenceSpan,
    EvidenceSpanStatus,
    RenderAssetType,
)
from app.models.graph_production_model import CourseEvidenceRecord, EvidenceStatus
from app.models.database import get_session
from app.services.course_access_service import require_course_permission
from app.services.course_build_service import course_release_service, quality_gate_service, source_material_service
from app.services.course_corpus_service import course_corpus_service
from app.services.document_parse_service import document_parse_service
from app.services.object_storage import LocalStorageProvider, get_object_storage
from app.services.task_service import TaskCreateRequest, task_service
from app.platform.tasks.worker import local_task_worker
from app.platform.tasks.document_parse_queue import document_parse_queue
from app.models.database import session_factory
from app.models.resource_model import ResourceItem, ResourceLifecycleStatus, ResourceVisibility
from app.models.agent_run_model import AgentRunRecord, AgentRunEventRecord, AgentLLMDiagnosticRecord
from app.services.ppt_generation_service import ppt_generation_service
from app.platform.agents.prep.actions import PrepAction, canonical_prep_action, resolve_prep_intent
from app.platform.agents.shared.error_messages import safe_prep_error_message
from app.platform.agents.providers.llm.debug_capture import prep_llm_debug_capture_store

router = APIRouter()
logger = logging.getLogger(__name__)

# Demo-process guard for long-running Prep optimization. It makes a second
# click fail fast instead of overlapping LLM plans and draft mutations. A
# multi-worker deployment needs a distributed lock before making this claim.
_prep_batch_locks: dict[int, asyncio.Lock] = {}
_prep_batch_locks_guard = asyncio.Lock()


async def _try_acquire_prep_batch_lock(course_id: int) -> asyncio.Lock | None:
    async with _prep_batch_locks_guard:
        lock = _prep_batch_locks.setdefault(course_id, asyncio.Lock())
        if lock.locked():
            return None
        await lock.acquire()
        return lock


def _prep_agent_busy_error() -> HTTPException:
    return HTTPException(
        409,
        detail={
            "error_code": "PREP_AGENT_BUSY",
            "message": "助教智能体正在处理该课程的一键优化，请完成后再发起其他智能优化",
        },
    )


def _operation_display(
    session: Session,
    course_id: int,
    operation: PatchProposalOperation | dict[str, Any],
) -> dict[str, str]:
    """Return the teacher-facing label for one auditable proposal operation.

    ``PatchProposalOperation.target`` is deliberately an internal, stable
    address used by the decision path.  It must stay machine-readable for
    audit and compatibility, but must never be used as the UI label.
    """
    target = operation.target if isinstance(operation, PatchProposalOperation) else str(operation.get("target") or "")
    target_kind, target_id, field = (target.split(":", 2) + ["", "", ""])[:3]
    resource = "course_change"
    resource_label = "课程内容"
    field_label = "内容"
    node_title = ""

    if target_kind == "outline":
        resource = "outline"
        resource_label = "课程节点"
        field_label = {"title": "标题", "structure": "结构"}.get(field, "内容")
        if target_id != "new":
            node = session.exec(select(CourseOutlineNode).where(
                CourseOutlineNode.course_id == course_id,
                CourseOutlineNode.outline_node_id == target_id,
            )).first()
            node_title = node.title if node else ""
    elif target_kind == "script":
        resource = "script"
        resource_label = "讲解脚本"
        field_label = {"content": "讲稿内容", "style": "讲解风格"}.get(field, "内容")
        if target_id != "new":
            script = session.exec(select(TeachingScriptNode).where(
                TeachingScriptNode.course_id == course_id,
                TeachingScriptNode.script_node_id == target_id,
            )).first()
            if script is not None:
                node = session.exec(select(CourseOutlineNode).where(
                    CourseOutlineNode.course_id == course_id,
                    CourseOutlineNode.outline_node_id == script.outline_node_id,
                )).first()
                node_title = node.title if node else ""

    prefix = "新增" if target_id == "new" else ""
    label = f"{prefix}{resource_label}"
    if node_title:
        label = f"{label}《{node_title}》"
    return {
        "resource": resource,
        "resource_label": resource_label,
        "field": field or "change",
        "field_label": field_label,
        "node_title": node_title,
        "label": f"{label}的{field_label}",
    }


def _change_summary(
    session: Session,
    course_id: int,
    operations: list[PatchProposalOperation] | list[dict[str, Any]],
    state: Literal["pending_review", "applied", "rejected", "no_change"],
) -> dict[str, Any]:
    """Build the common, display-safe proposal result shape."""
    items = [_operation_display(session, course_id, operation) for operation in operations]
    return {"state": state, "count": len(items), "items": items}


def _proposal_change_state(status: PatchProposalStatus) -> Literal[
    "pending_review", "applied", "rejected", "no_change"
]:
    if status == PatchProposalStatus.PENDING:
        return "pending_review"
    if status == PatchProposalStatus.REJECTED:
        return "rejected"
    if status in {PatchProposalStatus.ACCEPTED, PatchProposalStatus.PARTIALLY_ACCEPTED}:
        return "applied"
    return "no_change"


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


class ScriptCreate(BaseModel):
    outline_node_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)
    style: str = Field(default="beginner", max_length=64)


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
    material_version_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    page_range: Optional[str] = Field(default=None, max_length=64)
    page_refs: Optional[list[int]] = Field(default=None, min_length=1, max_length=200)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    locked: Optional[bool] = None


class PptMappingBulkItem(BaseModel):
    """One teacher-edited deck/node mapping saved with the mapping workbench."""

    outline_node_id: str = Field(min_length=1, max_length=128)
    material_version_id: str = Field(min_length=1, max_length=128)
    page_refs: list[int] = Field(min_length=1, max_length=200)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    # A manual correction is protected from future one-click optimisations by
    # default.  Teachers can explicitly save it unlocked when they want later
    # AI passes to keep refining it.
    locked: bool = True


class PptMappingBulkUpdate(BaseModel):
    mappings: list[PptMappingBulkItem] = Field(min_length=1, max_length=300)


class PptMappingMatchRequest(BaseModel):
    """Narrow, teacher-triggered automatic mapping scope."""

    mode: Literal["all_unlocked", "node", "selected_pages"]
    material_version_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    outline_node_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    page_refs: list[int] = Field(default_factory=list, max_length=200)


class PptGenerateRequest(BaseModel):
    template_id: Optional[str] = Field(default=None, max_length=128)
    search: bool = False


class PrepAgentCommandRequest(BaseModel):
    """Natural-language instruction for the teacher-facing preparation agent."""

    instruction: str = Field(default="", max_length=8_000)
    outline_node_id: Optional[str] = Field(default=None, max_length=100)
    # Buttons send the action directly; free-text chat leaves it empty and
    # lets the structured Prep intent router select a capability token.
    action: Optional[str] = Field(default=None, max_length=64)


class PrepAgentBatchRequest(BaseModel):
    """Explicit teacher-triggered batch action that applies without approval."""

    action: str = Field(min_length=1, max_length=64)
    instruction: str = Field(default="", max_length=8_000)
    outline_node_id: Optional[str] = Field(default=None, max_length=100)


class PrepLLMDebugCaptureRequest(BaseModel):
    """Explicit local-only opt-in for raw Prep LLM request/response capture."""

    enabled: bool


async def _plan_incremental_prep(
    *,
    request: Request,
    service: Any,
    session: Session,
    course_id: int,
    teacher_id: int,
    instruction: str,
    outline_node_id: str | None,
    action: str | None = None,
):
    """Use the registered Prep Runtime/Port, with a compatible service fallback."""
    platform = getattr(request.app.state, "agent_platform", None)
    gateway = getattr(platform, "gateway", None) if platform is not None else None
    if gateway is not None:
        from app.platform.agents.prep.enums import PrepGraphKind
        from app.platform.agents.runtime.base import AgentRunContext
        from app.platform.agents.runtime.profile import AgentType
        from app.platform.agents.runtime.registry import AgentDefinitionKey
        from app.platform.agents.prep.incremental.dependencies import IncrementalPrepResult

        start = await gateway.start(
            agent_type=AgentType.PREP,
            definition_key=AgentDefinitionKey(
                agent_type=AgentType.PREP.value,
                agent_version=PrepGraphKind.INCREMENTAL.value,
            ),
            context=AgentRunContext(
                agent_type=AgentType.PREP.value,
                scope=(str(course_id),),
                teacher_id=str(teacher_id),
                course_id=str(course_id),
                user_message=instruction,
                extras={
                    "outline_node_id": outline_node_id,
                    "action": action,
                },
            ),
        )
        if start.status == "completed" and start.result:
            result = start.result.get("result") or {}
            return IncrementalPrepResult(
                summary=result.get("summary", ""),
                operations=list(result.get("operations") or []),
                evidence=list(result.get("evidence") or []),
                excluded_locked_targets=list(
                    result.get("excluded_locked_targets") or []
                ),
                planner=result.get("planner", "llm"),
                run_id=start.run_id,
                trace_id=start.trace_id,
                error_code=start.error_code or "",
            )
        if start.error_code and start.error_code != "AGENT_NOT_AVAILABLE":
            from app.services.course_prep_agent_service import CoursePrepAgentPlanningError

            if start.error_code == "INCREMENTAL_PLAN_INVALID_REQUEST":
                raise ValueError(start.error_message or "助教智能体没有可执行的草稿目标")
            planning_error = CoursePrepAgentPlanningError(
                safe_prep_error_message(
                    RuntimeError(start.error_message),
                    default=f"助教智能体运行失败（{start.error_code}）",
                )
            )
            planning_error.run_id = start.run_id
            planning_error.trace_id = start.trace_id
            planning_error.error_code = start.error_code
            raise planning_error
        if start.error_code:
            logger.warning(
                "Prep Runtime unavailable; falling back to direct service: %s",
                start.error_code,
            )

    if action is not None:
        return await service.plan_action(
            session,
            course_id=course_id,
            action=action,
            instruction=instruction,
            outline_node_id=outline_node_id,
        )
    return await service.plan(
        session,
        course_id=course_id,
        instruction=instruction,
        outline_node_id=outline_node_id,
    )


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


def _try_structure_edit_context(
    session: Session,
    current_user: dict,
    course_id: int,
    permission: str = "course.structure.edit",
):
    """Return an edit context when the caller may seed a working draft.

    The read endpoints are also used by learners.  Only a caller with the
    relevant explicit Course Access v1 edit capability may cause a published
    version to be copied into a draft; everyone else remains read-only.
    """
    try:
        context = require_course_permission(session, current_user, course_id, permission)
        return context.user_id
    except HTTPException as exc:
        if exc.status_code == 403:
            return None
        raise


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
        # A copy of the published outline keeps its corpus lineage; otherwise
        # the next publish would fail the same-build-lineage gate because the
        # draft's corpus_snapshot_id stays NULL.
        corpus_snapshot_id=published.corpus_snapshot_id if published else None,
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
                corpus_snapshot_id=published_script.corpus_snapshot_id,
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
        # ``script_node_id`` is the stable editor identifier.  The media job
        # contract deliberately uses the database identity because its Cue
        # snapshot has a foreign key to ``script_nodes.id``.  Expose the two
        # values under distinct names so a teacher client never guesses.
        "script_node_db_id": node.id,
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


def _current_ppt_material_versions(
    session: Session,
    course_id: int,
) -> list[tuple[SourceMaterial, SourceMaterialVersion]]:
    """Resolve every current slide material version for a course.

    PPT slide numbers are scoped to the material version, not to the course.
    Keeping this selection in one helper prevents the mapping screen and the
    optimizer from accidentally choosing whichever deck happened to upload
    last.
    """
    materials = list(session.exec(
        select(SourceMaterial).where(
            SourceMaterial.course_id == course_id,
            SourceMaterial.material_type == "slide",
        ).order_by(SourceMaterial.id)
    ).all())
    result: list[tuple[SourceMaterial, SourceMaterialVersion]] = []
    seen_content: set[str] = set()
    for material in materials:
        version = None
        if material.current_version_id:
            version = session.exec(select(SourceMaterialVersion).where(
                SourceMaterialVersion.course_id == course_id,
                SourceMaterialVersion.material_id == material.material_id,
                SourceMaterialVersion.version_id == material.current_version_id,
            )).first()
        if version is None:
            version = session.exec(select(SourceMaterialVersion).where(
                SourceMaterialVersion.course_id == course_id,
                SourceMaterialVersion.material_id == material.material_id,
            ).order_by(
                SourceMaterialVersion.is_current.desc(),
                SourceMaterialVersion.id.desc(),
            )).first()
        if version is not None:
            # Pre-idempotency uploads could create several current material
            # rows for identical bytes.  PPT page references are per deck, so
            # keep one stable deck per hash while retaining old rows intact.
            content_key = (version.file_hash or version.version_id).strip()
            if content_key in seen_content:
                continue
            seen_content.add(content_key)
            result.append((material, version))
    return result


def _ppt_page_count(session: Session, *, course_id: int, material_version_id: str) -> int:
    """Return the highest known slide number for one current PPT version.

    OCR may be delayed or unavailable while the original PPTX renders are
    already usable.  The mapping UI must still expose the complete deck in
    that state, so count both parsed blocks and persisted source-slide assets.
    """
    pages = session.exec(select(DocumentBlock.page_or_slide).where(
        DocumentBlock.course_id == course_id,
        DocumentBlock.material_version_id == material_version_id,
    )).all()
    parsed_page_count = max((int(page or 0) for page in pages), default=0)
    rendered_pages = session.exec(select(EvidenceRenderAsset.page_number).where(
        EvidenceRenderAsset.course_id == course_id,
        EvidenceRenderAsset.asset_type == RenderAssetType.PPT_SLIDE_IMAGE,
        EvidenceRenderAsset.object_key.like(
            f"ppt-slide-render/course{course_id}/{material_version_id}/%"
        ),
    )).all()
    rendered_page_count = max((int(page or 0) for page in rendered_pages), default=0)
    return max(parsed_page_count, rendered_page_count)


def _ppt_material_view(
    session: Session,
    *,
    course_id: int,
    material: SourceMaterial,
    version: SourceMaterialVersion,
) -> dict[str, Any]:
    return {
        "material_id": material.material_id,
        "material_version_id": version.version_id,
        "name": material.name or version.version_id,
        "page_count": _ppt_page_count(
            session,
            course_id=course_id,
            material_version_id=version.version_id,
        ),
        "parse_status": version.parse_status.value,
    }


def _normalise_mapping_page_refs(
    *,
    page_range: str | None = None,
    page_refs: list[int] | None = None,
) -> list[int]:
    """Accept the legacy range input and the workbench's non-contiguous pages."""
    if page_refs is not None:
        normalized = sorted({int(page) for page in page_refs})
        if not normalized or normalized[0] < 1:
            raise HTTPException(400, "页码必须为大于等于 1 的整数")
        return normalized
    if page_range is None:
        return []
    raw = page_range.strip()
    parts = raw.split("-", 1)
    if not raw or not all(part.strip().isdigit() for part in parts):
        raise HTTPException(400, "页码格式应为 1、1-3 或多个页码数组")
    page_start = max(1, int(parts[0].strip()))
    page_end = max(page_start, int(parts[-1].strip()))
    return list(range(page_start, page_end + 1))


def _validate_mapping_pages(
    session: Session,
    *,
    course_id: int,
    material_version_id: str,
    page_refs: list[int],
) -> list[int]:
    normalized = _normalise_mapping_page_refs(page_refs=page_refs)
    page_count = _ppt_page_count(
        session,
        course_id=course_id,
        material_version_id=material_version_id,
    )
    if page_count and normalized[-1] > page_count:
        raise HTTPException(
            400,
            detail={
                "error_code": "PPT_PAGE_OUT_OF_RANGE",
                "message": f"This PPT has {page_count} parsed pages; page {normalized[-1]} is out of range.",
            },
        )
    return normalized


@router.get("/course/{course_id}/outline")
async def get_outline(course_id: int, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.view")
    version = _draft_outline(session, course_id) or _published_outline(session, course_id)
    if not version:
        return unified_response(200, "课程目录尚未生成", {"version": None, "nodes": []})
    if version.lifecycle_status == OutlineLifecycleStatus.PUBLISHED:
        editor_id = _try_structure_edit_context(session, current_user, course_id, "course.structure.edit")
        if editor_id is not None:
            version = _ensure_draft_outline(session, course_id, editor_id)
            session.commit()
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
    if outline.lifecycle_status == OutlineLifecycleStatus.PUBLISHED:
        editor_id = _try_structure_edit_context(session, current_user, course_id, "course.script.edit")
        if editor_id is not None:
            outline = _ensure_draft_outline(session, course_id, editor_id)
            session.commit()
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
    coverage_issues = list(session.exec(select(CourseScriptCoverageIssue).where(
        CourseScriptCoverageIssue.course_id == course_id,
        CourseScriptCoverageIssue.script_version_id == script.script_version_id,
        CourseScriptCoverageIssue.status == "open",
    ).order_by(CourseScriptCoverageIssue.created_at)).all())
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
        "coverage_issues": [
            {
                "issue_id": issue.issue_id,
                "outline_node_id": issue.outline_node_id,
                "code": issue.issue_code,
                "status": issue.status,
                "created_at": issue.created_at.isoformat() if issue.created_at else None,
            }
            for issue in coverage_issues
        ],
        "editable": script.lifecycle_status == OutlineLifecycleStatus.DRAFT,
    })


def _resolve_script_coverage_issues(
    session: Session,
    *,
    course_id: int,
    script_version_id: str,
    outline_node_id: str,
    resolved_by: int,
) -> None:
    now = utcnow_aware()
    issues = list(session.exec(select(CourseScriptCoverageIssue).where(
        CourseScriptCoverageIssue.course_id == course_id,
        CourseScriptCoverageIssue.script_version_id == script_version_id,
        CourseScriptCoverageIssue.outline_node_id == outline_node_id,
        CourseScriptCoverageIssue.status == "open",
    )).all())
    for issue in issues:
        issue.status = "resolved"
        issue.resolved_by = resolved_by
        issue.resolved_at = now
        session.add(issue)


@router.post("/course/{course_id}/scripts")
async def create_missing_script(
    course_id: int,
    payload: ScriptCreate,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Create a teacher-authored script for one missing draft knowledge point."""
    context = require_course_permission(session, current_user, course_id, "course.script.edit")
    content = payload.content.strip()
    if not content:
        raise HTTPException(422, "讲稿正文不能为空")
    outline = _draft_outline(session, course_id)
    if outline is None:
        raise HTTPException(409, "当前课程没有可编辑的目录草稿")
    script_version = session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.course_id == course_id,
        TeachingScriptVersion.outline_version_id == outline.outline_version_id,
        TeachingScriptVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
    ).order_by(TeachingScriptVersion.version.desc())).first()
    if script_version is None:
        raise HTTPException(409, "当前课程没有可编辑的讲稿草稿")
    outline_node = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
        CourseOutlineNode.outline_version_id == outline.outline_version_id,
        CourseOutlineNode.outline_node_id == payload.outline_node_id,
    )).first()
    if outline_node is None or outline_node.node_type != OutlineNodeType.KNOWLEDGE_POINT:
        raise HTTPException(422, "讲稿必须绑定当前草稿中的知识点节点")
    if outline_node.locked_by is not None:
        raise HTTPException(409, "知识点已锁定；请先解锁后再补齐讲稿")
    existing = session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.course_id == course_id,
        TeachingScriptNode.script_version_id == script_version.script_version_id,
        TeachingScriptNode.outline_node_id == outline_node.outline_node_id,
    )).first()
    if existing is not None:
        raise HTTPException(409, "该知识点已有讲稿，请刷新后编辑已有内容")
    source_refs = list(outline_node.source_block_refs or [])
    node = TeachingScriptNode(
        course_id=course_id,
        script_version_id=script_version.script_version_id,
        outline_node_id=outline_node.outline_node_id,
        content=content,
        style=(payload.style or "beginner").strip() or "beginner",
        source_block_refs=source_refs,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    _mark_teacher_edited(script_version)
    _mark_teacher_edited(outline)
    session.add(script_version)
    session.add(outline)
    session.add(node)
    _resolve_script_coverage_issues(
        session,
        course_id=course_id,
        script_version_id=script_version.script_version_id,
        outline_node_id=outline_node.outline_node_id,
        resolved_by=context.user_id,
    )
    session.commit()
    session.refresh(node)
    return unified_response(201, "讲稿已补齐", _script_node_view(node))


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
    if (node.content or "").strip():
        _resolve_script_coverage_issues(
            session,
            course_id=course_id,
            script_version_id=node.script_version_id,
            outline_node_id=node.outline_node_id,
            resolved_by=context.user_id,
        )
    node.updated_at = utcnow_aware(); session.add(node); session.commit(); session.refresh(node)
    return unified_response(200, "讲稿已保存", _script_node_view(node))


@router.post("/course/{course_id}/prep-agent/commands")
async def run_prep_agent_command(
    course_id: int,
    payload: PrepAgentCommandRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Turn a teacher's natural-language request into a reviewable proposal.

    This is intentionally a compatibility-facade route.  It uses the existing
    PatchProposal persistence and decision endpoint, so it cannot double-write
    the outline/script records.
    """
    from app.services.course_prep_agent_service import (
        CoursePrepAgentIntentRoutingError,
        CoursePrepAgentPlanningError,
        course_prep_agent_service,
    )

    if payload.action is not None:
        # Button actions are already explicit and deterministic.  They must
        # bypass the classifier so a model outage cannot disable a button.
        intent = resolve_prep_intent(
            payload.instruction,
            selected_outline_node_id=payload.outline_node_id,
            explicit_action=payload.action,
        )
    else:
        # Classifying a free-text request is itself a teacher-facing course
        # operation, so enforce the broad course capability before exposing a
        # bounded node summary to the router.  Action-specific permissions
        # are checked again below before planning or applying anything.
        require_course_permission(session, current_user, course_id, "course.edit")
        try:
            intent = await course_prep_agent_service.classify_intent(
                session,
                course_id=course_id,
                instruction=payload.instruction,
                outline_node_id=payload.outline_node_id,
            )
        except CoursePrepAgentIntentRoutingError as exc:
            raise HTTPException(
                503,
                detail={
                    "error_code": "PREP_AGENT_INTENT_UNAVAILABLE",
                    "message": "助教意图判断暂时不可用，未执行任何课程修改。",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                422,
                detail={
                    "error_code": "PREP_AGENT_NO_EDITABLE_TARGET",
                    "message": str(exc),
                },
            ) from exc
    if intent.needs_clarification:
        return unified_response(200, "需要补充操作范围", {
            "outcome": "needs_clarification",
            "clarification": intent.clarification,
        })
    assert intent.action is not None
    if intent.action == PrepAction.MATCH_PPT:
        # PPT mapping already has its own typed Port/workflow and trustworthy
        # no-candidate outcome. Natural language reaches that same workflow.
        return await optimize_ppt_mapping(course_id, request, session, current_user)
    if intent.apply_immediately:
        # "一键整理/优化全部" in chat is an explicit teacher authorization.
        # Reuse the exact batch endpoint rather than duplicating validation,
        # locking, auditing, or atomic-apply behaviour in the chat facade.
        return await run_prep_agent_batch_action(
            course_id,
            PrepAgentBatchRequest(
                action=intent.action.value,
                instruction=intent.instruction,
            ),
            request,
            session,
            current_user,
        )
    permission = (
        "course.structure.edit"
        if intent.action in {PrepAction.OPTIMIZE_NODE_TITLE, PrepAction.ORGANIZE_STRUCTURE}
        else "course.script.edit"
    )
    context = require_course_permission(session, current_user, course_id, permission)
    # Both checks are inside the guard so a batch request cannot race this
    # single-node command between observing and acquiring its course lock.
    async with _prep_batch_locks_guard:
        batch_lock = _prep_batch_locks.get(course_id)
        batch_running = batch_lock is not None and batch_lock.locked()
    if batch_running:
        raise _prep_agent_busy_error()
    try:
        result = await _plan_incremental_prep(
            request=request,
            service=course_prep_agent_service,
            session=session,
            course_id=course_id,
            teacher_id=context.user_id,
            instruction=intent.instruction,
            outline_node_id=payload.outline_node_id,
            action=intent.action.value,
        )
    except CoursePrepAgentPlanningError as exc:
        raise HTTPException(
            502,
            detail={
                "error_code": "PREP_AGENT_LLM_INVALID_RESPONSE",
                "message": safe_prep_error_message(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"error_code": "PREP_AGENT_NO_EDITABLE_TARGET", "message": str(exc)}) from exc

    proposal = PatchProposal(
        course_id=course_id,
        tool_name="CoursePrepAgent",
        policy_version="course-prep-agent/actions-2.0",
        reason=result.summary,
        created_by=context.user_id,
    )
    session.add(proposal)
    session.flush()
    operation_count = 0
    persisted_operations: list[PatchProposalOperation] = []
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
            before = _proposal_before_value(target, field)
        else:
            target = session.exec(select(TeachingScriptNode).where(
                TeachingScriptNode.course_id == course_id,
                TeachingScriptNode.script_node_id == target_id,
            )).first()
            if target is None or target.locked_by is not None:
                continue
            before = _proposal_before_value(target, field)
        operation = PatchProposalOperation(
            proposal_id=proposal.proposal_id,
            course_id=course_id,
            operation=PatchOperation(item.get("operation", "replace")),
            target=item["target"],
            before=before,
            after=item["after"],
            reason=item["reason"],
            evidence_refs=item["evidence_refs"],
            policy_version="course-prep-agent/actions-2.0",
        )
        session.add(operation)
        persisted_operations.append(operation)
        operation_count += 1
    if operation_count == 0:
        session.rollback()
        change_summary = _change_summary(session, course_id, [], "no_change")
        return unified_response(200, "未发现需要安全调整的内容，课程草稿保持不变", {
            "outcome": "no_change",
            "action": intent.action.value,
            "change_summary": change_summary,
            "explanation": {
                "changed": [],
                "reason": result.summary,
                "evidence": result.evidence,
                "excluded_locked_targets": result.excluded_locked_targets,
                "planner": result.planner,
                "change_summary": change_summary,
            },
        })
    session.commit()
    change_summary = _change_summary(
        session,
        course_id,
        persisted_operations,
        "pending_review",
    )
    return unified_response(201, "备课 Agent 已生成待教师审核的提案", {
        "proposal_id": proposal.proposal_id,
        "status": PatchProposalStatus.PENDING.value,
        "action": intent.action.value,
        "change_summary": change_summary,
        "explanation": {
            "changed": [item["target"] for item in result.operations],
            "reason": result.summary,
            "evidence": result.evidence,
            "excluded_locked_targets": result.excluded_locked_targets,
            "planner": result.planner,
            "change_summary": change_summary,
        },
    })


@router.post("/course/{course_id}/prep-agent/batch-actions")
async def run_prep_agent_batch_action(
    course_id: int,
    payload: PrepAgentBatchRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Apply one teacher-authorized batch optimization to every editable node.

    Clicking the one-click action is the teacher decision, so the generated
    PatchProposal is persisted as already accepted for audit and is never
    exposed as pending approval. Planning is completed and fully validated
    before any row is mutated.
    """
    action = canonical_prep_action(payload.action)
    if action not in {PrepAction.ORGANIZE_STRUCTURE, PrepAction.OPTIMIZE_ALL_SCRIPTS}:
        raise HTTPException(422, detail={
            "error_code": "PREP_AGENT_ACTION_INVALID",
            "message": "批量入口只支持一键整理结构或一键优化讲解脚本。",
        })
    permission = (
        "course.structure.edit"
        if action == PrepAction.ORGANIZE_STRUCTURE
        else "course.script.edit"
    )
    context = require_course_permission(session, current_user, course_id, permission)
    batch_lock = await _try_acquire_prep_batch_lock(course_id)
    if batch_lock is None:
        raise _prep_agent_busy_error()
    from app.services.course_prep_agent_service import (
        CoursePrepAgentPlanningError,
        course_prep_agent_service,
    )

    try:
        try:
            result = await _plan_incremental_prep(
                request=request,
                service=course_prep_agent_service,
                session=session,
                course_id=course_id,
                teacher_id=context.user_id,
                instruction=payload.instruction,
                outline_node_id=payload.outline_node_id,
                action=action.value,
            )
        except CoursePrepAgentPlanningError as exc:
            raise HTTPException(
                502,
                detail={
                    "error_code": getattr(exc, "error_code", "") or "PREP_AGENT_BATCH_INCOMPLETE",
                    "run_id": getattr(exc, "run_id", "") or None,
                    "trace_id": getattr(exc, "trace_id", "") or None,
                    "message": safe_prep_error_message(exc),
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                422,
                detail={
                    "error_code": "PREP_AGENT_NO_EDITABLE_TARGET",
                    "message": str(exc),
                },
            ) from exc

        if not result.operations:
            return unified_response(200, "未发现需要安全调整的内容，课程草稿保持不变", {
                "action": action.value,
                "outcome": "no_change",
                "updated_count": 0,
                "excluded_locked_targets": result.excluded_locked_targets,
                "planner": result.planner,
                "summary": result.summary,
                "run_id": result.run_id or None,
                "trace_id": result.trace_id or None,
            })

        decided_at = utcnow_aware()
        proposal = PatchProposal(
            course_id=course_id,
            tool_name=(
                "CourseStructureBatchOptimizer"
                if action == PrepAction.ORGANIZE_STRUCTURE
                else "TeachingScriptBatchOptimizer"
            ),
            policy_version="course-prep-agent/actions-2.0",
            status=PatchProposalStatus.ACCEPTED,
            reason=result.summary,
            created_by=context.user_id,
            decided_by=context.user_id,
            decided_at=decided_at,
        )
        session.add(proposal)
        session.flush()
        operations: list[PatchProposalOperation] = []
        for item in result.operations:
            target_kind, target_id, field = item["target"].split(":", 2)
            if action == PrepAction.ORGANIZE_STRUCTURE and (
                target_kind != "outline" or field not in {"title", "structure"}
            ):
                raise ValueError(f"结构整理返回了不允许的目标: {item['target']}")
            if action == PrepAction.OPTIMIZE_ALL_SCRIPTS and (
                target_kind != "script" or field != "content"
            ):
                raise ValueError(f"讲稿优化返回了不允许的目标: {item['target']}")
            if target_kind == "outline":
                target = session.exec(select(CourseOutlineNode).where(
                    CourseOutlineNode.course_id == course_id,
                    CourseOutlineNode.outline_node_id == target_id,
                )).first()
            else:
                target = session.exec(select(TeachingScriptNode).where(
                    TeachingScriptNode.course_id == course_id,
                    TeachingScriptNode.script_node_id == target_id,
                )).first()
            if target is None or target.locked_by is not None:
                raise HTTPException(
                    409,
                    detail={
                        "error_code": "PREP_AGENT_TARGET_CHANGED",
                        "message": "批量优化期间节点已被锁定或删除，未应用任何修改",
                    },
                )
            operation = PatchProposalOperation(
                proposal_id=proposal.proposal_id,
                course_id=course_id,
                operation=PatchOperation(item.get("operation", "replace")),
                target=item["target"],
                before=_proposal_before_value(target, field),
                after=item["after"],
                reason=item["reason"],
                evidence_refs=item["evidence_refs"],
                policy_version="course-prep-agent/actions-2.0",
                accepted=True,
                decided_at=decided_at,
            )
            session.add(operation)
            operations.append(operation)

        _apply_operations_atomically(session, course_id, operations, context.user_id)
        session.add(proposal)
        session.commit()
        return unified_response(200, "助教智能体已完成全量优化", {
            "action": action.value,
            "proposal_id": proposal.proposal_id,
            "status": PatchProposalStatus.ACCEPTED.value,
            "updated_count": len(operations),
            "excluded_locked_targets": result.excluded_locked_targets,
            "planner": result.planner,
            "change_summary": _change_summary(session, course_id, operations, "applied"),
            "summary": result.summary,
            "run_id": result.run_id or None,
            "trace_id": result.trace_id or None,
        })
    except Exception:
        session.rollback()
        raise
    finally:
        batch_lock.release()


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


@router.get("/course/{course_id}/prep-agent/runs/{run_id}/diagnostic")
async def get_prep_agent_run_diagnostic(
    course_id: int,
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.view")
    run = session.exec(select(AgentRunRecord).where(
        AgentRunRecord.run_id == run_id,
        AgentRunRecord.course_id == course_id,
        AgentRunRecord.agent_type == "prep",
    )).first()
    if run is None:
        raise HTTPException(404, detail={"error_code": "PREP_AGENT_RUN_NOT_FOUND", "message": "运行记录不存在"})
    diagnostics = session.exec(select(AgentLLMDiagnosticRecord).where(
        AgentLLMDiagnosticRecord.run_id == run_id,
        AgentLLMDiagnosticRecord.course_id == course_id,
    ).order_by(AgentLLMDiagnosticRecord.created_at, AgentLLMDiagnosticRecord.attempt)).all()
    events = session.exec(select(AgentRunEventRecord).where(
        AgentRunEventRecord.run_id == run_id,
    ).order_by(AgentRunEventRecord.created_at, AgentRunEventRecord.id)).all()
    return unified_response(200, "获取备课 Agent 诊断成功", {
        "run": {
            "run_id": run.run_id, "trace_id": run.trace_id,
            "agent_type": run.agent_type, "status": run.status,
            "stage": run.stage, "error_code": run.error_code or None,
            "errors": run.error_details or [],
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "updated_at": run.updated_at.isoformat(),
        },
        "llm_calls": [{
            "stage": item.stage, "node": item.node, "purpose": item.purpose,
            "prompt_version": item.prompt_version, "schema_name": item.schema_name,
            "model": item.model, "attempt": item.attempt, "repaired": item.repaired,
            "finish_reason": item.finish_reason, "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens, "input_chars": item.input_chars,
            "output_chars": item.output_chars, "response_hash": item.response_hash,
            "truncated": item.truncated, "response_format_fallback": item.response_format_fallback,
            "validation_errors": item.validation_errors or [], "usage": item.usage_metadata or {},
            "latency_ms": item.latency_ms, "created_at": item.created_at.isoformat(),
        } for item in diagnostics],
        "events": [{
            "event_type": item.event_type,
            "created_at": item.created_at.isoformat(),
            "payload": item.payload or {},
        } for item in events],
    })


@router.post("/course/{course_id}/prep-agent/debug-capture")
async def set_prep_agent_llm_debug_capture(
    course_id: int,
    payload: PrepLLMDebugCaptureRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Enable or disable raw local LLM capture for one editable course.

    This route is deliberately teacher/editor-only.  It controls a local
    ignored file store intended for the next manual troubleshooting run; it
    never exposes prompt/model text from this endpoint.
    """
    require_course_permission(session, current_user, course_id, "course.edit")
    enabled = prep_llm_debug_capture_store.set_enabled(
        course_id=course_id,
        enabled=payload.enabled,
    )
    return unified_response(200, "Prep LLM 本地调试备份已更新", {
        "course_id": course_id,
        "enabled": enabled,
        "storage": "local_ignored_debug_store",
    })


@router.get("/course/{course_id}/prep-agent/runs/{run_id}/debug-capture")
async def get_prep_agent_llm_debug_capture(
    course_id: int,
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Read explicitly captured raw Prep request/response records for one run."""
    require_course_permission(session, current_user, course_id, "course.edit")
    records = prep_llm_debug_capture_store.read_run(course_id=course_id, run_id=run_id)
    if not records:
        raise HTTPException(404, detail={
            "error_code": "PREP_AGENT_DEBUG_CAPTURE_NOT_FOUND",
            "message": "该运行没有本地调试备份；请先开启备份后重新发起请求。",
        })
    return unified_response(200, "获取 Prep LLM 本地调试备份成功", {
        "course_id": course_id,
        "run_id": run_id,
        "records": records,
    })


@router.post("/course/{course_id}/scripts/{script_node_id}/lock")
async def lock_script(course_id: int, script_node_id: str, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    context = require_course_permission(session, current_user, course_id, "course.script.edit")
    node = session.exec(select(TeachingScriptNode).where(TeachingScriptNode.script_node_id == script_node_id, TeachingScriptNode.course_id == course_id)).first()
    if not node: raise HTTPException(404, "讲稿节点不存在")
    node.locked_by = context.user_id; node.locked_at = utcnow_aware(); session.add(node); session.commit()
    return unified_response(200, "讲稿节点已锁定", _script_node_view(node))


@router.post("/course/{course_id}/scripts/{script_node_id}/unlock")
async def unlock_script(
    course_id: int,
    script_node_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Return a draft lecture-script node to the editable AI scope."""
    require_course_permission(session, current_user, course_id, "course.script.edit")
    node = session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.script_node_id == script_node_id,
        TeachingScriptNode.course_id == course_id,
    )).first()
    if node is None:
        raise HTTPException(404, "讲稿节点不存在")
    node.locked_by = None
    node.locked_at = None
    session.add(node)
    session.commit()
    session.refresh(node)
    return unified_response(200, "讲稿节点已解锁", _script_node_view(node))


@router.get("/course/{course_id}/proposals")
async def list_proposals(
    course_id: int,
    status: PatchProposalStatus | None = None,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.view")
    statement = select(PatchProposal).where(PatchProposal.course_id == course_id)
    if status is not None:
        statement = statement.where(PatchProposal.status == status)
    proposals = session.exec(statement.order_by(PatchProposal.created_at.desc())).all()
    result = []
    for proposal in proposals:
        ops = session.exec(select(PatchProposalOperation).where(PatchProposalOperation.proposal_id == proposal.proposal_id).order_by(PatchProposalOperation.id)).all()
        result.append({
            "proposal_id": proposal.proposal_id,
            "tool_name": proposal.tool_name,
            "policy_version": proposal.policy_version,
            "status": proposal.status.value,
            "reason": proposal.reason,
            "created_at": proposal.created_at.isoformat(),
            "change_summary": _change_summary(
                session,
                course_id,
                list(ops),
                _proposal_change_state(proposal.status),
            ),
            "operations": [{
                "op_id": o.op_id,
                "operation": o.operation.value,
                "target": o.target,
                "display": _operation_display(session, course_id, o),
                "before": o.before,
                "after": o.after,
                "reason": o.reason,
                "evidence_refs": o.evidence_refs or [],
                "external_ref": o.external_ref,
                "accepted": o.accepted,
            } for o in ops],
        })
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


def _proposal_before_value(target: Any, field: str) -> str:
    if field == "structure":
        return json.dumps({
            "parent_node_id": target.parent_node_id,
            "order_index": target.order_index,
        }, ensure_ascii=False)
    return str(getattr(target, field, ""))


def _apply_operations_atomically(
    session: Session,
    course_id: int,
    operations: list[PatchProposalOperation],
    user_id: int,
) -> None:
    """Apply a proposal without exposing a transient invalid outline tree.

    Title/script replacements retain the existing per-operation semantics.
    Structure moves, reorders and removals are computed against one draft tree
    and written in a two-phase order-index update, so the DB uniqueness rule
    cannot observe duplicate sibling positions halfway through the operation.
    """
    structure_ops = [
        op for op in operations
        if op.target.startswith("outline:") and op.target.endswith(":structure")
    ]
    simple_ops = [op for op in operations if op not in structure_ops]
    # Preflight every normal replace before mutating any row.  This makes an
    # old proposal fail as a whole instead of overwriting a teacher edit that
    # happened after the proposal was generated.
    for operation in simple_ops:
        if operation.operation != PatchOperation.REPLACE:
            raise HTTPException(422, "非结构提案只能执行字段替换")
        match = re.match(r"^(outline|script):([^:]+):(title|content|style)$", operation.target)
        if match is None:
            # Legacy initial-build proposals may still use the controlled
            # ``new`` target, whose existing idempotent path validates itself.
            continue
        kind, target_id, field = match.groups()
        if target_id == "new":
            continue
        model = CourseOutlineNode if kind == "outline" else TeachingScriptNode
        id_field = "outline_node_id" if kind == "outline" else "script_node_id"
        target = session.exec(select(model).where(
            model.course_id == course_id,
            getattr(model, id_field) == target_id,
        )).first()
        if target is None or target.locked_by is not None:
            raise HTTPException(409, "提案目标已被锁定或删除，未应用任何修改")
        if operation.before != _proposal_before_value(target, field):
            raise HTTPException(409, "提案生成后目标内容已变化，请刷新后重新生成")
    if structure_ops:
        first_target_id = structure_ops[0].target.split(":", 2)[1]
        first_target = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == course_id,
            CourseOutlineNode.outline_node_id == first_target_id,
        )).first()
        if first_target is None:
            raise HTTPException(409, "结构提案目标已被删除，未应用任何修改")
        nodes = list(session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == course_id,
            CourseOutlineNode.outline_version_id == first_target.outline_version_id,
        )).all())
        by_id = {node.outline_node_id: node for node in nodes}
        if not by_id:
            raise HTTPException(409, "当前草稿目录已不存在")
        version = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.outline_version_id == first_target.outline_version_id,
        )).first()
        if version is None or version.lifecycle_status != OutlineLifecycleStatus.DRAFT:
            raise HTTPException(409, "结构提案目标不再是草稿")

        # A course can retain published and historical script versions that
        # refer to the same logical outline node.  Structural cleanup must
        # affect only scripts in a draft version derived from this exact
        # draft outline; published/history rows are immutable records.
        draft_script_version_ids = {
            item.script_version_id
            for item in session.exec(select(TeachingScriptVersion).where(
                TeachingScriptVersion.course_id == course_id,
                TeachingScriptVersion.outline_version_id == version.outline_version_id,
                TeachingScriptVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
            )).all()
        }
        draft_scripts = [] if not draft_script_version_ids else list(session.exec(
            select(TeachingScriptNode).where(
                TeachingScriptNode.course_id == course_id,
                TeachingScriptNode.script_version_id.in_(draft_script_version_ids),
            )
        ).all())

        parent_by_id = {node.outline_node_id: node.parent_node_id for node in nodes}
        order_by_id = {node.outline_node_id: node.order_index for node in nodes}
        removals: set[str] = set()
        for op in structure_ops:
            _kind, target_id, _field = op.target.split(":", 2)
            target = by_id.get(target_id)
            if target is None or target.locked_by is not None:
                raise HTTPException(409, "结构提案目标已被锁定或删除，未应用任何修改")
            if op.before and op.before != _proposal_before_value(target, "structure"):
                raise HTTPException(409, "结构提案生成后目标位置已变化，请刷新后重新生成")
            op.evidence_refs = _filter_course_evidence_refs(session, course_id, op.evidence_refs)
            if op.operation == PatchOperation.MOVE:
                try:
                    payload = json.loads(op.after or "{}")
                except json.JSONDecodeError as exc:
                    raise HTTPException(422, "结构移动提案格式无效") from exc
                parent_id = payload.get("parent_node_id")
                parent = by_id.get(parent_id) if parent_id else None
                if parent_id and (parent is None or parent.locked_by is not None):
                    raise HTTPException(409, "不能移动到锁定或不存在的父节点")
                parent_by_id[target_id] = parent_id
                if payload.get("order_index") is not None:
                    order_by_id[target_id] = int(payload["order_index"])
            elif op.operation == PatchOperation.REORDER:
                try:
                    payload = json.loads(op.after or "{}")
                    order_by_id[target_id] = int(payload["order_index"])
                except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    raise HTTPException(422, "结构排序提案格式无效") from exc
            elif op.operation == PatchOperation.REMOVE:
                removals.add(target_id)
            else:
                raise HTTPException(422, "结构提案包含不支持的操作")

        for node_id in parent_by_id:
            seen: set[str] = set()
            cursor: str | None = node_id
            while cursor is not None:
                if cursor in seen:
                    raise HTTPException(409, "结构提案会形成父子循环，未应用任何修改")
                seen.add(cursor)
                cursor = parent_by_id.get(cursor)
        for node_id in removals:
            descendants = _proposal_outline_descendants(node_id, parent_by_id)
            if any(by_id[item].locked_by is not None for item in descendants):
                raise HTTPException(409, "不能删除含锁定后代的课程分支")
            surviving_children = {
                child_id for child_id, parent_id in parent_by_id.items()
                if parent_id == node_id and child_id not in removals
            }
            if surviving_children:
                raise HTTPException(409, "删除父节点前必须先移动其全部子节点")
            if any(
                script.outline_node_id == node_id and script.locked_by is not None
                for script in draft_scripts
            ):
                raise HTTPException(409, "不能删除关联了锁定讲解脚本的课程节点")

        # Make every old sibling position temporarily unique before applying
        # a new parent/order relation.  This avoids violating the unique
        # (outline_version_id, parent_node_id, order_index) constraint midway.
        for index, node in enumerate(nodes):
            node.order_index = 1_000_000 + index
            session.add(node)
        session.flush()

        remaining = [node for node in nodes if node.outline_node_id not in removals]
        by_parent: dict[str | None, list[CourseOutlineNode]] = {}
        for node in remaining:
            node.parent_node_id = parent_by_id[node.outline_node_id]
            by_parent.setdefault(node.parent_node_id, []).append(node)
        for siblings in by_parent.values():
            siblings.sort(key=lambda node: (order_by_id[node.outline_node_id], node.outline_node_id))
            for index, node in enumerate(siblings):
                node.order_index = index
                node.updated_at = utcnow_aware()
                session.add(node)
        for node_id in removals:
            for mapping in session.exec(select(CoursePptMapping).where(
                CoursePptMapping.course_id == course_id,
                CoursePptMapping.outline_node_id == node_id,
                CoursePptMapping.status == "draft",
            )).all():
                mapping.status = "stale"
                mapping.updated_by = user_id
                mapping.updated_at = utcnow_aware()
                session.add(mapping)
            for script in [
                item for item in draft_scripts
                if item.outline_node_id == node_id
            ]:
                if script.locked_by is not None:
                    raise HTTPException(409, "不能删除关联了锁定讲解脚本的课程节点")
                session.delete(script)
            session.delete(by_id[node_id])
        _mark_teacher_edited(version)
        session.add(version)

    for operation in simple_ops:
        _apply_operation(session, course_id, operation, user_id)


def _proposal_outline_descendants(
    node_id: str,
    parent_by_id: dict[str, str | None],
) -> set[str]:
    result: set[str] = set()
    frontier = [node_id]
    while frontier:
        parent = frontier.pop()
        children = [child_id for child_id, parent_id in parent_by_id.items() if parent_id == parent]
        for child_id in children:
            if child_id not in result:
                result.add(child_id)
                frontier.append(child_id)
    return result


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
        _apply_operations_atomically(session, course_id, list(ops), context.user_id)
        for op in ops: op.accepted = True; op.decided_at = utcnow_aware(); session.add(op)
        proposal.status = PatchProposalStatus.ACCEPTED
    else:
        for op in ops: op.accepted = False; op.decided_at = utcnow_aware(); session.add(op)
        proposal.status = PatchProposalStatus.REJECTED
    proposal.decided_by = context.user_id; proposal.decided_at = utcnow_aware(); session.add(proposal); session.commit()
    change_summary = _change_summary(
        session,
        course_id,
        list(ops),
        _proposal_change_state(proposal.status),
    )
    return unified_response(200, "提案已接受" if payload.accepted else "提案已拒绝", {
        "proposal_id": proposal_id,
        "status": proposal.status.value,
        "change_summary": change_summary,
    })


@router.get("/course/{course_id}/ppt-mapping")
async def get_ppt_mapping(course_id: int, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.view")
    outline = _draft_outline(session, course_id) or _published_outline(session, course_id)
    materials = session.exec(select(SourceMaterial).where(SourceMaterial.course_id == course_id)).all()
    has_ppt = any(m.material_type == "slide" for m in materials)
    current_ppt_versions = _current_ppt_material_versions(session, course_id)
    ppt_materials = [
        _ppt_material_view(
            session,
            course_id=course_id,
            material=material,
            version=version,
        )
        for material, version in current_ppt_versions
    ]
    material_by_version = {
        item["material_version_id"]: item
        for item in ppt_materials
    }
    ppt_manifest_available = session.exec(
        select(MediaRelease.id).where(
            MediaRelease.course_id == course_id,
            MediaRelease.ppt_manifest_object_key.is_not(None),
        ).order_by(MediaRelease.version_number.desc(), MediaRelease.id.desc())
    ).first() is not None
    nodes = list(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == outline.outline_version_id,
    )).all()) if outline else []
    ordered_nodes, displays = _outline_tree_views(nodes)
    current_node_ids = {node.outline_node_id for node in ordered_nodes}
    all_mappings = list(session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course_id,
    )).all())
    current_version_ids = set(material_by_version)
    mappings = [
        item for item in all_mappings
        if item.outline_node_id in current_node_ids
        and item.material_version_id in current_version_ids
    ]
    stale_mappings = [
        item for item in all_mappings
        if item.outline_node_id not in current_node_ids
        or item.material_version_id not in current_version_ids
    ]
    mappings_by_node: dict[str, list[CoursePptMapping]] = {}
    for mapping in mappings:
        mappings_by_node.setdefault(mapping.outline_node_id, []).append(mapping)

    def mapping_view(mapping: CoursePptMapping) -> dict[str, Any]:
        view = _ppt_mapping_view(mapping)
        material = material_by_version.get(mapping.material_version_id or "")
        if material:
            page_count = material["page_count"]
            view["material_name"] = material["name"]
            view["page_count"] = page_count
            view["out_of_bounds"] = bool(
                page_count and (
                    mapping.page_start < 1
                    or mapping.page_end > page_count
                    or any(
                        int(page) < 1 or int(page) > page_count
                        for page in (mapping.page_refs or [])
                    )
                )
            )
        return view

    node_views = []
    for node in ordered_nodes:
        view = _outline_node_view(node, displays[node.outline_node_id])
        node_mappings = sorted(
            mappings_by_node.get(node.outline_node_id, []),
            key=lambda mapping: (
                ppt_materials.index(material_by_version[mapping.material_version_id])
                if mapping.material_version_id in material_by_version else len(ppt_materials),
                mapping.id or 0,
            ),
        )
        # ``ppt_mapping`` remains as a compatibility summary for existing
        # consumers. New mapping clients must consume ``ppt_mappings`` so
        # page numbers always stay attached to their deck version.
        view["ppt_mappings"] = [mapping_view(mapping) for mapping in node_mappings]
        view["ppt_mapping"] = view["ppt_mappings"][0] if view["ppt_mappings"] else None
        node_views.append(view)
    return unified_response(200, "获取 PPT 映射状态成功", {
        "mapping_contract_version": "ppt-mapping/v2",
        "has_ppt": has_ppt,
        "content_source": "ppt_manifest" if ppt_manifest_available else "document_parse",
        "editable": bool(outline and outline.lifecycle_status == OutlineLifecycleStatus.DRAFT),
        "outline_version_id": outline.outline_version_id if outline else None,
        "ppt_materials": ppt_materials,
        "nodes": node_views,
        "mappings": [mapping_view(item) for item in mappings],
        "stale_mappings": [_ppt_mapping_view(item) for item in stale_mappings],
        "actions": {"upload_existing": True, "generate_ai": bool(nodes)},
    })


@router.get("/course/{course_id}/ppt-mapping/workspace")
async def get_ppt_mapping_workspace(
    course_id: int,
    material_version_id: str,
    page_start: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=30),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Return one material-version's small, visual mapping workbench slice.

    Page images are never copied into the response.  The browser receives a
    course-authorized content route for each persisted render asset, while OCR
    text and source block IDs remain page-scoped for the matching workflow.
    """
    require_course_permission(session, current_user, course_id, "course.mapping.edit")
    versions = {
        version.version_id: (material, version)
        for material, version in _current_ppt_material_versions(session, course_id)
    }
    if material_version_id not in versions:
        raise HTTPException(
            422,
            detail={
                "error_code": "PPT_MATERIAL_VERSION_INVALID",
                "message": "The selected PPT file is not a current editable material version for this course.",
            },
        )

    blocks = list(session.exec(select(DocumentBlock).where(
        DocumentBlock.course_id == course_id,
        DocumentBlock.material_version_id == material_version_id,
    ).order_by(DocumentBlock.page_or_slide, DocumentBlock.order_index)).all())
    blocks_by_page: dict[int, list[DocumentBlock]] = {}
    run_ids_by_page: dict[int, set[str]] = {}
    for block in blocks:
        page = int(block.page_or_slide or block.page_number or 0)
        if page < 1:
            continue
        blocks_by_page.setdefault(page, []).append(block)
        if block.run_id:
            run_ids_by_page.setdefault(page, set()).add(block.run_id)

    # OCR can be delayed or fail independently of a perfectly usable PPTX.
    # Always let the original source render establish a page window, rather
    # than hiding the visual mapper because ``DocumentBlock`` rows do not yet
    # exist.  Existing original-slide assets provide the best known extent;
    # an exactly-full final batch makes one additional lightweight request to
    # confirm the end of a deck whose OCR is not available.
    ocr_page_count = max(blocks_by_page, default=0)
    persisted_source_pages = list(session.exec(select(EvidenceRenderAsset.page_number).where(
        EvidenceRenderAsset.course_id == course_id,
        EvidenceRenderAsset.asset_type == RenderAssetType.PPT_SLIDE_IMAGE,
        EvidenceRenderAsset.object_key.like(f"ppt-slide-render/course{course_id}/{material_version_id}/%"),
    )).all())
    known_source_page_count = max((int(page or 0) for page in persisted_source_pages), default=0)
    known_page_count = max(ocr_page_count, known_source_page_count)
    page_end = page_start + page_size - 1
    requested_pages = list(range(page_start, page_end + 1))
    # Mapping previews deliberately use only native renders of the uploaded
    # deck. Generic evidence renders can be OCR reconstructions and must not
    # become the teacher-visible or learner-visible courseware image.
    assets_by_page: dict[int, EvidenceRenderAsset] = {}
    render_warning = ""
    if requested_pages:
        try:
            from app.services.ppt_slide_render_service import ensure_ppt_source_slide_renders

            assets_by_page = ensure_ppt_source_slide_renders(
                session,
                course_id=course_id,
                material_version_id=material_version_id,
                page_numbers=requested_pages,
                run_id=next(iter(run_ids_by_page.get(requested_pages[0], set())), None),
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            render_warning = f"Original PPT slide render unavailable: {type(exc).__name__}"

    visible_page_numbers = [
        page for page in requested_pages
        if page in assets_by_page or page in blocks_by_page
    ]
    pages = []
    for page in visible_page_numbers:
        page_blocks = blocks_by_page.get(page, [])
        asset = assets_by_page.get(page)
        text = "\n".join(
            (block.text or "").strip()
            for block in page_blocks
            if (block.text or "").strip()
        )
        pages.append({
            "page": page,
            "image_url": (
                f"/api/v1/course-editor/course/{course_id}/ppt-mapping/renders/{asset.asset_id}/content"
                if asset else None
            ),
            "width": asset.width if asset else 0,
            "height": asset.height if asset else 0,
            "image_source": "teacher_original_ppt" if asset else None,
            "ocr_preview": text[:1000],
            "ocr_available": bool(text),
            "source_block_refs": [block.block_id for block in page_blocks if block.block_id],
        })

    material, version = versions[material_version_id]
    return unified_response(200, "获取 PPT 映射工作区成功", {
        "workspace_contract_version": "ppt-mapping-workspace/v1",
        "material": _ppt_material_view(
            session,
            course_id=course_id,
            material=material,
            version=version,
        ),
        "page_count": max(known_page_count, max(assets_by_page, default=0)),
        "page_start": page_start,
        "page_size": page_size,
        "next_page_start": (
            page_end + 1
            if len(assets_by_page) == page_size or page_end < known_page_count
            else None
        ),
        "pages": pages,
        "rendered_page_count": len(assets_by_page),
        "render_source": "teacher_original_ppt",
        "render_warning": render_warning or None,
        "message": (
            "部分 PPT 页图仍在解析中；OCR 文本可先用于智能匹配。"
            if requested_pages and len(assets_by_page) < len(requested_pages)
            else "PPT 页图与 OCR 已就绪。"
        ),
    })


@router.get("/course/{course_id}/ppt-mapping/renders/{asset_id}/content")
async def get_ppt_mapping_render_content(
    course_id: int,
    asset_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Serve one page rendition after the mapping permission check."""
    context = require_course_permission(session, current_user, course_id, "course.mapping.edit")
    asset = session.exec(select(EvidenceRenderAsset).where(
        EvidenceRenderAsset.asset_id == asset_id,
        EvidenceRenderAsset.course_id == course_id,
    )).first()
    if asset is None or not asset.object_key:
        raise HTTPException(404, "PPT 页图不存在或尚未生成")
    try:
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
            scope={"course_id": course_id, "user_id": context.user_id, "purpose": "ppt_mapping"},
        ), status_code=307)
    except FileNotFoundError as error:
        raise HTTPException(404, "PPT 页图文件不存在") from error


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
    current_ppt_versions = _current_ppt_material_versions(session, course_id)
    if not current_ppt_versions:
        raise HTTPException(409, "No editable PPT material version exists for this course")
    versions_by_id = {
        item_version.version_id: (item_material, item_version)
        for item_material, item_version in current_ppt_versions
    }
    target_version_id = payload.material_version_id
    if target_version_id is None:
        if len(versions_by_id) != 1:
            raise HTTPException(
                422,
                detail={
                    "error_code": "PPT_MATERIAL_VERSION_REQUIRED",
                    "message": "This course has multiple PPT files; choose the PPT file before saving page numbers.",
                    "material_version_ids": list(versions_by_id),
                },
            )
        target_version_id = next(iter(versions_by_id))
    if target_version_id not in versions_by_id:
        raise HTTPException(
            422,
            detail={
                "error_code": "PPT_MATERIAL_VERSION_INVALID",
                "message": "The selected PPT file is not a current editable material version for this course.",
            },
        )
    mapping = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course_id,
        CoursePptMapping.outline_node_id == outline_node_id,
        CoursePptMapping.material_version_id == target_version_id,
        CoursePptMapping.status == "draft",
    )).first()
    if not mapping:
        mapping = CoursePptMapping(
            course_id=course_id,
            outline_node_id=outline_node_id,
            material_version_id=target_version_id,
            created_by=context.user_id,
        )
    if payload.page_range is not None or payload.page_refs is not None:
        page_refs = _normalise_mapping_page_refs(
            page_range=payload.page_range,
            page_refs=payload.page_refs,
        )
        page_refs = _validate_mapping_pages(
            session,
            course_id=course_id,
            material_version_id=target_version_id,
            page_refs=page_refs,
        )
        mapping.page_start = page_refs[0]
        mapping.page_end = page_refs[-1]
        mapping.page_refs = page_refs
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
    view["ppt_mappings"] = [view["ppt_mapping"]]
    return unified_response(200, "PPT 映射已保存", view)


@router.put("/course/{course_id}/ppt-mapping")
async def save_ppt_mappings(
    course_id: int,
    payload: PptMappingBulkUpdate,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Atomically save the teacher's visible mapping edits from one workbench pass."""
    context = require_course_permission(session, current_user, course_id, "course.mapping.edit")
    outline = _draft_outline(session, course_id)
    if outline is None or outline.lifecycle_status != OutlineLifecycleStatus.DRAFT:
        raise HTTPException(409, "已发布课程结构不可直接编辑")
    items_by_key: dict[tuple[str, str], PptMappingBulkItem] = {}
    for item in payload.mappings:
        key = (item.outline_node_id, item.material_version_id)
        if key in items_by_key:
            raise HTTPException(400, "同一知识点与 PPT 文件只能保存一条映射")
        items_by_key[key] = item

    current_versions = {
        version.version_id
        for _material, version in _current_ppt_material_versions(session, course_id)
    }
    invalid_versions = sorted({
        item.material_version_id
        for item in payload.mappings
        if item.material_version_id not in current_versions
    })
    if invalid_versions:
        raise HTTPException(
            422,
            detail={
                "error_code": "PPT_MATERIAL_VERSION_INVALID",
                "message": "The selected PPT file is not a current editable material version for this course.",
                "material_version_ids": invalid_versions,
            },
        )
    nodes = list(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
        CourseOutlineNode.outline_version_id == outline.outline_version_id,
        CourseOutlineNode.outline_node_id.in_([item.outline_node_id for item in payload.mappings]),
    )).all())
    nodes_by_id = {node.outline_node_id: node for node in nodes}
    missing_nodes = sorted({
        item.outline_node_id
        for item in payload.mappings
        if item.outline_node_id not in nodes_by_id
    })
    if missing_nodes:
        raise HTTPException(404, detail={"message": "课程结构节点不存在", "outline_node_ids": missing_nodes})
    protected_nodes = sorted(
        node.outline_node_id
        for node in nodes
        if node.locked_by is not None and node.locked_by != context.user_id
    )
    if protected_nodes:
        raise HTTPException(409, detail={"message": "部分节点已被其他教师锁定", "outline_node_ids": protected_nodes})

    existing = list(session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course_id,
        CoursePptMapping.status == "draft",
    )).all())
    existing_by_key = {
        (mapping.outline_node_id, mapping.material_version_id): mapping
        for mapping in existing
    }
    normalized_pages = {
        key: _validate_mapping_pages(
            session,
            course_id=course_id,
            material_version_id=item.material_version_id,
            page_refs=item.page_refs,
        )
        for key, item in items_by_key.items()
    }

    saved: list[CoursePptMapping] = []
    for key, item in items_by_key.items():
        page_refs = normalized_pages[key]
        mapping = existing_by_key.get(key)
        if mapping is None:
            mapping = CoursePptMapping(
                course_id=course_id,
                outline_node_id=item.outline_node_id,
                material_version_id=item.material_version_id,
                created_by=context.user_id,
                status="draft",
            )
        mapping.page_refs = page_refs
        mapping.page_start = page_refs[0]
        mapping.page_end = page_refs[-1]
        if item.confidence is not None:
            mapping.confidence = item.confidence
        mapping.teacher_locked = item.locked
        mapping.updated_by = context.user_id
        mapping.updated_at = utcnow_aware()
        session.add(mapping)
        saved.append(mapping)

    _mark_teacher_edited(outline)
    session.add(outline)
    session.commit()
    for mapping in saved:
        session.refresh(mapping)
    return unified_response(200, "PPT 映射已保存", {
        "mapping_contract_version": "ppt-mapping/v2",
        "saved_count": len(saved),
        "mappings": [_ppt_mapping_view(mapping) for mapping in saved],
    })


async def _run_ppt_mapping_agent(
    *,
    request: Request,
    course_id: int,
    teacher_id: int,
    material_version_ids: list[str],
    outline_node_ids: list[str] | None = None,
    page_refs_by_material: dict[str, list[int]] | None = None,
    seed_from_evidence: bool = True,
) -> dict[str, Any]:
    """Start the registered Prep pipeline with an intentionally small scope."""
    platform = getattr(request.app.state, "agent_platform", None)
    gateway = getattr(platform, "gateway", None) if platform is not None else None
    if gateway is None:
        raise HTTPException(
            503,
            detail={
                "error_code": "PREP_AGENT_UNAVAILABLE",
                "message": "助教智能体运行时未就绪，无法优化 PPT 映射",
            },
        )
    from app.platform.agents.prep.enums import PrepGraphKind
    from app.platform.agents.runtime.base import AgentRunContext
    from app.platform.agents.runtime.profile import AgentType
    from app.platform.agents.runtime.registry import AgentDefinitionKey

    extras: dict[str, Any] = {"material_version_ids": material_version_ids}
    if outline_node_ids:
        extras["outline_node_ids"] = outline_node_ids
    if page_refs_by_material:
        extras["page_refs_by_material"] = page_refs_by_material
    if not seed_from_evidence:
        extras["seed_from_evidence"] = False
    start = await gateway.start(
        agent_type=AgentType.PREP,
        definition_key=AgentDefinitionKey(
            agent_type=AgentType.PREP.value,
            agent_version=PrepGraphKind.PPT_MAPPING.value,
        ),
        context=AgentRunContext(
            agent_type=AgentType.PREP.value,
            scope=(str(course_id),),
            teacher_id=str(teacher_id),
            course_id=str(course_id),
            extras=extras,
        ),
    )
    if start.status != "completed" or not start.result:
        raise HTTPException(
            502,
            detail={
                "error_code": start.error_code or "PPT_MAPPING_FAILED",
                "message": start.error_message or "PPT 映射优化未完成",
            },
        )
    return dict(start.result.get("result") or {})


@router.post("/course/{course_id}/ppt-mapping/optimize")
async def optimize_ppt_mapping(
    course_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """一键优化 PPT 映射：通过 OCR 文本与知识点语义匹配自动调整映射。

    调用 ``ppt_mapping_optimization_service.optimize_mappings()``，加载
    PPT 每页 OCR 文本 + 最新草稿知识点节点 + 讲稿内容 + 父级标题，
    由 LLM 生成映射建议并直接更新 ``CoursePptMapping`` 行
    （teacher_locked=True 的映射不会被修改）。
    """
    context = require_course_permission(session, current_user, course_id, "course.mapping.edit")
    # Each deck has its own slide number space. Resolve all current versions
    # before the Prep runtime starts, rather than letting the newest upload
    # define the mapping scope.
    slide_materials = list(session.exec(select(SourceMaterial).where(
        SourceMaterial.course_id == course_id,
        SourceMaterial.material_type == "slide",
    )).all())
    current_ppt_versions = _current_ppt_material_versions(session, course_id)
    unresolved = []
    for material in slide_materials:
        version_id = material.current_version_id
        version_exists = bool(version_id and session.exec(select(SourceMaterialVersion).where(
            SourceMaterialVersion.course_id == course_id,
            SourceMaterialVersion.material_id == material.material_id,
            SourceMaterialVersion.version_id == version_id,
        )).first())
        if not version_exists:
            unresolved.append(material.name or material.material_id)
    if unresolved:
        raise HTTPException(
            409,
            detail={
                "error_code": "PPT_MATERIAL_VERSION_MISSING",
                "message": "One or more PPT files have no current material version.",
                "materials": unresolved,
            },
        )
    if not current_ppt_versions:
        raise HTTPException(409, "课程尚未上传 PPT 材料，无法优化映射")
    material_version_ids = [version.version_id for _material, version in current_ppt_versions]

    batch_lock = await _try_acquire_prep_batch_lock(course_id)
    if batch_lock is None:
        raise _prep_agent_busy_error()
    # Commit the request-scoped read transaction before the Prep agent opens
    # its own writer session.  SQLite (even in WAL mode) blocks a writer while
    # any read transaction is open on another connection, which previously
    # surfaced as ``database is locked`` during ``UPDATE course_ppt_mappings``.
    session.commit()
    try:
        summary = await _run_ppt_mapping_agent(
            request=request,
            course_id=course_id,
            teacher_id=context.user_id,
            material_version_ids=material_version_ids,
        )
    finally:
        batch_lock.release()

    updated_count = int(summary.get("updated_count") or 0)
    suggestions = list(summary.get("suggestions") or [])
    # A completed runtime only means the workflow returned a result.  It does
    # not mean that any mapping row was actually changed.  Reporting this as a
    # successful optimisation misleads teachers and hides empty/locked model
    # output behind a green assistant bubble.
    if updated_count == 0:
        if suggestions:
            message = "PPT 映射未修改：模型建议均对应教师锁定的映射，系统已保留原页码。"
            reason = "ALL_SUGGESTIONS_LOCKED"
        else:
            message = (
                "未找到可信候选页，可直接在页图中选择，或对当前知识点重新匹配。"
            )
            reason = "NO_RELIABLE_MATCH"
        return unified_response(200, message, {
            "outcome": "no_change",
            "reason": reason,
            "total_mappings": summary.get("total_mappings", 0),
            "updated_count": 0,
            "suggestions": suggestions,
            "material_version_ids": list(summary.get("material_version_ids") or material_version_ids),
            "manual_next_steps": ["select_pages", "match_current_node"],
        })

    return unified_response(200, "PPT 映射优化完成", {
        "outcome": "updated",
        "total_mappings": summary.get("total_mappings", 0),
        "updated_count": updated_count,
        "suggestions": suggestions,
        "material_version_ids": list(summary.get("material_version_ids") or material_version_ids),
    })


@router.post("/course/{course_id}/ppt-mapping/match")
async def match_ppt_mapping_scope(
    course_id: int,
    payload: PptMappingMatchRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Run one of the workbench's three direct-apply matching actions."""
    context = require_course_permission(session, current_user, course_id, "course.mapping.edit")
    current_versions = {
        version.version_id
        for _material, version in _current_ppt_material_versions(session, course_id)
    }
    if not current_versions:
        raise HTTPException(409, "课程尚未上传可用 PPT 材料，无法匹配")
    if payload.material_version_id and payload.material_version_id not in current_versions:
        raise HTTPException(
            422,
            detail={
                "error_code": "PPT_MATERIAL_VERSION_INVALID",
                "message": "The selected PPT file is not a current editable material version for this course.",
            },
        )

    material_version_ids = (
        [payload.material_version_id]
        if payload.material_version_id else sorted(current_versions)
    )
    outline_node_ids: list[str] | None = None
    page_refs_by_material: dict[str, list[int]] | None = None
    seed_from_evidence = payload.mode == "all_unlocked"

    if payload.mode == "node":
        if not payload.outline_node_id:
            raise HTTPException(422, "请选择要重新匹配的知识点")
        node = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == course_id,
            CourseOutlineNode.outline_node_id == payload.outline_node_id,
            CourseOutlineNode.node_type == OutlineNodeType.KNOWLEDGE_POINT,
        )).first()
        if node is None:
            raise HTTPException(404, "知识点不存在或不可用于 PPT 映射")
        outline_node_ids = [node.outline_node_id]
    elif payload.mode == "selected_pages":
        if not payload.material_version_id:
            raise HTTPException(422, "请先选择 PPT 文件")
        if not payload.page_refs:
            raise HTTPException(422, "请先选择至少一页 PPT")
        page_refs_by_material = {
            payload.material_version_id: _validate_mapping_pages(
                session,
                course_id=course_id,
                material_version_id=payload.material_version_id,
                page_refs=payload.page_refs,
            ),
        }

    batch_lock = await _try_acquire_prep_batch_lock(course_id)
    if batch_lock is None:
        raise _prep_agent_busy_error()
    # Commit the request-scoped read transaction before the Prep agent opens
    # its own writer session.  See ``optimize_ppt_mapping`` for the rationale:
    # SQLite otherwise blocks the writer behind the open read transaction and
    # raises ``database is locked``.
    session.commit()
    try:
        summary = await _run_ppt_mapping_agent(
            request=request,
            course_id=course_id,
            teacher_id=context.user_id,
            material_version_ids=material_version_ids,
            outline_node_ids=outline_node_ids,
            page_refs_by_material=page_refs_by_material,
            seed_from_evidence=seed_from_evidence,
        )
    finally:
        batch_lock.release()

    updated_count = int(summary.get("updated_count") or 0)
    suggestions = list(summary.get("suggestions") or [])
    if updated_count == 0:
        return unified_response(200, "未找到可信候选页，可直接在页图中选择，或调整范围后重新匹配。", {
            "outcome": "no_reliable_match",
            "mode": payload.mode,
            "updated_count": 0,
            "suggestions": suggestions,
            "material_version_ids": material_version_ids,
            "manual_next_steps": ["select_pages", "match_current_node"],
        })
    return unified_response(200, "PPT 映射匹配完成并已写入草稿", {
        "outcome": "updated",
        "mode": payload.mode,
        "updated_count": updated_count,
        "suggestions": suggestions,
        "material_version_ids": material_version_ids,
    })


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
            "pipeline": ParsePipeline.FULL.value,
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
        document_parse_queue.submit(session_factory, local_task_worker, task_view.task_id)
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
            if total > 100 * 1024 * 1024: raise HTTPException(413, "PPT 文件超过 100MB")
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
            "pipeline": ParsePipeline.FULL.value,
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
        document_parse_queue.submit(session_factory, local_task_worker, task_view.task_id)
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
    teacher_confirmed_at = gate.teacher_confirmation_at or gate.warning_override_at
    if gate.blocker_count or not gate.passed or (
        gate.error_count + gate.warning_count > 0 and not teacher_confirmed_at
    ):
        raise HTTPException(status_code=409, detail={"error_code": "QUALITY_GATE_FAILED", "message": "发布前检查仍有未确认的问题", "details": {"gate_run_id": gate.gate_run_id, "error_count": gate.error_count, "blocker_count": gate.blocker_count, "warning_count": gate.warning_count, "requires_teacher_confirmation": gate.error_count + gate.warning_count > 0 and not teacher_confirmed_at, "has_blockers": bool(gate.blocker_count)}})
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
    outline.lifecycle_status = OutlineLifecycleStatus.PUBLISHED
    scripts.lifecycle_status = OutlineLifecycleStatus.PUBLISHED
    course.status = CourseStatus.PUBLISHED
    course.updated_at = utcnow_aware()
    session.add(outline)
    session.add(scripts)
    session.add(course)

    # A release snapshot must never be edited in place.  Seed the next
    # editable draft before the transaction is committed so that the editor
    # immediately reads the new working copy after publication.
    next_draft = _ensure_draft_outline(session, course_id, context.user_id)
    next_draft_script = session.exec(
        select(TeachingScriptVersion)
        .where(
            TeachingScriptVersion.course_id == course_id,
            TeachingScriptVersion.outline_version_id == next_draft.outline_version_id,
        )
        .order_by(TeachingScriptVersion.version.desc())
    ).first()
    session.commit()
    return unified_response(200, "课程已发布", {
        "course_id": course_id,
        "release_id": release.release_id,
        "status": course.status.value,
        "draft": {
            "outline_version_id": next_draft.outline_version_id,
            "script_version_id": next_draft_script.script_version_id if next_draft_script else None,
            "editable": True,
        },
    })


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
