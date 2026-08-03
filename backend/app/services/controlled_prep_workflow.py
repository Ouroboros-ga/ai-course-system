"""Controlled, evidence-first course-preparation workflow.

The service keeps the LLM at the proposal boundary. It never mutates course
outline or script records; the existing teacher decision endpoint applies the
resulting PatchProposal.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from app.platform.agents.contracts.llm import StructuredOutputError
from app.schemas.controlled_prep import (
    ControlledPrepInput,
    EvidenceReference,
    EvidenceSegmenterResult,
    EvidenceVerifierResult,
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

    async def segment_evidence(self, request: ControlledPrepInput) -> EvidenceSegmenterResult:
        def validate(result: EvidenceSegmenterResult) -> EvidenceSegmenterResult:
            self._assert_evidence_ids(result, request.evidence)
            return result

        return await self._run_stage(
            "segment_evidence",
            self._call_stage("segment_evidence", request),
            validate,
        )

    async def plan_outline(
        self,
        request: ControlledPrepInput,
        segments: EvidenceSegmenterResult,
    ) -> OutlinePlannerResult:
        def validate(result: OutlinePlannerResult) -> OutlinePlannerResult:
            self._assert_evidence_ids(result, request.evidence)
            return result

        return await self._run_stage(
            "plan_outline",
            self._call_stage("plan_outline", request, segments),
            validate,
        )

    async def write_script(
        self,
        request: ControlledPrepInput,
        outline: OutlinePlannerResult,
        candidate_id: str,
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

        return await self._run_stage(
            "write_script",
            self._call_stage("write_script", request, outline, candidate_id),
            validate,
        )

    async def write_scripts_batch(
        self,
        request: ControlledPrepInput,
        outline: OutlinePlannerResult,
        candidates: list[Any],
    ) -> list[TeachingScriptNodeDraft]:
        """Generate all first-round scripts in one structured LLM request."""
        candidate_ids = {candidate.candidate_id for candidate in candidates}
        async def validate(scripts: list[TeachingScriptNodeDraft]) -> list[TeachingScriptNodeDraft]:
            returned_ids = {script.candidate_id for script in scripts}
            if returned_ids != candidate_ids:
                raise StructuredOutputError("script_writer_batch 返回的 candidate_id 与请求不一致")
            for script in scripts:
                self._assert_evidence_ids(script, request.evidence)
            return scripts

        return await self._run_stage(
            "write_scripts_batch",
            self._call_stage("write_scripts_batch", request, outline, candidates),
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

    async def _call_stage(self, stage: str, *args: Any) -> Any:
        """Call one stage and attach its name to errors for diagnosis."""
        try:
            return await self._stage_method(stage)(*args)
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
            result = await result_awaitable
            validated = validator(result)
            if hasattr(validated, "__await__"):
                return await validated
            return validated
        except Exception as error:  # noqa: BLE001 - preserve original type
            if not getattr(error, "stage", ""):
                try:
                    setattr(error, "stage", stage)
                except Exception:  # pragma: no cover - unusual exception type
                    pass
            raise

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
        outline = await self.plan_outline(request, segments)
        max_kp = 24
        knowledge = [item for item in outline.candidates if item.node_type == "knowledge_point"]
        if len(knowledge) > max_kp:
            by_id = {item.candidate_id: item for item in outline.candidates}
            keep_ids = {item.candidate_id for item in knowledge[:max_kp]}
            pending_parents = [item.parent_candidate_id for item in knowledge[:max_kp] if item.parent_candidate_id]
            while pending_parents:
                parent_id = pending_parents.pop()
                if not parent_id or parent_id in keep_ids:
                    continue
                keep_ids.add(parent_id)
                parent = by_id.get(parent_id)
                if parent and parent.parent_candidate_id:
                    pending_parents.append(parent.parent_candidate_id)
            kept_candidates = [item for item in outline.candidates if item.candidate_id in keep_ids]
            kept_ids = {item.candidate_id for item in kept_candidates}
            outline = outline.model_copy(update={
                "candidates": kept_candidates,
                "prerequisites": [
                    item for item in outline.prerequisites
                    if item.knowledge_point_candidate_id in kept_ids
                ],
            })
        await emit("outline", 30, outline)
        candidates = [item for item in outline.candidates if item.node_type == "knowledge_point"]
        if candidate_id:
            candidates = [item for item in candidates if item.candidate_id == candidate_id]
        if not candidates:
            raise ValueError("no knowledge point candidate selected")
        if len(candidates) == 1:
            scripts = [await self.write_script(request, outline, candidates[0].candidate_id)]
        else:
            scripts = await self.write_scripts_batch(request, outline, candidates)
        await emit("scripts", 80, scripts)
        verifications = []
        for index, script in enumerate(scripts, start=1):
            verifications.append(await self.verify_script(request, script))
            await emit("verification", 80 + int(15 * index / max(1, len(scripts))), verifications[-1])
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
