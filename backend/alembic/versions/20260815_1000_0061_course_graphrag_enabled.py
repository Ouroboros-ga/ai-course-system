"""Add per-course GraphRAG enable flag.

Revision ID: 0061
Revises: 0060

Teachers can opt out of automatic knowledge-graph (GraphRAG) building per
course.  ``graphrag_enabled`` defaults to true so existing courses keep their
current behaviour.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "courses", "graphrag_enabled"):
        return
    op.add_column(
        "courses",
        sa.Column(
            "graphrag_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "courses", "graphrag_enabled"):
        op.drop_column("courses", "graphrag_enabled")
