"""Canonical learning events and projections.

Revision ID: 0039
Revises: 0038
"""
from alembic import op
import sqlalchemy as sa

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.String(100), nullable=False),
        sa.Column("outline_node_id", sa.String(100), nullable=False),
        sa.Column("knowledge_node_key", sa.String(150), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default="learn_page"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id"),
        sa.UniqueConstraint("student_id", "idempotency_key", name="uq_learning_event_idempotency"),
    )
    op.create_index("ix_learning_events_student_id", "learning_events", ["student_id"])
    op.create_index("ix_learning_events_course_id", "learning_events", ["course_id"])
    op.create_index("ix_learning_events_release_id", "learning_events", ["release_id"])
    op.create_index("ix_learning_events_outline_node_id", "learning_events", ["outline_node_id"])
    op.create_index("ix_learning_events_occurred_at", "learning_events", ["occurred_at"])

    op.create_table(
        "student_learning_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.String(100), nullable=False),
        sa.Column("outline_node_id", sa.String(100), nullable=False),
        sa.Column("knowledge_node_key", sa.String(150), nullable=True),
        sa.Column("exposure_status", sa.String(32), nullable=False, server_default="not_started"),
        sa.Column("exposure_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("completion_reason", sa.String(64), nullable=True),
        sa.Column("current_timestamp", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_accessed_at", sa.DateTime(), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_event_id", sa.String(100), nullable=True),
        sa.Column("projection_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("student_id", "course_id", "release_id", "outline_node_id", name="uq_student_learning_projection_node"),
    )
    for col in ("student_id", "course_id", "release_id", "outline_node_id", "exposure_status", "last_accessed_at"):
        op.create_index(f"ix_student_learning_projections_{col}", "student_learning_projections", [col])

    op.create_table(
        "course_learning_stats_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.String(100), nullable=False),
        sa.Column("outline_node_id", sa.String(100), nullable=False),
        sa.Column("student_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("not_started_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("in_progress_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mastery_distribution", sa.JSON(), nullable=False),
        sa.Column("unknown_mastery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("low_confidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_recommendation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("projection_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_id", "release_id", "outline_node_id", name="uq_course_learning_stats_node"),
    )
    op.create_index("ix_course_learning_stats_projections_course_id", "course_learning_stats_projections", ["course_id"])
    op.create_index("ix_course_learning_stats_projections_release_id", "course_learning_stats_projections", ["release_id"])
    op.create_index("ix_course_learning_stats_projections_outline_node_id", "course_learning_stats_projections", ["outline_node_id"])

    op.create_table(
        "learning_evidence_contexts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_id", sa.String(150), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_node_key", sa.String(150), nullable=True),
        sa.Column("source_release_id", sa.String(100), nullable=True),
        sa.Column("outline_node_id", sa.String(100), nullable=True),
        sa.Column("event_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("evidence_id", name="uq_learning_evidence_context_evidence"),
    )
    op.create_index("ix_learning_evidence_contexts_course_id", "learning_evidence_contexts", ["course_id"])
    op.create_index("ix_learning_evidence_contexts_knowledge_node_key", "learning_evidence_contexts", ["knowledge_node_key"])


def downgrade() -> None:
    op.drop_table("learning_evidence_contexts")
    op.drop_table("course_learning_stats_projections")
    op.drop_table("student_learning_projections")
    op.drop_table("learning_events")
