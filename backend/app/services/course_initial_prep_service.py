"""Initial, evidence-grounded course preparation.

Document parsing records facts.  This service is the boundary that turns the
complete course corpus into the *first* teacher-visible outline and script
draft.  It deliberately does not fall back to the legacy block-to-node builder:
if the controlled agent cannot produce a valid, evidence-backed course tree,
the durable build task fails for retry instead of exposing raw parse fragments.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import logging
import re
import uuid
from typing import Any, Awaitable, Callable

from sqlmodel import Session, select

from app.core.config import settings
from app.models.course_build_model import CourseCorpusItem, CourseCorpusSnapshot, SourceMaterial
from app.models.course_model import Course
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    CoursePptMapping,
    CourseScriptCoverageIssue,
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


logger = logging.getLogger(__name__)


ROLE_PRIORITY = {
    "primary_courseware": 10,
    "syllabus": 20,
    "textbook": 30,
    "experiment_guide": 40,
    "exercise_bank": 50,
    "reference": 60,
}

@dataclass(frozen=True)
class EvidenceInputStats:
    total_units: int
    selected_units: int
    total_chars: int
    selected_chars: int

    @property
    def sampled(self) -> bool:
        return self.selected_units < self.total_units or self.selected_chars < self.total_chars


async def _run_prep_with_diagnostic_context(
    *,
    course_id: int,
    build_task_id: str | None,
    awaitable: Awaitable[Any],
) -> Any:
    """Bind the prep build's LLM calls to a stable run/trace/course context.

    LLM diagnostics are written metadata-only; without this, every record in
    ``agent_llm_diagnostic_records`` lands with ``run_id=""`` and
    ``course_id=null``, so a failed build cannot be traced to its task.
    """
    from app.platform.agents.runtime.diagnostic_context import (
        DiagnosticContext,
        current_diagnostic_context,
    )

    run_id = f"prep_initial_{build_task_id}" if build_task_id else f"prep_initial_{uuid.uuid4().hex[:12]}"
    trace_id = f"trace_{uuid.uuid4().hex[:16]}"
    token = current_diagnostic_context.set(DiagnosticContext(
        run_id=run_id,
        trace_id=trace_id,
        course_id=str(course_id),
    ))
    try:
        return await awaitable
    finally:
        current_diagnostic_context.reset(token)


@dataclass
class InitialCoursePrepService:
    """Build the initial course draft only after the Agent completes all stages."""

    # Optional sentence-level LLM reviewer for coalesced evidence units.  When
    # omitted, the service reuses the registered ``ControlledPrepWorkflow``
    # client (the shared ``PrepLLMAdapter``); when neither is available the
    # review is skipped and the original evidence is kept.
    evidence_reviewer: Any | None = None

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
        evidence, evidence_stats = self._build_agent_input(blocks, role_by_run, material_by_run)
        if not evidence:
            raise InitialCoursePreparationError("课程材料没有可用于智能备课的有效文本")

        course = session.get(Course, course_id)
        course_positioning = (
            course.description if course and course.description else course.title if course else "课程材料驱动的教学设计"
        )
        # Release the read/write transaction before any LLM wait: the
        # sentence-level evidence review and the controlled workflow must not
        # hold the SQLite transaction open while waiting on the network.
        session.commit()
        active_workflow = workflow or controlled_prep_workflow

        async def _review_and_run() -> tuple[Any, list[EvidenceReference], list[str]]:
            reviewed, review_warnings = await self._review_evidence(evidence)
            request = ControlledPrepInput(
                evidence=reviewed,
                course_positioning=course_positioning,
                style=TeachingStyleConfig(level="beginner", tone="conversational", language="zh-CN"),
            )
            prepared = (
                await active_workflow.run(request)
                if on_stage is None
                else await active_workflow.run(request, on_stage=on_stage)
            )
            return prepared, reviewed, review_warnings

        prepared, reviewed_evidence, review_warnings = await _run_prep_with_diagnostic_context(
            course_id=course_id,
            build_task_id=build_task_id,
            awaitable=_review_and_run(),
        )
        if on_stage is not None:
            outcome = on_stage("persisting", 95, None)
            if outcome is not None:
                await outcome
        prepared = self._expand_prepared_evidence(prepared, reviewed_evidence)
        by_block_id = {block.block_id: block for block in blocks}
        prepared["outline"], filled_titles = self._fill_empty_outline_titles(
            prepared["outline"],
            by_block_id,
        )
        self._validate_initial_outline(prepared["outline"])

        result = DraftAssetResult(
            course_id=course_id,
            run_id=f"corpus:{corpus_snapshot_id}",
            material_version_id=None,
            corpus_snapshot_id=corpus_snapshot_id,
        )
        if evidence_stats.sampled:
            result.warnings.append(
                "PREP_EVIDENCE_SAMPLED: corpus exceeded the bounded initial-prep evidence budget "
                f"({evidence_stats.selected_units}/{evidence_stats.total_units} units, "
                f"{evidence_stats.selected_chars}/{evidence_stats.total_chars} chars selected)"
            )
        result.warnings.extend(list(prepared.get("warnings") or []))
        result.warnings.extend(list(review_warnings))
        if filled_titles:
            result.warnings.append(
                f"PREP_EMPTY_TITLE_FALLBACK: {len(filled_titles)} 个节点标题为空或过短，"
                "已用材料文本兜底，请教师进入结构页复核标题"
            )
        if replace_unreviewed_initial:
            self._archive_unreviewed_initial_draft(session, course_id=course_id)
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
    ) -> tuple[list[EvidenceReference], EvidenceInputStats]:
        """Coalesce tiny parse blocks and select bounded, traceable evidence.

        OCR and layout parsers often emit dozens of tiny blocks per page. A
        one-block-per-evidence policy exhausts the evidence-count limit long
        before it consumes the text budget. Adjacent blocks are therefore
        merged into stable units while retaining every original block ID.
        """
        material_by_run = material_by_run or {}
        target_chars = max(1, int(settings.PREP_INITIAL_EVIDENCE_UNIT_TARGET_CHARS))
        unit_max_chars = max(
            target_chars,
            int(settings.PREP_INITIAL_EVIDENCE_UNIT_MAX_CHARS),
        )
        all_units: list[EvidenceReference] = []
        current_key: tuple[str, str, int] | None = None
        current_parts: list[str] = []
        current_block_ids: list[str] = []
        current_pages: list[int] = []

        def flush() -> None:
            nonlocal current_parts, current_block_ids, current_pages
            if not current_parts or current_key is None:
                current_parts = []
                current_block_ids = []
                current_pages = []
                return
            role, material, _page = current_key
            text = " ".join(current_parts)
            fingerprint = "\n".join([role, material, *current_block_ids, text])
            evidence_id = f"evg_{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:24]}"
            all_units.append(EvidenceReference(
                evidence_id=evidence_id,
                text=text,
                page=min(current_pages) if current_pages else None,
                page_end=max(current_pages) if current_pages else None,
                block_id=current_block_ids[0] if current_block_ids else None,
                source_block_ids=list(current_block_ids),
                material_version_id=material,
                material_role=role,
            ))
            current_parts = []
            current_block_ids = []
            current_pages = []

        for block in blocks:
            text = " ".join((block.text or "").split())
            if len(text) < 2 or block.semantic_role in {"header", "footer", "page_number"}:
                continue
            role = role_by_run.get(block.run_id, "reference")
            material = material_by_run.get(block.run_id, block.material_version_id or "unknown")
            page = int(block.page_or_slide or block.page_number or 1)
            # Page boundaries are evidence boundaries. Crossing a page here
            # would make a valid citation to one slide/page pull unrelated
            # neighbouring blocks into PPT mappings and source references.
            key = (role, material, page)
            for part in InitialCoursePrepService._split_evidence_text(text, unit_max_chars):
                current_chars = sum(len(value) for value in current_parts) + max(0, len(current_parts) - 1)
                if current_parts and (
                    key != current_key
                    or current_chars + 1 + len(part) > unit_max_chars
                    or (
                        block.block_id not in current_block_ids
                        and len(current_block_ids) >= 500
                    )
                ):
                    flush()
                current_key = key
                current_parts.append(part)
                if block.block_id not in current_block_ids:
                    current_block_ids.append(block.block_id)
                current_pages.append(page)
                current_chars = sum(len(value) for value in current_parts) + max(0, len(current_parts) - 1)
                if current_chars >= target_chars:
                    flush()
        flush()

        total_chars = sum(len(item.text) for item in all_units)
        selected = InitialCoursePrepService._select_evidence_units(
            all_units,
            max_units=max(1, int(settings.PREP_INITIAL_EVIDENCE_MAX_UNITS)),
            max_chars=max(1, int(settings.PREP_INITIAL_EVIDENCE_TOTAL_MAX_CHARS)),
        )
        return selected, EvidenceInputStats(
            total_units=len(all_units),
            selected_units=len(selected),
            total_chars=total_chars,
            selected_chars=sum(len(item.text) for item in selected),
        )

    @staticmethod
    def _split_evidence_text(text: str, limit: int) -> list[str]:
        """Split an oversized parser block near a sentence boundary."""
        remaining = text.strip()
        parts: list[str] = []
        boundary_chars = "。！？；.!?; "
        while len(remaining) > limit:
            lower_bound = max(1, int(limit * 0.7))
            cut = max(remaining.rfind(marker, lower_bound, limit + 1) for marker in boundary_chars)
            if cut < lower_bound:
                cut = limit
            elif remaining[cut] in boundary_chars.strip():
                cut += 1
            parts.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            parts.append(remaining)
        return parts

    @staticmethod
    def _coverage_indices(size: int) -> list[int]:
        """Return a deterministic coarse-to-fine order over a source."""
        if size <= 0:
            return []
        result: list[int] = [0]
        if size == 1:
            return result
        result.append(size - 1)
        queue: list[tuple[int, int]] = [(0, size - 1)]
        seen = set(result)
        while queue:
            left, right = queue.pop(0)
            if right - left <= 1:
                continue
            midpoint = (left + right) // 2
            if midpoint not in seen:
                result.append(midpoint)
                seen.add(midpoint)
            queue.extend([(left, midpoint), (midpoint, right)])
        return result

    @staticmethod
    def _select_evidence_units(
        units: list[EvidenceReference],
        *,
        max_units: int,
        max_chars: int,
    ) -> list[EvidenceReference]:
        """Select longitudinal coverage across every included material."""
        buckets: dict[tuple[str, str], list[EvidenceReference]] = defaultdict(list)
        for item in units:
            buckets[(item.material_role, item.material_version_id or "unknown")].append(item)
        ordered_keys = sorted(
            buckets,
            key=lambda key: (ROLE_PRIORITY.get(key[0], 99), key[1]),
        )
        coverage = {
            key: [buckets[key][index] for index in InitialCoursePrepService._coverage_indices(len(buckets[key]))]
            for key in ordered_keys
        }
        offsets = {key: 0 for key in ordered_keys}
        selected: list[EvidenceReference] = []
        selected_chars = 0
        while len(selected) < max_units and selected_chars < max_chars:
            progressed = False
            for key in ordered_keys:
                offset = offsets[key]
                if offset >= len(coverage[key]):
                    continue
                item = coverage[key][offset]
                offsets[key] = offset + 1
                if selected_chars + len(item.text) > max_chars:
                    continue
                selected.append(item)
                selected_chars += len(item.text)
                progressed = True
                if len(selected) >= max_units or selected_chars >= max_chars:
                    break
            if not progressed:
                break
        return sorted(
            selected,
            key=lambda item: (
                ROLE_PRIORITY.get(item.material_role, 99),
                item.material_version_id or "",
                item.page or 0,
                item.page_end or 0,
                item.evidence_id,
            ),
        )

    async def _review_evidence(
        self,
        evidence: list[EvidenceReference],
    ) -> tuple[list[EvidenceReference], list[str]]:
        """Stage 0: sentence-level LLM review of coalesced evidence units.

        Before segmentation the reviewer deletes near-duplicate, meaningless,
        and garbled sentences from each unit and keeps the rest verbatim.
        Review is best-effort: when it is disabled, no reviewer is available,
        a batch fails, or the whole result is empty, the original evidence is
        kept so the evidence-backed first draft still builds (evidence is
        never silently lost).
        """
        warnings: list[str] = []
        if not int(settings.PREP_INITIAL_EVIDENCE_REVIEW_ENABLED) or not evidence:
            return evidence, warnings
        reviewer = self.evidence_reviewer
        if reviewer is None:
            candidate = getattr(controlled_prep_workflow, "client", None)
            if candidate is not None and hasattr(candidate, "review_evidence"):
                reviewer = candidate
        if reviewer is None:
            return evidence, warnings

        per_unit_texts = [self._split_sentences(item.text) for item in evidence]
        batches = self._chunk_review_batches(evidence, per_unit_texts)
        reviewed: list[EvidenceReference] = []
        sentences_before = sum(len(texts) for texts in per_unit_texts)
        sentences_after = 0
        dropped_units = 0
        review_failures = 0
        for units, texts in batches:
            kept_batch: list[list[str]] | None = None
            try:
                wire = await reviewer.review_evidence(list(units))
                kept_batch = self._slice_batch(wire, texts)
            except Exception as exc:  # noqa: BLE001 - review must never break the build
                logger.warning("evidence review batch failed, keeping original evidence: %s", exc)
                review_failures += 1
            for batch_index, (unit, original_sentences) in enumerate(zip(units, texts, strict=True)):
                if kept_batch is None:
                    reviewed.append(unit)
                    sentences_after += len(original_sentences)
                    continue
                kept_sentences = kept_batch[batch_index]
                if not kept_sentences:
                    dropped_units += 1
                    continue
                new_text = " ".join(kept_sentences)
                if len(new_text) < 2:
                    dropped_units += 1
                    continue
                reviewed.append(unit.model_copy(update={"text": new_text}))
                sentences_after += len(kept_sentences)
        if not reviewed:
            warnings.append("PREP_EVIDENCE_REVIEW_EMPTY: 句级审查结果为空，已回退保留全部原始证据")
            return evidence, warnings
        if review_failures:
            warnings.append(
                f"PREP_EVIDENCE_REVIEW_PARTIAL: {review_failures} 个证据审查批次失败，已保留该批原始证据"
            )
        if sentences_after < sentences_before:
            warnings.append(
                f"PREP_EVIDENCE_REVIEWED: 句级审查共删去 {sentences_before - sentences_after} 个句子、"
                f"{dropped_units} 条整段证据，其余证据按原样保留"
            )
        return reviewed, warnings

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split evidence text into clean sentence candidates.

        Splits on CJK/Latin sentence-final punctuation (keeping the
        punctuation attached), strips OCR ordering prefixes such as ``3.`` or
        ``(1)``, and drops empty fragments.  The result is the server-side
        reference used to validate the reviewer's kept sentences.
        """
        fragments = re.split(r"(?<=[。！？；.!?;])", (text or "").strip())
        sentences: list[str] = []
        for fragment in fragments:
            cleaned = re.sub(
                r"^\s*(?:\d{1,3}\s*[.、．)）]|[（(]\s*\d{1,3}\s*[)）]|[①②③④⑤⑥⑦⑧⑨⑩])\s*",
                "",
                fragment,
            ).strip()
            cleaned = " ".join(cleaned.split())
            if cleaned:
                sentences.append(cleaned)
        return sentences

    @staticmethod
    def _chunk_review_batches(
        evidence: list[EvidenceReference],
        per_unit_texts: list[list[str]],
    ) -> list[tuple[list[EvidenceReference], list[list[str]]]]:
        """Split evidence into bounded review batches (unit count and chars)."""
        max_units = max(1, int(settings.PREP_INITIAL_EVIDENCE_REVIEW_BATCH_UNITS))
        max_chars = max(1, int(settings.PREP_INITIAL_EVIDENCE_REVIEW_BATCH_CHARS))
        batches: list[tuple[list[EvidenceReference], list[list[str]]]] = []
        current_units: list[EvidenceReference] = []
        current_texts: list[list[str]] = []
        current_chars = 0
        for item, sentences in zip(evidence, per_unit_texts, strict=True):
            if current_units and (
                len(current_units) >= max_units
                or current_chars + len(item.text) > max_chars
            ):
                batches.append((current_units, current_texts))
                current_units = []
                current_texts = []
                current_chars = 0
            current_units.append(item)
            current_texts.append(sentences)
            current_chars += len(item.text)
        if current_units:
            batches.append((current_units, current_texts))
        return batches

    @staticmethod
    def _slice_batch(
        wire: Any,
        per_unit_texts: list[list[str]],
    ) -> list[list[str]]:
        """Align and validate the reviewer's output against the input batch.

        The wire schema is positionally aligned with the input units, but a
        real model may omit items, add extra items, or rewrite a kept
        sentence.  Only sentences that appear verbatim in the unit's original
        text are accepted; a skipped unit keeps every original sentence; an
        explicitly empty unit is dropped as the reviewer intended.
        """
        items = list(getattr(wire, "items", []) or [])
        aligned: list[list[str]] = []
        for index, original_sentences in enumerate(per_unit_texts):
            if index >= len(items):
                aligned.append(list(original_sentences))
                continue
            raw = [
                " ".join(sentence.split())
                for sentence in items[index].sentences
                if " ".join(sentence.split())
            ]
            if not raw:
                # The reviewer deliberately deleted the whole unit.
                aligned.append([])
                continue
            original_text = "".join(original_sentences)
            normalized = [
                " ".join(sentence.split())
                for sentence in original_sentences
            ]
            kept: list[str] = []
            seen: set[str] = set()
            for sentence in raw:
                if sentence in seen:
                    continue
                if sentence in original_text or sentence in normalized:
                    kept.append(sentence)
                    seen.add(sentence)
            # Nothing validated -> this unit's review failed; keep the source.
            aligned.append(kept if kept else list(original_sentences))
        return aligned

    @staticmethod
    def _expand_prepared_evidence(
        prepared: dict[str, Any],
        evidence: list[EvidenceReference],
    ) -> dict[str, Any]:
        """Replace LLM-facing evidence-unit IDs with canonical block IDs."""
        expansion = {
            item.evidence_id: (
                list(item.source_block_ids)
                or ([item.block_id] if item.block_id else [item.evidence_id])
            )
            for item in evidence
        }

        def expand(values: list[str]) -> list[str]:
            result: list[str] = []
            seen: set[str] = set()
            for value in values:
                for block_id in expansion.get(value, [value]):
                    if block_id not in seen:
                        seen.add(block_id)
                        result.append(block_id)
            return result

        outline = prepared["outline"]
        expanded_candidates = [
            candidate.model_copy(update={"evidence_ids": expand(candidate.evidence_ids)})
            for candidate in outline.candidates
        ]
        expanded_prerequisites = [
            prerequisite.model_copy(update={"evidence_ids": expand(prerequisite.evidence_ids)})
            for prerequisite in outline.prerequisites
        ]
        expanded_outline = outline.model_copy(update={
            "candidates": expanded_candidates,
            "prerequisites": expanded_prerequisites,
        })

        expanded_scripts = [
            script.model_copy(update={
                "evidence_ids": expand(script.evidence_ids),
                "paragraph_evidence": [expand(values) for values in script.paragraph_evidence],
            })
            for script in prepared["scripts"]
        ]
        expanded_verifications = [
            verification.model_copy(update={
                "findings": [
                    finding.model_copy(update={"evidence_ids": expand(finding.evidence_ids)})
                    for finding in verification.findings
                ],
            })
            for verification in prepared["verifications"]
        ]
        return {
            **prepared,
            "outline": expanded_outline,
            "scripts": expanded_scripts,
            "verifications": expanded_verifications,
        }

    _NODE_TYPE_LABEL = {
        "chapter": "未命名章节",
        "section": "未命名单元",
        "knowledge_point": "未命名知识点",
    }

    @classmethod
    def _fill_empty_outline_titles(
        cls,
        outline: Any,
        by_block_id: dict[str, Any],
    ) -> tuple[Any, list[str]]:
        """Deterministically backfill empty or too-short outline titles.

        OCR-heavy courseware frequently emits icon/page-number fragments
        (e.g. ``\\uf06c``, ``P3``) that the planner may copy into a node title
        verbatim; such titles fail the teaching-title gate and would abort the
        whole build.  This pass replaces them with a real evidence-block text
        snippet, or a type-based placeholder when no usable block exists, and
        keeps the title unique within its parent so the hard gate below still
        passes.  Every filled title is reported back as a teacher-review
        warning instead of silently changing the draft.
        """
        used_by_parent: dict[str | None, set[str]] = defaultdict(set)
        for candidate in outline.candidates:
            title = " ".join(candidate.title.split())
            if len(title) >= 2:
                used_by_parent[candidate.parent_candidate_id].add(title.casefold())

        filled: list[str] = []
        candidates: list[Any] = []
        for candidate in outline.candidates:
            title = " ".join(candidate.title.split())
            if len(title) >= 2:
                candidates.append(candidate)
                continue
            fallback = cls._candidate_fallback_title(candidate, by_block_id)
            if fallback is None:
                fallback = cls._NODE_TYPE_LABEL.get(candidate.node_type, "未命名知识点")
            parent = candidate.parent_candidate_id
            unique = fallback
            suffix = 2
            while unique.casefold() in used_by_parent.setdefault(parent, set()):
                unique = f"{fallback}{suffix}"
                suffix += 1
            used_by_parent[parent].add(unique.casefold())
            candidates.append(candidate.model_copy(update={"title": unique}))
            filled.append(unique)
        return outline.model_copy(update={"candidates": candidates}), filled

    @staticmethod
    def _candidate_fallback_title(candidate: Any, by_block_id: dict[str, Any]) -> str | None:
        """Derive a real teaching-title candidate from the node's evidence blocks."""
        for block_id in candidate.evidence_ids:
            block = by_block_id.get(block_id)
            if block is None:
                continue
            raw = " ".join((block.text or "").split())
            # Strip PPT private-use-area icons, control chars and common
            # OCR fragment markers so ``\\uf06c`` / ``P3`` do not leak in.
            cleaned = "".join(
                ch for ch in raw
                if ord(ch) >= 32 and not 0xE000 <= ord(ch) <= 0xF8FF
            )
            cleaned = " ".join(cleaned.split())
            if len(cleaned) < 2 or cleaned.isdigit():
                continue
            if re.match(r"^(图|表)\s*\d", cleaned) or cleaned.count("-") >= 3:
                continue
            return cleaned[:40]
        return None

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
            brief = title if len(title) <= 40 else f"{title[:40]}…"
            if "\n" in candidate.title:
                raise InitialCoursePreparationError(
                    f"智能备课结果包含不适合作为教学标题的内容（标题包含换行：{brief}）"
                )
            if len(title) < 2:
                raise InitialCoursePreparationError("智能备课结果包含不适合作为教学标题的内容（标题为空或过短）")
            if len(title) > 120:
                raise InitialCoursePreparationError(
                    f"智能备课结果包含不适合作为教学标题的内容（标题超过 120 字上限：{brief}）"
                )
            if re.match(r"^(图|表)\s*\d", title) or title.count("-") >= 3:
                raise InitialCoursePreparationError(
                    f"智能备课结果将图注或部件清单误作教学标题：{brief}"
                )
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
        scripts_by_candidate = {script.candidate_id: script for script in prepared["scripts"]}
        if len(scripts_by_candidate) != len(prepared["scripts"]):
            raise InitialCoursePreparationError("智能备课返回了重复的讲稿候选")
        verdict_by_candidate = {
            script.candidate_id: verification.verdict
            for script, verification in zip(prepared["scripts"], prepared["verifications"], strict=True)
        }
        expected_candidate_ids = {
            candidate.candidate_id
            for candidate in prepared["outline"].candidates
            if candidate.node_type == "knowledge_point"
        }
        unexpected_candidate_ids = set(scripts_by_candidate) - expected_candidate_ids
        if unexpected_candidate_ids:
            raise InitialCoursePreparationError("智能备课返回了不属于知识点的讲稿候选")
        issue_code_by_candidate = {
            candidate_id: "SCRIPT_OUTPUT_MISSING"
            for candidate_id in expected_candidate_ids - set(scripts_by_candidate)
        }
        for candidate_id, verdict in verdict_by_candidate.items():
            if verdict == "failed":
                issue_code_by_candidate[candidate_id] = "EVIDENCE_VERIFICATION_FAILED"
        count = 0
        for candidate_id in sorted(expected_candidate_ids):
            node = candidate_to_node.get(candidate_id)
            if node is None:
                raise InitialCoursePreparationError("讲稿候选无法映射到课程知识点")
            issue_code = issue_code_by_candidate.get(candidate_id)
            if issue_code:
                session.add(CourseScriptCoverageIssue(
                    course_id=course_id,
                    build_task_id=build_task_id,
                    script_version_id=version.script_version_id,
                    outline_node_id=node.outline_node_id,
                    issue_code=issue_code,
                ))
                result.script_coverage_issues.append({
                    "outline_node_id": node.outline_node_id,
                    "code": issue_code,
                })
                continue
            script = scripts_by_candidate[candidate_id]
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
        if count + len(result.script_coverage_issues) != len(expected_candidate_ids):
            raise InitialCoursePreparationError("讲稿持久化后的知识点覆盖统计不一致")
        result.script_node_count = count
        if result.script_coverage_issues:
            result.warnings.append(
                f"SCRIPT_COVERAGE_INCOMPLETE: {len(result.script_coverage_issues)} 个知识点需要教师手工补齐讲稿"
            )

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
