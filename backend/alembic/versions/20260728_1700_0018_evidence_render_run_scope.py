"""Scope evidence render assets to their canonical parse run.

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "evidence_render_assets" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("evidence_render_assets")}
    if "run_id" not in columns:
        # SQLite cannot add a foreign key with ALTER TABLE. Batch mode recreates
        # the table there while emitting normal ALTER statements on other engines.
        with op.batch_alter_table("evidence_render_assets", recreate="always") as batch:
            batch.add_column(sa.Column("run_id", sa.String(length=64), nullable=True))
            batch.create_foreign_key(
                "fk_evidence_render_assets_run_id",
                "document_parse_runs",
                ["run_id"],
                ["run_id"],
            )
            batch.create_index("ix_evidence_render_assets_run_id", ["run_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "evidence_render_assets" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("evidence_render_assets")}
    if "run_id" not in columns:
        return
    with op.batch_alter_table("evidence_render_assets", recreate="always") as batch:
        batch.drop_constraint("fk_evidence_render_assets_run_id", type_="foreignkey")
        batch.drop_index("ix_evidence_render_assets_run_id")
        batch.drop_column("run_id")
