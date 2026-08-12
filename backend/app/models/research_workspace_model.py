"""Persistent ResearchAgent workspace domain.

This domain stores user-authored research plans, notes and memories.  It is
separate from Agent Runtime audit records: full system prompts and model traces
never enter these tables, while explicit notebook/memory content follows the
workspace retention and ownership boundary.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Text, UniqueConstraint
from sqlalchemy.types import UserDefinedType
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware

RESEARCH_WORKSPACE_DATA_POLICY_VERSION = "research-workspace/1"


class PgVectorType(UserDefinedType):
    """Dependency-free SQLAlchemy type for pgvector with SQLite compatibility.

    PostgreSQL resolves ``VECTOR`` through the pgvector extension installed by
    Alembic.  SQLite accepts the custom type name and stores the canonical
    ``[x,y,...]`` representation, which keeps local Demo/tests operational.
    """

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "VECTOR"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            vector = [float(component) for component in value]
            if not vector or any(not math.isfinite(component) for component in vector):
                raise ValueError("research memory vector must be finite and non-empty")
            return json.dumps(vector, ensure_ascii=True, separators=(",", ":"))

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None or isinstance(value, list):
                return value
            if isinstance(value, tuple):
                return list(value)
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return [float(component) for component in json.loads(str(value))]

        return process


class ResearchWorkspace(SQLModel, table=True):
    __tablename__ = "research_workspaces"
    __table_args__ = (
        UniqueConstraint("course_id", "owner_user_id", name="uq_research_workspace_course_owner"),
    )

    id: int | None = Field(default=None, primary_key=True)
    workspace_id: str = Field(
        default_factory=lambda: f"rws_{uuid.uuid4().hex}",
        unique=True,
        index=True,
        max_length=80,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    owner_user_id: int = Field(foreign_key="users.id", index=True)
    title: str = Field(default="科研工作台", max_length=200)
    status: str = Field(default="active", index=True, max_length=32)
    active_scope_id: str | None = Field(default=None, index=True, max_length=80)
    short_term_summary: str = Field(default="", sa_column=Column(Text, nullable=False))
    context_budget_tokens: int = Field(default=4_000, ge=256, le=64_000)
    data_policy_version: str = Field(
        default=RESEARCH_WORKSPACE_DATA_POLICY_VERSION,
        max_length=64,
    )
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(
        default_factory=utcnow_aware,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    updated_at: datetime = Field(
        default_factory=utcnow_aware,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class ResearchTodo(SQLModel, table=True):
    __tablename__ = "research_todos"

    id: int | None = Field(default=None, primary_key=True)
    todo_id: str = Field(
        default_factory=lambda: f"rtodo_{uuid.uuid4().hex}",
        unique=True,
        index=True,
        max_length=80,
    )
    workspace_id: str = Field(foreign_key="research_workspaces.workspace_id", index=True, max_length=80)
    scope_id: str | None = Field(default=None, index=True, max_length=80)
    title: str = Field(max_length=300)
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    priority: int = Field(default=1, ge=0, le=3, index=True)
    position: int = Field(default=0, ge=0)
    status: str = Field(default="pending", index=True, max_length=32)
    version: int = Field(default=1, ge=1)
    created_by: int = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=utcnow_aware, sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    updated_at: datetime = Field(default_factory=utcnow_aware, sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class ResearchNote(SQLModel, table=True):
    __tablename__ = "research_notes"

    id: int | None = Field(default=None, primary_key=True)
    note_id: str = Field(default_factory=lambda: f"rnote_{uuid.uuid4().hex}", unique=True, index=True, max_length=80)
    workspace_id: str = Field(foreign_key="research_workspaces.workspace_id", index=True, max_length=80)
    scope_id: str | None = Field(default=None, index=True, max_length=80)
    title: str = Field(default="研究笔记", max_length=300)
    content: str = Field(sa_column=Column(Text, nullable=False))
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    version: int = Field(default=1, ge=1)
    created_by: int = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=utcnow_aware, sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    updated_at: datetime = Field(default_factory=utcnow_aware, sa_column=Column(DateTime(timezone=True), nullable=False, index=True))


class ResearchScope(SQLModel, table=True):
    __tablename__ = "research_scopes"

    id: int | None = Field(default=None, primary_key=True)
    scope_id: str = Field(default_factory=lambda: f"rscope_{uuid.uuid4().hex}", unique=True, index=True, max_length=80)
    workspace_id: str = Field(foreign_key="research_workspaces.workspace_id", index=True, max_length=80)
    parent_scope_id: str | None = Field(default=None, index=True, max_length=80)
    title: str = Field(max_length=240)
    objective: str = Field(default="", sa_column=Column(Text, nullable=False))
    status: str = Field(default="active", index=True, max_length=32)
    context_summary: str = Field(default="", sa_column=Column(Text, nullable=False))
    scope_thread_id: str = Field(
        default_factory=lambda: f"research_thread_{uuid.uuid4().hex}",
        unique=True,
        index=True,
        max_length=128,
    )
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utcnow_aware, sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    updated_at: datetime = Field(default_factory=utcnow_aware, sa_column=Column(DateTime(timezone=True), nullable=False, index=True))


class ResearchMemory(SQLModel, table=True):
    __tablename__ = "research_memories"
    __table_args__ = (
        UniqueConstraint("workspace_id", "content_hash", name="uq_research_memory_workspace_hash"),
    )

    id: int | None = Field(default=None, primary_key=True)
    memory_id: str = Field(default_factory=lambda: f"rmem_{uuid.uuid4().hex}", unique=True, index=True, max_length=80)
    workspace_id: str = Field(foreign_key="research_workspaces.workspace_id", index=True, max_length=80)
    scope_id: str | None = Field(default=None, index=True, max_length=80)
    tier: str = Field(default="long_term", index=True, max_length=32)
    content: str = Field(sa_column=Column(Text, nullable=False))
    content_hash: str = Field(index=True, max_length=64)
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    embedding: list[float] | None = Field(default=None, sa_column=Column(PgVectorType(), nullable=True))
    embedding_provider: str = Field(default="", max_length=80)
    embedding_model: str = Field(default="", max_length=160)
    embedding_dimensions: int = Field(default=0, ge=0)
    created_by: int = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=utcnow_aware, sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    last_accessed_at: datetime = Field(default_factory=utcnow_aware, sa_column=Column(DateTime(timezone=True), nullable=False, index=True))


__all__ = [
    "RESEARCH_WORKSPACE_DATA_POLICY_VERSION",
    "PgVectorType",
    "ResearchMemory",
    "ResearchNote",
    "ResearchScope",
    "ResearchTodo",
    "ResearchWorkspace",
]
