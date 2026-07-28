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
    CoursePptMapping,
    OutlineLifecycleStatus,
    OutlineNodeType,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.document_parse_model import DocumentBlock, EvidenceSpan
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
    corpus_snapshot_id: Optional[str] = None
    outline_version_id: Optional[str] = None
    script_version_id: Optional[str] = None
    rag_indexed_chunks: int = 0
    graph_node_candidates: int = 0
    graph_relation_candidates: int = 0
    outline_node_count: int = 0
    script_node_count: int = 0
    markdown_resource_id: Optional[str] = None
    markdown_resource_version_id: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def to_progress_data(self) -> dict[str, Any]:
        return {
            "outline_version_id": self.outline_version_id,
            "script_version_id": self.script_version_id,
            "rag_indexed_chunks": self.rag_indexed_chunks,
            "graph_node_candidates": self.graph_node_candidates,
            "outline_node_count": self.outline_node_count,
            "script_node_count": self.script_node_count,
            "markdown_resource_id": self.markdown_resource_id,
            "markdown_resource_version_id": self.markdown_resource_version_id,
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


# ---------------------------------------------------------------------------
# TeachingStructureBuilder（课程目录草稿）
# ---------------------------------------------------------------------------


def build_outline_draft(
    session: Session,
    *,
    course_id: int,
    run_id: Optional[str],
    material_version_id: Optional[str],
    blocks: list[DocumentBlock],
    created_by: Optional[int] = None,
    corpus_snapshot_id: Optional[str] = None,
    build_task_id: Optional[str] = None,
) -> tuple[str, int]:
    """从 DocumentBlock 生成课程目录草稿（CourseOutlineVersion + Node）。

    Demo 策略：按 block 顺序生成 knowledge_point 节点（扁平）；真实层级划分
    （chapter/section/knowledge_point）由 Step 5 教师编辑或后续 LLM 优化。
    返回 (outline_version_id, node_count)。
    """
    latest = session.exec(select(CourseOutlineVersion).where(
        CourseOutlineVersion.course_id == course_id,
    ).order_by(CourseOutlineVersion.version.desc())).first()
    version = CourseOutlineVersion(
        course_id=course_id, version=(latest.version + 1) if latest else 1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        source_parse_run_id=run_id, created_by=created_by,
        corpus_snapshot_id=corpus_snapshot_id, build_task_id=build_task_id,
        generation_source="agent_initial_generation", review_status="pending",
    )
    session.add(version)
    session.flush()
    ordered = sorted(blocks, key=lambda item: (
        int(item.page_or_slide or item.page_number or 0),
        int(getattr(item, "reading_order", 0) or item.order_index or 0),
    ))
    nonempty = [b for b in ordered if (b.text or "").strip()]
    first_section = next((b for b in nonempty if b.semantic_role == "section_title"), None)

    def add_node(node_type, title, parent, refs, node_order, confidence):
        pages = [int((b.page_or_slide or b.page_number or 1)) for b in ordered if b.block_id in refs]
        page_start, page_end = (min(pages), max(pages)) if pages else (1, 1)
        node = CourseOutlineNode(
            outline_version_id=version.outline_version_id, course_id=course_id,
            parent_node_id=parent.outline_node_id if parent else None,
            node_type=node_type, title=title[:300], order_index=node_order,
            source_block_refs=list(refs),
            page_range=str(page_start) if page_start == page_end else f"{page_start}-{page_end}",
            generation_reason="deterministic_semantic_builder",
            confidence=max(0.0, min(1.0, confidence)),
            content_hash=(refs[0] if refs else ""),
        )
        session.add(node)
        if node_type == OutlineNodeType.KNOWLEDGE_POINT and material_version_id:
            session.add(CoursePptMapping(
                course_id=course_id, outline_node_id=node.outline_node_id,
                material_version_id=material_version_id, page_start=page_start,
                page_end=page_end, page_refs=list(range(page_start, page_end + 1)),
                confidence=node.confidence, source_block_refs=list(refs),
                status="draft", created_by=created_by,
            ))
        return node

    section = add_node(
        OutlineNodeType.SECTION,
        first_section.text.strip() if first_section else "课程内容",
        None,
        [first_section.block_id] if first_section else ([nonempty[0].block_id] if nonempty else []),
        0,
        first_section.confidence if first_section else 0.55,
    )
    current_kp = None
    kp_refs = []
    kp_order = 0
    child_order = 0

    def flush_kp():
        nonlocal current_kp, kp_refs, kp_order, child_order
        if current_kp is not None:
            current_kp.source_block_refs = list(dict.fromkeys(kp_refs))
            pages = [int((b.page_or_slide or b.page_number or 1)) for b in ordered if b.block_id in kp_refs]
            if pages:
                current_kp.page_range = str(min(pages)) if min(pages) == max(pages) else f"{min(pages)}-{max(pages)}"
            session.add(current_kp)
        current_kp, kp_refs = None, []
        kp_order += 1
        child_order = 0

    for blk in nonempty:
        if first_section and blk.block_id == first_section.block_id:
            continue
        role = blk.semantic_role or "explanation"
        text = blk.text.strip()
        if role == "section_title":
            flush_kp()
            section = add_node(OutlineNodeType.SECTION, text, None, [blk.block_id], kp_order + 1, blk.confidence)
        elif current_kp is None or role == "knowledge_title" or (first_section is None and role == "explanation"):
            flush_kp()
            current_kp = add_node(OutlineNodeType.KNOWLEDGE_POINT, text, section, [blk.block_id], kp_order, blk.confidence)
            kp_refs = [blk.block_id]
        elif role in {"example", "practice_suggestion"}:
            child_type = OutlineNodeType.EXAMPLE if role == "example" else OutlineNodeType.PRACTICE_SUGGESTION
            add_node(child_type, text, current_kp, [blk.block_id], child_order, blk.confidence)
            child_order += 1
        else:
            kp_refs.append(blk.block_id)
    flush_kp()
    session.flush()
    generated_count = len(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == version.outline_version_id,
        CourseOutlineNode.node_type == OutlineNodeType.KNOWLEDGE_POINT,
    )).all())
    return version.outline_version_id, generated_count
    """
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
        if blk.page_or_slide or blk.page_number:
            page = int(blk.page_or_slide or blk.page_number or 1)
            session.add(CoursePptMapping(
                course_id=course_id,
                outline_node_id=node.outline_node_id,
                material_version_id=material_version_id,
                page_start=page,
                page_end=page,
                page_refs=[page],
                confidence=blk.confidence,
                source_block_refs=[blk.block_id],
                status="draft",
                created_by=created_by,
            ))
        order += 1
    session.flush()
    return version.outline_version_id, order
    """


# ---------------------------------------------------------------------------
# TeachingScriptBuilder（讲稿草稿，按目录组织）
# ---------------------------------------------------------------------------


def build_teaching_script_draft(
    session: Session,
    *,
    course_id: int,
    run_id: Optional[str],
    outline_version_id: str,
    outline_node_ids: list[str],
    blocks_by_node: dict[str, list[DocumentBlock]],
    created_by: Optional[int] = None,
    corpus_snapshot_id: Optional[str] = None,
    build_task_id: Optional[str] = None,
) -> tuple[str, int]:
    """根据草稿目录 + Evidence 生成讲稿草稿（TeachingScriptNode）。

    与目录版本对齐（同一 outline_version_id），保证目录与讲稿发布状态一致。
    返回 (script_version_id, node_count)。
    """
    latest = session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.course_id == course_id,
    ).order_by(TeachingScriptVersion.version.desc())).first()
    script_version = TeachingScriptVersion(
        course_id=course_id, outline_version_id=outline_version_id,
        version=(latest.version + 1) if latest else 1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        source_parse_run_id=run_id, created_by=created_by,
        corpus_snapshot_id=corpus_snapshot_id, build_task_id=build_task_id,
        generation_source="agent_initial_generation", review_status="pending",
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
    run_id: Optional[str] = None,
    material_version_id: Optional[str] = None,
    created_by: Optional[int] = None,
    corpus_snapshot_id: Optional[str] = None,
    build_task_id: Optional[str] = None,
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
        course_id=course_id, run_id=run_id or "", material_version_id=material_version_id,
        corpus_snapshot_id=corpus_snapshot_id,
    )
    stmt = select(DocumentBlock).where(DocumentBlock.course_id == course_id)
    if corpus_snapshot_id:
        from app.models.course_build_model import CourseCorpusSnapshot
        corpus = session.exec(select(CourseCorpusSnapshot).where(
            CourseCorpusSnapshot.course_id == course_id,
            CourseCorpusSnapshot.corpus_snapshot_id == corpus_snapshot_id,
        )).first()
        if corpus is None:
            raise ValueError("course corpus snapshot not found")
        stmt = stmt.where(DocumentBlock.run_id.in_(list(corpus.parse_run_ids or [])))
    elif run_id:
        stmt = stmt.where(DocumentBlock.run_id == run_id)
    else:
        raise ValueError("run_id or corpus_snapshot_id is required")
    blocks = session.exec(stmt.order_by(DocumentBlock.page_or_slide, DocumentBlock.order_index)).all()
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
    result.rag_indexed_chunks = sum(1 for block in blocks if len((block.text or "").strip()) >= 5)

    # 2. 图谱候选草稿
    _stage("graph_draft")
    result.warnings.append("graph candidates remain material-level parser output")

    # 3. 课程目录草稿
    _stage("outline_draft")
    try:
        ov_id, node_count = build_outline_draft(
            session, course_id=course_id, run_id=run_id,
            material_version_id=material_version_id,
            blocks=list(blocks), created_by=created_by,
            corpus_snapshot_id=corpus_snapshot_id, build_task_id=build_task_id,
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
            # Only knowledge points are playable teaching units. Sections and
            # child examples/practice items remain outline nodes but do not get
            # placeholder lecture scripts.
            script_nodes = [n for n in outline_nodes if n.node_type == OutlineNodeType.KNOWLEDGE_POINT]
            # 每个节点关联其 source_block_refs 指向的 blocks
            blocks_by_id = {b.block_id: b for b in blocks}
            blocks_by_node: dict[str, list[DocumentBlock]] = {}
            for n in script_nodes:
                refs = n.source_block_refs or []
                blocks_by_node[n.outline_node_id] = [
                    blocks_by_id[r] for r in refs if r in blocks_by_id
                ]
            sv_id, scount = build_teaching_script_draft(
                session, course_id=course_id, run_id=run_id,
                outline_version_id=result.outline_version_id,
                outline_node_ids=[n.outline_node_id for n in script_nodes],
                blocks_by_node=blocks_by_node, created_by=created_by,
                corpus_snapshot_id=corpus_snapshot_id, build_task_id=build_task_id,
            )
            result.script_version_id = sv_id
            result.script_node_count = scount
        except Exception as exc:
            result.warnings.append(f"teaching_script_draft failed: {exc}")

    # 5. Markdown 资源草稿
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

    # Deprecated compatibility block: initial generation is already a pending
    # system draft. It must not also create a duplicate accept/reject proposal.
    return_after_initial_draft = True
    if return_after_initial_draft:
        session.commit()
        return result

    # First import is a teacher-reviewable proposal, never a direct mutation.
    # Existing proposals are left untouched so a retry cannot duplicate them.
    try:
        from app.models.course_outline_model import PatchProposal, PatchProposalOperation, PatchOperation, TeachingScriptNode
        existing = session.exec(select(PatchProposal).where(
            PatchProposal.course_id == course_id,
            PatchProposal.tool_name == "CourseBuildAgent",
        )).first()
        if not existing and result.outline_version_id:
            outline_nodes = session.exec(select(CourseOutlineNode).where(
                CourseOutlineNode.outline_version_id == result.outline_version_id,
            ).order_by(CourseOutlineNode.order_index)).all()
            proposal = PatchProposal(
                course_id=course_id,
                tool_name="CourseBuildAgent",
                policy_version="course-build-agent/1.0",
                reason="首次上传课件后，根据统一解析结果生成课程结构与讲授脚本候选，请教师审核后应用。",
                created_by=created_by,
            )
            session.add(proposal)
            session.flush()
            for node in outline_nodes:
                if node.node_type != OutlineNodeType.KNOWLEDGE_POINT:
                    continue
                session.add(PatchProposalOperation(
                    proposal_id=proposal.proposal_id,
                    course_id=course_id,
                    operation=PatchOperation.REPLACE,
                    target=f"outline:{node.outline_node_id}:title",
                    before="",
                    after=node.title,
                    reason="解析块生成的课程结构候选",
                    evidence_refs=[],
                    policy_version="course-build-agent/1.0",
                ))
            script_nodes = session.exec(select(TeachingScriptNode).where(
                TeachingScriptNode.script_version_id == result.script_version_id,
            )).all() if result.script_version_id else []
            for script_node in script_nodes:
                session.add(PatchProposalOperation(
                    proposal_id=proposal.proposal_id,
                    course_id=course_id,
                    operation=PatchOperation.REPLACE,
                    target=f"script:{script_node.script_node_id}:content",
                    before="",
                    after=script_node.content,
                    reason="解析块生成的讲授脚本候选",
                    evidence_refs=[],
                    policy_version="course-build-agent/1.0",
                ))
            result.warnings.append("created initial teacher-review proposal")
    except Exception as exc:
        result.warnings.append(f"initial proposal creation failed: {exc}")

    session.commit()
    return result
