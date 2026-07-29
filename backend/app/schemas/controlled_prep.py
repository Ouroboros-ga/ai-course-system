"""Structured contracts for the controlled course-preparation workflow."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceReference(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20_000)
    page: int | None = Field(default=None, ge=1)
    block_id: str | None = Field(default=None, max_length=200)


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


class EvidenceSegmenterResult(StrictModel):
    stage: Literal["evidence_segmenter"] = "evidence_segmenter"
    segments: list[EvidenceSegment] = Field(min_length=1, max_length=100)


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
    candidates: list[OutlineCandidate] = Field(min_length=1, max_length=200)
    prerequisites: list[PrerequisiteCandidate] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_parent_candidates(self) -> "OutlinePlannerResult":
        ids = {candidate.candidate_id for candidate in self.candidates}
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


class TeachingScriptNodeDraft(StrictModel):
    stage: Literal["script_writer"] = "script_writer"
    candidate_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(min_length=1)
    course_positioning: str = Field(min_length=1, max_length=2_000)
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    style: TeachingStyleConfig
    content: str = Field(min_length=1, max_length=50_000)
    claims: list[str] = Field(min_length=1, max_length=100)
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


class ControlledPrepInput(StrictModel):
    source_text: str = Field(min_length=1, max_length=200_000)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=500)
    course_positioning: str = Field(default="", max_length=2_000)
    style: TeachingStyleConfig = Field(default_factory=TeachingStyleConfig)

    @model_validator(mode="after")
    def validate_unique_evidence(self) -> "ControlledPrepInput":
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id values must be unique")
        return self
