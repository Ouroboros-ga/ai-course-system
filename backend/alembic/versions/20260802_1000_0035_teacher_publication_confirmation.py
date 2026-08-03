"""Record teacher confirmation for publishable check findings.

Revision ID: 0035
Revises: 0034
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("course_quality_gate_runs") as batch:
        batch.add_column(sa.Column("teacher_confirmation_confirmed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("teacher_confirmation_reason", sa.String(), nullable=False, server_default=""))
        batch.add_column(sa.Column("teacher_confirmation_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_course_quality_gate_teacher_confirmation_user",
            "users",
            ["teacher_confirmation_confirmed_by"],
            ["id"],
        )
    with op.batch_alter_table("course_releases") as batch:
        batch.add_column(sa.Column("publication_check_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("publication_issues", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("teacher_confirmation_confirmed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("teacher_confirmation_reason", sa.String(), nullable=False, server_default=""))
        batch.add_column(sa.Column("teacher_confirmation_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_course_release_teacher_confirmation_user",
            "users",
            ["teacher_confirmation_confirmed_by"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("course_releases") as batch:
        batch.drop_constraint("fk_course_release_teacher_confirmation_user", type_="foreignkey")
        batch.drop_column("teacher_confirmation_at")
        batch.drop_column("teacher_confirmation_reason")
        batch.drop_column("teacher_confirmation_confirmed_by")
        batch.drop_column("publication_issues")
        batch.drop_column("publication_check_snapshot")
    with op.batch_alter_table("course_quality_gate_runs") as batch:
        batch.drop_constraint("fk_course_quality_gate_teacher_confirmation_user", type_="foreignkey")
        batch.drop_column("teacher_confirmation_at")
        batch.drop_column("teacher_confirmation_reason")
        batch.drop_column("teacher_confirmation_confirmed_by")
