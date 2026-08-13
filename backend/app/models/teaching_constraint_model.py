"""Versioned TeachingAgent constraint policy and minimized evaluation audit."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Index, Text, UniqueConstraint, text
from sqlmodel import Column, Field, SQLModel

from app.core.time_utils import utcnow_aware


class TeachingConstraintPolicyVersion(SQLModel, table=True):
    """Append-only policy snapshot; only the active marker may be superseded."""

    __tablename__ = "teaching_constraint_policy_versions"
    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "version",
            name="uq_teaching_constraint_course_version",
        ),
        Index(
            "uq_teaching_constraint_active_course",
            "course_id",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    version: int = Field(ge=1)
    policy_snapshot: str = Field(sa_column=Column(Text, nullable=False))
    policy_hash: str = Field(max_length=64, index=True)
    is_active: bool = Field(default=True, index=True)
    change_reason: str = Field(max_length=256)
    created_by: int = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)


class TeachingConstraintEvaluation(SQLModel, table=True):
    """Small operational audit without questions, answers, prompts or traces."""

    __tablename__ = "teaching_constraint_evaluations"

    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(max_length=128, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    policy_version_id: int = Field(
        foreign_key="teaching_constraint_policy_versions.id", index=True
    )
    effective_level: str = Field(max_length=16, index=True)
    matched_rule_ids: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    applied_scopes: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    decision_codes: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    context_input_chars: int = Field(default=0, ge=0)
    context_output_chars: int = Field(default=0, ge=0)
    valid_citation_count: int = Field(default=0, ge=0)
    enforcement_status: str = Field(default="enforced", max_length=32, index=True)
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)
