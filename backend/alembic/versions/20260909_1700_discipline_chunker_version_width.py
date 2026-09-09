"""CR2 修复：chunker_version 列宽 32 → 128（含分块参数后串长 45 字符）。

Revision ID: dk20260909v3
Revises: dk20260909v2
Create Date: 2026-09-09
Batch: dk20260909v3

背景：P2-13 修复后 ``chunker_version`` 形如
``corpus-chunk/1+char-fallback/1+t320+o32+m512``（45 字符），超过
``varchar(32)``。SQLite 不校验长度所以本地测试全绿；真实 PG 导入直接
``StringDataRightTruncation``（2026-09-09 cs-textbooks 首批导入实测）。

方向说明：放宽列宽（upgrade 无数据风险；downgrade 收紧需先清理超长行，
属预期失败）。用 batch_alter_table 兼容 SQLite 部署（重建表）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "dk20260909v3"
down_revision = "dk20260909v2"
branch_labels = None
depends_on = None

BATCH_ID = "dk20260909v3"


def upgrade() -> None:
    with op.batch_alter_table("discipline_chunks") as batch_op:
        batch_op.alter_column(
            "chunker_version",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=False,
            existing_server_default="chunk/1",
        )


def downgrade() -> None:
    with op.batch_alter_table("discipline_chunks") as batch_op:
        batch_op.alter_column(
            "chunker_version",
            existing_type=sa.String(length=128),
            type_=sa.String(length=32),
            existing_nullable=False,
            existing_server_default="chunk/1",
        )
