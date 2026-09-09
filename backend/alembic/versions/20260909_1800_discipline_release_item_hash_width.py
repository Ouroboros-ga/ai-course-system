"""CR3 修复：release_items.content_hash 列宽 64 → 80（值带 "sha256:" 前缀共 71 字符）。

Revision ID: dk20260909v4
Revises: dk20260909v3
Create Date: 2026-09-09
Batch: dk20260909v4

背景：``corpus_index.py`` 的 item 内容哈希写作 ``"sha256:" + hex``（71 字符），
而列宽为 ``varchar(64)``。SQLite 不校验长度，本地测试全绿；真实 PG 在
``build`` 组装 release items 时 ``StringDataRightTruncation``
（2026-09-09 cs-textbooks 首批 build 实测）。

方向说明：放宽列宽（upgrade 无数据风险；downgrade 收紧需先清理超长行）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "dk20260909v4"
down_revision = "dk20260909v3"
branch_labels = None
depends_on = None

BATCH_ID = "dk20260909v4"


def upgrade() -> None:
    with op.batch_alter_table("discipline_release_items") as batch_op:
        batch_op.alter_column(
            "content_hash",
            existing_type=sa.String(length=64),
            type_=sa.String(length=80),
            existing_nullable=False,
            existing_server_default="",
        )


def downgrade() -> None:
    with op.batch_alter_table("discipline_release_items") as batch_op:
        batch_op.alter_column(
            "content_hash",
            existing_type=sa.String(length=80),
            type_=sa.String(length=64),
            existing_nullable=False,
            existing_server_default="",
        )
