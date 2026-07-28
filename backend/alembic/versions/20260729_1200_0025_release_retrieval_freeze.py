"""Freeze learner retrieval selections inside course releases.

Revision ID: 0025
Revises: 0024
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("course_retrieval_snapshots") as batch:
        batch.add_column(sa.Column(
            "snapshot_kind", sa.String(), nullable=False, server_default="candidate",
        ))
        batch.add_column(sa.Column(
            "retrieval_chunk_ids", sa.JSON(), nullable=False, server_default="[]",
        ))
        batch.add_column(sa.Column(
            "evidence_anchor_ids", sa.JSON(), nullable=False, server_default="[]",
        ))
    op.create_index(
        "ix_course_retrieval_snapshots_snapshot_kind",
        "course_retrieval_snapshots", ["snapshot_kind"],
    )


def downgrade():
    op.drop_index(
        "ix_course_retrieval_snapshots_snapshot_kind",
        table_name="course_retrieval_snapshots",
    )
    with op.batch_alter_table("course_retrieval_snapshots") as batch:
        batch.drop_column("evidence_anchor_ids")
        batch.drop_column("retrieval_chunk_ids")
        batch.drop_column("snapshot_kind")
