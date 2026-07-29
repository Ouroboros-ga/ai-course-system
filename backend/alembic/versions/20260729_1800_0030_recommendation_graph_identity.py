"""Persist graph snapshot and formal knowledge identity on recommendations.

Revision ID: 0030
Revises: 0029
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("recommendation_records")}
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("recommendation_records")}
    with op.batch_alter_table("recommendation_records") as batch:
        if "graph_snapshot_id" not in columns:
            batch.add_column(sa.Column("graph_snapshot_id", sa.String(), nullable=True))
        if "knowledge_node_id" not in columns:
            batch.add_column(sa.Column("knowledge_node_id", sa.Integer(), nullable=True))
        if "ix_recommendation_records_graph_snapshot_id" not in indexes:
            batch.create_index("ix_recommendation_records_graph_snapshot_id", ["graph_snapshot_id"])
        if "ix_recommendation_records_knowledge_node_id" not in indexes:
            batch.create_index("ix_recommendation_records_knowledge_node_id", ["knowledge_node_id"])


def downgrade() -> None:
    with op.batch_alter_table("recommendation_records") as batch:
        for name in (
            "ix_recommendation_records_graph_snapshot_id",
            "ix_recommendation_records_knowledge_node_id",
        ):
            try:
                batch.drop_index(name)
            except Exception:
                pass
        for column in ("graph_snapshot_id", "knowledge_node_id"):
            try:
                batch.drop_column(column)
            except Exception:
                pass
