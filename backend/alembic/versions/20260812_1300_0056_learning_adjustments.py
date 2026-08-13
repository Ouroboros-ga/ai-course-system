"""Add minimal learner-confirmed learning adjustment records.

Revision ID: 0056
Revises: 0055
Create Date: 2026-08-12 13:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "learning_adjustments"


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_table(TABLE):
        op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("adjustment_id", sa.String(length=128), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("source_trace_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="proposed"),
        sa.Column("question_course_release_id", sa.String(length=128), nullable=False),
        sa.Column("question_media_release_id", sa.String(length=128), nullable=False),
        sa.Column("question_media_release_item_id", sa.String(length=128), nullable=False),
        sa.Column("question_outline_node_id", sa.String(length=128), nullable=False),
        sa.Column("question_local_time_ms", sa.Integer(), nullable=False),
        sa.Column("question_page", sa.Integer(), nullable=False),
        sa.Column("question_global_time_ms", sa.Integer(), nullable=True),
        sa.Column("review_course_release_id", sa.String(length=128), nullable=False),
        sa.Column("review_media_release_id", sa.String(length=128), nullable=False),
        sa.Column("review_media_release_item_id", sa.String(length=128), nullable=False),
        sa.Column("review_outline_node_id", sa.String(length=128), nullable=False),
        sa.Column("review_local_time_ms", sa.Integer(), nullable=False),
        sa.Column("review_page", sa.Integer(), nullable=False),
        sa.Column("review_global_time_ms", sa.Integer(), nullable=True),
        sa.Column("return_course_release_id", sa.String(length=128), nullable=True),
        sa.Column("return_media_release_id", sa.String(length=128), nullable=True),
        sa.Column("return_media_release_item_id", sa.String(length=128), nullable=True),
        sa.Column("return_outline_node_id", sa.String(length=128), nullable=True),
        sa.Column("return_local_time_ms", sa.Integer(), nullable=True),
        sa.Column("return_page", sa.Integer(), nullable=True),
        sa.Column("return_global_time_ms", sa.Integer(), nullable=True),
        sa.Column("teaching_action", sa.String(length=64), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("recommended_playback_rate", sa.Float(), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("apply_idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("return_idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("dismiss_idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('proposed', 'applied', 'returned')", name="ck_learning_adjustment_status"),
        sa.CheckConstraint("question_local_time_ms >= 0 AND review_local_time_ms >= 0", name="ck_learning_adjustment_coordinate_time"),
        sa.CheckConstraint("question_page >= 1 AND review_page >= 1", name="ck_learning_adjustment_coordinate_page"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("adjustment_id", name="uq_learning_adjustment_adjustment_id"),
        sa.UniqueConstraint("student_id", "adjustment_id", name="uq_learning_adjustment_student_id"),
        sa.UniqueConstraint("student_id", "apply_idempotency_key", name="uq_learning_adjustment_apply_idempotency"),
        sa.UniqueConstraint("student_id", "return_idempotency_key", name="uq_learning_adjustment_return_idempotency"),
        sa.UniqueConstraint("student_id", "dismiss_idempotency_key", name="uq_learning_adjustment_dismiss_idempotency"),
    )
        for column in (
            "adjustment_id", "course_id", "student_id", "source_trace_id", "status",
            "question_course_release_id", "question_media_release_id",
            "review_course_release_id", "review_media_release_id",
            "declined_at", "invalidated_at", "created_at",
        ):
            op.create_index(f"ix_{TABLE}_{column}", TABLE, [column])
    elif not _has_column(TABLE, "source_trace_id"):
        with op.batch_alter_table(TABLE) as batch_op:
            batch_op.add_column(sa.Column("source_trace_id", sa.String(length=128), nullable=True))
        op.create_index(f"ix_{TABLE}_source_trace_id", TABLE, ["source_trace_id"])


def downgrade() -> None:
    if _has_table(TABLE):
        op.drop_table(TABLE)
