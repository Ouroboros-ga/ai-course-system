"""Align recommendation lock columns with the current model.

Revision ID: 0031
Revises: 0030
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("recommendation_records")}
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("recommendation_records")}
    with op.batch_alter_table("recommendation_records") as batch:
        if "is_locked" not in columns:
            batch.add_column(sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "locked_by" not in columns:
            batch.add_column(sa.Column("locked_by", sa.Integer(), nullable=True))
        if "locked_at" not in columns:
            batch.add_column(sa.Column("locked_at", sa.DateTime(), nullable=True))
        if "ix_recommendation_records_is_locked" not in indexes:
            batch.create_index("ix_recommendation_records_is_locked", ["is_locked"])


def downgrade() -> None:
    with op.batch_alter_table("recommendation_records") as batch:
        try:
            batch.drop_index("ix_recommendation_records_is_locked")
        except Exception:
            pass
        for column in ("locked_at", "locked_by", "is_locked"):
            try:
                batch.drop_column(column)
            except Exception:
                pass
