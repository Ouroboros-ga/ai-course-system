"""Create conversation_messages table for the Conversation Domain.

Revision ID: 0040
Revises: 0039

This introduces an independent product-experience domain that persists full
learner / teaching-agent messages so conversations can be resumed after refresh
or re-entry. It is intentionally separate from the data-minimized Agent Runtime
Context / Audit tables (agent_learning_events / agent_trace_records /
agent_conversation_sessions), which still never carry raw messages, answers,
prompts or full traces. See AGENTS.md §5.1 for the boundary.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("concept_id", sa.String(128), nullable=True),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("data_policy_version", sa.String(64), nullable=False, server_default="conversation-domain/1"),
        sa.Column("retention_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_conversation_messages_student_id",
        "conversation_messages",
        ["student_id"],
    )
    op.create_index(
        "ix_conversation_messages_course_id",
        "conversation_messages",
        ["course_id"],
    )
    op.create_index(
        "ix_conversation_messages_session_id",
        "conversation_messages",
        ["session_id"],
    )
    op.create_index(
        "ix_conversation_messages_concept_id",
        "conversation_messages",
        ["concept_id"],
    )
    op.create_index(
        "ix_conversation_messages_retention_until",
        "conversation_messages",
        ["retention_until"],
    )
    op.create_index(
        "ix_conversation_messages_created_at",
        "conversation_messages",
        ["created_at"],
    )
    # Composite index: load a learner's conversation history within a course,
    # ordered by creation time. Covers (student_id, course_id, created_at).
    op.create_index(
        "ix_conversation_messages_student_course_created",
        "conversation_messages",
        ["student_id", "course_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_messages_student_course_created",
        table_name="conversation_messages",
    )
    op.drop_index(
        "ix_conversation_messages_created_at",
        table_name="conversation_messages",
    )
    op.drop_index(
        "ix_conversation_messages_retention_until",
        table_name="conversation_messages",
    )
    op.drop_index(
        "ix_conversation_messages_concept_id",
        table_name="conversation_messages",
    )
    op.drop_index(
        "ix_conversation_messages_session_id",
        table_name="conversation_messages",
    )
    op.drop_index(
        "ix_conversation_messages_course_id",
        table_name="conversation_messages",
    )
    op.drop_index(
        "ix_conversation_messages_student_id",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
