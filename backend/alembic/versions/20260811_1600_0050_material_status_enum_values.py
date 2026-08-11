"""Allow current material-status enum values in PostgreSQL.

Revision ID: 0050
Revises: 0049
Create Date: 2026-08-11 16:00:00
"""
from __future__ import annotations

from alembic import op


revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


CURRENT_MATERIAL_STATUS_VALUES = (
    "uploaded",
    "parsing",
    "parsed",
    "needs_review",
    "failed",
    "superseded",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # The baseline used SQLAlchemy enum member names.  Current course build
    # code stores lower-case state values, including the newer needs_review.
    for value in CURRENT_MATERIAL_STATUS_VALUES:
        op.execute(f"ALTER TYPE materialstatus ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        raise RuntimeError(
            "0050 appends PostgreSQL enum values and cannot be safely downgraded; "
            "roll back by restoring the previous service/database environment before traffic resumes"
        )
