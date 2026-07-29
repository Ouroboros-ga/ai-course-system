"""Initial, evidence-grounded course preparation.

Document parsing records facts.  This service is the boundary that turns the
complete course corpus into the *first* teacher-visible outline and script
draft.  It deliberately does not fall back to the legacy block-to-node builder:
if the controlled agent cannot produce a valid, evidence-backed course tree,
the durable build task fails for retry instead of exposing raw parse fragments.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any, Awaitable, Callable

from sqlmodel import Session, select

from app.models.course_build_model import CourseCorpusItem, CourseCorpusSnapshot, SourceMaterial
from app.models.course_model import Course
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    CoursePptMapping,
    OutlineLifecycleStatus,
    OutlineNodeType,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.document_parse_model import DocumentBlock, EvidenceAnchor
from app.schemas.controlled_prep import ControlledPrepInput, EvidenceReference, TeachingStyleConfig
from app.services.controlled_prep_workflow import ControlledPrepWorkflow, controlled_prep_workflow
from app.services.document_draft_builders import DraftAssetResult, build_markdown_resource_draft
from app.services.document_parse_service import graph_candidate_service


class InitialCoursePreparationError(ValueError):
    """The first course draft is not safe to make teacher-visible."""


ROLE_PRIORITY = {
    "primary_courseware": 10,
    "syllabus": 20,
    "textbook": 30,
    "experiment_guide": 40,
    "exercise_bank": 50,
    "reference": 60,
}

# Keep the first course-planning request within ordinary OpenAI-compatible
# gateway context windows.  The controlled workflow receives evidence text
# separately, so sending hundreds of full blocks twice only adds latency and
# timeout risk without improving traceability.
MAX_AGENT_EVIDENCE = 120
MAX_AGENT_SOURCE_CHARS = 60_000


@dataclass
class InitialCoursePrepService:
    """Build the initial course draft only after the Agent completes all stages."""

    async def build(
        self,
        session: Session,
        *,
        course_id: int,
        corpus_snapshot_id: str,
        created_by: int | None,
        build_task_id: str | None = None,
        workflow: ControlledPrepWorkflow | None = None,
        replace_unreviewed_initial: bool = False,
        on_stage: Callable[[str, int, Any], Awaitable[None] | None] | None = None,
    ) -> DraftAssetResult:
        corpus = session.exec(select(CourseCorpusSnapshot).where(
            CourseCorpusSnapshot.course_id == course_id,
            CourseCorpusSnapshot.corpus_snapshot_id == corpus_snapshot_id,
        )).first()
        if corpus is None:
            raise InitialCoursePreparationError("课程语料快照不存在")

        items = list(session.exec(select(CourseCorpusItem).where(
            CourseCorpusItem.course_id == course_id,
            CourseCorpusItem.corpus_snapshot_id == corpus_snapshot_id,
            CourseCorpusItem.included == True,  # noqa: E712
        )).all())
        if not items:
            raise InitialCoursePreparationError("课程语料快照中没有可用材料")
        role_by_run = {item.parse_run_id: item.material_role for item in items}
        material_by_run = {item.parse_run_id: item.material_version_id for item in items}
        blocks = list(session.exec(select(DocumentBlock).where(
            DocumentBlock.course_id == course_id,
            DocumentBlock.run_id.in_(list(role_by_run)),
        )).all())
        blocks = self._ordered_blocks(blocks, role_by_run)
        evidence, source_text = self._build_agent_input(blocks, role_by_run, material_by_run)
        if not evidence:
            raise InitialCoursePreparationError("课程材料没有可用于智能备课的有效文本")

        course = session.get(Course, course_id)
        request = ControlledPrepInput(
            source_text=source_text,
            evidence=evidence,
            course_positioning=(course.description if course and course.description else course.title if course else "课程材料驱动的教学设计"),
            style=TeachingStyleConfig(level="beginner", tone="conversational", language="zh-CN"),
        )
        # ``ControlledPrepWorkflow.run`` can spend minutes waiting for an
        # external LLM.  Do not keep the SQLite read/write transaction open
        # during that network wait: otherwise a teacher's next material upload
        # competes with this task and surfaces as a misleading HTTP 500.
        # All mutations happen only after the workflow returns and remain in
        # the caller's normal durable task transaction.
        session.commit()
        active_workflow = workflow or controlled_prep_workflow
        if on_stage is None:
            # Preserve the small fake-workflow contract used by existing
            # service tests and integrations.
            prepared = await active_workflow.run(request)
        else:
            prepared = await active_workflow.run(request, on_stage=on_stage)
        if on_stage is not None:
            outcome = on_stage("persisting", 95, None)
            if outcome is not None:
                await outcome
        self._validate_initial_outline(prepared["outline"])

        result = DraftAssetResult(
            course_id=course_id,
            run_id=f"corpus:{corpus_snapshot_id}",
            material_version_id=None,
            corpus_snapshot_id=corpus_snapshot_id,
        )
        if replace_unreviewed_initial:
            self._archive_unreviewed_initial_draft(session, course_id=course_id)
        by_block_id = {block.block_id: block for block in blocks}
        candidate_to_node = self._persist_outline(
            session,
            course_id=course_id,
            corpus_snapshot_id=corpus_snapshot_id,
            build_task_id=build_task_id,
            created_by=created_by,
            outline=prepared["outline"],
            valid_block_ids=set(by_block_id),
            result=result,
        )
        self._persist_scripts(
            session,
            course_id=course_id,
            corpus_snapshot_id=corpus_snapshot_id,
            build_task_id=build_task_id,
            created_by=created_by,
            outline_version_id=result.outline_version_id or "",
            prepared=prepared,
            candidate_to_node=candidate_to_node,
            valid_block_ids=set(by_block_id),
            result=result,
        )
        self._persist_primary_ppt_mappings(
            session,
            course_id=course_id,
            items=items,
            nodes=list(candidate_to_node.values()),
            blocks_by_id=by_block_id,
            created_by=created_by,
        )
        result.rag_indexed_chunks = sum(1 for block in blocks if len((block.text or "").strip()) >= 5)
        (
            result.graph_candidate_batch_id,
            result.graph_node_candidates,
            result.graph_relation_candidates,
        ) = self._persist_agent_graph(
            session,
            course_id=course_id,
            corpus_snapshot_id=corpus_snapshot_id,
            outline=prepared["outline"],
            candidate_to_node=candidate_to_node,
            created_by=created_by,
        )
        primary_version_id = self._primary_slide_version_id(session, course_id=course_id, items=items)
        result.markdown_resource_id, result.markdown_resource_version_id = build_markdown_resource_draft(
            session,
            course_id=course_id,
            run_id=f"corpus:{corpus_snapshot_id}",
            material_version_id=primary_version_id,
            blocks=blocks,
            created_by=created_by,
        )
        result.warnings.extend(
            "讲稿证据需要教师复核" for verification in prepared["verifications"]
            if verification.verdict == "needs_review"
        )
        return result

    @staticmethod
    def _archive_unreviewed_initial_draft(session: Session, *, course_id: int) -> None:
        """Explicitly replace an untouched system-generated first draft only.

        This is intentionally narrower than a normal rebuild.  Once a teacher
        has reviewed, edited, or locked content, later Agent work must remain a
        PatchProposal and cannot take this replacement path.
        """
        current = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.course_id == course_id,
            CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
        ).order_by(CourseOutlineVersion.version.desc())).first()
        if current is None:
            return
        if current.generation_source != "agent_initial_generation" or current.review_status != "pending":
            raise InitialCoursePreparationError("已有教师审核或编辑的草稿只能通过 Proposal 调整")
        outline_nodes = list(session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == course_id,
            CourseOutlineNode.outline_version_id == current.outline_version_id,
        )).all())
        if any(node.locked_by is not None for node in outline_nodes):
            raise InitialCoursePreparationError("存在教师锁定的目录节点，不能替换初稿")
        scripts = list(session.exec(select(TeachingScriptVersion).where(
            TeachingScriptVersion.course_id == course_id,
            TeachingScriptVersion.outline_version_id == current.outline_version_id,
            TeachingScriptVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
        )).all())
        script_ids = [script.script_version_id for script in scripts]
        if script_ids:
            script_nodes = list(session.exec(select(TeachingScriptNode).where(
                TeachingScriptNode.course_id == course_id,
                TeachingScriptNode.script_version_id.in_(script_ids),
            )).all())
            if any(node.locked_by is not None for node in script_nodes):
                raise InitialCoursePreparationError("存在教师锁定的讲稿节点，不能替换初稿")
        for mapping in session.exec(select(CoursePptMapping).where(
            CoursePptMapping.course_id == course_id,
            CoursePptMapping.outline_node_id.in_([node.outline_node_id for node in outline_nodes]),
            CoursePptMapping.status == "draft",
        )).all() if outline_nodes else []:
            mapping.status = "stale"
            session.add(mapping)
        current.lifecycle_status = OutlineLifecycleStatus.ARCHIVED
        session.add(current)
        for script in scripts:
            script.lifecycle_status = OutlineLifecycleStatus.ARCHIVED
            session.add(script)

    @staticmethod
    def _ordered_blocks(blocks: list[DocumentBlock], role_by_run: dict[str, str]) -> list[DocumentBlock]:
        return sorted(
            blocks,
            key=lambda block: (
                ROLE_PRIORITY.get(role_by_run.get(block.run_id, "reference"), 99),
                int(block.page_or_slide or block.page_number or 0),
                int(block.order_index or 0),
            ),
        )

    @staticmethod
    def _build_agent_input(
        blocks: list[DocumentBlock],
        role_by_run: dict[str, str],
        material_by_run: dict[str, str] | None = None,
    ) -> tuple[list[EvidenceReference], str]:
        """Sample evidence round-robin across role/file/page buckets.

        The former prefix slice could consume all 120 slots from the first
        primary deck pages.  A deterministic bucket round-robin keeps every
        selected material, role and chapter/page represented when possible.
        """
        material_by_run = material_by_run or {}
        buckets: dict[tuple[str, str, int], list[DocumentBlock]] = defaultdict(list)
        for block in blocks:
            text = " ".join((block.text or "").split())
            if len(text) < 2 or block.semantic_role in {"header", "footer", "page_number"}:
                continue
            role = role_by_run.get(block.run_id, "reference")
            material = material_by_run.get(block.run_id, block.material_version_id or "unknown")
            page = int(block.page_or_slide or block.page_number or 1)
            buckets[(role, material, page)].append(block)
        ordered_buckets = [buckets[key] for key in sorted(
            buckets,
            key=lambda key: (ROLE_PRIORITY.get(key[0], 99), key[1], key[2]),
        )]
        evidence: list[EvidenceReference] = []
        source_parts: list[str] = []
        remaining = MAX_AGENT_SOURCE_CHARS
        offset = 0
        while ordered_buckets and remaining > 0 and len(evidence) < MAX_AGENT_EVIDENCE:
            next_buckets: list[list[DocumentBlock]] = []
            for bucket in ordered_buckets:
                if offset >= len(bucket):
                    continue
                block = bucket[offset]
                text = " ".join((block.text or "").split())[:4_000]
                if text and len(text) <= remaining:
                    remaining -= len(text) + 80
                    evidence.append(EvidenceReference(
                        evidence_id=block.block_id,
                        block_id=block.block_id,
                        page=int(block.page_or_slide or block.page_number or 1),
                        text=text,
                    ))
                    source_parts.append(
                        f"[{role_by_run.get(block.run_id, 'reference')} / file {material_by_run.get(block.run_id, '-')[:24]} / page {block.page_or_slide or block.page_number or '-'} / {block.semantic_role or 'text'}] {text}"
                    )
                if offset + 1 < len(bucket):
                    next_buckets.append(bucket)
                if len(evidence) >= MAX_AGENT_EVIDENCE or remaining <= 0:
                    break
            ordered_buckets = next_buckets
            offset += 1
        return evidence, "\n".join(source_parts)

    @staticmethod
    def _validate_initial_outline(outline: Any) -> None:
        candidates = list(outline.candidates)
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        if not any(candidate.node_type == "chapter" for candidate in candidates):
            raise InitialCoursePreparationError("智能备课结果缺少章节层级，请重试")
        if not any(candidate.node_type == "knowledge_point" for candidate in candidates):
            raise InitialCoursePreparationError("智能备课结果缺少知识点，请重试")
        seen_titles: set[tuple[str | None, str]] = set()
        for candidate in candidates:
            title = " ".join(candidate.title.split())
            if len(title) < 2 or len(title) > 120 or "\n" in candidate.title:
                raise InitialCoursePreparationError("智能备课结果包含不适合作为教学标题的内容")
            if re.match(r"^(图|表)\s*\d", title) or title.count("-") >= 3:
                raise InitialCoursePreparationError("智能备课结果将图注或部件清单误作教学标题")
            if candidate.node_type == "chapter" and candidate.parent_candidate_id:
                raise InitialCoursePreparationError("章节不能拥有父节点")
            if candidate.parent_candidate_id:
                parent = by_id[candidate.parent_candidate_id]
                expected_parent = {"section": "chapter", "knowledge_point": "section"}.get(candidate.node_type)
                if expected_parent and parent.node_type != expected_parent:
                    raise InitialCoursePreparationError("智能备课结果的课程层级不完整")
            key = (candidate.parent_candidate_id, title.casefold())
            if key in seen_titles:
                raise InitialCoursePreparationError("智能备课结果包含同层重复标题")
            seen_titles.add(key)

    @staticmethod
    def _persist_outline(
        session: Session,
        *,
        course_id: int,
        corpus_snapshot_id: str,
        build_task_id: str | None,
        created_by: int | None,
        outline: Any,
        valid_block_ids: set[str],
        result: DraftAssetResult,
    ) -> dict[str, CourseOutlineNode]:
        latest = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.course_id == course_id,
        ).order_by(CourseOutlineVersion.version.desc())).first()
        version = CourseOutlineVersion(
            course_id=course_id,
            version=(latest.version + 1) if latest else 1,
            lifecycle_status=OutlineLifecycleStatus.DRAFT,
            corpus_snapshot_id=corpus_snapshot_id,
            build_task_id=build_task_id,
            generation_source="agent_initial_generation",
            review_status="pending",
            created_by=created_by,
        )
        session.add(version)
        session.flush()
        result.outline_version_id = version.outline_version_id
        candidate_to_node: dict[str, CourseOutlineNode] = {}
        sibling_orders: defaultdict[str | None, int] = defaultdict(int)
        pending = list(outline.candidates)
        while pending:
            progressed = False
            for candidate in list(pending):
                if candidate.parent_candidate_id and candidate.parent_candidate_id not in candidate_to_node:
                    continue
                parent = candidate_to_node.get(candidate.parent_candidate_id or "")
                refs = [reference for reference in candidate.evidence_ids if reference in valid_block_ids]
                node = CourseOutlineNode(
                    course_id=course_id,
                    outline_version_id=version.outline_version_id,
                    parent_node_id=parent.outline_node_id if parent else None,
                    node_type=OutlineNodeType(candidate.node_type),
                    title=" ".join(candidate.title.split()),
                    order_index=sibling_orders[parent.outline_node_id if parent else None],
                    source_block_refs=refs,
                    generation_reason=candidate.rationale or "controlled_initial_prep",
                    confidence=0.82,
                    content_hash="",
                )
                sibling_orders[parent.outline_node_id if parent else None] += 1
                session.add(node)
                session.flush()
                candidate_to_node[candidate.candidate_id] = node
                pending.remove(candidate)
                progressed = True
            if not progressed:
                raise InitialCoursePreparationError("智能备课结果无法形成完整课程树")
        result.outline_node_count = len(candidate_to_node)
        return candidate_to_node

    @staticmethod
    def _persist_scripts(
        session: Session,
        *,
        course_id: int,
        corpus_snapshot_id: str,
        build_task_id: str | None,
        created_by: int | None,
        outline_version_id: str,
        prepared: dict[str, Any],
        candidate_to_node: dict[str, CourseOutlineNode],
        valid_block_ids: set[str],
        result: DraftAssetResult,
    ) -> None:
        latest = session.exec(select(TeachingScriptVersion).where(
            TeachingScriptVersion.course_id == course_id,
        ).order_by(TeachingScriptVersion.version.desc())).first()
        version = TeachingScriptVersion(
            course_id=course_id,
            outline_version_id=outline_version_id,
            version=(latest.version + 1) if latest else 1,
            lifecycle_status=OutlineLifecycleStatus.DRAFT,
            corpus_snapshot_id=corpus_snapshot_id,
            build_task_id=build_task_id,
            generation_source="agent_initial_generation",
            review_status="pending",
            created_by=created_by,
        )
        session.add(version)
        session.flush()
        result.script_version_id = version.script_version_id
        verdict_by_candidate = {
            script.candidate_id: verification.verdict
            for script, verification in zip(prepared["scripts"], prepared["verifications"], strict=True)
        }
        count = 0
        for script in prepared["scripts"]:
            if verdict_by_candidate.get(script.candidate_id) == "failed":
                continue
            node = candidate_to_node.get(script.candidate_id)
            if node is None:
                continue
            refs = [reference for reference in script.evidence_ids if reference in valid_block_ids]
            session.add(TeachingScriptNode(
                course_id=course_id,
                script_version_id=version.script_version_id,
                outline_node_id=node.outline_node_id,
                content=script.content,
                style=script.style.level,
                source_block_refs=refs,
                content_hash="",
            ))
            count += 1
        if not count:
            raise InitialCoursePreparationError("智能备课未生成可核验的基础讲稿")
        result.script_node_count = count

    @staticmethod
    def _primary_slide_version_id(session: Session, *, course_id: int, items: list[CourseCorpusItem]) -> str | None:
        for item in sorted(items, key=lambda value: value.priority):
            material = session.exec(select(SourceMaterial).where(
                SourceMaterial.course_id == course_id,
                SourceMaterial.material_id == item.material_id,
            )).first()
            if item.material_role == "primary_courseware" and material and material.material_type == "slide":
                return item.material_version_id
        return None

    def _persist_primary_ppt_mappings(
        self,
        session: Session,
        *,
        course_id: int,
        items: list[CourseCorpusItem],
        nodes: list[CourseOutlineNode],
        blocks_by_id: dict[str, DocumentBlock],
        created_by: int | None,
    ) -> None:
        version_id = self._primary_slide_version_id(session, course_id=course_id, items=items)
        if not version_id:
            return
        primary_run_ids = {
            item.parse_run_id for item in items
            if item.material_version_id == version_id and item.material_role == "primary_courseware"
        }
        for node in nodes:
            if node.node_type != OutlineNodeType.KNOWLEDGE_POINT:
                continue
            pages = sorted({
                int(block.page_or_slide or block.page_number)
                for ref in (node.source_block_refs or [])
                if (block := blocks_by_id.get(ref)) is not None
                and block.run_id in primary_run_ids
                and (block.page_or_slide or block.page_number)
            })
            if not pages:
                continue
            session.add(CoursePptMapping(
                course_id=course_id,
                outline_node_id=node.outline_node_id,
                material_version_id=version_id,
                page_start=min(pages),
                page_end=max(pages),
                page_refs=pages,
                confidence=0.82,
                source_block_refs=[
                    ref for ref in (node.source_block_refs or [])
                    if ref in blocks_by_id and blocks_by_id[ref].run_id in primary_run_ids
                ],
                status="draft",
                created_by=created_by,
            ))

    @staticmethod
    def _persist_agent_graph(
        session: Session,
        *,
        course_id: int,
        corpus_snapshot_id: str,
        outline: Any,
        candidate_to_node: dict[str, CourseOutlineNode],
        created_by: int | None,
    ) -> tuple[str, int, int]:
        knowledge = [candidate for candidate in outline.candidates if candidate.node_type == "knowledge_point"]
        block_ids = [
            block_id for node in candidate_to_node.values()
            for block_id in (node.source_block_refs or [])
        ]
        anchors = list(session.exec(select(EvidenceAnchor).where(
            EvidenceAnchor.course_id == course_id,
            EvidenceAnchor.block_id.in_(block_ids),
        )).all()) if block_ids else []
        anchor_by_block = {anchor.block_id: anchor.anchor_id for anchor in anchors}
        nodes = []
        candidate_graph_id: dict[str, str] = {}
        for candidate in knowledge:
            outline_node = candidate_to_node[candidate.candidate_id]
            graph_id = f"cgcn_{outline_node.outline_node_id.removeprefix('on_')}"
            candidate_graph_id[candidate.candidate_id] = graph_id
            refs = outline_node.source_block_refs or []
            nodes.append({
                "candidate_id": graph_id,
                "label": outline_node.title,
                "kind": "concept",
                "status": "proposed",
                "confidence": outline_node.confidence,
                "source_block_ids": refs,
                "anchor_ids": [anchor_by_block[reference] for reference in refs if reference in anchor_by_block],
                "page_or_slide": None,
            })
        relations = []
        siblings: defaultdict[str | None, list[Any]] = defaultdict(list)
        for candidate in knowledge:
            siblings[candidate.parent_candidate_id].append(candidate)
        for grouped in siblings.values():
            for left, right in zip(grouped, grouped[1:]):
                relations.append({
                    "candidate_id": f"cgcr_{candidate_graph_id[left.candidate_id]}_{candidate_graph_id[right.candidate_id]}",
                    "source_candidate_id": candidate_graph_id[left.candidate_id],
                    "target_candidate_id": candidate_graph_id[right.candidate_id],
                    "relation_type": "next_topic",
                    "status": "proposed",
                    "confidence": 0.8,
                    "anchor_ids": [],
                })
        batch = graph_candidate_service.create_batch(
            session, course_id=course_id, parse_run_id=None, initiated_by=created_by,
        )
        graph_candidate_service.mark_succeeded(
            session,
            course_id=course_id,
            batch_id=batch.batch_id,
            node_candidate_count=len(nodes),
            relation_candidate_count=len(relations),
            node_candidates=nodes,
            relation_candidates=relations,
        )
        return batch.batch_id, len(nodes), len(relations)


initial_course_prep_service = InitialCoursePrepService()
