"""Persist Prep Agent run lifecycle and bounded LLM diagnostics.

Revision ID: 0036
Revises: 0035
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "agent_run_records" not in tables:
        op.create_table(
            "agent_run_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(128), nullable=False),
            sa.Column("trace_id", sa.String(128), nullable=False),
            sa.Column("agent_type", sa.String(64), nullable=False),
            sa.Column("actor_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("actor_type", sa.String(32), nullable=False, server_default="teacher"),
            sa.Column("course_id", sa.Integer(), nullable=True),
            sa.Column("config_version", sa.String(64), nullable=False, server_default="v1"),
            sa.Column("idempotency_key", sa.String(256), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="running"),
            sa.Column("stage", sa.String(128), nullable=False, server_default=""),
            sa.Column("error_code", sa.String(128), nullable=False, server_default=""),
            sa.Column("error_details", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("result_summary", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
            sa.UniqueConstraint("run_id", name="uq_agent_run_records_run_id"),
        )
        op.create_index("ix_agent_run_records_trace_id", "agent_run_records", ["trace_id"])
        op.create_index("ix_agent_run_records_course_id", "agent_run_records", ["course_id"])
        op.create_index("ix_agent_run_records_status", "agent_run_records", ["status"])
    if "agent_run_event_records" not in tables:
        op.create_table(
            "agent_run_event_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_id", sa.String(128), nullable=False),
            sa.Column("run_id", sa.String(128), nullable=False),
            sa.Column("trace_id", sa.String(128), nullable=False),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("event_id", name="uq_agent_run_event_records_event_id"),
        )
        op.create_index("ix_agent_run_event_records_run_id", "agent_run_event_records", ["run_id"])
        op.create_index("ix_agent_run_event_records_created_at", "agent_run_event_records", ["created_at"])
    if "agent_llm_diagnostic_records" not in tables:
        op.create_table(
            "agent_llm_diagnostic_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("diagnostic_id", sa.String(128), nullable=False),
            sa.Column("run_id", sa.String(128), nullable=False),
            sa.Column("trace_id", sa.String(128), nullable=False),
            sa.Column("course_id", sa.Integer(), nullable=True),
            sa.Column("agent_type", sa.String(64), nullable=False, server_default="prep"),
            sa.Column("stage", sa.String(128), nullable=False, server_default=""),
            sa.Column("node", sa.String(128), nullable=False, server_default=""),
            sa.Column("purpose", sa.String(256), nullable=False, server_default=""),
            sa.Column("prompt_version", sa.String(128), nullable=False, server_default=""),
            sa.Column("schema_name", sa.String(128), nullable=False, server_default=""),
            sa.Column("model", sa.String(256), nullable=False, server_default=""),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("repaired", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("finish_reason", sa.String(64), nullable=False, server_default=""),
            sa.Column("input_tokens", sa.Integer(), nullable=True),
            sa.Column("output_tokens", sa.Integer(), nullable=True),
            sa.Column("input_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("response_hash", sa.String(128), nullable=False, server_default=""),
            sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("response_format_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("response_format_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("validation_errors", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("usage_metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
            sa.UniqueConstraint("diagnostic_id", name="uq_agent_llm_diagnostic_records_diagnostic_id"),
        )
        op.create_index("ix_agent_llm_diagnostic_records_run_id", "agent_llm_diagnostic_records", ["run_id"])
        op.create_index("ix_agent_llm_diagnostic_records_course_id", "agent_llm_diagnostic_records", ["course_id"])
        op.create_index("ix_agent_llm_diagnostic_records_truncated", "agent_llm_diagnostic_records", ["truncated"])


def downgrade() -> None:
    for table in ("agent_llm_diagnostic_records", "agent_run_event_records", "agent_run_records"):
        op.drop_table(table)
