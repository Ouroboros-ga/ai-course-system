"""Minimal durable state for a learner-confirmed review proposal.

This table intentionally contains coordinates and state only.  Product
conversation messages own question/answer text, while runtime audit tables
remain minimised under the project data policy.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class LearningAdjustmentRecord(SQLModel, table=True):
    __tablename__ = "learning_adjustments"
    __table_args__ = (
        UniqueConstraint("student_id", "adjustment_id", name="uq_learning_adjustment_student_id"),
        UniqueConstraint("student_id", "apply_idempotency_key", name="uq_learning_adjustment_apply_idempotency"),
        UniqueConstraint("student_id", "return_idempotency_key", name="uq_learning_adjustment_return_idempotency"),
        UniqueConstraint("student_id", "dismiss_idempotency_key", name="uq_learning_adjustment_dismiss_idempotency"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    adjustment_id: str = Field(default_factory=lambda: f"lad_{uuid.uuid4().hex}", unique=True, index=True, max_length=128)
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    # Internal correlation only.  The product Conversation Domain owns the
    # question/answer text for this turn; this record never stores that text.
    source_trace_id: str | None = Field(default=None, index=True, max_length=128)
    status: str = Field(default="proposed", index=True, max_length=16)

    question_course_release_id: str = Field(index=True, max_length=128)
    question_media_release_id: str = Field(index=True, max_length=128)
    question_media_release_item_id: str = Field(max_length=128)
    question_outline_node_id: str = Field(max_length=128)
    question_local_time_ms: int = Field(ge=0)
    question_page: int = Field(ge=1)
    question_global_time_ms: int | None = Field(default=None, ge=0)

    review_course_release_id: str = Field(index=True, max_length=128)
    review_media_release_id: str = Field(index=True, max_length=128)
    review_media_release_item_id: str = Field(max_length=128)
    review_outline_node_id: str = Field(max_length=128)
    review_local_time_ms: int = Field(ge=0)
    review_page: int = Field(ge=1)
    review_global_time_ms: int | None = Field(default=None, ge=0)

    return_course_release_id: str | None = Field(default=None, max_length=128)
    return_media_release_id: str | None = Field(default=None, max_length=128)
    return_media_release_item_id: str | None = Field(default=None, max_length=128)
    return_outline_node_id: str | None = Field(default=None, max_length=128)
    return_local_time_ms: int | None = Field(default=None, ge=0)
    return_page: int | None = Field(default=None, ge=1)
    return_global_time_ms: int | None = Field(default=None, ge=0)

    teaching_action: str = Field(max_length=64)
    reason_codes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    recommended_playback_rate: float = Field(default=1.0, ge=0.5, le=1.0)
    requires_confirmation: bool = Field(default=True)
    apply_idempotency_key: str | None = Field(default=None, max_length=200)
    return_idempotency_key: str | None = Field(default=None, max_length=200)
    dismiss_idempotency_key: str | None = Field(default=None, max_length=200)
    declined_at: datetime | None = Field(default=None, index=True)
    invalidated_at: datetime | None = Field(default=None, index=True)
    invalidation_reason_code: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)
    applied_at: datetime | None = Field(default=None)
    returned_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow_aware)
