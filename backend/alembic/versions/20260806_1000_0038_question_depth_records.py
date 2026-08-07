"""Create question_depth_records table for LLM-calibrated inquiry depth.

Revision ID: 0038
Revises: 0037
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_depth_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=True),
        sa.Column("depth_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("depth_label", sa.String(), nullable=False, server_default=""),
        sa.Column("trace_id", sa.String(), nullable=False, server_default=""),
        sa.Column("source", sa.String(), nullable=False, server_default="teaching_agent"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_question_depth_records_student_id",
        "question_depth_records",
        ["student_id"],
    )
    op.create_index(
        "ix_question_depth_records_course_id",
        "question_depth_records",
        ["course_id"],
    )
    op.create_index(
        "ix_question_depth_records_node_id",
        "question_depth_records",
        ["node_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_question_depth_records_node_id",
        table_name="question_depth_records",
    )
    op.drop_index(
        "ix_question_depth_records_course_id",
        table_name="question_depth_records",
    )
    op.drop_index(
        "ix_question_depth_records_student_id",
        table_name="question_depth_records",
    )
    op.drop_table("question_depth_records")
