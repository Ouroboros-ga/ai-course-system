"""Persisted, scope-bound CodingEduAgent diagnoses.

The record deliberately contains a bounded diagnosis and references to the
execution artifacts, not the student's source code or a raw LLM trace.  A
diagnosis is teaching context; it is never a formal LearningEvidence record.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


CODING_DIAGNOSIS_POLICY_VERSION = "coding-diagnosis/rule-v1"


class CodingDiagnosisRecord(SQLModel, table=True):
    """One deterministic diagnosis for one completed experiment run."""

    __tablename__ = "coding_diagnosis_records"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_coding_diagnosis_run_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    diagnosis_id: str = Field(unique=True, index=True)
    run_id: str = Field(index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)

    status: str = Field(default="ready", index=True)
    outcome: str = Field(default="unknown", index=True)
    error_class: str = Field(default="unknown", index=True)
    line: Optional[int] = Field(default=None)
    column: Optional[int] = Field(default=None)
    summary: str = Field(default="")
    debug_steps: list = Field(default_factory=list, sa_column=Column(JSON))
    hints: list = Field(default_factory=list, sa_column=Column(JSON))
    confidence: float = Field(default=0.0)
    evidence_refs: list = Field(default_factory=list, sa_column=Column(JSON))
    reason_codes: list = Field(default_factory=list, sa_column=Column(JSON))
    policy_version: str = Field(default=CODING_DIAGNOSIS_POLICY_VERSION)
    generated_by: str = Field(default="coding-rules")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)
