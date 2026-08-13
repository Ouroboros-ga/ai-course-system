"""Add versioned TeachingAgent constraints and minimized evaluations.

Revision ID: 0055
Revises: 0054
Create Date: 2026-08-12 10:00:00

This migration is intentionally additive.  It does not reuse or mutate the
existing generic agent policy/version tables, Conversation Domain, learning
evidence or media tables.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

POLICY_TABLE = "teaching_constraint_policy_versions"
EVALUATION_TABLE = "teaching_constraint_evaluations"


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table(POLICY_TABLE):
        op.create_table(
            POLICY_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("course_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("policy_snapshot", sa.Text(), nullable=False),
            sa.Column("policy_hash", sa.String(length=64), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("change_reason", sa.String(length=256), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("version >= 1", name="ck_teaching_constraint_version_positive"),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "course_id",
                "version",
                name="uq_teaching_constraint_course_version",
            ),
        )
        op.create_index(
            "uq_teaching_constraint_active_course",
            POLICY_TABLE,
            ["course_id"],
            unique=True,
            postgresql_where=sa.text("is_active"),
            sqlite_where=sa.text("is_active = 1"),
        )
        op.create_index(
            "ix_teaching_constraint_policy_versions_course_id",
            POLICY_TABLE,
            ["course_id"],
        )
        op.create_index(
            "ix_teaching_constraint_policy_versions_policy_hash",
            POLICY_TABLE,
            ["policy_hash"],
        )
        op.create_index(
            "ix_teaching_constraint_policy_versions_is_active",
            POLICY_TABLE,
            ["is_active"],
        )
        op.create_index(
            "ix_teaching_constraint_policy_versions_created_by",
            POLICY_TABLE,
            ["created_by"],
        )
        op.create_index(
            "ix_teaching_constraint_policy_versions_created_at",
            POLICY_TABLE,
            ["created_at"],
        )

    if not _has_table(EVALUATION_TABLE):
        op.create_table(
            EVALUATION_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("trace_id", sa.String(length=128), nullable=False),
            sa.Column("course_id", sa.Integer(), nullable=False),
            sa.Column("student_id", sa.Integer(), nullable=False),
            sa.Column("policy_version_id", sa.Integer(), nullable=False),
            sa.Column("effective_level", sa.String(length=16), nullable=False),
            sa.Column("matched_rule_ids", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("applied_scopes", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("decision_codes", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("context_input_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("context_output_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_citation_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("enforcement_status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "context_input_chars >= 0 AND context_output_chars >= 0 AND valid_citation_count >= 0",
                name="ck_teaching_constraint_evaluation_counts",
            ),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
            sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
            sa.ForeignKeyConstraint(
                ["policy_version_id"],
                [f"{POLICY_TABLE}.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in (
            "trace_id",
            "course_id",
            "student_id",
            "policy_version_id",
            "effective_level",
            "enforcement_status",
            "created_at",
        ):
            op.create_index(
                f"ix_{EVALUATION_TABLE}_{column}",
                EVALUATION_TABLE,
                [column],
            )


def downgrade() -> None:
    if _has_table(EVALUATION_TABLE):
        op.drop_table(EVALUATION_TABLE)
    if _has_table(POLICY_TABLE):
        op.drop_table(POLICY_TABLE)
