"""Trusted asynchronous experiment execution and lab projection boundary.

Revision ID: 0055
Revises: 0054
Create Date: 2026-08-12 15:30:00

Batch: experiment-sandbox-reliability-20260812

The migration is intentionally explicit rather than relying on SQLModel
metadata at startup.  Existing lab rows retain ``legacy_unverified`` and are
excluded from the new projection reads; only the worker can create rows marked
``experiment_finalization``.  The partial unique index gives each terminal
attempt one trusted lab record without invalidating historical duplicates.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _columns(name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(name)}


def _indexes(name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(name)}


def upgrade() -> None:
    if _has_table("experiment_runs"):
        existing = _columns("experiment_runs")
        with op.batch_alter_table("experiment_runs", recreate="auto") as batch:
            if "idempotency_key" not in existing:
                batch.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        if "uq_experiment_run_attempt_idempotency" not in _indexes("experiment_runs"):
            op.create_index(
                "uq_experiment_run_attempt_idempotency",
                "experiment_runs",
                ["attempt_id", "idempotency_key"],
                unique=True,
            )

    if _has_table("experiment_versions") and "reference_preview_verified_at" not in _columns("experiment_versions"):
        with op.batch_alter_table("experiment_versions", recreate="auto") as batch:
            batch.add_column(sa.Column("reference_preview_verified_at", sa.DateTime(), nullable=True))

    if _has_table("lab_records"):
        existing = _columns("lab_records")
        with op.batch_alter_table("lab_records", recreate="auto") as batch:
            if "record_source" not in existing:
                batch.add_column(
                    sa.Column(
                        "record_source",
                        sa.String(length=64),
                        nullable=False,
                        server_default="legacy_unverified",
                    )
                )
            if "projection_id" not in existing:
                batch.add_column(sa.Column("projection_id", sa.String(length=128), nullable=True))
        if "ix_lab_records_record_source" not in _indexes("lab_records"):
            op.create_index("ix_lab_records_record_source", "lab_records", ["record_source"])
        if "ix_lab_records_projection_id" not in _indexes("lab_records"):
            op.create_index("ix_lab_records_projection_id", "lab_records", ["projection_id"])
        dialect = op.get_bind().dialect.name
        if dialect == "sqlite":
            op.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_lab_record_terminal_attempt "
                "ON lab_records (attempt_id) "
                "WHERE record_source = 'experiment_finalization' AND attempt_id IS NOT NULL"
            )
        elif dialect == "postgresql":
            op.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_lab_record_terminal_attempt "
                "ON lab_records (attempt_id) "
                "WHERE record_source = 'experiment_finalization' AND attempt_id IS NOT NULL"
            )

    if _has_table("platform_task_concurrency_configs") and "sandbox_execution" not in _columns("platform_task_concurrency_configs"):
        with op.batch_alter_table("platform_task_concurrency_configs", recreate="auto") as batch:
            batch.add_column(sa.Column("sandbox_execution", sa.Integer(), nullable=False, server_default="1"))

    if not _has_table("free_sandbox_quota_windows"):
        op.create_table(
            "free_sandbox_quota_windows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("window_started_at", sa.DateTime(), nullable=False),
            sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("course_id", "student_id", "window_started_at", name="uq_free_sandbox_quota_window"),
        )
        op.create_index("ix_free_sandbox_quota_windows_course_id", "free_sandbox_quota_windows", ["course_id"])
        op.create_index("ix_free_sandbox_quota_windows_student_id", "free_sandbox_quota_windows", ["student_id"])
        op.create_index("ix_free_sandbox_quota_windows_window_started_at", "free_sandbox_quota_windows", ["window_started_at"])

    if not _has_table("sandbox_execution_leases"):
        op.create_table(
            "sandbox_execution_leases",
            sa.Column("lease_name", sa.String(length=80), primary_key=True),
            sa.Column("holder_task_id", sa.String(length=128), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_sandbox_execution_leases_holder_task_id", "sandbox_execution_leases", ["holder_task_id"])
        op.create_index("ix_sandbox_execution_leases_lease_expires_at", "sandbox_execution_leases", ["lease_expires_at"])

    if not _has_table("experiment_lab_projections"):
        op.create_table(
            "experiment_lab_projections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("projection_id", sa.String(length=128), nullable=False, unique=True),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("experiment_id", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("course_id", "experiment_id", name="uq_experiment_lab_projection"),
        )
        op.create_index("ix_experiment_lab_projections_course_id", "experiment_lab_projections", ["course_id"])
        op.create_index("ix_experiment_lab_projections_experiment_id", "experiment_lab_projections", ["experiment_id"])

    if not _has_table("experiment_recommendations"):
        op.create_table(
            "experiment_recommendations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("recommendation_id", sa.String(length=128), nullable=False, unique=True),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("experiment_id", sa.String(length=128), nullable=False),
            sa.Column("version_id", sa.String(length=128), nullable=False),
            sa.Column("proposal_id", sa.String(length=128), nullable=False),
            sa.Column("directory_node_id", sa.String(length=128), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "course_id", "student_id", "experiment_id", "proposal_id",
                name="uq_experiment_recommendation_proposal",
            ),
        )
        for field in ("recommendation_id", "course_id", "student_id", "experiment_id", "version_id", "proposal_id", "directory_node_id"):
            op.create_index(f"ix_experiment_recommendations_{field}", "experiment_recommendations", [field])


def downgrade() -> None:
    # Only schema introduced by this explicit batch is reversed. Historical
    # lab values are preserved; after downgrade they simply become unread by
    # the trusted projection API.
    if _has_table("experiment_recommendations"):
        op.drop_table("experiment_recommendations")
    if _has_table("experiment_lab_projections"):
        op.drop_table("experiment_lab_projections")
    if _has_table("sandbox_execution_leases"):
        op.drop_table("sandbox_execution_leases")
    if _has_table("free_sandbox_quota_windows"):
        op.drop_table("free_sandbox_quota_windows")
    if _has_table("platform_task_concurrency_configs") and "sandbox_execution" in _columns("platform_task_concurrency_configs"):
        with op.batch_alter_table("platform_task_concurrency_configs", recreate="auto") as batch:
            batch.drop_column("sandbox_execution")
    if _has_table("lab_records"):
        op.execute("DROP INDEX IF EXISTS uq_lab_record_terminal_attempt")
        with op.batch_alter_table("lab_records", recreate="auto") as batch:
            if "projection_id" in _columns("lab_records"):
                batch.drop_column("projection_id")
            if "record_source" in _columns("lab_records"):
                batch.drop_column("record_source")
    if _has_table("experiment_versions") and "reference_preview_verified_at" in _columns("experiment_versions"):
        with op.batch_alter_table("experiment_versions", recreate="auto") as batch:
            batch.drop_column("reference_preview_verified_at")
    if _has_table("experiment_runs"):
        op.drop_index("uq_experiment_run_attempt_idempotency", table_name="experiment_runs")
        if "idempotency_key" in _columns("experiment_runs"):
            with op.batch_alter_table("experiment_runs", recreate="auto") as batch:
                batch.drop_column("idempotency_key")
