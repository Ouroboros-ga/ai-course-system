"""Harden course experiment grading and laboratory projections.

Revision ID: 0057
Revises: 20260812_learning_adjust
Create Date: 2026-08-13 09:00:00

Batch ``experiment_sandbox_reliability_v1`` establishes the server-owned
formal-run boundary.  Existing lab records are explicitly retained as
``legacy_unverified`` and are not backfilled into trusted projections.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0057"
down_revision = "20260812_learning_adjust"
branch_labels = None
depends_on = None

BATCH_ID = "experiment_sandbox_reliability_v1"
BATCH_NAME = "Experiment sandbox reliability and trusted lab projections"
BATCH_ROLLBACK_NOTES = (
        "Drops 0057 sandbox queue, projection, and recommendation schema. "
    "Legacy lab records remain legacy_unverified; no trusted grade is restored."
)


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    return index in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _record_batch(status: str) -> None:
    """Upsert the business migration ledger inside the Alembic transaction."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "schema_migration_records" not in tables:
        return
    existing = bind.execute(
        sa.text(
            "SELECT id FROM schema_migration_records WHERE batch_id = :batch_id"
        ),
        {"batch_id": BATCH_ID},
    ).first()
    values = {
        "batch_id": BATCH_ID,
        "name": BATCH_NAME,
        "status": status,
        "rollback_notes": BATCH_ROLLBACK_NOTES,
        "preflight_ok": True,
        "applied_rows": 0,
    }
    if existing is None:
        bind.execute(
            sa.text(
                "INSERT INTO schema_migration_records "
                "(batch_id, name, applied_at, status, rollback_notes, "
                "preflight_ok, applied_rows, created_at) "
                "VALUES (:batch_id, :name, CURRENT_TIMESTAMP, :status, "
                ":rollback_notes, :preflight_ok, :applied_rows, CURRENT_TIMESTAMP)"
            ),
            values,
        )
        return
    bind.execute(
        sa.text(
            "UPDATE schema_migration_records "
            "SET name = :name, applied_at = CURRENT_TIMESTAMP, status = :status, "
            "rollback_notes = :rollback_notes, preflight_ok = :preflight_ok, "
            "applied_rows = :applied_rows "
            "WHERE batch_id = :batch_id"
        ),
        values,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column("experiment_versions", "reference_preview_verified_at"):
        op.add_column("experiment_versions", sa.Column("reference_preview_verified_at", sa.DateTime(), nullable=True))
    if not _has_column("experiment_runs", "idempotency_key"):
        op.add_column("experiment_runs", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        op.create_index("ix_experiment_runs_idempotency_key", "experiment_runs", ["idempotency_key"])
    # Formal assessed submissions are idempotent across all web processes. A
    # partial unique index preserves historical rows without an idempotency key.
    predicate = "idempotency_key IS NOT NULL"
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_run_assessed_idempotency "
        "ON experiment_runs (course_id, attempt_id, student_id, idempotency_key) "
        f"WHERE {predicate}"
    )
    if not _has_column("experiment_runs", "cancel_requested_at"):
        op.add_column("experiment_runs", sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))

    if not _has_column("lab_records", "source_kind"):
        op.add_column("lab_records", sa.Column("source_kind", sa.String(length=64), nullable=False, server_default="legacy_unverified"))
    if not _has_column("lab_records", "projection_id"):
        op.add_column("lab_records", sa.Column("projection_id", sa.String(length=100), nullable=True))
    if not _has_column("lab_records", "experiment_id"):
        op.add_column("lab_records", sa.Column("experiment_id", sa.String(length=100), nullable=True))
    if not _has_column("lab_records", "trusted_source"):
        op.add_column("lab_records", sa.Column("trusted_source", sa.Boolean(), nullable=False, server_default=sa.false()))
    for name, columns in (
        ("ix_lab_records_source_kind", ["source_kind"]),
        ("ix_lab_records_projection_id", ["projection_id"]),
        ("ix_lab_records_experiment_id", ["experiment_id"]),
        ("ix_lab_records_trusted_source", ["trusted_source"]),
    ):
        if name not in {item["name"] for item in sa.inspect(bind).get_indexes("lab_records")}:
            op.create_index(name, "lab_records", columns)

    columns = {item["name"] for item in sa.inspect(bind).get_columns("platform_task_concurrency_configs")}
    if "sandbox_execution" not in columns:
        op.add_column(
            "platform_task_concurrency_configs",
            sa.Column("sandbox_execution", sa.Integer(), nullable=False, server_default="1"),
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "sandbox_execution_leases" not in tables:
        op.create_table(
            "sandbox_execution_leases",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("lease_key", sa.String(length=64), nullable=False),
            sa.Column("holder_task_id", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("acquired_at", sa.DateTime(), nullable=True),
            sa.Column("renewed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("lease_key", name="uq_sandbox_execution_leases_lease_key"),
        )
        op.create_index("ix_sandbox_execution_leases_lease_key", "sandbox_execution_leases", ["lease_key"])
        op.create_index("ix_sandbox_execution_leases_holder_task_id", "sandbox_execution_leases", ["holder_task_id"])
        op.create_index("ix_sandbox_execution_leases_lease_expires_at", "sandbox_execution_leases", ["lease_expires_at"])
    if "free_sandbox_quota_windows" not in tables:
        op.create_table(
            "free_sandbox_quota_windows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("window_started_at", sa.DateTime(), nullable=False),
            sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("student_id", "course_id", "window_started_at", name="uq_free_sandbox_quota_window"),
        )
        op.create_index("ix_free_sandbox_quota_windows_student_id", "free_sandbox_quota_windows", ["student_id"])
        op.create_index("ix_free_sandbox_quota_windows_course_id", "free_sandbox_quota_windows", ["course_id"])
        op.create_index("ix_free_sandbox_quota_windows_window_started_at", "free_sandbox_quota_windows", ["window_started_at"])
    if "experiment_lab_projections" not in tables:
        op.create_table(
            "experiment_lab_projections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("projection_id", sa.String(length=100), nullable=False),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("experiment_id", sa.String(length=100), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("projection_id", name="uq_experiment_lab_projections_projection_id"),
            sa.UniqueConstraint("course_id", "experiment_id", name="uq_experiment_lab_projection"),
        )
        op.create_index("ix_experiment_lab_projections_projection_id", "experiment_lab_projections", ["projection_id"])
        op.create_index("ix_experiment_lab_projections_course_id", "experiment_lab_projections", ["course_id"])
        op.create_index("ix_experiment_lab_projections_experiment_id", "experiment_lab_projections", ["experiment_id"])
    if "experiment_recommendations" not in tables:
        op.create_table(
            "experiment_recommendations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("recommendation_id", sa.String(length=100), nullable=False),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("experiment_id", sa.String(length=100), nullable=False),
            sa.Column("version_id", sa.String(length=100), nullable=False),
            sa.Column("outline_node_id", sa.String(length=100), nullable=True),
            sa.Column("proposal_id", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("recommendation_id", name="uq_experiment_recommendations_recommendation_id"),
            sa.UniqueConstraint("course_id", "student_id", "experiment_id", name="uq_experiment_recommendation"),
        )
        for name, columns in (
            ("ix_experiment_recommendations_recommendation_id", ["recommendation_id"]),
            ("ix_experiment_recommendations_course_id", ["course_id"]),
            ("ix_experiment_recommendations_student_id", ["student_id"]),
            ("ix_experiment_recommendations_experiment_id", ["experiment_id"]),
            ("ix_experiment_recommendations_version_id", ["version_id"]),
            ("ix_experiment_recommendations_outline_node_id", ["outline_node_id"]),
            ("ix_experiment_recommendations_proposal_id", ["proposal_id"]),
        ):
            op.create_index(name, "experiment_recommendations", columns)

    # Historical partial-score versions become ACM/ICPC compatible before the
    # publication validator begins rejecting non-binary thresholds.
    bind.execute(sa.text(
        "UPDATE experiment_versions SET passing_score = 1.0 "
        "WHERE passing_score IS NULL OR passing_score <> 1.0"
    ))

    # Boolean literals differ across supported engines.  The partial index is
    # intentionally restricted to trusted projections so historical rows can
    # remain untouched as legacy_unverified data.
    predicate = "trusted_source IS TRUE" if bind.dialect.name == "postgresql" else "trusted_source = 1"
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_lab_records_trusted_attempt "
        f"ON lab_records (attempt_id) WHERE {predicate}"
    )
    _record_batch("applied")


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "experiment_recommendations" in tables:
        op.drop_table("experiment_recommendations")
    if "experiment_lab_projections" in tables:
        op.drop_table("experiment_lab_projections")
    if "free_sandbox_quota_windows" in tables:
        op.drop_table("free_sandbox_quota_windows")
    if "sandbox_execution_leases" in tables:
        op.drop_table("sandbox_execution_leases")
    if "lab_records" in tables:
        op.execute("DROP INDEX IF EXISTS uq_lab_records_trusted_attempt")
        for index in (
            "ix_lab_records_source_kind",
            "ix_lab_records_projection_id",
            "ix_lab_records_experiment_id",
            "ix_lab_records_trusted_source",
        ):
            if _has_index("lab_records", index):
                op.drop_index(index, table_name="lab_records")
        with op.batch_alter_table("lab_records") as batch:
            for column in ("trusted_source", "experiment_id", "projection_id", "source_kind"):
                if _has_column("lab_records", column):
                    batch.drop_column(column)
    if "experiment_runs" in tables:
        op.execute("DROP INDEX IF EXISTS uq_experiment_run_assessed_idempotency")
        if _has_index("experiment_runs", "ix_experiment_runs_idempotency_key"):
            op.drop_index("ix_experiment_runs_idempotency_key", table_name="experiment_runs")
        with op.batch_alter_table("experiment_runs") as batch:
            for column in ("cancel_requested_at", "idempotency_key"):
                if _has_column("experiment_runs", column):
                    batch.drop_column(column)
    if "experiment_versions" in tables and _has_column("experiment_versions", "reference_preview_verified_at"):
        with op.batch_alter_table("experiment_versions") as batch:
            batch.drop_column("reference_preview_verified_at")
    if "platform_task_concurrency_configs" in tables and _has_column("platform_task_concurrency_configs", "sandbox_execution"):
        with op.batch_alter_table("platform_task_concurrency_configs") as batch:
            batch.drop_column("sandbox_execution")
    _record_batch("rolled_back")
