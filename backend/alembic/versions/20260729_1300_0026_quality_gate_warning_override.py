"""Require explicit teacher acknowledgement for release warnings.

Revision ID: 0026
Revises: 0025
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("course_quality_gate_runs") as batch:
        batch.add_column(sa.Column(
            "warning_override_confirmed_by", sa.Integer(), nullable=True,
        ))
        batch.add_column(sa.Column(
            "warning_override_reason", sa.String(), nullable=False, server_default="",
        ))
        batch.add_column(sa.Column(
            "warning_override_at", sa.DateTime(timezone=True), nullable=True,
        ))
        batch.create_foreign_key(
            "fk_course_quality_gate_warning_override_user",
            "users",
            ["warning_override_confirmed_by"], ["id"],
        )


def downgrade():
    with op.batch_alter_table("course_quality_gate_runs") as batch:
        batch.drop_constraint("fk_course_quality_gate_warning_override_user", type_="foreignkey")
        batch.drop_column("warning_override_at")
        batch.drop_column("warning_override_reason")
        batch.drop_column("warning_override_confirmed_by")
