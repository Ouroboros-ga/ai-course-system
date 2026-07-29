"""Controlled, evidence-first course-preparation workflow.

The service keeps the LLM at the proposal boundary. It never mutates course
outline or script records; the existing teacher decision endpoint applies the
resulting PatchProposal.
"""
from __future__ import annotations

import json
import logging
import asyncio
from typing import Any, Awaitable, Callable, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.common.llm_client import LLMClient, Message, llm_client
from app.core.config import settings
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
    TeachingScriptBatchResult,
    TeachingStyleConfig,
)

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredOutputError(ValueError):
    """Raised when an LLM response cannot satisfy the stage contract."""


class CourseBuildStageTimeout(StructuredOutputError):
    """A single preparation stage exceeded its configured wall-clock budget."""


class CourseBuildCancelled(StructuredOutputError):
    """The corpus/build lease changed while an LLM stage was in flight."""


class ControlledPrepWorkflow:
    def __init__(self, client: Any = llm_client, max_retries: int = 1):
        self.client = client
        self.max_retries = max(0, max_retries)
        # Some OpenAI-compatible gateways implement chat completions but reject
        # every ``response_format`` variant.  Capability is remembered for one
        # workflow run so the four preparation stages do not each make a known
        # failing request.
        self._json_schema_supported: bool | None = None

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
        use_json_schema = self._json_schema_supported is not False
        attempt = 0
        while attempt <= self.max_retries:
            messages = [
                Message(role="system", content=system_prompt),
                Message(
                    role="user",
                    content=(
                        user_prompt + correction
                        + (
                            "\n\n你的服务不支持 response_format。只返回一个合法 JSON 对象，"
                            "不得使用 Markdown、代码围栏或解释文字；它必须严格符合以下 JSON Schema：\n"
                            + json.dumps(schema, ensure_ascii=False)
                            if not use_json_schema else ""
                        )
                    ),
                ),
            ]
            try:
                kwargs: dict[str, Any] = {"temperature": 0.2}
                if use_json_schema:
                    kwargs["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": f"controlled_prep_{stage}",
                            "strict": True,
                            "schema": schema,
                        },
                    }
                try:
                    response = await asyncio.wait_for(
                        self.client.chat(messages, **kwargs),
                        timeout=max(1, int(settings.COURSE_BUILD_STAGE_TIMEOUT_SECONDS)),
                    )
                except asyncio.TimeoutError as exc:
                    raise CourseBuildStageTimeout(
                        f"{stage}: LLM 阶段超时（{settings.COURSE_BUILD_STAGE_TIMEOUT_SECONDS} 秒）"
                    ) from exc
                raw = response.content if hasattr(response, "content") else response
                if not isinstance(raw, str):
                    raise StructuredOutputError(f"{stage}: LLM response is not text")
                result = output_model.model_validate_json(self._json_text(raw))
                if use_json_schema:
                    self._json_schema_supported = True
                return result
            except (ValidationError, json.JSONDecodeError, StructuredOutputError) as exc:
                last_error = exc
                attempt += 1
                if isinstance(exc, CourseBuildStageTimeout):
                    break
                correction = (
                    "\n\n上一次输出未通过严格校验。只返回符合给定 JSON Schema 的 JSON，"
                    f"不要 Markdown，不要解释。校验错误：{str(exc)[:500]}"
                )
                logger.warning("Structured stage %s failed on attempt %s", stage, attempt + 1)
            except Exception as exc:
                if use_json_schema and self._response_format_unsupported(exc):
                    self._json_schema_supported = False
                    use_json_schema = False
                    correction = "\n\n请严格遵循上面的 JSON Schema。"
                    logger.info(
                        "LLM gateway does not support json_schema response_format; "
                        "using prompt-constrained JSON fallback for controlled preparation"
                    )
                    continue
                last_error = exc
                logger.exception("Structured stage %s failed", stage)
                break
        if isinstance(last_error, CourseBuildStageTimeout):
            raise last_error
        raise StructuredOutputError(f"{stage} output validation failed: {last_error}") from last_error

    @staticmethod
    def _response_format_unsupported(exc: Exception) -> bool:
        message = str(exc).lower()
        return "response_format" in message and any(
            marker in message
            for marker in ("unavailable", "unsupported", "not support", "invalid_request")
        )

    @staticmethod
    def _json_text(raw: str) -> str:
        """Accept a single fenced JSON object from a gateway fallback.

        The resulting object still goes through the exact Pydantic contract,
        evidence-ID checks and initial-outline validation below.
        """
        text = raw.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
        return text

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
            # Evidence already carries the selected block text and page.  Do
            # not repeat the complete source corpus here: doing so doubles the
            # request size and can stall compatible gateway implementations.
            f"可引用 Evidence：\n{self._evidence_text(request.evidence)}",
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
            (
                "你是 OutlinePlanner。为首次智能备课生成 chapter → section → knowledge_point "
                "的课程树和 prerequisite 候选，不生成讲稿。chapter 必须无父节点，section 必须归属 "
                "chapter，knowledge_point 必须归属 section。不要把图号、图注、零件清单、整段正文、"
                "页眉页脚或重复标题当作知识点。所有候选必须引用输入 Evidence。"
            ),
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
        candidate_evidence = [
            item for item in request.evidence if item.evidence_id in set(candidate.evidence_ids)
        ] or request.evidence
        result = await self._structured_call(
            "script_writer",
            TeachingScriptNodeDraft,
            "你是 ScriptWriter。只为一个知识点生成 TeachingScriptNode。段落之间用两个换行分隔，paragraph_evidence 必须逐段对应，不能写无证据课程事实。",
            (
                f"课程定位：{request.course_positioning}\n"
                f"教学风格：{request.style.model_dump_json()}\n"
                f"知识点：{candidate.model_dump_json()}\n"
                f"前置知识：{json.dumps(prerequisites, ensure_ascii=False)}\n"
                f"Evidence：\n{self._evidence_text(candidate_evidence)}"
            ),
        )
        self._assert_evidence_ids(result, request.evidence)
        if result.candidate_id != candidate_id:
            raise StructuredOutputError("script_writer returned a different candidate_id")
        return result

    async def write_scripts_batch(
        self,
        request: ControlledPrepInput,
        outline: OutlinePlannerResult,
        candidates: list[Any],
    ) -> list[TeachingScriptNodeDraft]:
        """Generate all first-round scripts in one structured LLM request."""
        candidate_ids = {candidate.candidate_id for candidate in candidates}
        candidate_payload = []
        for candidate in candidates:
            prerequisites = [
                item.prerequisite_title
                for item in outline.prerequisites
                if item.knowledge_point_candidate_id == candidate.candidate_id
            ]
            candidate_evidence = [
                item for item in request.evidence if item.evidence_id in set(candidate.evidence_ids)
            ] or request.evidence
            candidate_payload.append({
                "candidate": candidate.model_dump(),
                "prerequisites": prerequisites,
                "evidence": self._evidence_text(candidate_evidence),
            })
        result = await self._structured_call(
            "script_writer_batch",
            TeachingScriptBatchResult,
            "你是 ScriptWriter。一次为给定的全部知识点生成 TeachingScriptNode。每个脚本必须绑定输入 Evidence；不要生成候选列表之外的知识点。",
            (
                f"课程定位：{request.course_positioning}\n"
                f"教学风格：{request.style.model_dump_json()}\n"
                f"知识点脚本任务：{json.dumps(candidate_payload, ensure_ascii=False)}"
            ),
        )
        returned_ids = {script.candidate_id for script in result.scripts}
        if returned_ids != candidate_ids:
            raise StructuredOutputError("script_writer_batch 返回的 candidate_id 与请求不一致")
        for script in result.scripts:
            self._assert_evidence_ids(script, request.evidence)
        return result.scripts

    async def verify_script(
        self,
        request: ControlledPrepInput,
        script: TeachingScriptNodeDraft,
    ) -> EvidenceVerifierResult:
        script_evidence = [
            item for item in request.evidence if item.evidence_id in set(script.evidence_ids)
        ] or request.evidence
        result = await self._structured_call(
            "evidence_verifier",
            EvidenceVerifierResult,
            "你是 EvidenceVerifier。逐项检查结论和段落是否被 Evidence 支撑。无法支撑就标记 needs_review 或 failed，不得替作者补证据。",
            f"TeachingScriptNode：\n{script.model_dump_json()}\n\nEvidence：\n{self._evidence_text(script_evidence)}",
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
