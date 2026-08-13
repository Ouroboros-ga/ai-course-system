"""Structured contracts for the controlled course-preparation workflow."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceReference(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20_000)
    page: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    block_id: str | None = Field(default=None, max_length=200)
    source_block_ids: list[str] = Field(default_factory=list, max_length=500)
    material_version_id: str | None = Field(default=None, max_length=200)
    material_role: str = Field(default="reference", max_length=64)

    def llm_payload(self) -> dict[str, object]:
        """Return the minimal model-facing view; provenance stays server-side.

        ``evidence_id`` is intentionally excluded: LLMs must never see or
        return evidence identifiers.  The workflow backfills them from the
        deterministic input scope after each stage.
        """
        return {
            "text": self.text,
            "page": self.page,
            "page_end": self.page_end,
            "material_version_id": self.material_version_id,
            "material_role": self.material_role,
        }


class TeachingStyleConfig(StrictModel):
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    tone: Literal["calm", "enthusiastic", "academic", "conversational"] = "conversational"
    language: str = Field(default="zh-CN", min_length=2, max_length=20)
    include_examples: bool = True
    include_practice_prompt: bool = True


class EvidenceSegment(StrictModel):
    segment_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    topic: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1)
    examples: list[str] = Field(default_factory=list, max_length=10)
    exercises: list[str] = Field(default_factory=list, max_length=10)


class BoundedSuggestionFields(StrictModel):
    """Shared stable normalization for descriptive examples/exercises lists.

    The model may repeat, over-produce, or emit whitespace-padded suggestions
    in both the Map and Reduce wire responses.  These fields are descriptive,
    so an otherwise valid course organization must not fail merely because the
    model exceeded the ten-item cap; they are stably deduplicated, stripped,
    and truncated to ten before strict validation.
    """

    examples: list[str] = Field(default_factory=list, max_length=10)
    exercises: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("examples", "exercises", mode="before")
    @classmethod
    def normalize_bounded_suggestions(cls, value: object) -> object:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return value
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = item.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
            if len(normalized) == 10:
                break
        return normalized


class EvidenceReduceSegment(BoundedSuggestionFields):
    """Reduce wire shape with deterministic normalization for safe list fields.

    The JSON schema still advertises the public ten-item limit for
    examples/exercises (inherited from ``BoundedSuggestionFields``).  Identity
    and segment-count fields remain strictly validated.  ``evidence_ids`` is
    deliberately absent: the program backfills the deterministic union of the
    input group after the call.
    """

    segment_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    topic: str = Field(min_length=1, max_length=500)


class EvidenceSegmenterResult(StrictModel):
    stage: Literal["evidence_segmenter"] = "evidence_segmenter"
    segments: list[EvidenceSegment] = Field(min_length=1, max_length=32)


class EvidenceReduceResult(StrictModel):
    """Model-facing Reduce result normalized before the strict domain result."""

    stage: Literal["evidence_segmenter"] = "evidence_segmenter"
    segments: list[EvidenceReduceSegment] = Field(min_length=1, max_length=32)


class LeanEvidenceSegment(StrictModel):
    """Intermediate Reduce output keeping only identity and provenance.

    Examples/exercises are descriptive suggestions that no downstream stage
    consumes; carrying them through every hierarchical level is what made
    intermediate Reduce responses hit ``finish_reason=length`` and burn the
    bounded call budget.  Intermediate levels therefore merge on title/topic
    only, and the final level re-adds suggestions.  ``evidence_ids`` stays
    server-side and is backfilled as the input group's deterministic union.
    """

    segment_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    topic: str = Field(min_length=1, max_length=500)


class LeanEvidenceReduceResult(StrictModel):
    """Model-facing Reduce result for intermediate (non-final) levels."""

    stage: Literal["evidence_segmenter"] = "evidence_segmenter"
    segments: list[LeanEvidenceSegment] = Field(min_length=1, max_length=32)


class EvidenceMapSegment(BoundedSuggestionFields):
    """Map wire shape with the same stable suggestion normalization.

    LLMs never return evidence identifiers.  examples/exercises inherit the
    deterministic deduplicate/strip/truncate-to-ten behavior from
    ``BoundedSuggestionFields`` so an over-produced Map response is normalized
    instead of failing the whole course build.  The model sometimes repeats
    the top-level ``stage`` inside each segment; that single meaningless field
    is dropped here, while every other unknown field stays strictly rejected.
    """

    segment_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    topic: str = Field(min_length=1, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def drop_nested_stage(cls, value: object) -> object:
        if isinstance(value, dict) and "stage" in value:
            data = dict(value)
            data.pop("stage", None)
            return data
        return value


class EvidenceSegmentMapWireResult(StrictModel):
    """Model-facing Map result; the program backfills evidence_ids per batch."""

    stage: Literal["evidence_segmenter"] = "evidence_segmenter"
    segments: list[EvidenceMapSegment] = Field(min_length=1, max_length=12)


class EvidenceSegmentMapResult(StrictModel):
    """Bounded domain result used by one evidence Map request (backfilled)."""

    stage: Literal["evidence_segmenter"] = "evidence_segmenter"
    segments: list[EvidenceSegment] = Field(min_length=1, max_length=12)


class OutlineCandidate(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=100)
    # A first course draft is a tree, rather than a flat list of extracted
    # headings.  Keeping chapter in the structured contract lets the initial
    # preparation workflow establish the stable hierarchy that scripts and
    # slide mappings later reference.
    node_type: Literal["chapter", "section", "knowledge_point"]
    title: str = Field(min_length=1, max_length=300)
    parent_candidate_id: str | None = Field(default=None, max_length=100)
    evidence_ids: list[str] = Field(min_length=1)
    rationale: str = Field(default="", max_length=2_000)


class PrerequisiteCandidate(StrictModel):
    knowledge_point_candidate_id: str = Field(min_length=1, max_length=100)
    prerequisite_title: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(min_length=1)
    rationale: str = Field(default="", max_length=2_000)


class OutlinePlannerResult(StrictModel):
    stage: Literal["outline_planner"] = "outline_planner"
    candidates: list[OutlineCandidate] = Field(min_length=1, max_length=64)
    prerequisites: list[PrerequisiteCandidate] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_parent_candidates(self) -> "OutlinePlannerResult":
        ids = {candidate.candidate_id for candidate in self.candidates}
        knowledge_point_count = sum(
            candidate.node_type == "knowledge_point" for candidate in self.candidates
        )
        if knowledge_point_count > 24:
            raise ValueError("outline cannot contain more than 24 knowledge points")
        for candidate in self.candidates:
            if candidate.parent_candidate_id and candidate.parent_candidate_id not in ids:
                raise ValueError(f"unknown parent_candidate_id: {candidate.parent_candidate_id}")
            if candidate.node_type == "chapter" and candidate.parent_candidate_id:
                raise ValueError("chapter candidates cannot have a parent")
        kp_ids = {candidate.candidate_id for candidate in self.candidates if candidate.node_type == "knowledge_point"}
        for prerequisite in self.prerequisites:
            if prerequisite.knowledge_point_candidate_id not in kp_ids:
                raise ValueError(
                    "prerequisite must reference a knowledge_point candidate: "
                    f"{prerequisite.knowledge_point_candidate_id}"
                )
        return self


class OutlineCandidateWire(StrictModel):
    """Outline wire shape: LLMs never return evidence identifiers."""

    candidate_id: str = Field(min_length=1, max_length=100)
    node_type: Literal["chapter", "section", "knowledge_point"]
    title: str = Field(min_length=1, max_length=300)
    parent_candidate_id: str | None = Field(default=None, max_length=100)
    rationale: str = Field(default="", max_length=2_000)


class PrerequisiteCandidateWire(StrictModel):
    knowledge_point_candidate_id: str = Field(min_length=1, max_length=100)
    prerequisite_title: str = Field(min_length=1, max_length=300)
    rationale: str = Field(default="", max_length=2_000)


class OutlinePlannerWireResult(StrictModel):
    """Model-facing Outline result; the program backfills evidence_ids.

    The tree-shape constraints mirror the domain ``OutlinePlannerResult`` so
    an invalid hierarchy is rejected before backfill, not after.
    """

    stage: Literal["outline_planner"] = "outline_planner"
    candidates: list[OutlineCandidateWire] = Field(min_length=1, max_length=64)
    prerequisites: list[PrerequisiteCandidateWire] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_parent_candidates(self) -> "OutlinePlannerWireResult":
        ids = {candidate.candidate_id for candidate in self.candidates}
        knowledge_point_count = sum(
            candidate.node_type == "knowledge_point" for candidate in self.candidates
        )
        if knowledge_point_count > 24:
            raise ValueError("outline cannot contain more than 24 knowledge points")
        for candidate in self.candidates:
            if candidate.parent_candidate_id and candidate.parent_candidate_id not in ids:
                raise ValueError(f"unknown parent_candidate_id: {candidate.parent_candidate_id}")
            if candidate.node_type == "chapter" and candidate.parent_candidate_id:
                raise ValueError("chapter candidates cannot have a parent")
        return self


class ScriptWireDraft(StrictModel):
    """Script wire shape: no evidence_ids / paragraph_evidence from the model.

    The program backfills ``evidence_ids`` from the bound candidate and
    ``paragraph_evidence`` per paragraph so the strict domain contract stays
    aligned without asking the LLM for any identifier.
    """

    stage: Literal["script_writer"] = "script_writer"
    candidate_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    course_positioning: str = Field(min_length=1, max_length=2_000)
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    style: TeachingStyleConfig
    content: str = Field(min_length=1, max_length=50_000)
    claims: list[str] = Field(
        min_length=1,
        max_length=100,
        description="该知识点讲稿所依据的核心论断（由材料支撑的事实性陈述），1~10 条自然语言短句，每条即一条论断；不是证据 ID 或引用编号，必填且至少 1 条",
    )


class TeachingScriptBatchWireResult(StrictModel):
    """One model-facing response containing the first-round scripts."""

    stage: Literal["script_writer_batch", "script_writer"] = "script_writer_batch"
    scripts: list[ScriptWireDraft] = Field(min_length=1, max_length=50)


class EvidenceFindingWire(StrictModel):
    """Verifier wire finding without evidence identifiers."""

    claim: str = Field(min_length=1, max_length=2_000)
    supported: bool
    reason: str = Field(default="", max_length=2_000)


class EvidenceVerifierWireResult(StrictModel):
    """Model-facing Verifier result; the program backfills finding evidence_ids."""

    stage: Literal["evidence_verifier"] = "evidence_verifier"
    verdict: Literal["passed", "needs_review", "failed"]
    findings: list[EvidenceFindingWire] = Field(min_length=1, max_length=200)
    unsupported_paragraph_indexes: list[int] = Field(default_factory=list, max_length=200)


class TeachingScriptNodeDraft(StrictModel):
    stage: Literal["script_writer"] = "script_writer"
    candidate_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(min_length=1)
    course_positioning: str = Field(min_length=1, max_length=2_000)
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    style: TeachingStyleConfig
    content: str = Field(min_length=1, max_length=50_000)
    claims: list[str] = Field(
        min_length=1,
        max_length=100,
        description="该知识点讲稿所依据的核心论断（由材料支撑的事实性陈述），1~10 条自然语言短句，每条即一条论断；不是证据 ID 或引用编号，必填且至少 1 条",
    )
    paragraph_evidence: list[list[str]] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_paragraph_shape(self) -> "TeachingScriptNodeDraft":
        if len(self.paragraph_evidence) != len(self.content.split("\n\n")):
            raise ValueError("paragraph_evidence must align with content paragraphs")
        return self


class TeachingScriptBatchResult(StrictModel):
    """One LLM response containing the first-round scripts for all KPs."""

    stage: Literal["script_writer_batch", "script_writer"] = "script_writer_batch"
    scripts: list[TeachingScriptNodeDraft] = Field(min_length=1, max_length=50)


class EvidenceFinding(StrictModel):
    claim: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(default_factory=list)
    supported: bool
    reason: str = Field(default="", max_length=2_000)


class EvidenceVerifierResult(StrictModel):
    stage: Literal["evidence_verifier"] = "evidence_verifier"
    verdict: Literal["passed", "needs_review", "failed"]
    findings: list[EvidenceFinding] = Field(min_length=1, max_length=200)
    unsupported_paragraph_indexes: list[int] = Field(default_factory=list, max_length=200)


class PatchOperationDraft(StrictModel):
    operation: Literal["add", "replace", "remove", "move", "reorder"]
    target: str = Field(min_length=1, max_length=300)
    before: str = ""
    after: str = ""
    reason: str = Field(default="", max_length=2_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    external_ref: str | None = Field(default=None, max_length=500)


class PatchProposalDraft(StrictModel):
    stage: Literal["patch_compiler"] = "patch_compiler"
    tool_name: str = Field(default="ControlledPrepAgent", max_length=64)
    policy_version: str = Field(default="controlled-prep/1.0", max_length=32)
    reason: str = Field(min_length=1, max_length=2_000)
    operations: list[PatchOperationDraft] = Field(min_length=1, max_length=500)


class CourseSkeletonBudget(StrictModel):
    """Single source of truth for the first-draft course-skeleton targets.

    The initial preparation produces an auditable course skeleton (chapter ->
    section -> knowledge_point), not a replica of a textbook table of contents.
    Targets are ideal ranges the model aims for; ``max_*`` fields are hard
    ceilings enforced by the outline schema and the workflow.  Small corpora
    receive proportionally smaller targets so the model never invents structure
    to fill a quota.
    """

    mode: Literal["course_skeleton"] = "course_skeleton"
    target_sections: int = Field(default=10, ge=1, le=12)
    target_knowledge_points: int = Field(default=16, ge=1, le=24)
    target_total_nodes: int = Field(default=30, ge=1, le=48)
    max_sections: int = Field(default=12, ge=1, le=12)
    max_knowledge_points: int = Field(default=24, ge=1, le=24)
    max_total_nodes: int = Field(default=64, ge=1, le=64)

    @model_validator(mode="after")
    def _validate_ranges(self) -> "CourseSkeletonBudget":
        if self.target_sections > self.max_sections:
            raise ValueError("target_sections cannot exceed max_sections")
        if self.target_knowledge_points > self.max_knowledge_points:
            raise ValueError("target_knowledge_points cannot exceed max_knowledge_points")
        if self.target_total_nodes > self.max_total_nodes:
            raise ValueError("target_total_nodes cannot exceed max_total_nodes")
        return self

    @classmethod
    def for_evidence_segment_count(cls, segment_count: int) -> "CourseSkeletonBudget":
        """Derive proportionate targets from the resolved evidence segments.

        A 577-page textbook yielding 32 segments targets ~10 sections / ~16
        knowledge points; a 3-page handout with 2 segments targets 1-2 of
        each instead of inventing 8 units to fill a quota.
        """
        n = max(1, int(segment_count))
        target_sections = max(1, min(12, min(10, (n + 1) // 3)))
        target_kp = max(1, min(24, max(target_sections, min(16, n))))
        target_nodes = target_sections + target_kp + 1
        return cls(
            target_sections=target_sections,
            target_knowledge_points=target_kp,
            target_total_nodes=min(48, target_nodes),
        )


class ControlledPrepInput(StrictModel):
    # Deprecated compatibility field. Initial Prep sends typed evidence units
    # only; excluding this field prevents the corpus from being serialized a
    # second time into every LLM request.
    source_text: str = Field(default="", max_length=200_000, exclude=True)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=1000)
    course_positioning: str = Field(default="", max_length=2_000)
    style: TeachingStyleConfig = Field(default_factory=TeachingStyleConfig)
    skeleton_budget: CourseSkeletonBudget = Field(default_factory=CourseSkeletonBudget)

    @model_validator(mode="after")
    def validate_unique_evidence(self) -> "ControlledPrepInput":
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id values must be unique")
        return self
