"""Step 4 - 草稿资产构建器。

解析产出 DocumentBlock + EvidenceSpan 候选后，并行生成草稿资产：
- RagIndexBuilder：课程隔离 RAG 索引（草稿），索引项带 course_id/material_version_id/evidence_refs。
- GraphDraftBuilder：知识图谱候选节点/关系/说明（草稿，不直接发布）。
- TeachingStructureBuilder：DocumentBlock + GraphDraft -> CourseOutlineVersion/Node 草稿。
- TeachingScriptBuilder：草稿目录 + Evidence -> TeachingScriptNode 草稿。
- MarkdownBuilder：带 source_block_refs 的 Markdown。
- CourseResourceWriter：把 Markdown 写为 ResourceItem/ResourceVersion（lifecycle_status=draft）。

关键约束：
- RAG/图谱/目录/讲稿可并行；但目录与讲稿的发布状态必须一致（都 draft 或都 published）。
- 学生只读已发布版本；草稿仅建设角色可读（ResourceVersion.lifecycle_status=draft, visibility=teachers）。
- Markdown 不塞进任务 JSON，写为 ResourceItem/ResourceVersion，带 source_block_refs。

见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §8 Step 4。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlmodel import Session, select

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
from app.models.document_parse_model import DocumentBlock, EvidenceSpan
from app.models.graph_production_model import GraphNodeReview
from app.models.resource_model import (
    ResourceItem,
    ResourceLifecycleStatus,
    ResourceScope,
    ResourceVisibility,
    ResourceItemType,
    ResourceVersion,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 子阶段结果
# ---------------------------------------------------------------------------


@dataclass
class DraftAssetResult:
    """一次解析的草稿资产汇总，供 TaskRecord 产物引用。"""
    course_id: int
    run_id: str
    material_version_id: Optional[str]
    outline_version_id: Optional[str] = None
    script_version_id: Optional[str] = None
    rag_indexed_chunks: int = 0
    graph_node_candidates: int = 0
    graph_relation_candidates: int = 0
    graph_review_candidate_count: int = 0
    outline_node_count: int = 0
    script_node_count: int = 0
    markdown_resource_id: Optional[str] = None
    markdown_resource_version_id: Optional[str] = None
    patch_proposal_id: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def to_progress_data(self) -> dict[str, Any]:
        return {
            "outline_version_id": self.outline_version_id,
            "script_version_id": self.script_version_id,
            "rag_indexed_chunks": self.rag_indexed_chunks,
            "graph_node_candidates": self.graph_node_candidates,
            "graph_review_candidate_count": self.graph_review_candidate_count,
            "outline_node_count": self.outline_node_count,
            "script_node_count": self.script_node_count,
            "markdown_resource_id": self.markdown_resource_id,
            "markdown_resource_version_id": self.markdown_resource_version_id,
            "patch_proposal_id": self.patch_proposal_id,
        }


# ---------------------------------------------------------------------------
# RagIndexBuilder（草稿）
# ---------------------------------------------------------------------------


def build_rag_index_draft(
    session: Session,
    *,
    course_id: int,
    run_id: str,
    material_version_id: Optional[str],
    blocks: list[DocumentBlock],
) -> int:
    """构建课程隔离 RAG 草稿索引，返回索引块数。

    Demo 阶段使用进程内关键词占位索引，不调用真实向量模型。
    每个非空文本块作为一个草稿索引项，带 course_id/material_version_id/evidence_refs；
    学生 RAG 在发布后构建（Step 8），备课 Agent 可查草稿索引。真实向量索引（G5B canary）后置。
    """
    count = 0
    for blk in blocks:
        text = (blk.text or "").strip()
        if len(text) < 5:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# GraphDraftBuilder（草稿候选）
# ---------------------------------------------------------------------------


def build_graph_draft(
    session: Session,
    *,
    course_id: int,
    run_id: str,
    blocks: list[DocumentBlock],
) -> tuple[int, int]:
    """生成知识图谱候选节点/关系（草稿，不直接发布）。

    复用现有 GraphCandidateBatch 规则占位：每 block 一个节点候选，相邻一条关系候选。
    真实图谱构建（LLM 抽取）后置；本阶段保证候选可追溯、不入正式发布。
    """
    node_count = len(blocks)
    relation_count = max(0, len(blocks) - 1)
    return node_count, relation_count


def build_graph_review_candidates(
    session: Session,
    *,
    course_id: int,
    run_id: str,
    blocks: list[DocumentBlock],
) -> int:
    """Persist deterministic, teacher-reviewable graph candidates.

    The parser does not claim that adjacent text blocks are true educational
    relations.  It records them as ``proposed`` review rows with stable source
    and Evidence references.  A later graph/LLM strategy may replace these
    candidates, but it must create a new policy version rather than silently
    changing this baseline.
    """
    evidence_by_block = {
        span.block_id: span.span_id
        for span in session.exec(
            select(EvidenceSpan).where(
                EvidenceSpan.course_id == course_id,
                EvidenceSpan.run_id == run_id,
            )
        ).all()
    }
    created = 0
    previous_target: str | None = None
    previous_evidence: str | None = None
    for block in blocks:
        text = (block.text or "").strip()
        if not text:
            continue
        target_id = f"candidate:{run_id}:{block.block_id}"
        if not session.exec(select(GraphNodeReview).where(
            GraphNodeReview.course_id == course_id,
            GraphNodeReview.target_id == target_id,
        )).first():
            session.add(GraphNodeReview(
                course_id=course_id,
                target_id=target_id,
                target_type="node",
                target_content_hash=block.content_hash,
                decision="proposed",
                evidence_ids=[evidence_by_block[block.block_id]] if block.block_id in evidence_by_block else [],
            ))
            created += 1
        current_evidence = evidence_by_block.get(block.block_id)
        if previous_target and current_evidence:
            relation_target = f"relation:{run_id}:{previous_target}:{target_id}"
            if not session.exec(select(GraphNodeReview).where(
                GraphNodeReview.course_id == course_id,
                GraphNodeReview.target_id == relation_target,
            )).first():
                evidence_ids = [x for x in (previous_evidence, current_evidence) if x]
                session.add(GraphNodeReview(
                    course_id=course_id,
                    target_id=relation_target,
                    target_type="relation",
                    target_content_hash=block.content_hash,
                    decision="proposed",
                    evidence_ids=evidence_ids,
                ))
                created += 1
        previous_target = target_id
        previous_evidence = current_evidence
    session.flush()
    return created


def build_patch_proposal_draft(
    session: Session,
    *,
    course_id: int,
    run_id: str,
    outline_version_id: str,
    script_version_id: Optional[str],
    blocks: list[DocumentBlock],
    created_by: Optional[int],
) -> Optional[str]:
    """Create a reviewable proposal for deterministic title cleanup.

    This is deliberately not an LLM result.  It only proposes the first
    non-empty source line as a shorter title when that differs from the raw
    parser title.  The teacher must accept it before any draft node changes.
    """
    existing = session.exec(select(PatchProposal).where(
        PatchProposal.course_id == course_id,
        PatchProposal.tool_name == "document_parse_baseline",
        PatchProposal.reason == f"generated_from_parse_run:{run_id}",
    )).first()
    if existing:
        return existing.proposal_id

    outline_nodes = list(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
        CourseOutlineNode.outline_version_id == outline_version_id,
    ).order_by(CourseOutlineNode.order_index)).all())
    blocks_by_id = {block.block_id: block for block in blocks}
    operations: list[PatchProposalOperation] = []
    for node in outline_nodes:
        refs = node.source_block_refs or []
        source = next((blocks_by_id[ref] for ref in refs if ref in blocks_by_id), None)
        if source is None:
            continue
        source_line = next((line.strip() for line in (source.text or "").splitlines() if line.strip()), "")
        candidate_title = source_line[:80]
        if not candidate_title or candidate_title == node.title:
            continue
        span = session.exec(select(EvidenceSpan).where(
            EvidenceSpan.course_id == course_id,
            EvidenceSpan.run_id == run_id,
            EvidenceSpan.block_id == source.block_id,
        )).first()
        operations.append(PatchProposalOperation(
            course_id=course_id,
            operation=PatchOperation.REPLACE,
            target=f"outline:{node.outline_node_id}:title",
            before=node.title,
            after=candidate_title,
            reason="按源材料首行收敛知识点标题；仅作为教师审核候选",
            evidence_refs=[span.span_id] if span else [],
            policy_version="document-draft-baseline/1.0",
        ))
    if not operations:
        return None
    proposal = PatchProposal(
        course_id=course_id,
        tool_name="document_parse_baseline",
        policy_version="document-draft-baseline/1.0",
        status=PatchProposalStatus.PENDING,
        reason=f"generated_from_parse_run:{run_id}",
        created_by=created_by,
    )
    session.add(proposal)
    session.flush()
    for operation in operations:
        operation.proposal_id = proposal.proposal_id
        session.add(operation)
    session.flush()
    return proposal.proposal_id


# ---------------------------------------------------------------------------
# TeachingStructureBuilder（课程目录草稿）
# ---------------------------------------------------------------------------


def build_outline_draft(
    session: Session,
    *,
    course_id: int,
    run_id: str,
    material_version_id: Optional[str],
    blocks: list[DocumentBlock],
    created_by: Optional[int],
) -> tuple[str, int]:
    """从 DocumentBlock 生成课程目录草稿（CourseOutlineVersion + Node）。

    Demo 策略：按 block 顺序生成 knowledge_point 节点（扁平）；真实层级划分
    （chapter/section/knowledge_point）由 Step 5 教师编辑或后续 LLM 优化。
    返回 (outline_version_id, node_count)。
    """
    version = CourseOutlineVersion(
        course_id=course_id, version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        source_parse_run_id=run_id, created_by=created_by,
    )
    session.add(version)
    session.flush()
    order = 0
    for blk in blocks:
        title = (blk.text or "").strip()[:80] or f"知识点 {order + 1}"
        node = CourseOutlineNode(
            outline_version_id=version.outline_version_id,
            course_id=course_id,
            node_type=OutlineNodeType.KNOWLEDGE_POINT,
            title=title,
            order_index=order,
            source_block_refs=[blk.block_id],
            page_range=str(blk.page_or_slide or blk.page_number),
            confidence=blk.confidence,
            content_hash=blk.content_hash,
        )
        session.add(node)
        order += 1
    session.flush()
    return version.outline_version_id, order


# ---------------------------------------------------------------------------
# TeachingScriptBuilder（讲稿草稿，按目录组织）
# ---------------------------------------------------------------------------


def build_teaching_script_draft(
    session: Session,
    *,
    course_id: int,
    run_id: str,
    outline_version_id: str,
    outline_node_ids: list[str],
    blocks_by_node: dict[str, list[DocumentBlock]],
    created_by: Optional[int],
) -> tuple[str, int]:
    """根据草稿目录 + Evidence 生成讲稿草稿（TeachingScriptNode）。

    与目录版本对齐（同一 outline_version_id），保证目录与讲稿发布状态一致。
    返回 (script_version_id, node_count)。
    """
    script_version = TeachingScriptVersion(
        course_id=course_id, outline_version_id=outline_version_id, version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        source_parse_run_id=run_id, created_by=created_by,
    )
    session.add(script_version)
    session.flush()
    count = 0
    for node_id in outline_node_ids:
        node_blocks = blocks_by_node.get(node_id, [])
        content = "\n\n".join((b.text or "").strip() for b in node_blocks if (b.text or "").strip())
        if not content:
            content = "（待补充讲稿）"
        tsn = TeachingScriptNode(
            script_version_id=script_version.script_version_id,
            course_id=course_id,
            outline_node_id=node_id,
            content=content,
            source_block_refs=[b.block_id for b in node_blocks],
            content_hash="",
        )
        session.add(tsn)
        count += 1
    session.flush()
    return script_version.script_version_id, count


# ---------------------------------------------------------------------------
# MarkdownBuilder + CourseResourceWriter
# ---------------------------------------------------------------------------


def build_markdown_resource_draft(
    session: Session,
    *,
    course_id: int,
    run_id: str,
    material_version_id: Optional[str],
    blocks: list[DocumentBlock],
    created_by: Optional[int],
) -> tuple[str, str]:
    """生成解析版 Markdown，写为 ResourceItem + ResourceVersion（draft, teachers）。

    Markdown 段落保留 source_block_refs（记录在 ResourceVersion.source_block_refs）。
    草稿仅建设角色可读；发布版对有效课程成员开放（Step 8 发布时改 lifecycle_status）。
    返回 (resource_id, version_id)。
    """
    # 构建 Markdown 文本（按页/块顺序）
    lines: list[str] = [f"# 课程解析 Markdown（草稿，run {run_id}）\n"]
    block_refs: list[str] = []
    current_page = None
    for blk in blocks:
        page = blk.page_or_slide or blk.page_number
        if page != current_page:
            lines.append(f"\n## 第 {page} 页\n")
            current_page = page
        text = (blk.text or "").strip()
        if text:
            lines.append(f"{text}\n")
            block_refs.append(blk.block_id)
    markdown_text = "\n".join(lines)
    import hashlib
    content_hash = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()

    # ResourceItem（scope=course, lifecycle=draft, visibility=teachers）
    item = ResourceItem(
        owner_user_id=created_by or 0,
        course_id=course_id,
        scope=ResourceScope.COURSE,
        name=f"解析 Markdown（草稿 run {run_id}）",
        resource_type=ResourceItemType.DOCUMENT,
        mime_type="text/markdown",
        file_size=len(markdown_text.encode("utf-8")),
        lifecycle_status=ResourceLifecycleStatus.DRAFT,
        visibility=ResourceVisibility.TEACHERS,
    )
    session.add(item)
    session.flush()

    # ResourceVersion：object_key 指向对象存储（Demo 写入本地存储）
    from app.services.object_storage import get_object_storage
    object_key = f"course-md/course{course_id}/{item.resource_id}/v1.md"
    try:
        import io
        get_object_storage().put(
            object_key, io.BytesIO(markdown_text.encode("utf-8")),
            mime_type="text/markdown",
        )
    except Exception:
        logger.exception("Markdown resource write failed; object_key=%s", object_key)

    version = ResourceVersion(
        resource_id=item.resource_id,
        owner_user_id=created_by or 0,
        course_id=course_id,
        version_number=1,
        label="draft",
        object_key=object_key,
        content_hash=content_hash,
        file_size=len(markdown_text.encode("utf-8")),
        mime_type="text/markdown",
        is_active=True,
        uploaded_by=created_by or 0,
        material_version_id=material_version_id,
        parse_run_id=run_id,
        source_block_refs=block_refs,
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.version_id
    session.add(item)
    session.flush()
    return item.resource_id, version.version_id


# ---------------------------------------------------------------------------
# 总入口：build_draft_assets（可观测子阶段）
# ---------------------------------------------------------------------------


def build_draft_assets(
    session: Session,
    *,
    course_id: int,
    run_id: str,
    material_version_id: Optional[str],
    created_by: Optional[int],
    progress_cb=None,
) -> DraftAssetResult:
    """解析后生成全部草稿资产，逐子阶段回调进度。

    ``progress_cb(stage_name)`` 可选，由 handler 调 task_service.mark_progress
    记录到 TaskRecord，使前端看到分阶段进度而非模糊进度条。

    顺序：rag_index_draft -> graph_draft -> outline_draft -> teaching_script_draft
    -> markdown_resource_draft。outline 与 script 同一 outline_version_id，
    保证发布状态一致。
    """
    result = DraftAssetResult(
        course_id=course_id, run_id=run_id, material_version_id=material_version_id,
    )
    blocks = session.exec(
        select(DocumentBlock).where(
            DocumentBlock.run_id == run_id,
            DocumentBlock.course_id == course_id,
        ).order_by(DocumentBlock.order_index)
    ).all()
    if not blocks:
        result.warnings.append("no DocumentBlock found; skipping draft asset build")
        return result

    def _stage(name: str) -> None:
        if progress_cb is not None:
            try:
                progress_cb(name)
            except Exception:
                logger.exception("progress_cb failed for stage %s", name)

    # 1. RAG 草稿索引
    _stage("rag_index_draft")
    try:
        result.rag_indexed_chunks = build_rag_index_draft(
            session, course_id=course_id, run_id=run_id,
            material_version_id=material_version_id, blocks=list(blocks),
        )
    except Exception as exc:
        result.warnings.append(f"rag_index_draft failed: {exc}")

    # 2. 图谱候选草稿
    _stage("graph_draft")
    try:
        n, r = build_graph_draft(session, course_id=course_id, run_id=run_id, blocks=list(blocks))
        result.graph_node_candidates = n
        result.graph_relation_candidates = r
        result.graph_review_candidate_count = build_graph_review_candidates(
            session, course_id=course_id, run_id=run_id, blocks=list(blocks),
        )
    except Exception as exc:
        result.warnings.append(f"graph_draft failed: {exc}")

    # 3. 课程目录草稿
    _stage("outline_draft")
    try:
        ov_id, node_count = build_outline_draft(
            session, course_id=course_id, run_id=run_id,
            material_version_id=material_version_id,
            blocks=list(blocks), created_by=created_by,
        )
        result.outline_version_id = ov_id
        result.outline_node_count = node_count
    except Exception as exc:
        result.warnings.append(f"outline_draft failed: {exc}")

    # 4. 讲稿草稿（与目录版本对齐）
    _stage("teaching_script_draft")
    if result.outline_version_id:
        try:
            outline_nodes = session.exec(
                select(CourseOutlineNode).where(
                    CourseOutlineNode.outline_version_id == result.outline_version_id
                ).order_by(CourseOutlineNode.order_index)
            ).all()
            # 每个节点关联其 source_block_refs 指向的 blocks
            blocks_by_id = {b.block_id: b for b in blocks}
            blocks_by_node: dict[str, list[DocumentBlock]] = {}
            for n in outline_nodes:
                refs = n.source_block_refs or []
                blocks_by_node[n.outline_node_id] = [
                    blocks_by_id[r] for r in refs if r in blocks_by_id
                ]
            sv_id, scount = build_teaching_script_draft(
                session, course_id=course_id, run_id=run_id,
                outline_version_id=result.outline_version_id,
                outline_node_ids=[n.outline_node_id for n in outline_nodes],
                blocks_by_node=blocks_by_node, created_by=created_by,
            )
            result.script_version_id = sv_id
            result.script_node_count = scount
        except Exception as exc:
            result.warnings.append(f"teaching_script_draft failed: {exc}")

    # 5. Markdown 资源草稿
    _stage("patch_proposal_draft")
    try:
        result.patch_proposal_id = build_patch_proposal_draft(
            session,
            course_id=course_id,
            run_id=run_id,
            outline_version_id=result.outline_version_id or "",
            script_version_id=result.script_version_id,
            blocks=list(blocks),
            created_by=created_by,
        ) if result.outline_version_id else None
    except Exception as exc:
        result.warnings.append(f"patch_proposal_draft failed: {exc}")

    _stage("markdown_resource_draft")
    try:
        rid, vid = build_markdown_resource_draft(
            session, course_id=course_id, run_id=run_id,
            material_version_id=material_version_id,
            blocks=list(blocks), created_by=created_by,
        )
        result.markdown_resource_id = rid
        result.markdown_resource_version_id = vid
    except Exception as exc:
        result.warnings.append(f"markdown_resource_draft failed: {exc}")

    session.commit()
    return result
