"""Course-scoped Prep Agent run and structured-LLM diagnostics.

Only bounded operational metadata is stored here.  Prompts, model responses,
course text and learner data are intentionally excluded.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class AgentRunRecord(SQLModel, table=True):
    __tablename__ = "agent_run_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(default_factory=lambda: f"run_{uuid.uuid4().hex}", unique=True, index=True, max_length=128)
    trace_id: str = Field(index=True, max_length=128)
    agent_type: str = Field(index=True, max_length=64)
    actor_id: str = Field(default="", index=True, max_length=128)
    actor_type: str = Field(default="teacher", max_length=32)
    course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True)
    config_version: str = Field(default="v1", max_length=64)
    idempotency_key: Optional[str] = Field(default=None, index=True, max_length=256)
    status: str = Field(default="running", index=True, max_length=32)
    stage: str = Field(default="", index=True, max_length=128)
    error_code: str = Field(default="", max_length=128)
    error_details: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    result_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    started_at: datetime = Field(default_factory=utcnow_aware, index=True)
    completed_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow_aware, index=True)


class AgentRunEventRecord(SQLModel, table=True):
    __tablename__ = "agent_run_event_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex}", unique=True, index=True, max_length=128)
    run_id: str = Field(index=True, max_length=128)
    trace_id: str = Field(index=True, max_length=128)
    event_type: str = Field(index=True, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)


class AgentLLMDiagnosticRecord(SQLModel, table=True):
    __tablename__ = "agent_llm_diagnostic_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    diagnostic_id: str = Field(default_factory=lambda: f"llm_{uuid.uuid4().hex}", unique=True, index=True, max_length=128)
    run_id: str = Field(index=True, max_length=128)
    trace_id: str = Field(index=True, max_length=128)
    course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True)
    agent_type: str = Field(default="prep", index=True, max_length=64)
    stage: str = Field(default="", index=True, max_length=128)
    node: str = Field(default="", max_length=128)
    purpose: str = Field(default="", max_length=256)
    prompt_version: str = Field(default="", max_length=128)
    schema_name: str = Field(default="", max_length=128)
    model: str = Field(default="", max_length=256)
    attempt: int = Field(default=1, ge=1)
    repaired: bool = Field(default=False)
    finish_reason: str = Field(default="", max_length=64)
    input_tokens: Optional[int] = Field(default=None)
    output_tokens: Optional[int] = Field(default=None)
    input_chars: int = Field(default=0, ge=0)
    output_chars: int = Field(default=0, ge=0)
    response_hash: str = Field(default="", max_length=128)
    truncated: bool = Field(default=False, index=True)
    response_format_requested: bool = Field(default=False)
    response_format_fallback: bool = Field(default=False)
    validation_errors: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    usage_metadata: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    latency_ms: float = Field(default=0.0, ge=0)
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)


__all__ = ["AgentRunRecord", "AgentRunEventRecord", "AgentLLMDiagnosticRecord"]
