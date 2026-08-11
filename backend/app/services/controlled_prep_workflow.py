"""Controlled, evidence-first course-preparation workflow.

The service keeps the LLM at the proposal boundary. It never mutates course
outline or script records; the existing teacher decision endpoint applies the
resulting PatchProposal.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from app.core.config import settings
from app.platform.agents.contracts.llm import StructuredOutputError
from app.schemas.controlled_prep import (
    ControlledPrepInput,
    CourseSkeletonBudget,
    EvidenceReference,
    EvidenceSegment,
    EvidenceSegmentMapResult,
    EvidenceSegmenterResult,
    EvidenceVerifierResult,
    OutlineCandidate,
    OutlinePlannerResult,
    PatchOperationDraft,
    PatchProposalDraft,
    TeachingScriptNodeDraft,
)

logger = logging.getLogger(__name__)


class CourseBuildStageTimeout(StructuredOutputError):
    """A single preparation stage exceeded its configured wall-clock budget."""


class CourseBuildCancelled(StructuredOutputError):
    """The corpus/build lease changed while an LLM stage was in flight."""


class EvidenceAttemptBudget:
    """Bound provider calls made while organizing one course corpus."""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self.used = 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise StructuredOutputError(
                "initial evidence preparation exceeded its bounded LLM call budget",
                reason_code="PREP_EVIDENCE_CALL_BUDGET_EXCEEDED",
                stage="segment_evidence",
                attempts=self.used,
            )
        self.used += 1


class ControlledPrepWorkflow:
    def __init__(self, client: Any | None = None, max_retries: int = 1):
        # ``max_retries`` remains accepted for constructor compatibility.  The
        # registered StructuredLLMPort owns repair/retry policy.
        del max_retries
        self.client = client

    def _stage_method(self, stage: str) -> Callable[..., Awaitable[Any]]:
        """Resolve an operation from the registered prep stage adapter.

        Course preparation must use the structured Prep port.  A generic
        ``client.chat`` fallback creates a second workflow, bypasses provider
        capability handling, and was the source of incompatible
        ``response_format`` retries.
        """
        method = getattr(self.client, stage, None) if self.client is not None else None
        if not callable(method):
            raise StructuredOutputError(
                "PREP_STRUCTURED_PORT_UNAVAILABLE: 智能备课结构化端口未注册"
            )
        return method

    @staticmethod
    async def _run_concurrent(coroutines: list[Awaitable[Any]]) -> list[Any]:
        """Run coroutines concurrently and cancel in-flight siblings on failure.

        ``asyncio.gather`` alone leaves sibling tasks running in the background
        when one child raises, so a budget-exceeded error leaked live LLM
        requests until they finished on their own.  This helper cancels the
        survivors, awaits their shutdown, and re-raises the first original
        exception so ``except StructuredOutputError`` paths keep working.
        """
        tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
        try:
            return await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def segment_evidence(self, request: ControlledPrepInput) -> EvidenceSegmenterResult:
        """Map bounded evidence batches, then hierarchically reduce them."""
        chunks = self._chunk_evidence(request)
        concurrency = max(1, int(settings.PREP_INITIAL_EVIDENCE_CONCURRENCY))
        semaphore = asyncio.Semaphore(concurrency)
        budget = EvidenceAttemptBudget(int(settings.PREP_INITIAL_EVIDENCE_MAX_ATTEMPTS))
        mapped = await self._run_concurrent([
            self._segment_evidence_group(
                request,
                chunk,
                path=str(index),
                semaphore=semaphore,
                budget=budget,
            )
            for index, chunk in enumerate(chunks)
        ])
        segments = [segment for group in mapped for segment in group]
        if len(mapped) == 1:
            return EvidenceSegmenterResult(segments=segments)
        return await self._reduce_evidence_hierarchically(
            request,
            segments,
            semaphore=semaphore,
            budget=budget,
        )

    @staticmethod
    def _evidence_payload_chars(
        request: ControlledPrepInput,
        evidence: list[EvidenceReference],
    ) -> int:
        payload = {
            "course_positioning": request.course_positioning,
            "style": request.style.model_dump(mode="json"),
            "evidence": [item.llm_payload() for item in evidence],
        }
        return len(json.dumps(payload, ensure_ascii=False))

    def _chunk_evidence(self, request: ControlledPrepInput) -> list[list[EvidenceReference]]:
        text_limit = max(1, int(settings.PREP_INITIAL_EVIDENCE_MAP_TEXT_CHARS))
        payload_limit = max(text_limit, int(settings.PREP_INITIAL_EVIDENCE_MAP_PAYLOAD_CHARS))
        chunks: list[list[EvidenceReference]] = []
        current: list[EvidenceReference] = []
        current_text_chars = 0
        for item in request.evidence:
            candidate = [*current, item]
            candidate_text_chars = current_text_chars + len(item.text)
            if current and (
                candidate_text_chars > text_limit
                or self._evidence_payload_chars(request, candidate) > payload_limit
            ):
                chunks.append(current)
                current = []
                current_text_chars = 0
            current.append(item)
            current_text_chars += len(item.text)
        if current:
            chunks.append(current)
        max_chunks = max(1, int(settings.PREP_INITIAL_EVIDENCE_MAP_MAX_CHUNKS))
        if len(chunks) > max_chunks:
            raise StructuredOutputError(
                f"initial evidence requires {len(chunks)} map chunks; limit is {max_chunks}",
                reason_code="PREP_EVIDENCE_CHUNK_LIMIT_EXCEEDED",
                stage="segment_evidence",
                attempts=len(chunks),
            )
        return chunks

    async def _segment_evidence_group(
        self,
        request: ControlledPrepInput,
        evidence: list[EvidenceReference],
        *,
        path: str,
        semaphore: asyncio.Semaphore,
        budget: EvidenceAttemptBudget,
        retry_tokens: int | None = None,
    ) -> list[EvidenceSegment]:
        subset = request.model_copy(update={"source_text": "", "evidence": evidence})

        def validate(result: EvidenceSegmentMapResult) -> EvidenceSegmentMapResult:
            self._assert_evidence_ids(result, evidence)
            if len(result.segments) > 12:
                raise StructuredOutputError(
                    "evidence map returned more than 12 local segments",
                    reason_code="structured_output_invalid",
                    stage="segment_evidence",
                )
            return result

        try:
            budget.take()
            kwargs = {} if retry_tokens is None else {"max_tokens": retry_tokens}
            async with semaphore:
                result = await self._run_stage(
                    "segment_evidence",
                    self._call_stage("segment_evidence", subset, **kwargs),
                    validate,
                )
        except StructuredOutputError as error:
            if error.reason_code != "MODEL_OUTPUT_TRUNCATED":
                raise
            if len(evidence) > 1:
                midpoint = len(evidence) // 2
                left, right = await self._run_concurrent([
                    self._segment_evidence_group(
                        request,
                        evidence[:midpoint],
                        path=f"{path}L",
                        semaphore=semaphore,
                        budget=budget,
                    ),
                    self._segment_evidence_group(
                        request,
                        evidence[midpoint:],
                        path=f"{path}R",
                        semaphore=semaphore,
                        budget=budget,
                    ),
                ])
                return [*left, *right]
            retry_limit = max(
                int(settings.PREP_INITIAL_EVIDENCE_MAP_MAX_TOKENS),
                int(settings.PREP_INITIAL_EVIDENCE_MAP_RETRY_MAX_TOKENS),
            )
            if retry_tokens is None:
                return await self._segment_evidence_group(
                    request,
                    evidence,
                    path=f"{path}R",
                    semaphore=semaphore,
                    budget=budget,
                    retry_tokens=retry_limit,
                )
            raise
        return [
            segment.model_copy(update={"segment_id": f"map_{path}_{index}"})
            for index, segment in enumerate(result.segments, start=1)
        ]

    @staticmethod
    def _segment_payload_chars(segments: list[EvidenceSegment]) -> int:
        # Size groups by the payload the model actually receives.  The Reduce
        # wire format deliberately excludes server-side evidence ids, so they
        # must not inflate group sizing here either; this mirrors
        # ``PrepLLMAdapter._segment_llm_payload`` and keeps evidence
        # backfill/audit untouched on the service side.
        payload = {"segments": [
            {
                key: value
                for key, value in item.model_dump(mode="json").items()
                if key != "evidence_ids"
            }
            for item in segments
        ]}
        return len(json.dumps(payload, ensure_ascii=False))

    def _chunk_segment_summaries(
        self,
        segments: list[EvidenceSegment],
    ) -> list[list[EvidenceSegment]]:
        payload_limit = max(1, int(settings.PREP_INITIAL_EVIDENCE_MAP_PAYLOAD_CHARS))
        chunks: list[list[EvidenceSegment]] = []
        current: list[EvidenceSegment] = []
        for segment in segments:
            candidate = [*current, segment]
            if current and self._segment_payload_chars(candidate) > payload_limit:
                chunks.append(current)
                current = []
            current.append(segment)
        if current:
            chunks.append(current)
        return chunks

    async def _reduce_evidence_group(
        self,
        request: ControlledPrepInput,
        segments: list[EvidenceSegment],
        *,
        path: str,
        semaphore: asyncio.Semaphore,
        budget: EvidenceAttemptBudget,
        lean: bool = False,
        preferred_target: int | None = None,
        hard_limit: int | None = None,
    ) -> list[EvidenceSegment]:
        def validate(result: EvidenceSegmenterResult) -> EvidenceSegmenterResult:
            self._assert_evidence_ids(result, request.evidence)
            return result

        async def invoke() -> EvidenceSegmenterResult:
            budget.take()
            async with semaphore:
                return await self._run_stage(
                    "segment_evidence_reduce",
                    self._call_stage(
                        "reduce_evidence",
                        segments,
                        max_tokens=int(settings.PREP_INITIAL_EVIDENCE_REDUCE_MAX_TOKENS),
                        lean=lean,
                        preferred_target=preferred_target,
                    ),
                    validate,
                )

        def accepted(output_n: int) -> bool:
            # Real progress means the group actually shrank AND landed at or
            # under the hard safety ceiling.  ``preferred_target`` is only the
            # ideal; missing it by a few segments is still legitimate progress
            # (e.g. 34 -> 10 when the preferred is 9 and the hard limit is 17).
            if preferred_target is None or hard_limit is None:
                return True
            return output_n < len(segments) and output_n <= hard_limit

        try:
            result = await invoke()
        except StructuredOutputError as error:
            if error.reason_code != "MODEL_OUTPUT_TRUNCATED" or len(segments) <= 1:
                raise
            midpoint = len(segments) // 2
            left, right = await self._run_concurrent([
                self._reduce_evidence_group(
                    request,
                    segments[:midpoint],
                    path=f"{path}L",
                    semaphore=semaphore,
                    budget=budget,
                    lean=lean,
                    preferred_target=preferred_target,
                    hard_limit=hard_limit,
                ),
                self._reduce_evidence_group(
                    request,
                    segments[midpoint:],
                    path=f"{path}R",
                    semaphore=semaphore,
                    budget=budget,
                    lean=lean,
                    preferred_target=preferred_target,
                    hard_limit=hard_limit,
                ),
            ])
            return [*left, *right]
        output_n = len(result.segments)
        if accepted(output_n):
            return [
                segment.model_copy(update={"segment_id": f"reduce_{path}_{index}"})
                for index, segment in enumerate(result.segments, start=1)
            ]
        # One targeted retry for a group that made no real progress (either it
        # did not shrink or it stayed above the hard ceiling).  A second miss
        # is an accurate non-convergence error rather than a silent multi-level
        # budget drain.
        retry_reason = "no_shrinkage" if output_n >= len(segments) else "over_hard_limit"
        logger.warning(
            "Reduce group %s missed its safety ceiling (input=%d preferred=%s "
            "hard=%s output=%d); retrying once",
            path,
            len(segments),
            preferred_target,
            hard_limit,
            output_n,
        )
        result = await invoke()
        output_n = len(result.segments)
        if not accepted(output_n):
            compression_ratio = (output_n / len(segments)) if segments else 0.0
            raise StructuredOutputError(
                f"reduce group {path} made no sufficient progress "
                f"(level/group={path}, input={len(segments)}, "
                f"preferred_target={preferred_target}, hard_limit={hard_limit}, "
                f"output={output_n}, compression_ratio={compression_ratio:.2f}, "
                f"retry_reason={retry_reason}, budget_used={budget.used})",
                reason_code="PREP_EVIDENCE_REDUCE_NON_CONVERGENT",
                stage="segment_evidence_reduce",
                attempts=budget.used,
            )
        return [
            segment.model_copy(update={"segment_id": f"reduce_{path}_{index}"})
            for index, segment in enumerate(result.segments, start=1)
        ]

    async def _reduce_evidence_hierarchically(
        self,
        request: ControlledPrepInput,
        segments: list[EvidenceSegment],
        *,
        semaphore: asyncio.Semaphore,
        budget: EvidenceAttemptBudget,
    ) -> EvidenceSegmenterResult:
        ratio = max(0.05, float(settings.PREP_INITIAL_EVIDENCE_REDUCE_RATIO))
        hard_ratio = max(ratio, float(settings.PREP_INITIAL_EVIDENCE_REDUCE_HARD_RATIO))
        max_levels = max(1, int(settings.PREP_INITIAL_EVIDENCE_REDUCE_MAX_LEVELS))
        current = segments
        for level in range(max_levels):
            groups = self._chunk_segment_summaries(current)
            final_level = len(groups) == 1
            reduced = await self._run_concurrent([
                self._reduce_evidence_group(
                    request,
                    group,
                    path=f"{level}_{index}",
                    semaphore=semaphore,
                    budget=budget,
                    # Only the last level re-adds examples/exercises and is
                    # exempt from the convergence targets; every intermediate
                    # level receives an ideal (preferred) ceiling of
                    # ceil(n * ratio) and a hard safety ceiling of
                    # ceil(n * hard_ratio).  Real progress is accepted even
                    # when the ideal is missed (34 -> 10 with preferred 9);
                    # only no-shrinkage or above-hard-ceiling groups retry and
                    # fail with PREP_EVIDENCE_REDUCE_NON_CONVERGENT.  A
                    # single-segment group is a pass-through.
                    lean=not final_level,
                    preferred_target=(
                        None
                        if final_level or len(group) == 1
                        else max(1, min(32, math.ceil(len(group) * ratio)))
                    ),
                    hard_limit=(
                        None
                        if final_level or len(group) == 1
                        else max(1, min(32, math.ceil(len(group) * hard_ratio)))
                    ),
                )
                for index, group in enumerate(groups)
            ])
            flattened = [segment for group in reduced for segment in group]
            if len(groups) == 1:
                if len(flattened) <= 32:
                    return EvidenceSegmenterResult(segments=flattened)
                # The final group truncated and bisection concatenated two
                # <=32-segment responses.  One more merge pass squeezes the
                # result under the EvidenceSegmenterResult cap instead of
                # failing the whole build with a schema error.
                current = flattened
                continue
            if all(len(group) == 1 for group in groups):
                raise StructuredOutputError(
                    f"reduce level {level} contains only single-segment groups; "
                    f"no further compression is possible ({len(flattened)} segments)",
                    reason_code="PREP_EVIDENCE_REDUCE_NON_CONVERGENT",
                    stage="segment_evidence_reduce",
                    attempts=budget.used,
                )
            current = flattened
        raise StructuredOutputError(
            f"evidence summaries could not be reduced within {max_levels} bounded levels "
            f"(remaining {len(current)} segments after the last level)",
            reason_code="PREP_EVIDENCE_REDUCE_NON_CONVERGENT",
            stage="segment_evidence_reduce",
            attempts=budget.used,
        )

    async def plan_outline(
        self,
        request: ControlledPrepInput,
        segments: EvidenceSegmenterResult,
    ) -> tuple[OutlinePlannerResult, list[str]]:
        """Plan the course tree with a four-level recovery ladder.

        Returns ``(outline, warnings)``.  Recovery order:
        1. Normal outline generation (structured port + JSON auto-repair).
        2. If the result is over-budget or has an invalid tree, one
           "compact course skeleton" call with the same port.
        3. If the compacted result still lacks knowledge points, deterministic
           leaf-section knowledge-point backfill.
        4. If no usable tree exists at all, a deterministic skeleton compiled
           from the evidence segment titles (no model, no fabricated evidence).

        Only step 4 writes a draft when the model could not produce a valid
        tree at all; it is marked ``PREP_OUTLINE_DETERMINISTIC_FALLBACK`` so the
        teacher knows the structure is system-generated and needs review.
        """
        budget = CourseSkeletonBudget.for_evidence_segment_count(
            len(segments.segments)
        )
        request = request.model_copy(update={"skeleton_budget": budget})

        def validate(result: OutlinePlannerResult) -> OutlinePlannerResult:
            self._assert_evidence_ids(result, request.evidence)
            return self._validate_outline_tree(result)

        async def invoke() -> OutlinePlannerResult:
            return await self._run_stage(
                "plan_outline",
                self._call_stage("plan_outline", request, segments),
                validate,
            )

        warnings: list[str] = []
        outline: OutlinePlannerResult | None = None
        active_budget = budget
        compact_attempted = False

        async def recover_compact(reason: str) -> OutlinePlannerResult | None:
            nonlocal active_budget, compact_attempted
            compact_attempted = True
            try:
                recovered = await self._compact_outline_recovery(
                    request, segments, validate
                )
            except StructuredOutputError as error:
                if error.reason_code != "structured_output_invalid":
                    raise
                logger.warning(
                    "PREP_OUTLINE_COMPACT_RECOVERY_FAILED: compact outline "
                    "recovery remained invalid (%s)",
                    reason,
                )
                warnings.append(
                    "PREP_OUTLINE_COMPACT_RECOVERY_FAILED: 压缩课程骨架仍不符合"
                    "结构契约，系统已切换到确定性保底生成。"
                )
                return None
            active_budget = self._compact_skeleton_budget(budget)
            warnings.append(
                f"PREP_OUTLINE_COMPACTED: {reason}，系统已执行一次压缩课程骨架恢复。"
            )
            return recovered

        try:
            outline = await invoke()
        except StructuredOutputError as error:
            if error.reason_code != "structured_output_invalid":
                raise
            # JSON auto-repair already failed inside the port; try one compact
            # skeleton call before falling through to deterministic compile.
            outline = await recover_compact(
                "大纲首次返回不合法"
            )

        if (
            outline is not None
            and self._is_outline_within_budget(outline, active_budget)
            and self._has_knowledge_point(outline)
        ):
            return outline, warnings

        # An over-budget result gets exactly one compact skeleton call.
        if (
            outline is not None
            and not compact_attempted
            and not self._is_outline_within_budget(outline, budget)
        ):
            outline = await recover_compact("大纲超出骨架预算")
            if (
                outline is not None
                and self._is_outline_within_budget(outline, active_budget)
                and self._has_knowledge_point(outline)
            ):
                return outline, warnings

        # Still missing knowledge points: deterministic leaf backfill.
        if outline is not None and not self._has_knowledge_point(outline):
            try:
                backfill_warnings = self._backfill_knowledge_points(
                    outline, active_budget
                )
                self._validate_outline_tree(outline)
                if not self._is_outline_within_budget(outline, active_budget):
                    raise StructuredOutputError(
                        "knowledge-point backfill exceeded the active skeleton budget",
                        reason_code="structured_output_invalid",
                        stage="plan_outline",
                    )
                warnings.extend(backfill_warnings)
                return outline, warnings
            except StructuredOutputError:
                pass

        # No usable tree at all: deterministic skeleton from segment titles.
        outline, fallback_warnings = self._compile_deterministic_skeleton(
            request, segments, budget
        )
        warnings.extend(fallback_warnings)
        return outline, warnings

    @staticmethod
    def _compact_skeleton_budget(
        budget: CourseSkeletonBudget,
    ) -> CourseSkeletonBudget:
        """Return a genuinely tighter, internally consistent retry budget."""
        sections = max(1, budget.target_sections // 2)
        knowledge_points = max(1, budget.target_knowledge_points // 2)
        total_nodes = 1 + sections + knowledge_points
        return CourseSkeletonBudget(
            target_sections=sections,
            target_knowledge_points=knowledge_points,
            target_total_nodes=total_nodes,
            max_sections=sections,
            max_knowledge_points=knowledge_points,
            max_total_nodes=total_nodes,
        )

    async def _compact_outline_recovery(
        self,
        request: ControlledPrepInput,
        segments: EvidenceSegmenterResult,
        validate: Callable[[OutlinePlannerResult], OutlinePlannerResult],
    ) -> OutlinePlannerResult:
        """One targeted "compact course skeleton" retry with a tighter budget."""
        compact_budget = self._compact_skeleton_budget(request.skeleton_budget)
        compact_request = request.model_copy(update={"skeleton_budget": compact_budget})

        def validate_compact(result: OutlinePlannerResult) -> OutlinePlannerResult:
            validated = validate(result)
            if not self._is_outline_within_budget(validated, compact_budget):
                raise StructuredOutputError(
                    "compact outline exceeded its tightened skeleton budget",
                    reason_code="structured_output_invalid",
                    stage="plan_outline",
                    schema_name=type(validated).__name__,
                )
            return validated

        return await self._run_stage(
            "plan_outline",
            self._call_stage("plan_outline", compact_request, segments),
            validate_compact,
        )

    @staticmethod
    def _is_outline_within_budget(
        outline: OutlinePlannerResult, budget: CourseSkeletonBudget
    ) -> bool:
        section_count = sum(
            1 for c in outline.candidates if c.node_type == "section"
        )
        kp_count = sum(
            1 for c in outline.candidates if c.node_type == "knowledge_point"
        )
        return (
            len(outline.candidates) <= budget.max_total_nodes
            and section_count <= budget.max_sections
            and kp_count <= budget.max_knowledge_points
        )

    @staticmethod
    def _validate_outline_tree(
        outline: OutlinePlannerResult,
    ) -> OutlinePlannerResult:
        """Enforce the declared chapter -> section -> knowledge-point tree."""
        candidates_by_id: dict[str, OutlineCandidate] = {}
        for candidate in outline.candidates:
            if candidate.candidate_id in candidates_by_id:
                raise StructuredOutputError(
                    f"duplicate outline candidate_id: {candidate.candidate_id}",
                    reason_code="structured_output_invalid",
                    stage="plan_outline",
                )
            candidates_by_id[candidate.candidate_id] = candidate

        if not any(
            candidate.node_type == "chapter" for candidate in outline.candidates
        ):
            raise StructuredOutputError(
                "outline must contain at least one chapter",
                reason_code="structured_output_invalid",
                stage="plan_outline",
            )

        for candidate in outline.candidates:
            if candidate.node_type == "chapter":
                if candidate.parent_candidate_id is not None:
                    raise StructuredOutputError(
                        "chapter candidates cannot have a parent",
                        reason_code="structured_output_invalid",
                        stage="plan_outline",
                    )
                continue

            parent = candidates_by_id.get(candidate.parent_candidate_id or "")
            expected_parent_type = (
                "chapter" if candidate.node_type == "section" else "section"
            )
            if parent is None or parent.node_type != expected_parent_type:
                raise StructuredOutputError(
                    f"{candidate.node_type} candidate '{candidate.candidate_id}' "
                    f"must have a {expected_parent_type} parent",
                    reason_code="structured_output_invalid",
                    stage="plan_outline",
                )
        return outline

    @staticmethod
    def _has_knowledge_point(outline: OutlinePlannerResult) -> bool:
        return any(
            candidate.node_type == "knowledge_point"
            for candidate in outline.candidates
        )

    def _backfill_knowledge_points(
        self,
        outline: OutlinePlannerResult,
        budget: CourseSkeletonBudget,
    ) -> list[str]:
        """Attach a same-title ``knowledge_point`` child to each leaf section.

        Leaf nodes must be sections so the generated points preserve the
        declared three-level hierarchy.  Everything else (titles, parent
        links, programmatically-backfilled evidence) is preserved.
        """
        candidates = outline.candidates
        referenced_as_parent = {
            candidate.parent_candidate_id
            for candidate in candidates
            if candidate.parent_candidate_id
        }
        leaves = [
            candidate for candidate in candidates
            if candidate.node_type == "section"
            and candidate.candidate_id not in referenced_as_parent
        ]
        if not leaves:
            raise StructuredOutputError(
                "outline contains no leaf section to attach a "
                "knowledge point to",
                reason_code="PREP_OUTLINE_NO_KNOWLEDGE_POINTS",
                stage="plan_outline",
            )
        available_nodes = max(0, budget.max_total_nodes - len(candidates))
        max_kp = min(budget.max_knowledge_points, available_nodes)
        leaves = leaves[:max_kp]
        if not leaves:
            raise StructuredOutputError(
                "outline has no remaining skeleton budget for knowledge points",
                reason_code="structured_output_invalid",
                stage="plan_outline",
            )
        existing_ids = {candidate.candidate_id for candidate in candidates}
        new_candidates = list(candidates)
        for index, leaf in enumerate(leaves):
            candidate_id = f"kp_fallback_{index}"
            while candidate_id in existing_ids:
                index += 1
                candidate_id = f"kp_fallback_{index}"
            existing_ids.add(candidate_id)
            new_candidates.append(OutlineCandidate(
                candidate_id=candidate_id,
                node_type="knowledge_point",
                title=leaf.title,
                parent_candidate_id=leaf.candidate_id,
                evidence_ids=list(leaf.evidence_ids),
                rationale=leaf.rationale,
            ))
        outline.candidates = new_candidates
        logger.warning(
            "PREP_OUTLINE_KNOWLEDGE_POINT_BACKFILLED: model returned %d outline "
            "nodes without any knowledge_point; %d leaf node(s) got system "
            "generated knowledge_point children",
            len(candidates),
            len(leaves),
        )
        return [
            f"PREP_OUTLINE_KNOWLEDGE_POINT_BACKFILLED: 大纲模型未生成可讲授知识点，"
            f"系统已为 {len(leaves)} 个叶子章节生成同名知识点保底结构。"
        ]

    def _compile_deterministic_skeleton(
        self,
        request: ControlledPrepInput,
        segments: EvidenceSegmenterResult,
        budget: CourseSkeletonBudget,
    ) -> tuple[OutlinePlannerResult, list[str]]:
        """Compile a course skeleton purely from evidence segment titles.

        This is the last-resort recovery when the model cannot produce any
        valid tree.  It uses only the already-parsed, evidence-bound segment
        titles to build a valid ``chapter -> section -> knowledge_point`` tree:
        it never calls the model, never fabricates evidence, and never leaks
        evidence ids to the model.  The result is marked
        ``PREP_OUTLINE_DETERMINISTIC_FALLBACK`` so the teacher knows the
        structure is system-generated and needs review.
        """
        segment_limit = min(
            budget.target_knowledge_points,
            budget.max_knowledge_points,
            max(1, budget.max_total_nodes - 2),
        )
        segment_items = list(segments.segments)[:segment_limit]
        if not segment_items:
            raise StructuredOutputError(
                "cannot compile a deterministic skeleton without segments",
                reason_code="PREP_OUTLINE_NO_KNOWLEDGE_POINTS",
                stage="plan_outline",
            )

        def local_refs(values: list[str], limit: int) -> list[str]:
            """Keep deterministic fallback evidence local to each segment."""
            result: list[str] = []
            for value in values:
                if value and value not in result:
                    result.append(value)
                if len(result) >= limit:
                    break
            return result

        chapter_refs: list[str] = []
        for segment in segment_items:
            for evidence_id in local_refs(list(segment.evidence_ids), 8):
                if evidence_id not in chapter_refs:
                    chapter_refs.append(evidence_id)
                if len(chapter_refs) >= 24:
                    break
            if len(chapter_refs) >= 24:
                break
        if not chapter_refs:
            raise StructuredOutputError(
                "cannot compile a deterministic skeleton without bound evidence",
                reason_code="PREP_OUTLINE_NO_KNOWLEDGE_POINTS",
                stage="plan_outline",
            )
        candidates: list[OutlineCandidate] = []
        chapter_id = "ch_deterministic_0"
        candidates.append(OutlineCandidate(
            candidate_id=chapter_id,
            node_type="chapter",
            title="课程骨架（系统生成）",
            parent_candidate_id=None,
            evidence_ids=chapter_refs,
            rationale="确定性兜底生成的课程根章节",
        ))
        section_count = min(
            len(segment_items), budget.target_sections, budget.max_sections
        )
        while 1 + section_count + len(segment_items) > budget.max_total_nodes:
            if len(segment_items) > section_count and len(segment_items) > 1:
                segment_items.pop()
            elif section_count > 1:
                section_count -= 1
            else:
                raise StructuredOutputError(
                    "skeleton budget cannot represent the required three-level tree",
                    reason_code="structured_output_invalid",
                    stage="plan_outline",
                )

        group_size, remainder = divmod(len(segment_items), section_count)
        offset = 0
        for section_index in range(section_count):
            size = group_size + (1 if section_index < remainder else 0)
            group = segment_items[offset:offset + size]
            offset += size
            section_refs: list[str] = []
            for segment in group:
                for evidence_id in local_refs(list(segment.evidence_ids), 8):
                    if evidence_id not in section_refs:
                        section_refs.append(evidence_id)
                    if len(section_refs) >= 12:
                        break
                if len(section_refs) >= 12:
                    break
            section_id = f"sec_deterministic_{section_index}"
            section_title = (
                group[0].title
                if len(group) == 1
                else f"{group[0].title}—{group[-1].title}"
            )
            candidates.append(OutlineCandidate(
                candidate_id=section_id,
                node_type="section",
                title=section_title[:300] or f"主题单元 {section_index + 1}",
                parent_candidate_id=chapter_id,
                evidence_ids=section_refs,
                rationale="确定性兜底：按相邻证据分段编组",
            ))
            for segment_index, segment in enumerate(group):
                absolute_index = offset - size + segment_index
                candidates.append(OutlineCandidate(
                    candidate_id=f"kp_deterministic_{absolute_index}",
                    node_type="knowledge_point",
                    title=segment.title[:300] or f"知识点 {absolute_index + 1}",
                    parent_candidate_id=section_id,
                    evidence_ids=local_refs(list(segment.evidence_ids), 8),
                    rationale="确定性兜底：源自证据分段标题",
                ))
        outline = OutlinePlannerResult(candidates=candidates, prerequisites=[])
        self._validate_outline_tree(outline)
        self._assert_evidence_ids(outline, request.evidence)
        if not self._is_outline_within_budget(outline, budget):
            raise StructuredOutputError(
                "deterministic skeleton exceeded its budget",
                reason_code="structured_output_invalid",
                stage="plan_outline",
            )
        logger.warning(
            "PREP_OUTLINE_DETERMINISTIC_FALLBACK: model produced no valid tree; "
            "compiled %d knowledge points from %d evidence segments",
            len(segment_items),
            len(segments.segments),
        )
        return outline, [
            "PREP_OUTLINE_DETERMINISTIC_FALLBACK: 模型未能生成有效课程结构，"
            f"系统已根据 {len(segment_items)} 个证据分段标题确定性编译课程骨架，"
            "该结构为系统保底生成，请教师进入结构页复核。"
        ]

    async def write_script(
        self,
        request: ControlledPrepInput,
        outline: OutlinePlannerResult,
        candidate_id: str,
        *,
        max_tokens: int | None = None,
    ) -> TeachingScriptNodeDraft:
        candidate = next(
            (item for item in outline.candidates if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None or candidate.node_type != "knowledge_point":
            raise ValueError(f"knowledge point candidate not found: {candidate_id}")
        async def validate(result: TeachingScriptNodeDraft) -> TeachingScriptNodeDraft:
            self._assert_evidence_ids(result, request.evidence)
            if result.candidate_id != candidate_id:
                raise StructuredOutputError("script_writer returned a different candidate_id")
            return result

        kwargs = {} if max_tokens is None else {"max_tokens": max_tokens}
        return await self._run_stage(
            "write_script",
            self._call_stage("write_script", request, outline, candidate_id, **kwargs),
            validate,
        )

    async def write_scripts_batch(
        self,
        request: ControlledPrepInput,
        outline: OutlinePlannerResult,
        candidates: list[Any],
        *,
        max_tokens: int | None = None,
    ) -> list[TeachingScriptNodeDraft]:
        """Generate all first-round scripts in one structured LLM request."""
        candidate_ids = {candidate.candidate_id for candidate in candidates}
        async def validate(scripts: list[TeachingScriptNodeDraft]) -> list[TeachingScriptNodeDraft]:
            returned_id_list = [script.candidate_id for script in scripts]
            returned_ids = set(returned_id_list)
            unknown_ids = returned_ids - candidate_ids
            if unknown_ids:
                raise StructuredOutputError("script_writer_batch 返回了未请求的 candidate_id")
            if len(returned_ids) != len(returned_id_list):
                raise StructuredOutputError("script_writer_batch 返回了重复的 candidate_id")
            # A model may validly omit individual scripts in a large batch.
            # Preserve the valid subset; persistence creates a safe coverage
            # issue for each omitted knowledge point instead of discarding the
            # entire teacher-visible draft.
            for script in scripts:
                self._assert_evidence_ids(script, request.evidence)
            return scripts

        kwargs = {} if max_tokens is None else {"max_tokens": max_tokens}
        return await self._run_stage(
            "write_scripts_batch",
            self._call_stage("write_scripts_batch", request, outline, candidates, **kwargs),
            validate,
        )

    async def verify_script(
        self,
        request: ControlledPrepInput,
        script: TeachingScriptNodeDraft,
    ) -> EvidenceVerifierResult:
        def validate(result: EvidenceVerifierResult) -> EvidenceVerifierResult:
            self._assert_evidence_ids(result, request.evidence)
            return result

        return await self._run_stage(
            "verify_script",
            self._call_stage("verify_script", request, script),
            validate,
        )

    async def _call_stage(self, stage: str, *args: Any, **kwargs: Any) -> Any:
        """Call one stage and attach its name to errors for diagnosis."""
        try:
            return await self._stage_method(stage)(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - preserve original type
            if not getattr(error, "stage", ""):
                try:
                    setattr(error, "stage", stage)
                except Exception:  # pragma: no cover - unusual exception type
                    pass
            raise

    async def _run_stage(
        self,
        stage: str,
        result_awaitable: Awaitable[Any],
        validator: Callable[[Any], Any],
    ) -> Any:
        """Attach a stage to both provider and post-parse validation errors."""
        try:
            result = await asyncio.wait_for(
                result_awaitable,
                timeout=max(1, int(settings.COURSE_BUILD_STAGE_TIMEOUT_SECONDS)),
            )
            validated = validator(result)
            if hasattr(validated, "__await__"):
                return await validated
            return validated
        except asyncio.TimeoutError as error:
            raise CourseBuildStageTimeout(
                f"course preparation stage '{stage}' exceeded "
                f"{settings.COURSE_BUILD_STAGE_TIMEOUT_SECONDS} seconds",
                reason_code="llm_call_timeout",
                stage=stage,
            ) from error
        except Exception as error:  # noqa: BLE001 - preserve original type
            if getattr(error, "reason_code", "") == "llm_call_timeout":
                raise CourseBuildStageTimeout(
                    f"course preparation stage '{stage}' exceeded "
                    f"{settings.COURSE_BUILD_STAGE_TIMEOUT_SECONDS} seconds",
                    reason_code="llm_call_timeout",
                    stage=stage,
                ) from error
            if not getattr(error, "stage", ""):
                try:
                    setattr(error, "stage", stage)
                except Exception:  # pragma: no cover - unusual exception type
                    pass
            raise

    # -- initial script chunking (P0/P2) -----------------------------------

    def _group_max_tokens(self) -> int:
        return max(1, int(getattr(settings, "PREP_INITIAL_SCRIPT_MAX_TOKENS", 4096)))

    def _single_script_max_tokens(self) -> int:
        return max(
            int(getattr(settings, "PREP_INITIAL_SCRIPT_SINGLE_MAX_TOKENS", 8192)),
            self._group_max_tokens(),
        )

    @staticmethod
    def _estimate_script_tokens(
        request: ControlledPrepInput,
        candidate: Any,
    ) -> int:
        """Heuristic: a script tracks the length of its bound evidence.

        Chinese text is roughly one token per character for these gateways;
        the fixed overhead reserves room for JSON metadata, claims and the
        paragraph_evidence array.  This is only used to pick group sizes.
        """
        bound_ids = {
            item.evidence_id
            for item in request.evidence
            if item.evidence_id in candidate.evidence_ids
        }
        evidence_len = sum(len(item.text) for item in request.evidence if item.evidence_id in bound_ids)
        return int(evidence_len * 0.9) + 500

    def _group_script_candidates(
        self,
        request: ControlledPrepInput,
        candidates: list[Any],
        *,
        batch_size: int,
        group_max_tokens: int,
    ) -> list[list[Any]]:
        """Pack knowledge points so each request stays inside the output budget.

        A candidate whose own estimate already exceeds the group budget is
        returned as a singleton group; the caller then routes it through the
        single-node ``write_script`` path with the larger budget instead of
        truncating a batch.
        """
        groups: list[list[Any]] = []
        current: list[Any] = []
        current_estimate = 0
        for candidate in candidates:
            estimate = self._estimate_script_tokens(request, candidate)
            if estimate >= group_max_tokens:
                if current:
                    groups.append(current)
                    current = []
                    current_estimate = 0
                groups.append([candidate])
                continue
            if current and (
                len(current) >= batch_size
                or current_estimate + estimate > group_max_tokens
            ):
                groups.append(current)
                current = []
                current_estimate = 0
            current.append(candidate)
            current_estimate += estimate
        if current:
            groups.append(current)
        return groups or [[]]

    async def _write_scripts_chunked(
        self,
        request: ControlledPrepInput,
        outline: OutlinePlannerResult,
        candidates: list[Any],
    ) -> list[TeachingScriptNodeDraft]:
        """Generate first-round scripts in bounded, budget-aware requests."""
        batch_size = max(1, int(getattr(settings, "PREP_INITIAL_SCRIPT_BATCH_SIZE", 3)))
        group_max_tokens = self._group_max_tokens()
        groups = self._group_script_candidates(
            request,
            candidates,
            batch_size=batch_size,
            group_max_tokens=group_max_tokens,
        )
        scripts: list[TeachingScriptNodeDraft] = []
        for group in groups:
            scripts.extend(await self._generate_scripts_for_group(request, outline, group))
        return scripts

    async def _generate_scripts_for_group(
        self,
        request: ControlledPrepInput,
        outline: OutlinePlannerResult,
        group: list[Any],
    ) -> list[TeachingScriptNodeDraft]:
        """Generate one group, splitting it on output truncation.

        A truncated batch is a signal that the completion budget is too small
        for this group.  Splitting in half and retrying keeps the draft
        generation working for legitimately large courses instead of failing
        the whole build; a single node that still truncates falls back to the
        larger single-node budget.
        """
        group_max_tokens = self._group_max_tokens()
        if len(group) == 1 and self._estimate_script_tokens(request, group[0]) >= group_max_tokens:
            # Oversized single node: go straight to the larger single-node
            # budget instead of paying for a batch call that will truncate.
            return [await self.write_script(
                request,
                outline,
                group[0].candidate_id,
                max_tokens=self._single_script_max_tokens(),
            )]
        try:
            return await self.write_scripts_batch(
                request,
                outline,
                group,
                max_tokens=group_max_tokens,
            )
        except StructuredOutputError as error:
            if error.reason_code != "MODEL_OUTPUT_TRUNCATED":
                raise
            logger.warning(
                "Initial script batch truncated (stage=write_scripts_batch, group=%d); "
                "splitting group for retry.",
                len(group),
            )
            if len(group) == 1:
                return [await self.write_script(
                    request,
                    outline,
                    group[0].candidate_id,
                    max_tokens=self._single_script_max_tokens(),
                )]
            midpoint = len(group) // 2
            left = await self._generate_scripts_for_group(request, outline, group[:midpoint])
            right = await self._generate_scripts_for_group(request, outline, group[midpoint:])
            return [*left, *right]

    def compile_patch(
        self,
        request: ControlledPrepInput,
        outline: OutlinePlannerResult,
        scripts: list[TeachingScriptNodeDraft],
        verifications: list[EvidenceVerifierResult],
        existing_outline_ids: dict[str, str] | None = None,
        existing_script_ids: dict[str, str] | None = None,
    ) -> PatchProposalDraft:
        existing_outline_ids = existing_outline_ids or {}
        existing_script_ids = existing_script_ids or {}
        operations: list[PatchOperationDraft] = []
        # Apply parents before children so the teacher decision path can create
        # a real outline tree in one proposal.
        candidates = sorted(
            outline.candidates,
            key=lambda item: (0 if item.parent_candidate_id is None else 1, item.candidate_id),
        )
        for index, candidate in enumerate(candidates):
            node_id = existing_outline_ids.get(candidate.candidate_id)
            target = f"outline:{node_id}:title" if node_id else "outline:new:title"
            after = candidate.title if node_id else json.dumps(
                {
                    "outline_node_id": f"on_agent_{candidate.candidate_id}",
                    "node_type": candidate.node_type,
                    "title": candidate.title,
                    "parent_node_id": (
                        f"on_agent_{candidate.parent_candidate_id}"
                        if candidate.parent_candidate_id else None
                    ),
                    "order_index": index,
                    "source_block_refs": candidate.evidence_ids,
                    "evidence_refs": candidate.evidence_ids,
                },
                ensure_ascii=False,
            )
            operations.append(PatchOperationDraft(
                operation="replace" if node_id else "add",
                target=target,
                after=after,
                reason=candidate.rationale or "来自 OutlinePlanner 的结构候选",
                evidence_refs=candidate.evidence_ids,
            ))

        for script, verification in zip(scripts, verifications, strict=True):
            if verification.verdict == "failed":
                continue
            node_id = existing_script_ids.get(script.candidate_id)
            target = f"script:{node_id}:content" if node_id else "script:new:content"
            after = script.content if node_id else json.dumps(
                {
                    "outline_candidate_id": script.candidate_id,
                    "outline_node_id": (
                        existing_outline_ids.get(script.candidate_id)
                        or f"on_agent_{script.candidate_id}"
                    ),
                    "content": script.content,
                    "style": script.style.level,
                    "evidence_refs": script.evidence_ids,
                },
                ensure_ascii=False,
            )
            operations.append(PatchOperationDraft(
                operation="replace" if node_id else "add",
                target=target,
                after=after,
                reason=f"EvidenceVerifier verdict={verification.verdict}",
                evidence_refs=script.evidence_ids,
            ))
        if not operations:
            raise ValueError("no verifiable operations to compile")
        return PatchProposalDraft(
            reason="五阶段受控备课流水线生成，等待教师逐项审核",
            operations=operations,
        )

    async def run(
        self,
        request: ControlledPrepInput,
        candidate_id: str | None = None,
        existing_outline_ids: dict[str, str] | None = None,
        existing_script_ids: dict[str, str] | None = None,
        on_stage: Callable[[str, int, Any], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        async def emit(stage: str, progress: int, value: Any) -> None:
            if on_stage is None:
                return
            outcome = on_stage(stage, progress, value)
            if outcome is not None:
                await outcome

        await emit("evidence", 0, None)
        segments = await self.segment_evidence(request)
        await emit("evidence", 10, segments)
        warnings: list[str] = []
        outline, outline_warnings = await self.plan_outline(request, segments)
        warnings.extend(outline_warnings)
        budget = request.skeleton_budget
        max_kp = max(1, int(budget.max_knowledge_points))
        max_nodes = max(max_kp, int(budget.max_total_nodes))
        knowledge = [item for item in outline.candidates if item.node_type == "knowledge_point"]
        if len(knowledge) > max_kp or len(outline.candidates) > max_nodes:
            raise StructuredOutputError(
                f"outline exceeded bounded size ({len(knowledge)} knowledge points, "
                f"{len(outline.candidates)} total nodes; budget max_kp={max_kp}, "
                f"max_nodes={max_nodes})",
                reason_code="structured_output_invalid",
                stage="plan_outline",
                schema_name=type(outline).__name__,
            )
        await emit("outline", 30, outline)
        candidates = [item for item in outline.candidates if item.node_type == "knowledge_point"]
        if candidate_id:
            candidates = [item for item in candidates if item.candidate_id == candidate_id]
        if not candidates:
            # Defense in depth: plan_outline now guarantees at least one
            # knowledge point via retry + deterministic backfill, so reaching
            # this point is a hard contract violation, not a user error.
            raise StructuredOutputError(
                "outline produced no knowledge point candidate",
                reason_code="PREP_OUTLINE_NO_KNOWLEDGE_POINTS",
                stage="plan_outline",
            )
        if len(candidates) == 1:
            # A single knowledge point gets the larger single-node budget so a
            # legitimately long script never fails the whole first draft.
            scripts = [await self.write_script(
                request,
                outline,
                candidates[0].candidate_id,
                max_tokens=self._single_script_max_tokens(),
            )]
        else:
            scripts = await self._write_scripts_chunked(request, outline, candidates)
        await emit("scripts", 80, scripts)
        verification_semaphore = asyncio.Semaphore(
            max(1, int(settings.PREP_INITIAL_EVIDENCE_CONCURRENCY))
        )

        async def verify_one(script: TeachingScriptNodeDraft) -> EvidenceVerifierResult:
            async with verification_semaphore:
                return await self.verify_script(request, script)

        verifications = list(await asyncio.gather(*(verify_one(script) for script in scripts)))
        for index, verification in enumerate(verifications, start=1):
            await emit(
                "verification",
                80 + int(15 * index / max(1, len(verifications))),
                verification,
            )
        proposal = self.compile_patch(
            request, outline, scripts, verifications,
            existing_outline_ids=existing_outline_ids,
            existing_script_ids=existing_script_ids,
        )
        return {
            "segments": segments,
            "outline": outline,
            "scripts": scripts,
            "verifications": verifications,
            "proposal": proposal,
            "warnings": warnings,
        }

    @staticmethod
    def _assert_evidence_ids(value: BaseModel, evidence: list[EvidenceReference]) -> None:
        allowed = {item.evidence_id for item in evidence}
        raw = value.model_dump()
        found: set[str] = set()

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if key in {"evidence_id", "evidence_ids", "evidence_refs"}:
                        if isinstance(child, str):
                            found.add(child)
                        elif isinstance(child, list):
                            found.update(str(value) for value in child)
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(raw)
        unknown = found - allowed
        if unknown:
            raise StructuredOutputError(f"unknown evidence ids: {sorted(unknown)}")


controlled_prep_workflow = ControlledPrepWorkflow()
