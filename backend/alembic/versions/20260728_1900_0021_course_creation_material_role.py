"""Add course material role for the P0 multi-material creation flow.

Revision ID: 0021
Revises: 0020
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "source_materials" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("source_materials")}
    if "material_role" not in columns:
        op.add_column(
            "source_materials",
            sa.Column("material_role", sa.String(length=64), nullable=False, server_default="reference"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "source_materials" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("source_materials")}
    if "material_role" in columns:
        op.drop_column("source_materials", "material_role")
