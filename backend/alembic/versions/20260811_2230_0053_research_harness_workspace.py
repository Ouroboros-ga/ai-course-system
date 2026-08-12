"""Add ResearchAgent Harness workspace and pgvector memory.

Revision ID: 0053
Revises: 0052
Migration batch: research-harness-workspace-v1

There is no legacy ResearchAgent workspace data to transform.  The upgrade
therefore creates an empty schema only.  PostgreSQL installs pgvector before
the ``VECTOR`` column is created; SQLite keeps a custom VECTOR affinity for
local Demo and migration tests.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


class VectorType(sa.types.UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):  # noqa: ANN001, ANN201, ARG002
        return "VECTOR"


def _has_table(bind, name: str) -> bool:  # noqa: ANN001
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    if not _has_table(bind, "research_workspaces"):
        op.create_table(
            "research_workspaces",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.String(80), nullable=False),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("active_scope_id", sa.String(80), nullable=True),
            sa.Column("short_term_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("context_budget_tokens", sa.Integer(), nullable=False, server_default="4000"),
            sa.Column("data_policy_version", sa.String(64), nullable=False, server_default="research-workspace/1"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("workspace_id", name="uq_research_workspaces_workspace_id"),
            sa.UniqueConstraint("course_id", "owner_user_id", name="uq_research_workspace_course_owner"),
        )
        op.create_index("ix_research_workspaces_workspace_id", "research_workspaces", ["workspace_id"])
        op.create_index("ix_research_workspace_course_owner", "research_workspaces", ["course_id", "owner_user_id"])
        op.create_index("ix_research_workspaces_status", "research_workspaces", ["status"])
        op.create_index("ix_research_workspaces_active_scope_id", "research_workspaces", ["active_scope_id"])
        op.create_index("ix_research_workspaces_created_at", "research_workspaces", ["created_at"])
        op.create_index("ix_research_workspaces_updated_at", "research_workspaces", ["updated_at"])

    if not _has_table(bind, "research_scopes"):
        op.create_table(
            "research_scopes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("scope_id", sa.String(80), nullable=False),
            sa.Column("workspace_id", sa.String(80), sa.ForeignKey("research_workspaces.workspace_id"), nullable=False),
            sa.Column("parent_scope_id", sa.String(80), nullable=True),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("objective", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("context_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("scope_thread_id", sa.String(128), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("scope_id", name="uq_research_scopes_scope_id"),
            sa.UniqueConstraint("scope_thread_id", name="uq_research_scopes_scope_thread_id"),
        )
        op.create_index("ix_research_scopes_workspace_status", "research_scopes", ["workspace_id", "status"])
        op.create_index("ix_research_scopes_parent_scope_id", "research_scopes", ["parent_scope_id"])
        op.create_index("ix_research_scopes_scope_thread_id", "research_scopes", ["scope_thread_id"])

    if not _has_table(bind, "research_todos"):
        op.create_table(
            "research_todos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("todo_id", sa.String(80), nullable=False),
            sa.Column("workspace_id", sa.String(80), sa.ForeignKey("research_workspaces.workspace_id"), nullable=False),
            sa.Column("scope_id", sa.String(80), nullable=True),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("todo_id", name="uq_research_todos_todo_id"),
        )
        op.create_index("ix_research_todos_workspace_status_priority", "research_todos", ["workspace_id", "status", "priority"])
        op.create_index("ix_research_todos_scope_id", "research_todos", ["scope_id"])
        op.create_index("ix_research_todos_created_by", "research_todos", ["created_by"])

    if not _has_table(bind, "research_notes"):
        op.create_table(
            "research_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("note_id", sa.String(80), nullable=False),
            sa.Column("workspace_id", sa.String(80), sa.ForeignKey("research_workspaces.workspace_id"), nullable=False),
            sa.Column("scope_id", sa.String(80), nullable=True),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("note_id", name="uq_research_notes_note_id"),
        )
        op.create_index("ix_research_notes_workspace_scope", "research_notes", ["workspace_id", "scope_id"])
        op.create_index("ix_research_notes_updated_at", "research_notes", ["updated_at"])

    if not _has_table(bind, "research_memories"):
        op.create_table(
            "research_memories",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("memory_id", sa.String(80), nullable=False),
            sa.Column("workspace_id", sa.String(80), sa.ForeignKey("research_workspaces.workspace_id"), nullable=False),
            sa.Column("scope_id", sa.String(80), nullable=True),
            sa.Column("tier", sa.String(32), nullable=False, server_default="long_term"),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("keywords", sa.JSON(), nullable=False),
            sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("embedding", VectorType(), nullable=True),
            sa.Column("embedding_provider", sa.String(80), nullable=False, server_default=""),
            sa.Column("embedding_model", sa.String(160), nullable=False, server_default=""),
            sa.Column("embedding_dimensions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("memory_id", name="uq_research_memories_memory_id"),
            sa.UniqueConstraint("workspace_id", "content_hash", name="uq_research_memory_workspace_hash"),
        )
        op.create_index("ix_research_memories_workspace_tier", "research_memories", ["workspace_id", "tier"])
        op.create_index("ix_research_memories_scope_id", "research_memories", ["scope_id"])
        op.create_index("ix_research_memories_embedding_dimensions", "research_memories", ["embedding_dimensions"])
        op.create_index("ix_research_memories_last_accessed_at", "research_memories", ["last_accessed_at"])


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in (
        "research_memories",
        "research_notes",
        "research_todos",
        "research_scopes",
        "research_workspaces",
    ):
        if _has_table(bind, table_name):
            op.drop_table(table_name)
    # pgvector may be shared by other domains; downgrade intentionally keeps
    # the extension installed and removes only ResearchAgent-owned objects.
