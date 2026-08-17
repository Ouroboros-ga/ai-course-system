"""Create learning_trajectory_records table for per-student per-course trajectory.

Revision ID: 0065
Revises: 0064
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_trajectory_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=True),
        sa.Column("dedup_key", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_learning_trajectory_records_student_id",
        "learning_trajectory_records",
        ["student_id"],
    )
    op.create_index(
        "ix_learning_trajectory_records_course_id",
        "learning_trajectory_records",
        ["course_id"],
    )
    op.create_index(
        "ix_learning_trajectory_records_event_type",
        "learning_trajectory_records",
        ["event_type"],
    )
    op.create_index(
        "ix_learning_trajectory_records_concept_id",
        "learning_trajectory_records",
        ["concept_id"],
    )
    op.create_index(
        "ix_learning_trajectory_records_dedup_key",
        "learning_trajectory_records",
        ["dedup_key"],
    )
    op.create_index(
        "ix_learning_trajectory_records_created_at",
        "learning_trajectory_records",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learning_trajectory_records_created_at",
        table_name="learning_trajectory_records",
    )
    op.drop_index(
        "ix_learning_trajectory_records_dedup_key",
        table_name="learning_trajectory_records",
    )
    op.drop_index(
        "ix_learning_trajectory_records_concept_id",
        table_name="learning_trajectory_records",
    )
    op.drop_index(
        "ix_learning_trajectory_records_event_type",
        table_name="learning_trajectory_records",
    )
    op.drop_index(
        "ix_learning_trajectory_records_course_id",
        table_name="learning_trajectory_records",
    )
    op.drop_index(
        "ix_learning_trajectory_records_student_id",
        table_name="learning_trajectory_records",
    )
    op.drop_table("learning_trajectory_records")
