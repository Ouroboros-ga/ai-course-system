"""Persist reviewable graph candidate payloads.

Revision ID: 0019
Revises: 0018
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "graph_candidate_batches" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("graph_candidate_batches")}
    with op.batch_alter_table("graph_candidate_batches") as batch:
        if "node_candidates" not in columns:
            batch.add_column(sa.Column("node_candidates", sa.JSON(), nullable=True))
        if "relation_candidates" not in columns:
            batch.add_column(sa.Column("relation_candidates", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "graph_candidate_batches" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("graph_candidate_batches")}
    with op.batch_alter_table("graph_candidate_batches") as batch:
        if "relation_candidates" in columns:
            batch.drop_column("relation_candidates")
        if "node_candidates" in columns:
            batch.drop_column("node_candidates")
