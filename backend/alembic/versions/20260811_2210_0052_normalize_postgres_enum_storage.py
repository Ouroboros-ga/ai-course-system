"""Normalize migrated PostgreSQL enum storage to SQLAlchemy member names.

Revision ID: 0052
Revises: 0051
Create Date: 2026-08-11 22:10:00
"""
from __future__ import annotations

from alembic import op


revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Repair lowercase values introduced by the first SQLite transfer."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        "UPDATE source_materials "
        "SET status = upper(status::text)::materialstatus "
        "WHERE status::text IN "
        "('uploaded', 'parsing', 'parsed', 'needs_review', 'failed', 'superseded')"
    )
    op.execute(
        "UPDATE source_material_versions "
        "SET parse_status = upper(parse_status::text)::materialstatus "
        "WHERE parse_status::text IN "
        "('uploaded', 'parsing', 'parsed', 'needs_review', 'failed', 'superseded')"
    )
    op.execute(
        "UPDATE evidence_render_assets "
        "SET asset_type = upper(asset_type::text)::renderassettype "
        "WHERE asset_type::text IN "
        "('page_image', 'ppt_slide_image', 'region_image', 'thumbnail')"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        raise RuntimeError(
            "0052 normalizes enum rows for the SQLAlchemy storage contract and "
            "cannot be safely downgraded; restore the prior database environment "
            "before resuming traffic instead"
        )
