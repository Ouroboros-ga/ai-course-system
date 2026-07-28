"""Add durable non-binary outcomes to existing Canonical IR versions.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_ir_versions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("document_ir_versions")}
    if "parse_outcome" not in columns:
        op.add_column(
            "document_ir_versions",
            sa.Column("parse_outcome", sa.String(length=64), nullable=False, server_default=""),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("document_ir_versions")}
    if "ix_document_ir_versions_parse_outcome" not in indexes:
        op.create_index(
            "ix_document_ir_versions_parse_outcome",
            "document_ir_versions",
            ["parse_outcome"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "document_ir_versions" not in sa.inspect(bind).get_table_names():
        return
    with op.batch_alter_table("document_ir_versions") as batch:
        try:
            batch.drop_index("ix_document_ir_versions_parse_outcome")
        except Exception:
            pass
        try:
            batch.drop_column("parse_outcome")
        except Exception:
            pass
