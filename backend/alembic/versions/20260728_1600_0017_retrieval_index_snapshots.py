"""Add versioned formal retrieval index snapshots.

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "retrieval_index_snapshots" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "retrieval_index_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column(
            "ir_version_id", sa.String(length=64),
            sa.ForeignKey("document_ir_versions.ir_version_id"), nullable=False, unique=True,
        ),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="candidate"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("snapshot_id", "course_id", "ir_version_id", "document_id", "status", "content_hash"):
        op.create_index(
            f"ix_retrieval_index_snapshots_{column}",
            "retrieval_index_snapshots", [column],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "retrieval_index_snapshots" in sa.inspect(bind).get_table_names():
        op.drop_table("retrieval_index_snapshots")
