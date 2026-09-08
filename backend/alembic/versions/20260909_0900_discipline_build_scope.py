"""DK4 构建作用域/阶段列与提及上下文列。

Revision ID: dk20260908v2
Revises: dk20260908v1
Create Date: 2026-09-08
Batch: dk20260908v2

- ``discipline_builds.scope / stages``（JSON）：DK4 worker 做增量规划与
  认领需要的构建范围与阶段清单；
- ``discipline_mentions.domain / node_type / context``：Resolver B 消歧
  需要的提及领域、类型与定义的语境（DK2 抽取时填写；缺失则判 ambiguous，
  不静默合并）。
前向兼容旧行（默认空）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "dk20260908v2"
down_revision = "dk20260908v1"
branch_labels = None
depends_on = None

BATCH_ID = "dk20260908v2"


def upgrade() -> None:
    op.add_column(
        "discipline_builds",
        sa.Column("scope", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "discipline_builds",
        sa.Column("stages", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "discipline_mentions",
        sa.Column("domain", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "discipline_mentions",
        sa.Column("node_type", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "discipline_mentions",
        sa.Column("context", sa.String(length=2048), nullable=False, server_default=""),
    )


def downgrade() -> None:
    # SQLite 不支持原生 DROP COLUMN，走 batch 模式；PG 同语法兼容。
    with op.batch_alter_table("discipline_builds") as batch:
        batch.drop_column("stages")
        batch.drop_column("scope")
    with op.batch_alter_table("discipline_mentions") as batch:
        batch.drop_column("context")
        batch.drop_column("node_type")
        batch.drop_column("domain")
