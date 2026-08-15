"""Add admin-managed GraphRAG input token budget.

Revision ID: 0060
Revises: 0059

The budget is stored as platform runtime policy so platform admins can adjust
it without touching server env.  ``0`` keeps the env default
(``GRAPHRAG_MAX_INPUT_TOKENS``).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "platform_task_concurrency_configs", "graphrag_max_input_tokens"):
        return
    op.add_column(
        "platform_task_concurrency_configs",
        sa.Column(
            "graphrag_max_input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "platform_task_concurrency_configs", "graphrag_max_input_tokens"):
        op.drop_column("platform_task_concurrency_configs", "graphrag_max_input_tokens")
