"""Minimal, course-scoped TeachingAgent audit and session records.

These records deliberately exclude raw learner messages, generated answers,
prompts, and full model traces.  They are operational audit/context data only:
they never create ``LearningEvent`` / ``LearningEvidence`` and never update a
formal cognition or mastery result.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_naive


class AgentLearningEvent(SQLModel, table=True):
    """Sanitized teaching-agent audit event, not a formal learning event."""

    __tablename__ = "agent_learning_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True, max_length=128)
    student_id: int = Field(index=True)
    course_id: int = Field(index=True)
    session_id: str = Field(max_length=128)
    event_type: str = Field(default="teaching_agent_response", max_length=64)
    # Only structured action/error metadata; never raw message or answer text.
    event_data: str = Field(default="{}", description="JSON: sanitized audit metadata")
    data_policy_version: str = Field(default="agent-log-minimization/1", max_length=64)
    migration_batch_id: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=utcnow_naive)


class AgentTraceRecord(SQLModel, table=True):
    """Sanitized workflow metadata, not a raw replay transcript."""

    __tablename__ = "agent_trace_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True, max_length=128)
    student_id: int = Field(index=True)
    course_id: int = Field(index=True)
    session_id: str = Field(default="", max_length=128)
    # Node names, error codes and evidence identifiers only.
    trace_data: str = Field(default="{}", description="JSON: sanitized trace metadata")
    data_policy_version: str = Field(default="agent-log-minimization/1", max_length=64)
    migration_batch_id: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=utcnow_naive)


class AgentConversationSession(SQLModel, table=True):
    """Bounded structured continuity state; it is never a chat transcript."""

    __tablename__ = "agent_conversation_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(index=True)
    course_id: int = Field(index=True)
    session_id: str = Field(index=True, max_length=128)
    context_data: str = Field(default="{}", description="JSON: structured, non-content continuity state")
    data_policy_version: str = Field(default="agent-session-context/1", max_length=64)
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive, index=True)


class AgentLogMigrationRecord(SQLModel, table=True):
    """Idempotency ledger for the privacy-preserving Agent log migration."""

    __tablename__ = "agent_log_migration_records"

    batch_id: str = Field(primary_key=True, max_length=64)
    applied_at: datetime = Field(default_factory=utcnow_naive)
    redacted_event_rows: int = Field(default=0)
    redacted_trace_rows: int = Field(default=0)
