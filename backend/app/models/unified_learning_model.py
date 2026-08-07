"""Canonical learning facts and read projections.

The learning projection is intentionally independent from cognition and
recommendation persistence.  It records exposure/completion only; mastery is
read from the existing cognition tables when a view is assembled.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class LearningEventType(str, Enum):
    NODE_OPENED = "node_opened"
    MEDIA_PROGRESS = "media_progress"
    READ_PROGRESS = "read_progress"
    EXPLICIT_COMPLETE = "explicit_complete"
    RECOMMENDATION_CONSUMED = "recommendation_consumed"
    AGENT_LEARNING_ACTION = "agent_learning_action"


class ExposureStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class LearningEvent(SQLModel, table=True):
    __tablename__ = "learning_events"
    __table_args__ = (
        UniqueConstraint("student_id", "idempotency_key", name="uq_learning_event_idempotency"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: str = Field(default_factory=lambda: f"le_{uuid.uuid4().hex}", unique=True, index=True)
    idempotency_key: str = Field(index=True, max_length=200)
    student_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    release_id: str = Field(index=True, max_length=100)
    outline_node_id: str = Field(index=True, max_length=100)
    knowledge_node_key: Optional[str] = Field(default=None, index=True, max_length=150)
    event_type: LearningEventType = Field(index=True)
    occurred_at: datetime = Field(default_factory=utcnow_aware, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    source: str = Field(default="learn_page", max_length=64)
    schema_version: int = Field(default=1)
    created_at: datetime = Field(default_factory=utcnow_aware)


class StudentLearningProjection(SQLModel, table=True):
    __tablename__ = "student_learning_projections"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "course_id", "release_id", "outline_node_id",
            name="uq_student_learning_projection_node",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    release_id: str = Field(index=True, max_length=100)
    outline_node_id: str = Field(index=True, max_length=100)
    knowledge_node_key: Optional[str] = Field(default=None, index=True, max_length=150)
    exposure_status: ExposureStatus = Field(default=ExposureStatus.NOT_STARTED, index=True)
    exposure_seconds: int = Field(default=0, ge=0)
    visit_count: int = Field(default=0, ge=0)
    completion_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    completion_reason: Optional[str] = Field(default=None, max_length=64)
    current_timestamp: float = Field(default=0.0, ge=0.0)
    current_page: int = Field(default=1, ge=1)
    first_accessed_at: Optional[datetime] = Field(default=None)
    last_accessed_at: Optional[datetime] = Field(default=None, index=True)
    completed_at: Optional[datetime] = Field(default=None)
    last_event_id: Optional[str] = Field(default=None, index=True)
    projection_version: int = Field(default=1)
    updated_at: datetime = Field(default_factory=utcnow_aware, index=True)


class CourseLearningStatsProjection(SQLModel, table=True):
    __tablename__ = "course_learning_stats_projections"
    __table_args__ = (
        UniqueConstraint("course_id", "release_id", "outline_node_id", name="uq_course_learning_stats_node"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    release_id: str = Field(index=True, max_length=100)
    outline_node_id: str = Field(index=True, max_length=100)
    student_count: int = Field(default=0, ge=0)
    not_started_count: int = Field(default=0, ge=0)
    in_progress_count: int = Field(default=0, ge=0)
    completed_count: int = Field(default=0, ge=0)
    mastery_distribution: dict = Field(default_factory=dict, sa_column=Column(JSON))
    unknown_mastery_count: int = Field(default=0, ge=0)
    low_confidence_count: int = Field(default=0, ge=0)
    pending_recommendation_count: int = Field(default=0, ge=0)
    projection_version: int = Field(default=1)
    computed_at: datetime = Field(default_factory=utcnow_aware, index=True)


class LearningEvidenceContext(SQLModel, table=True):
    __tablename__ = "learning_evidence_contexts"
    __table_args__ = (
        UniqueConstraint("evidence_id", name="uq_learning_evidence_context_evidence"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    evidence_id: str = Field(index=True, max_length=150)
    course_id: int = Field(foreign_key="courses.id", index=True)
    knowledge_node_key: Optional[str] = Field(default=None, index=True, max_length=150)
    source_release_id: Optional[str] = Field(default=None, index=True, max_length=100)
    outline_node_id: Optional[str] = Field(default=None, index=True, max_length=100)
    event_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow_aware)
