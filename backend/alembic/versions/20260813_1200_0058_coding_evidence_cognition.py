"""Generalize learning projection events for server-scored code evidence.

Revision ID: 0058
Revises: 0057
Create Date: 2026-08-13 12:00:00

The legacy question-attempt FK remains available for compatibility.  Generic
source identity permits non-question evidence such as a finalized experiment
attempt to schedule the same cognition/recommendation projection safely.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

BATCH_ID = "coding_evidence_cognition_v1"
BATCH_NAME = "Generic learning projection sources for code evidence"
BATCH_ROLLBACK_NOTES = (
    "Downgrade removes generic projection events because the legacy schema "
    "requires a question_attempt FK; question-attempt events are retained."
)


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def _unique_constraints(table: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table)
        if constraint.get("name")
    }


def _record_batch(status: str) -> None:
    bind = op.get_bind()
    if "schema_migration_records" not in set(sa.inspect(bind).get_table_names()):
        return
    existing = bind.execute(
        sa.text("SELECT id FROM schema_migration_records WHERE batch_id = :batch_id"),
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
    else:
        bind.execute(
            sa.text(
                "UPDATE schema_migration_records "
                "SET name = :name, applied_at = CURRENT_TIMESTAMP, status = :status, "
                "rollback_notes = :rollback_notes, preflight_ok = :preflight_ok, "
                "applied_rows = :applied_rows WHERE batch_id = :batch_id"
            ),
            values,
        )


def upgrade() -> None:
    table = "learning_projection_outbox"
    if table not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    if "source_type" not in _columns(table):
        op.add_column(
            table,
            sa.Column("source_type", sa.String(length=32), nullable=False, server_default="question_attempt"),
        )
    if "source_ref" not in _columns(table):
        op.add_column(
            table,
            sa.Column("source_ref", sa.String(length=128), nullable=False, server_default=""),
        )
    op.execute(
        "UPDATE learning_projection_outbox SET source_type = 'question_attempt' "
        "WHERE source_type IS NULL OR source_type = ''"
    )
    op.execute(
        "UPDATE learning_projection_outbox SET source_ref = CAST(attempt_id AS TEXT) "
        "WHERE source_ref IS NULL OR source_ref = ''"
    )
    uniques = _unique_constraints(table)
    with op.batch_alter_table(table) as batch:
        if "uq_projection_attempt_node" in uniques:
            batch.drop_constraint("uq_projection_attempt_node", type_="unique")
        batch.alter_column("attempt_id", existing_type=sa.Integer(), nullable=True)
        if "uq_projection_source_scope_node" not in uniques:
            batch.create_unique_constraint(
                "uq_projection_source_scope_node",
                [
                    "source_type",
                    "source_ref",
                    "student_id",
                    "course_id",
                    "knowledge_node_id",
                ],
            )
    existing_indexes = _indexes(table)
    if "ix_learning_projection_outbox_source_type" not in existing_indexes:
        op.create_index("ix_learning_projection_outbox_source_type", table, ["source_type"])
    if "ix_learning_projection_outbox_source_ref" not in existing_indexes:
        op.create_index("ix_learning_projection_outbox_source_ref", table, ["source_ref"])
    _record_batch("applied")


def downgrade() -> None:
    table = "learning_projection_outbox"
    if table not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    # Code-source rows have no representable legacy FK.  Preserve legacy
    # question events, then restore their original uniqueness requirement.
    op.execute(
        "DELETE FROM learning_projection_outbox "
        "WHERE source_type IS NOT NULL AND source_type <> 'question_attempt'"
    )
    indexes = _indexes(table)
    if "ix_learning_projection_outbox_source_ref" in indexes:
        op.drop_index("ix_learning_projection_outbox_source_ref", table_name=table)
    if "ix_learning_projection_outbox_source_type" in indexes:
        op.drop_index("ix_learning_projection_outbox_source_type", table_name=table)
    uniques = _unique_constraints(table)
    with op.batch_alter_table(table) as batch:
        if "uq_projection_source_scope_node" in uniques:
            batch.drop_constraint("uq_projection_source_scope_node", type_="unique")
        batch.create_unique_constraint(
            "uq_projection_attempt_node",
            ["attempt_id", "knowledge_node_id"],
        )
        batch.alter_column("attempt_id", existing_type=sa.Integer(), nullable=False)
        if "source_ref" in _columns(table):
            batch.drop_column("source_ref")
        if "source_type" in _columns(table):
            batch.drop_column("source_type")
    _record_batch("rolled_back")
