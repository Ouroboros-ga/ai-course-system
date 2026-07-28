"""course-level corpus snapshots and draft build orchestration.

Revision ID: 0021
Revises: 0020
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "course_corpus_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("corpus_snapshot_id", sa.String(), nullable=False, unique=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("material_version_ids", sa.JSON(), nullable=False),
        sa.Column("parse_run_ids", sa.JSON(), nullable=False),
        sa.Column("document_ir_version_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_course_corpus_snapshots_course_id", "course_corpus_snapshots", ["course_id"])
    op.create_index("ix_course_corpus_snapshots_status", "course_corpus_snapshots", ["status"])

    op.create_table(
        "course_retrieval_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("retrieval_snapshot_id", sa.String(), nullable=False, unique=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("corpus_snapshot_id", sa.String(), nullable=False),
        sa.Column("material_version_ids", sa.JSON(), nullable=False),
        sa.Column("document_ir_version_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("provider_policy_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_course_retrieval_snapshots_course_id", "course_retrieval_snapshots", ["course_id"])
    op.create_index("ix_course_retrieval_snapshots_corpus_snapshot_id", "course_retrieval_snapshots", ["corpus_snapshot_id"])
    op.create_index("ix_course_retrieval_snapshots_status", "course_retrieval_snapshots", ["status"])

    op.create_table(
        "course_draft_build_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("build_task_id", sa.String(), nullable=False, unique=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("corpus_snapshot_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("generation_mode", sa.String(), nullable=False),
        sa.Column("base_outline_version_id", sa.String(), nullable=True),
        sa.Column("base_script_version_id", sa.String(), nullable=True),
        sa.Column("result_outline_version_id", sa.String(), nullable=True),
        sa.Column("result_script_version_id", sa.String(), nullable=True),
        sa.Column("result_retrieval_snapshot_id", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("course_id", "corpus_snapshot_id", "task_id", "status"):
        op.create_index(f"ix_course_draft_build_tasks_{column}", "course_draft_build_tasks", [column])

    with op.batch_alter_table("course_releases") as batch:
        batch.add_column(sa.Column("material_version_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("document_ir_run_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("document_ir_version_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("corpus_snapshot_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("retrieval_snapshot_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("outline_version_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("script_version_id", sa.String(), nullable=True))
    for column in ("corpus_snapshot_id", "retrieval_snapshot_id", "outline_version_id", "script_version_id"):
        op.create_index(f"ix_course_releases_{column}", "course_releases", [column])

    for table in ("course_outline_versions", "teaching_script_versions"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("corpus_snapshot_id", sa.String(), nullable=True))
            batch.add_column(sa.Column("build_task_id", sa.String(), nullable=True))
            batch.add_column(sa.Column("generation_source", sa.String(length=64), nullable=False, server_default="teacher"))
            batch.add_column(sa.Column("review_status", sa.String(length=32), nullable=False, server_default="pending"))
        op.create_index(f"ix_{table}_corpus_snapshot_id", table, ["corpus_snapshot_id"])
        op.create_index(f"ix_{table}_build_task_id", table, ["build_task_id"])


def downgrade() -> None:
    for table in ("teaching_script_versions", "course_outline_versions"):
        op.drop_index(f"ix_{table}_build_task_id", table_name=table)
        op.drop_index(f"ix_{table}_corpus_snapshot_id", table_name=table)
        with op.batch_alter_table(table) as batch:
            for column in ("review_status", "generation_source", "build_task_id", "corpus_snapshot_id"):
                batch.drop_column(column)
    for column in ("corpus_snapshot_id", "retrieval_snapshot_id", "outline_version_id", "script_version_id"):
        op.drop_index(f"ix_course_releases_{column}", table_name="course_releases")
    with op.batch_alter_table("course_releases") as batch:
        for column in ("script_version_id", "outline_version_id", "retrieval_snapshot_id", "corpus_snapshot_id", "document_ir_version_ids", "document_ir_run_ids", "material_version_ids"):
            batch.drop_column(column)
    op.drop_table("course_draft_build_tasks")
    op.drop_table("course_retrieval_snapshots")
    op.drop_table("course_corpus_snapshots")
