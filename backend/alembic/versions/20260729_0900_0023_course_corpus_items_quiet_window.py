"""Add explicit corpus items and deferred course-draft build scheduling.

Revision ID: 0024
Revises: 0023
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("source_materials") as batch:
        batch.add_column(sa.Column(
            "include_in_course_corpus", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ))

    with op.batch_alter_table("course_corpus_snapshots") as batch:
        batch.add_column(sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"))

    op.create_table(
        "course_corpus_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("corpus_snapshot_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("material_id", sa.String(), nullable=False),
        sa.Column("material_version_id", sa.String(), nullable=False),
        sa.Column("material_role", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("document_ir_version_id", sa.String(), nullable=False),
        sa.Column("parse_run_id", sa.String(), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("quality_warning", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("corpus_snapshot_id", "material_version_id", name="uq_corpus_item_version"),
    )
    for column in (
        "corpus_snapshot_id", "course_id", "material_id", "material_version_id",
        "material_role", "document_ir_version_id", "parse_run_id", "included",
    ):
        op.create_index(f"ix_course_corpus_items_{column}", "course_corpus_items", [column])

    with op.batch_alter_table("course_draft_build_tasks") as batch:
        batch.add_column(sa.Column("not_before_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_course_draft_build_tasks_not_before_at", "course_draft_build_tasks", ["not_before_at"])


def downgrade():
    op.drop_index("ix_course_draft_build_tasks_not_before_at", table_name="course_draft_build_tasks")
    with op.batch_alter_table("course_draft_build_tasks") as batch:
        batch.drop_column("not_before_at")
    op.drop_table("course_corpus_items")
    with op.batch_alter_table("course_corpus_snapshots") as batch:
        batch.drop_column("warnings")
    with op.batch_alter_table("source_materials") as batch:
        batch.drop_column("include_in_course_corpus")
