"""Controlled, evidence-first course-preparation workflow.

The service keeps the LLM at the proposal boundary. It never mutates course
outline or script records; the existing teacher decision endpoint applies the
resulting PatchProposal.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.common.llm_client import LLMClient, Message, llm_client
from app.schemas.controlled_prep import (
    ControlledPrepInput,
    EvidenceFinding,
    EvidenceReference,
    EvidenceSegmenterResult,
    EvidenceVerifierResult,
    OutlinePlannerResult,
    PatchOperationDraft,
    PatchProposalDraft,
    TeachingScriptNodeDraft,
    TeachingStyleConfig,
)

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredOutputError(ValueError):
    """Raised when an LLM response cannot satisfy the stage contract."""


class ControlledPrepWorkflow:
    def __init__(self, client: Any = llm_client, max_retries: int = 1):
        self.client = client
        self.max_retries = max(0, max_retries)

    async def _structured_call(
        self,
        stage: str,
        output_model: type[ModelT],
        system_prompt: str,
        user_prompt: str,
    ) -> ModelT:
        schema = output_model.model_json_schema()
        correction = ""
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt + correction),
            ]
            try:
                response = await self.client.chat(
                    messages,
                    temperature=0.2,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": f"controlled_prep_{stage}",
                            "strict": True,
                            "schema": schema,
                        },
                    },
                )
                raw = response.content if hasattr(response, "content") else response
                if not isinstance(raw, str):
                    raise StructuredOutputError(f"{stage}: LLM response is not text")
                return output_model.model_validate_json(raw)
            except (ValidationError, json.JSONDecodeError, StructuredOutputError) as exc:
                last_error = exc
                correction = (
                    "\n\n上一次输出未通过严格校验。只返回符合给定 JSON Schema 的 JSON，"
                    f"不要 Markdown，不要解释。校验错误：{str(exc)[:500]}"
                )
                logger.warning("Structured stage %s failed on attempt %s", stage, attempt + 1)
            except Exception as exc:
                last_error = exc
                logger.exception("Structured stage %s failed", stage)
                break
        raise StructuredOutputError(f"{stage} output validation failed: {last_error}") from last_error

    def _evidence_text(self, evidence: list[EvidenceReference]) -> str:
        return "\n".join(
            f"[{item.evidence_id}] page={item.page or '-'}: {item.text}"
            for item in evidence
        )

    async def segment_evidence(self, request: ControlledPrepInput) -> EvidenceSegmenterResult:
        result = await self._structured_call(
            "evidence_segmenter",
            EvidenceSegmenterResult,
            "你是 EvidenceSegmenter。只根据材料确定主题边界、标题、例子和练习。每个 evidence_id 必须来自输入。",
            f"材料：\n{request.source_text}\n\n可引用 Evidence：\n{self._evidence_text(request.evidence)}",
        )
        self._assert_evidence_ids(result, request.evidence)
        return result

    async def plan_outline(
        self,
        request: ControlledPrepInput,
        segments: EvidenceSegmenterResult,
    ) -> OutlinePlannerResult:
        result = await self._structured_call(
            "outline_planner",
            OutlinePlannerResult,
            "你是 OutlinePlanner。生成 section、knowledge_point 和 prerequisite 候选，不生成讲稿。所有候选必须引用输入 Evidence。",
            f"Evidence：\n{self._evidence_text(request.evidence)}\n\n分段结果：\n{segments.model_dump_json()}",
        )
        self._assert_evidence_ids(result, request.evidence)
        return result

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
        prerequisites = [
            item.prerequisite_title
            for item in outline.prerequisites
            if item.knowledge_point_candidate_id == candidate_id
        ]
        result = await self._structured_call(
            "script_writer",
            TeachingScriptNodeDraft,
            "你是 ScriptWriter。只为一个知识点生成 TeachingScriptNode。段落之间用两个换行分隔，paragraph_evidence 必须逐段对应，不能写无证据课程事实。",
            (
                f"课程定位：{request.course_positioning}\n"
                f"教学风格：{request.style.model_dump_json()}\n"
                f"知识点：{candidate.model_dump_json()}\n"
                f"前置知识：{json.dumps(prerequisites, ensure_ascii=False)}\n"
                f"Evidence：\n{self._evidence_text(request.evidence)}"
            ),
        )
        self._assert_evidence_ids(result, request.evidence)
        if result.candidate_id != candidate_id:
            raise StructuredOutputError("script_writer returned a different candidate_id")
        return result

    async def verify_script(
        self,
        request: ControlledPrepInput,
        script: TeachingScriptNodeDraft,
    ) -> EvidenceVerifierResult:
        result = await self._structured_call(
            "evidence_verifier",
            EvidenceVerifierResult,
            "你是 EvidenceVerifier。逐项检查结论和段落是否被 Evidence 支撑。无法支撑就标记 needs_review 或 failed，不得替作者补证据。",
            f"TeachingScriptNode：\n{script.model_dump_json()}\n\nEvidence：\n{self._evidence_text(request.evidence)}",
        )
        self._assert_evidence_ids(result, request.evidence)
        return result

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
    ) -> dict[str, Any]:
        segments = await self.segment_evidence(request)
        outline = await self.plan_outline(request, segments)
        candidates = [item for item in outline.candidates if item.node_type == "knowledge_point"]
        if candidate_id:
            candidates = [item for item in candidates if item.candidate_id == candidate_id]
        if not candidates:
            raise ValueError("no knowledge point candidate selected")
        scripts = [
            await self.write_script(request, outline, candidate.candidate_id)
            for candidate in candidates
        ]
        verifications = [await self.verify_script(request, script) for script in scripts]
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
