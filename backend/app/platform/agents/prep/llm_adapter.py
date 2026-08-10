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
from app.platform.agents.contracts.llm import StructuredOutputError
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
    def _script_evidence_max_chars() -> int:
        """Cap the evidence text sent into one script/verifier prompt.

        Outline backfill attributes the whole course corpus to every node, so
        without this bound each script request would carry the entire material.
        """
        return max(1, int(settings.PREP_INITIAL_SCRIPT_EVIDENCE_MAX_CHARS))

    @staticmethod
    def _coarse_to_fine_order(size: int) -> list[int]:
        """Deterministic coarse-to-fine order over a list (0, last, mid, ...)."""
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
    def _bounded_evidence_items(
        request: "ControlledPrepInput",
        evidence_ids: set[str],
        *,
        max_chars: int,
    ) -> list[Any]:
        """Deterministically sample a candidate's evidence for one prompt.

        Outline backfill attributes the whole course corpus to every node, so
        sending ``evidence_ids`` verbatim would push the entire material into
        every script/verifier request.  This samples the allowed set in a
        fixed coarse-to-fine order, bounded by ``max_chars``.
        """
        items = [item for item in request.evidence if item.evidence_id in evidence_ids]
        selected: list[Any] = []
        used = 0
        for index in PrepLLMAdapter._coarse_to_fine_order(len(items)):
            item = items[index]
            if used + len(item.text) > max_chars:
                continue
            selected.append(item)
            used += len(item.text)
        return selected

    @staticmethod
    def _union_evidence_ids(segments: list[Any]) -> list[str]:
        """Deterministic, deduplicated union of the input group's evidence."""
        ids: list[str] = []
        seen: set[str] = set()
        for segment in segments:
            for value in segment.evidence_ids:
                if value not in seen:
                    seen.add(value)
                    ids.append(value)
        return ids

    @staticmethod
    def _cap_evidence_ids(ids: list[str], limit: int = 100) -> list[str]:
        """Deterministically cap a backfilled reference set.

        ``PatchOperationDraft.evidence_refs`` allows at most 100 entries, so
        outline nodes and scripts keep a representative, bounded citation set
        sampled coarse-to-fine instead of the whole course corpus.
        """
        if len(ids) <= limit:
            return list(ids)
        return [ids[index] for index in PrepLLMAdapter._coarse_to_fine_order(len(ids))][:limit]

    @staticmethod
    def _segment_llm_payload(segment: Any) -> dict[str, object]:
        data = segment.model_dump(mode="json")
        data.pop("evidence_ids", None)
        return data

    @staticmethod
    def _candidate_llm_payload(candidate: Any) -> dict[str, object]:
        data = candidate.model_dump(mode="json")
        data.pop("evidence_ids", None)
        return data

    @staticmethod
    def _script_llm_payload(script: Any) -> dict[str, object]:
        data = script.model_dump(mode="json")
        data.pop("evidence_ids", None)
        data.pop("paragraph_evidence", None)
        return data

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
                PrepLLMAdapter._candidate_llm_payload(item)
                for item in outline.candidates
                if item.candidate_id in keep_ids
            ],
            "prerequisites": [
                PrepLLMAdapter._candidate_llm_payload(item)
                for item in outline.prerequisites
                if item.knowledge_point_candidate_id in candidate_ids
            ],
        }

    @staticmethod
    def _backfilled_script(wire: Any, candidate: Any) -> "TeachingScriptNodeDraft":
        """Fill the strict domain script from a model-facing wire draft.

        ``evidence_ids`` come from the bound outline candidate and
        ``paragraph_evidence`` mirrors them per paragraph, so the strict
        alignment validator holds without asking the model for identifiers.
        """
        from app.schemas.controlled_prep import TeachingScriptNodeDraft as _Result

        evidence_ids = PrepLLMAdapter._cap_evidence_ids(list(candidate.evidence_ids))
        paragraph_count = len(wire.content.split("\n\n"))
        return _Result(
            stage="script_writer",
            candidate_id=wire.candidate_id,
            title=wire.title,
            evidence_ids=evidence_ids,
            course_positioning=wire.course_positioning,
            prerequisites=wire.prerequisites,
            style=wire.style,
            content=wire.content,
            claims=wire.claims,
            paragraph_evidence=[evidence_ids] * paragraph_count,
        )

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
        """Stage 1 Map: segment one bounded evidence batch.

        The model returns topic segments without any evidence identifier; the
        adapter attributes every segment to the whole input batch afterwards.
        """
        from app.schemas.controlled_prep import (
            EvidenceSegment as _Segment,
            EvidenceSegmentMapResult as _Result,
            EvidenceSegmentMapWireResult as _WireResult,
        )

        user_payload = {
            **self._request_context(request),
            "constraints": {
                "max_segments": 12,
                "return_json_only": True,
                "do_not_output_evidence_ids": True,
            },
            "evidence": [item.llm_payload() for item in request.evidence],
        }
        response = await self._complete(
            spec=EVIDENCE_SEGMENTER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="segment_evidence",
            purpose="segment course evidence",
            output_schema=_WireResult,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=(
                int(settings.PREP_INITIAL_EVIDENCE_MAP_MAX_TOKENS)
                if max_tokens is None else max_tokens
            ),
            run_id=run_id,
            trace_id=trace_id,
        )
        wire_result = self._parsed_or_validate(response, _WireResult)
        batch_ids = [item.evidence_id for item in request.evidence]
        return _Result(segments=[
            _Segment(
                segment_id=item.segment_id,
                title=item.title,
                topic=item.topic,
                evidence_ids=batch_ids,
                examples=item.examples,
                exercises=item.exercises,
            )
            for item in wire_result.segments
        ])

    async def reduce_evidence(
        self,
        segments: list["EvidenceSegment"],
        *,
        run_id: str = "",
        trace_id: str = "",
        max_tokens: int | None = None,
        lean: bool = False,
        target_segments: int | None = None,
    ) -> "EvidenceSegmenterResult":
        """Stage 1 Reduce: merge summaries without resending source text.

        Intermediate hierarchical levels pass ``lean=True``: the wire schema
        then only carries ``title``/``topic`` so a level's request and response
        stay small and finish within the completion budget.  The final level
        keeps ``lean=False`` and re-adds bounded examples/exercises.  Evidence
        ids are never returned by the model: every merged segment receives the
        deterministic union of its input group.  ``target_segments`` is a
        must-compress hint for non-final levels; the caller validates the
        actual compression ratio.
        """
        from app.schemas.controlled_prep import (
            EvidenceReduceResult as _WireResult,
            EvidenceSegment as _Segment,
            EvidenceSegmenterResult as _Result,
            LeanEvidenceReduceResult as _LeanWireResult,
        )

        wire_schema = _LeanWireResult if lean else _WireResult
        user_payload = {
            "constraints": {
                "max_segments": target_segments or 32,
                "max_examples_per_segment": 0 if lean else 10,
                "max_exercises_per_segment": 0 if lean else 10,
                "return_json_only": True,
                "do_not_output_evidence_ids": True,
            },
            "segments": [PrepLLMAdapter._segment_llm_payload(item) for item in segments],
        }
        response = await self._complete(
            spec=EVIDENCE_REDUCER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="segment_evidence_reduce",
            purpose="reduce course evidence summaries",
            output_schema=wire_schema,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=(
                int(settings.PREP_INITIAL_EVIDENCE_REDUCE_MAX_TOKENS)
                if max_tokens is None else max_tokens
            ),
            run_id=run_id,
            trace_id=trace_id,
        )
        wire_result = self._parsed_or_validate(response, wire_schema)
        union_ids = PrepLLMAdapter._union_evidence_ids(segments)
        return _Result(segments=[
            _Segment(
                segment_id=item.segment_id,
                title=item.title,
                topic=item.topic,
                evidence_ids=union_ids,
                examples=getattr(item, "examples", []) or [],
                exercises=getattr(item, "exercises", []) or [],
            )
            for item in wire_result.segments
        ])

    async def plan_outline(
        self,
        request: "ControlledPrepInput",
        segments: "EvidenceSegmenterResult",
        *,
        run_id: str = "",
        trace_id: str = "",
    ) -> "OutlinePlannerResult":
        """Stage 2: plan the chapter -> section -> knowledge_point outline tree.

        The model never returns evidence identifiers; every candidate and
        prerequisite receives the deterministic union of the input segments'
        evidence after the call.
        """
        from app.schemas.controlled_prep import (
            OutlineCandidate as _Candidate,
            OutlinePlannerResult as _Result,
            OutlinePlannerWireResult as _WireResult,
            PrerequisiteCandidate as _Prerequisite,
        )

        user_payload = {
            **self._request_context(request),
            "constraints": {
                "max_knowledge_points": int(settings.PREP_INITIAL_MAX_KNOWLEDGE_POINTS),
                "max_total_nodes": int(settings.PREP_INITIAL_MAX_OUTLINE_NODES),
                "return_json_only": True,
                "do_not_output_evidence_ids": True,
            },
            "segments": [PrepLLMAdapter._segment_llm_payload(item) for item in segments.segments],
        }
        response = await self._complete(
            spec=OUTLINE_PLANNER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="plan_outline",
            purpose="plan course outline",
            output_schema=_WireResult,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=int(settings.PREP_INITIAL_OUTLINE_MAX_TOKENS),
            run_id=run_id,
            trace_id=trace_id,
        )
        wire_result = self._parsed_or_validate(response, _WireResult)
        union_ids = PrepLLMAdapter._cap_evidence_ids(
            PrepLLMAdapter._union_evidence_ids(segments.segments)
        )
        return _Result(
            candidates=[
                _Candidate(
                    candidate_id=item.candidate_id,
                    node_type=item.node_type,
                    title=item.title,
                    parent_candidate_id=item.parent_candidate_id,
                    evidence_ids=union_ids,
                    rationale=item.rationale,
                )
                for item in wire_result.candidates
            ],
            prerequisites=[
                _Prerequisite(
                    knowledge_point_candidate_id=item.knowledge_point_candidate_id,
                    prerequisite_title=item.prerequisite_title,
                    evidence_ids=union_ids,
                    rationale=item.rationale,
                )
                for item in wire_result.prerequisites
            ],
        )

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
        from app.schemas.controlled_prep import ScriptWireDraft as _WireDraft

        candidate = next(
            item for item in outline.candidates if item.candidate_id == candidate_id
        )
        user_payload = {
            **self._request_context(request),
            "outline": self._outline_context(outline, {candidate_id}),
            "candidate_id": candidate_id,
            "evidence": [
                item.llm_payload()
                for item in self._bounded_evidence_items(
                    request,
                    set(candidate.evidence_ids),
                    max_chars=self._script_evidence_max_chars(),
                )
            ],
        }
        response = await self._complete(
            spec=SCRIPT_WRITER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="write_script",
            purpose="write single teaching script",
            output_schema=_WireDraft,
            run_id=run_id,
            trace_id=trace_id,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=max_tokens,
        )
        wire_draft = self._parsed_or_validate(response, _WireDraft)
        return PrepLLMAdapter._backfilled_script(wire_draft, candidate)

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

        Parses the model-facing wire batch and backfills each script from its
        bound candidate.
        """
        from app.schemas.controlled_prep import TeachingScriptBatchWireResult as _WireBatch

        candidate_ids = {candidate.candidate_id for candidate in candidates}
        evidence_ids = {
            evidence_id
            for candidate in candidates
            for evidence_id in candidate.evidence_ids
        }
        user_payload = {
            **self._request_context(request),
            "outline": self._outline_context(outline, candidate_ids),
            "candidates": [PrepLLMAdapter._candidate_llm_payload(c) for c in candidates],
            "evidence": [
                item.llm_payload()
                for item in self._bounded_evidence_items(
                    request,
                    evidence_ids,
                    max_chars=self._script_evidence_max_chars(),
                )
            ],
        }
        response = await self._complete(
            spec=SCRIPT_WRITER_BATCH_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="write_scripts_batch",
            purpose="write batch teaching scripts",
            output_schema=_WireBatch,
            run_id=run_id,
            trace_id=trace_id,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=max_tokens,
        )
        batch = self._parsed_or_validate(response, _WireBatch)
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        scripts: list[Any] = []
        for wire_draft in batch.scripts:
            candidate = by_id.get(wire_draft.candidate_id)
            if candidate is None:
                raise StructuredOutputError(
                    "script_writer_batch returned an unknown candidate_id",
                    reason_code="structured_output_invalid",
                    stage="write_scripts_batch",
                )
            scripts.append(PrepLLMAdapter._backfilled_script(wire_draft, candidate))
        return scripts

    async def verify_script(
        self,
        request: "ControlledPrepInput",
        script: "TeachingScriptNodeDraft",
        *,
        run_id: str = "",
        trace_id: str = "",
    ) -> "EvidenceVerifierResult":
        """Stage 4: verify that the script's conclusions are evidence-backed.

        Findings receive the script's evidence set as their backfilled
        ``evidence_ids``; the model never returns identifiers.
        """
        from app.schemas.controlled_prep import (
            EvidenceFinding as _Finding,
            EvidenceVerifierResult as _Result,
            EvidenceVerifierWireResult as _WireResult,
        )

        evidence_ids = set(script.evidence_ids)
        for paragraph_ids in script.paragraph_evidence:
            evidence_ids.update(paragraph_ids)
        user_payload = {
            **self._request_context(request),
            "script": PrepLLMAdapter._script_llm_payload(script),
            "evidence": [
                item.llm_payload()
                for item in self._bounded_evidence_items(
                    request,
                    evidence_ids,
                    max_chars=self._script_evidence_max_chars(),
                )
            ],
        }
        response = await self._complete(
            spec=EVIDENCE_VERIFIER_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            node="verify_script",
            purpose="verify script evidence",
            output_schema=_WireResult,
            provider_options=self._structured_prep_provider_options("initial"),
            max_tokens=int(settings.PREP_INITIAL_VERIFIER_MAX_TOKENS),
            run_id=run_id,
            trace_id=trace_id,
        )
        wire_result = self._parsed_or_validate(response, _WireResult)
        backfilled_ids = list(script.evidence_ids)
        return _Result(
            stage="evidence_verifier",
            verdict=wire_result.verdict,
            findings=[
                _Finding(
                    claim=item.claim,
                    evidence_ids=backfilled_ids,
                    supported=item.supported,
                    reason=item.reason,
                )
                for item in wire_result.findings
            ],
            unsupported_paragraph_indexes=wire_result.unsupported_paragraph_indexes,
        )

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
