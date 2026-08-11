"""Add missing PostgreSQL enum labels used by SQLAlchemy member-name storage.

Revision ID: 0051
Revises: 0050
Create Date: 2026-08-11 22:00:00
"""
from __future__ import annotations

from alembic import op


revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the two member names absent from the historical baseline.

    SQLAlchemy's default Enum mapping persists and reads Python member names,
    so PostgreSQL needs these uppercase labels before any migrated lowercase
    row can be normalized by the following revision.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # PostgreSQL rejects any use of an enum label until the transaction that
    # added it commits.  ``0052`` runs immediately after this revision during
    # ``alembic upgrade head``, so force a bounded commit here before that
    # follow-up transaction normalizes existing rows.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE materialstatus ADD VALUE IF NOT EXISTS 'NEEDS_REVIEW'")
        op.execute("ALTER TYPE renderassettype ADD VALUE IF NOT EXISTS 'PPT_SLIDE_IMAGE'")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        raise RuntimeError(
            "0051 appends PostgreSQL enum values and cannot be safely downgraded; "
            "restore the prior database environment before resuming traffic instead"
        )
