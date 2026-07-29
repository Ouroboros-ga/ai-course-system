"""Add durable course-build stage checkpoints.

Revision ID: 0029
Revises: 0028
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "course_draft_build_checkpoints" in inspector.get_table_names():
        return
    op.create_table(
        "course_draft_build_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("checkpoint_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("build_task_id", sa.String(), nullable=False),
        sa.Column("corpus_snapshot_id", sa.String(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.UniqueConstraint("checkpoint_id"),
        sa.UniqueConstraint("build_task_id", "stage", name="uq_course_build_checkpoint_stage"),
    )
    op.create_index("ix_course_draft_build_checkpoints_checkpoint_id", "course_draft_build_checkpoints", ["checkpoint_id"], unique=True)
    op.create_index("ix_course_draft_build_checkpoints_course_id", "course_draft_build_checkpoints", ["course_id"])
    op.create_index("ix_course_draft_build_checkpoints_build_task_id", "course_draft_build_checkpoints", ["build_task_id"])
    op.create_index("ix_course_draft_build_checkpoints_corpus_snapshot_id", "course_draft_build_checkpoints", ["corpus_snapshot_id"])
    op.create_index("ix_course_draft_build_checkpoints_stage", "course_draft_build_checkpoints", ["stage"])
    # The active-build index is added in this migration so two workers cannot
    # acquire the same course lease even if they race between SELECT and INSERT.
    if "course_draft_build_tasks" in inspector.get_table_names():
        active_rows = bind.execute(sa.text(
            "SELECT id, course_id FROM course_draft_build_tasks "
            "WHERE status IN ('queued', 'running') ORDER BY id DESC"
        )).mappings().all()
        seen_courses: set[int] = set()
        for row in active_rows:
            if row["course_id"] in seen_courses:
                bind.execute(sa.text(
                    "UPDATE course_draft_build_tasks SET status='cancelled', "
                    "error_code='CORPUS_CHANGED', error_message='migration: duplicate active course build' "
                    "WHERE id=:id"
                ), {"id": row["id"]})
            else:
                seen_courses.add(row["course_id"])
        op.create_index(
            "uq_course_draft_build_active_course",
            "course_draft_build_tasks",
            ["course_id"],
            unique=True,
            sqlite_where=sa.text("status IN ('queued', 'running')"),
        )


def downgrade() -> None:
    op.drop_table("course_draft_build_checkpoints")
