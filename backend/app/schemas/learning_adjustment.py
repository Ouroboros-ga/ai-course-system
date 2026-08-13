"""Strict public contracts for learner-confirmed learning adjustments.

The three coordinate objects deliberately have separate names.  A question
observation is context only, a review target is server-derived, and a return
anchor is captured only when the learner chooses to review.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LearningAdjustmentStatus(str, Enum):
    PROPOSED = "proposed"
    APPLIED = "applied"
    RETURNED = "returned"


class _PlaybackCoordinate(_StrictContract):
    """An item-local coordinate, optionally paired with a verified playlist clock."""

    course_release_id: str = Field(min_length=1, max_length=128)
    media_release_id: str = Field(min_length=1, max_length=128)
    media_release_item_id: str = Field(min_length=1, max_length=128)
    outline_node_id: str = Field(min_length=1, max_length=128)
    local_time_ms: int = Field(ge=0, le=86_400_000)
    page: int = Field(ge=1, le=10_000)
    global_time_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class QuestionObservation(_PlaybackCoordinate):
    """Question-time context supplied by the learner client and server validated."""


class ReviewTarget(_PlaybackCoordinate):
    """Immutable review destination derived only from frozen release data."""


class ReturnAnchor(_PlaybackCoordinate):
    """Click-time location to restore after a voluntary review."""


class LearningAdjustmentProposal(_StrictContract):
    """Safe learner-facing proposal without prompt, answer or browser commands."""

    schema_version: str = Field(default="learning-adjustment/v1", pattern=r"^learning-adjustment/v1$")
    adjustment_id: str = Field(min_length=1, max_length=128, pattern=r"^lad_[A-Za-z0-9]+$")
    status: LearningAdjustmentStatus
    question_observation: QuestionObservation
    review_target: ReviewTarget
    return_anchor: ReturnAnchor | None = None
    teaching_action: str = Field(min_length=1, max_length=64)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)
    recommended_playback_rate: float = Field(ge=0.5, le=1.0)
    requires_confirmation: bool
    declined_at: datetime | None = None
    invalidated_at: datetime | None = None
    invalidation_reason_code: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _require_learner_confirmation_and_valid_reason_codes(self) -> "LearningAdjustmentProposal":
        if not self.requires_confirmation:
            raise ValueError("learning adjustments always require learner confirmation")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must be unique")
        for code in self.reason_codes:
            if not code or len(code) > 64 or not code.replace("_", "").isalnum():
                raise ValueError("reason_codes must be bounded identifiers")
        return self


class ApplyLearningAdjustmentRequest(_StrictContract):
    return_anchor: ReturnAnchor
    idempotency_key: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")


class ReturnLearningAdjustmentRequest(_StrictContract):
    idempotency_key: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")


class DismissLearningAdjustmentRequest(_StrictContract):
    idempotency_key: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")
