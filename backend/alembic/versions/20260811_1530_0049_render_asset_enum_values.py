"""Retain legacy lowercased render-asset labels in PostgreSQL.

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-11 15:30:00
"""
from __future__ import annotations

from alembic import op


revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


LEGACY_RENDER_ASSET_VALUES = (
    "page_image",
    "ppt_slide_image",
    "region_image",
    "thumbnail",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # The original SQLite transfer incorrectly rewrote SQLAlchemy member names
    # to lowercase.  Keep those historical labels available so the following
    # 0051/0052 repair can normalize existing rows without data loss.
    for value in LEGACY_RENDER_ASSET_VALUES:
        op.execute(f"ALTER TYPE renderassettype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        raise RuntimeError(
            "0049 appends PostgreSQL enum values and cannot be safely downgraded; "
            "roll back by restoring the previous service/database environment before traffic resumes"
        )
