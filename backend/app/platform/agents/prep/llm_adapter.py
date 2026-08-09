"""PrepLLMAdapter: adapts StructuredLLMPort to the Prep Service LLM surface.

This is an Adapter (interface conversion), not a Port. It sits between the
low-level ``StructuredLLMPort`` (``contracts/llm.py``) and the Prep Agent's
business layer, exposing the seven LLM operations the Prep pipelines need:

    - segment_evidence        (Initial pipeline, stage 1)
    - plan_outline            (Initial pipeline, stage 2)
    - write_script            (Initial pipeline, stage 3, single)
    - write_scripts_batch     (Initial pipeline, stage 3, batch)
    - verify_script           (Initial pipeline, stage 4)
    - plan_incremental        (Incremental pipeline)
    - optimize_ppt_mappings   (PPT mapping pipeline)

Design notes:
    - ``ControlledPrepWorkflow`` calls these typed stage methods directly.
      There is intentionally no generic ``chat`` bridge: every preparation
      request follows the same prompt, schema, fallback, and audit path.
    - Service-layer schema types (``EvidenceSegmenterResult``,
      ``OutlinePlannerResult``, ``TeachingScriptNodeDraft``,
      ``TeachingScriptBatchResult``, ``EvidenceVerifierResult``,
      ``AgentPlan``) live in ``app.schemas.controlled_prep`` and
      ``app.services.course_prep_agent_service``. They are imported only
      under ``TYPE_CHECKING`` to avoid runtime circular imports; the adapter
      resolves the concrete model inside each method via a local import and
      returns it. Final schema/evidence validation stays in the Service /
      ``PrepPlanValidator``.

The adapter does NOT:
    - Re-implement evidence-ID hard gating (that stays in the Service /
      ``PrepPlanValidator``).
    - Own retry/repair policy beyond what ``StructuredLLMPort`` provides.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Mapping

from ..contracts.llm import (
    LLMOptions,
    LLMResponse,
    LLMTraceContext,
    StructuredLLMPort,
)
from app.core.config import settings
from .prompts import (
    EVIDENCE_REDUCER_PROMPT,
    EVIDENCE_SEGMENTER_PROMPT,
    EVIDENCE_VERIFIER_PROMPT,
    INCREMENTAL_PLANNER_PROMPT,
    PREP_ACTION_PLANNER_PROMPT,
    STRUCTURE_PLANNER_PROMPT,
    OUTLINE_PLANNER_PROMPT,
    PPT_MAPPING_OPTIMIZER_PROMPT,
    SCRIPT_WRITER_BATCH_PROMPT,
    SCRIPT_WRITER_PROMPT,
    PromptSpec,
)

if TYPE_CHECKING:  # pragma: no cover - import-only types
    from app.schemas.controlled_prep import (
        ControlledPrepInput,
        EvidenceSegmenterResult,
        EvidenceSegment,
        EvidenceSegmentMapResult,
        EvidenceVerifierResult,
        OutlineCandidate,
        OutlinePlannerResult,
        TeachingScriptNodeDraft,
    )
    from app.services.course_prep_agent_service import AgentPlan

logger = logging.getLogger(__name__)


class PrepLLMAdapter:
    """Adapts a ``StructuredLLMPort`` to the Prep Service LLM surface.

    Each method:
        1. Resolves the matching ``PromptSpec`` from ``prompts.py``.
        2. Builds ``messages`` (system + user).
        3. Calls ``self._llm.complete(...)``.
        4. Returns the structured result (parsed when an ``output_schema`` is
           supplied, otherwise parsed from the raw content).

    The adapter is stateless beyond the injected LLM port; callers pass
    per-request data each invocation. Optional ``run_id`` / ``trace_id``
    keyword arguments populate ``LLMTraceContext`` for audit/metrics.
    """

    def __init__(
        self,
        *,
        structured_llm: StructuredLLMPort,
        agent_type: str = "prep",
    ) -> None:
        self._llm = structured_llm
        self._agent_type = agent_type

    # -- private helpers -------------------------------------------------

    def _trace(
        self,
        node: str,
        purpose: str,
        *,
        run_id: str = "",
        trace_id: str = "",
    ) -> LLMTraceContext:
        """Build an ``LLMTraceContext`` for one LLM call."""
        return LLMTraceContext(
            run_id=run_id,
            trace_id=trace_id,
            agent_type=self._agent_type,
            node=node,
            purpose=purpose,
        )

    @staticmethod
    def _options(
        spec: PromptSpec,
        *,
        temperature: float = 0.2,
        provider_options: Mapping[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> LLMOptions:
        """Build ``LLMOptions`` from a ``PromptSpec``.

        Provider options are deliberately supplied only by the adapter for
        bounded structured tasks.  They are not persisted with prompts or
        responses.
        """
        return LLMOptions(
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=max(1, int(settings.COURSE_BUILD_STAGE_TIMEOUT_SECONDS)),
            response_format={"type": "json_object"},
            prompt_version=spec.version,
            provider_options=dict(provider_options or {}),
        )

    @staticmethod
    def _structured_prep_provider_options(action: str | None) -> Mapping[str, Any] | None:
        """Disable reasoning for bounded Prep JSON calls.

        ``thinking={type: disabled}`` is the DeepSeek-compatible request
        switch.  The captured raw request lets a local debug run verify that
        the gateway received it; we deliberately do not replace the configured
        model with a different model name behind the teacher's back.
        """
        if action not in {
            "initial",
            "organize_structure",
            "optimize_all_scripts",
            "optimize_node_script",
        }:
            return None
        return {"thinking": {"type": "disabled"}}

    @staticmethod
    def _request_context(request: "ControlledPrepInput") -> Mapping[str, Any]:
        return {
            "course_positioning": request.course_positioning,
            "style": request.style.model_dump(mode="json"),
        }

    @staticmethod
    def _evidence_for_ids(
        request: "ControlledPrepInput",
        evidence_ids: set[str],
    ) -> list[Mapping[str, Any]]:
        return [
            item.llm_payload()
            for item in request.evidence
            if item.evidence_id in evidence_ids
        ]

    @staticmethod
    def _outline_context(
        outline: "OutlinePlannerResult",
        candidate_ids: set[str],
    ) -> Mapping[str, Any]:
        by_id = {item.candidate_id: item for item in outline.candidates}
        keep_ids = set(candidate_ids)
        pending = [by_id[item_id].parent_candidate_id for item_id in candidate_ids if item_id in by_id]
        while pending:
            parent_id = pending.pop()
            if not parent_id or parent_id in keep_ids:
                continue
            keep_ids.add(parent_id)
            parent = by_id.get(parent_id)
            if parent and parent.parent_candidate_id:
                pending.append(parent.parent_candidate_id)
        return {
            "candidates": [
                item.model_dump(mode="json")
                for item in outline.candidates
                if item.candidate_id in keep_ids
            ],
            "prerequisites": [
                item.model_dump(mode="json")
                for item in outline.prerequisites
                if item.knowledge_point_candidate_id in candidate_ids
            ],
        }

    @staticmethod
    def _messages(spec: PromptSpec, user_prompt: str) -> list[Mapping[str, str]]:
        """Build the ``[system, user]`` message list for one call."""
        return [
            {"role": "system", "content": spec.system_template},
            {"role": "user", "content": user_prompt},
        ]

    async def _complete(
        self,
        *,
        spec: PromptSpec,
        user_prompt: str,
        node: str,
        purpose: str,
        output_schema: type | None = None,
        run_id: str = "",
        trace_id: str = "",
        provider_options: Mapping[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Invoke the underlying ``StructuredLLMPort.complete``."""
        return await self._llm.complete(
            messages=self._messages(spec, user_prompt),
            output_schema=output_schema,
            options=self._options(
                spec,
                provider_options=provider_options,
                max_tokens=max_tokens,
            ),
            trace_context=self._trace(node, purpose, run_id=run_id, trace_id=trace_id),
        )

    @staticmethod
    def _parsed_or_validate(response: LLMResponse, model: type) -> Any:
        """Return ``response.parsed`` when present, else validate ``content``."""
        if response.parsed is not None:
            return response.parsed
        return model.model_validate_json(response.content)

    # -- Initial pipeline ------------------------------------------------

    async def segment_evidence(
        self,
        request: "ControlledPrepInput",
        *,
        run_id: str = "",
        trace_id: str = "",
        max_tokens: int | None = None,
    ) -> "EvidenceSegmentMapResult":
        """Stage 1 Map: segment one bounded evidence batch."""
        from app.schemas.controlled_prep import EvidenceSegmentMapResult as _Result

        user_payload = {
            **self._request_context(request),
            "constraints": {
                "max_segments": 12,
                "return_json_only": True,
                "evidence_ids_must_come_from_input": True,
            },
            "evidence": [item.llm_payload() for item in request.evidence],
        }
        response = await self._complete(
            spec=EVIDENCE_SEGMENTER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="segment_evidence",
            purpose="segment course evidence",
            output_schema=_Result,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=(
                int(settings.PREP_INITIAL_EVIDENCE_MAP_MAX_TOKENS)
                if max_tokens is None else max_tokens
            ),
            run_id=run_id,
            trace_id=trace_id,
        )
        return self._parsed_or_validate(response, _Result)

    async def reduce_evidence(
        self,
        segments: list["EvidenceSegment"],
        *,
        run_id: str = "",
        trace_id: str = "",
        max_tokens: int | None = None,
    ) -> "EvidenceSegmenterResult":
        """Stage 1 Reduce: merge summaries without resending source text."""
        from app.schemas.controlled_prep import EvidenceSegmenterResult as _Result

        user_payload = {
            "constraints": {
                "max_segments": 32,
                "return_json_only": True,
                "evidence_ids_must_come_from_input": True,
            },
            "segments": [item.model_dump(mode="json") for item in segments],
        }
        response = await self._complete(
            spec=EVIDENCE_REDUCER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="segment_evidence_reduce",
            purpose="reduce course evidence summaries",
            output_schema=_Result,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=(
                int(settings.PREP_INITIAL_EVIDENCE_REDUCE_MAX_TOKENS)
                if max_tokens is None else max_tokens
            ),
            run_id=run_id,
            trace_id=trace_id,
        )
        return self._parsed_or_validate(response, _Result)

    async def plan_outline(
        self,
        request: "ControlledPrepInput",
        segments: "EvidenceSegmenterResult",
        *,
        run_id: str = "",
        trace_id: str = "",
    ) -> "OutlinePlannerResult":
        """Stage 2: plan the chapter -> section -> knowledge_point outline tree."""
        from app.schemas.controlled_prep import OutlinePlannerResult as _Result

        user_payload = {
            **self._request_context(request),
            "constraints": {
                "max_knowledge_points": int(settings.PREP_INITIAL_MAX_KNOWLEDGE_POINTS),
                "max_total_nodes": int(settings.PREP_INITIAL_MAX_OUTLINE_NODES),
                "return_json_only": True,
            },
            "segments": segments.model_dump(mode="json"),
        }
        response = await self._complete(
            spec=OUTLINE_PLANNER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="plan_outline",
            purpose="plan course outline",
            output_schema=_Result,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=int(settings.PREP_INITIAL_OUTLINE_MAX_TOKENS),
            run_id=run_id,
            trace_id=trace_id,
        )
        return self._parsed_or_validate(response, _Result)

    async def write_script(
        self,
        request: "ControlledPrepInput",
        outline: "OutlinePlannerResult",
        candidate_id: str,
        *,
        run_id: str = "",
        trace_id: str = "",
        max_tokens: int | None = None,
    ) -> "TeachingScriptNodeDraft":
        """Stage 3 (single): write a TeachingScriptNode for one knowledge point."""
        from app.schemas.controlled_prep import TeachingScriptNodeDraft as _Result

        candidate = next(
            item for item in outline.candidates if item.candidate_id == candidate_id
        )
        evidence_ids = set(candidate.evidence_ids)
        user_payload = {
            **self._request_context(request),
            "outline": self._outline_context(outline, {candidate_id}),
            "candidate_id": candidate_id,
            "evidence": self._evidence_for_ids(request, evidence_ids),
        }
        response = await self._complete(
            spec=SCRIPT_WRITER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="write_script",
            purpose="write single teaching script",
            output_schema=_Result,
            run_id=run_id,
            trace_id=trace_id,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=max_tokens,
        )
        return self._parsed_or_validate(response, _Result)

    async def write_scripts_batch(
        self,
        request: "ControlledPrepInput",
        outline: "OutlinePlannerResult",
        candidates: list["OutlineCandidate"],
        *,
        run_id: str = "",
        trace_id: str = "",
        max_tokens: int | None = None,
    ) -> list["TeachingScriptNodeDraft"]:
        """Stage 3 (batch): write TeachingScriptNodes for multiple knowledge points.

        Uses ``TeachingScriptBatchResult`` as the output schema and returns
        its ``scripts`` list, mirroring ``ControlledPrepWorkflow``.
        """
        from app.schemas.controlled_prep import TeachingScriptBatchResult as _Batch

        candidate_ids = {candidate.candidate_id for candidate in candidates}
        evidence_ids = {
            evidence_id
            for candidate in candidates
            for evidence_id in candidate.evidence_ids
        }
        user_payload = {
            **self._request_context(request),
            "outline": self._outline_context(outline, candidate_ids),
            "candidates": [c.model_dump(mode="json") for c in candidates],
            "evidence": self._evidence_for_ids(request, evidence_ids),
        }
        response = await self._complete(
            spec=SCRIPT_WRITER_BATCH_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="write_scripts_batch",
            purpose="write batch teaching scripts",
            output_schema=_Batch,
            run_id=run_id,
            trace_id=trace_id,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=max_tokens,
        )
        batch = self._parsed_or_validate(response, _Batch)
        return list(batch.scripts)

    async def verify_script(
        self,
        request: "ControlledPrepInput",
        script: "TeachingScriptNodeDraft",
        *,
        run_id: str = "",
        trace_id: str = "",
    ) -> "EvidenceVerifierResult":
        """Stage 4: verify that the script's conclusions are evidence-backed."""
        from app.schemas.controlled_prep import EvidenceVerifierResult as _Result

        evidence_ids = set(script.evidence_ids)
        for paragraph_ids in script.paragraph_evidence:
            evidence_ids.update(paragraph_ids)
        user_payload = {
            **self._request_context(request),
            "script": script.model_dump(mode="json"),
            "evidence": self._evidence_for_ids(request, evidence_ids),
        }
        response = await self._complete(
            spec=EVIDENCE_VERIFIER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="verify_script",
            purpose="verify script evidence",
            output_schema=_Result,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=int(settings.PREP_INITIAL_VERIFIER_MAX_TOKENS),
            run_id=run_id,
            trace_id=trace_id,
        )
        return self._parsed_or_validate(response, _Result)

    # -- Incremental pipeline --------------------------------------------

    async def plan_incremental(
        self,
        payload: Any,
        *,
        run_id: str = "",
        trace_id: str = "",
    ) -> "AgentPlan":
        """Incremental pipeline: produce a controlled edit plan (``AgentPlan``).

        ``payload`` is the Service-level incremental planning payload
        (instruction + editable outline/scripts + confirmed evidence). Its
        exact shape is owned by ``CoursePrepAgentService``; the adapter
        serialises it for the user message when it is not already a string.
        """
        from app.services.course_prep_agent_service import AgentPlan as _Result, StructurePlan as _StructureResult

        user_prompt = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False, default=str)
        )
        action = payload.get("batch_action") if isinstance(payload, Mapping) else None
        result_schema = _StructureResult if action == "organize_structure" else _Result
        response = await self._complete(
            spec=(
                STRUCTURE_PLANNER_PROMPT
                if action == "organize_structure"
                else PREP_ACTION_PLANNER_PROMPT
                if action
                else INCREMENTAL_PLANNER_PROMPT
            ),
            user_prompt=user_prompt,
            node="plan_incremental",
            purpose="incremental edit planning",
            output_schema=result_schema,
            # Structure planning is intentionally sparse and must return a
            # small JSON object. DeepSeek otherwise spends the entire output
            # budget on hidden reasoning and returns no JSON (finish_reason=
            # length). Disable reasoning for this bounded edit compiler when
            # the gateway supports the OpenAI-compatible switch.
            provider_options=self._structured_prep_provider_options(action),
            # A script batch carries rewritten text.  A structure plan is
            # normally sparse, yet it must also accommodate a genuine
            # course-wide title cleanup without truncating its JSON.
            max_tokens=(
                int(settings.PREP_STRUCTURE_MAX_TOKENS) if action == "organize_structure"
                else int(settings.PREP_SCRIPT_MAX_TOKENS) if action in {"optimize_all_scripts", "optimize_node_script"}
                else None
            ),
            run_id=run_id,
            trace_id=trace_id,
        )
        return self._parsed_or_validate(response, result_schema)

    # -- PPT mapping pipeline --------------------------------------------

    async def optimize_ppt_mappings(
        self,
        blocks: Any,
        nodes: Any,
        mappings: Any,
        *,
        run_id: str = "",
        trace_id: str = "",
    ) -> list[Any]:
        """PPT mapping pipeline: suggest knowledge-point mappings per PPT page.

        Returns a list of mapping-suggestion dicts. The concrete
        ``PptMappingSuggestion`` schema is not yet defined in
        ``app.schemas``; the Service validates/normalises the raw payload, so
        this method returns ``list[Any]`` until the schema lands. The
        ``PPT_MAPPING_OPTIMIZER_PROMPT`` declares the
        ``{"suggestions": [...]}`` envelope, which is parsed here.
        """
        user_payload = {
            "blocks": blocks,
            "nodes": nodes,
            "mappings": mappings,
        }
        response = await self._complete(
            spec=PPT_MAPPING_OPTIMIZER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False, default=str),
            node="optimize_ppt_mappings",
            purpose="optimize ppt mappings",
            output_schema=None,
            run_id=run_id,
            trace_id=trace_id,
        )
        try:
            parsed = json.loads(response.content)
        except (TypeError, ValueError):
            logger.warning("PrepLLMAdapter.optimize_ppt_mappings: non-JSON response")
            return []
        if isinstance(parsed, dict):
            suggestions = parsed.get("suggestions", [])
        elif isinstance(parsed, list):
            suggestions = parsed
        else:
            suggestions = []
        return list(suggestions)


__all__ = ["PrepLLMAdapter"]
