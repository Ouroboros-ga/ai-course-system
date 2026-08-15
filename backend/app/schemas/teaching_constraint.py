"""Strict, versioned contracts for teacher-governed TeachingAgent constraints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ConstraintLevel = Literal["flexible", "balanced", "strict", "locked"]
ConstraintScope = Literal["evidence", "response", "context", "tools", "actions"]
EvidenceMode = Literal["best_effort", "course_grounded", "course_only"]
GuidanceMode = Literal["direct_guided", "guided", "socratic"]
ConfirmationMode = Literal["high_risk", "medium_and_high", "all_actions"]
ExternalResearchMode = Literal["disabled", "tool_policy"]
ConstraintTargetType = Literal["group", "student"]
ConstraintIntent = Literal[
    "concept_question",
    "code_debugging",
    "learning_guidance",
    "other",
]


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TeachingConstraintParameters(_StrictContract):
    """Fully resolved parameters consumed by the runtime and tool governance."""

    max_context_chars: int = Field(ge=3_000, le=24_000)
    max_answer_chars: int = Field(ge=300, le=4_000)
    max_evidence: int = Field(ge=1, le=20)
    min_course_evidence: int = Field(ge=0, le=3)
    evidence_mode: EvidenceMode
    guidance_mode: GuidanceMode
    confirmation_mode: ConfirmationMode
    external_research: ExternalResearchMode
    require_citations: bool = True


class TeachingConstraintParameterOverrides(_StrictContract):
    """Sparse teacher overrides applied before immutable platform floors."""

    max_context_chars: int | None = Field(default=None, ge=3_000, le=24_000)
    max_answer_chars: int | None = Field(default=None, ge=300, le=4_000)
    max_evidence: int | None = Field(default=None, ge=1, le=20)
    min_course_evidence: int | None = Field(default=None, ge=0, le=3)
    evidence_mode: EvidenceMode | None = None
    guidance_mode: GuidanceMode | None = None
    confirmation_mode: ConfirmationMode | None = None
    external_research: ExternalResearchMode | None = None
    require_citations: bool | None = None


class TeachingConstraintProfile(_StrictContract):
    level: ConstraintLevel = "balanced"
    scopes: tuple[ConstraintScope, ...] = (
        "evidence",
        "response",
        "context",
        "tools",
        "actions",
    )
    parameters: TeachingConstraintParameterOverrides = Field(
        default_factory=TeachingConstraintParameterOverrides
    )

    @model_validator(mode="after")
    def _reject_duplicate_scopes(self) -> "TeachingConstraintProfile":
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("constraint scopes must be unique")
        if not self.scopes:
            raise ValueError("at least one constraint scope is required")
        return self


class TeachingConstraintRule(_StrictContract):
    rule_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    priority: int = Field(default=0, ge=-1_000, le=1_000)
    target_type: ConstraintTargetType
    target_id: str = Field(min_length=1, max_length=128)
    level: ConstraintLevel
    scopes: tuple[ConstraintScope, ...] | None = None
    parameters: TeachingConstraintParameterOverrides = Field(
        default_factory=TeachingConstraintParameterOverrides
    )
    intent: ConstraintIntent | None = None
    concept_id: str | None = Field(default=None, min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=256)
    effective_from: datetime | None = None
    effective_until: datetime | None = None

    @model_validator(mode="after")
    def _validate_rule(self) -> "TeachingConstraintRule":
        if self.scopes is not None:
            if not self.scopes:
                raise ValueError("rule scopes cannot be empty")
            if len(set(self.scopes)) != len(self.scopes):
                raise ValueError("rule scopes must be unique")
        for field_name in ("effective_from", "effective_until"):
            value = getattr(self, field_name)
            if value is not None and value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("effective_until must be later than effective_from")
        return self


class TeachingConstraintSnapshot(_StrictContract):
    """Immutable policy payload stored inside an AgentPolicyVersion snapshot."""

    schema_version: Literal["teaching-constraint/1"] = "teaching-constraint/1"
    platform_floor_version: Literal["teaching-platform-floor/1"] = (
        "teaching-platform-floor/1"
    )
    baseline: TeachingConstraintProfile
    rules: tuple[TeachingConstraintRule, ...] = ()

    @model_validator(mode="after")
    def _reject_duplicate_rule_ids(self) -> "TeachingConstraintSnapshot":
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("constraint rule_id values must be unique")
        return self


class TeachingConstraintEnvelope(_StrictContract):
    """Resolved, floor-enforced constraint attached to one agent run."""

    schema_version: Literal["teaching-constraint-envelope/1"] = (
        "teaching-constraint-envelope/1"
    )
    level: ConstraintLevel
    scopes: tuple[ConstraintScope, ...]
    parameters: TeachingConstraintParameters
    disabled_tools: tuple[str, ...] = ()
    matched_rule_ids: tuple[str, ...] = ()
    decision_codes: tuple[str, ...] = ()
