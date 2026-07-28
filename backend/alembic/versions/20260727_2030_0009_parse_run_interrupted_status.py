"""parse_run_interrupted_status

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-27 20:30:00

统一课程建设九步实施计划 Step 0：给 DocumentParseRun.status (ParseRunStatus)
枚举新增 ``interrupted`` 值。

后端重启时，启动扫尾把遗留的 pending/running 解析运行标记为 interrupted，
使其从"处理中"视图中移除并允许"重新解析"，而不是永久停在 running。
interrupted 不是业务终态成功，与 TaskRecord.status 的 interrupted 一致。

Dialect handling（与 0006 mapping_status_pending_review 同模式）：
- PostgreSQL: ``ALTER TYPE parserunstatus ADD VALUE IF NOT EXISTS 'interrupted'``
- SQLite: SQLModel Enum 列存为带 CHECK 约束的 VARCHAR，CHECK 不能原地改，
  用 batch mode 重建为普通 VARCHAR；应用层 ``ParseRunStatus`` 枚举继续约束取值。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "document_parse_runs"
COLUMN_NAME = "status"
NEW_VALUE = "interrupted"

# 完整枚举值（含新增的 interrupted），用于 SQLite 重建与 downgrade 还原
ENUM_VALUES_WITH_NEW = (
    "pending", "running", "succeeded", "failed", "cancelled",
    "interrupted", "partial_success",
)
ENUM_VALUES_ORIGINAL = (
    "pending", "running", "succeeded", "failed", "cancelled", "partial_success",
)


def _dialect_name(bind) -> str:
    return bind.dialect.name


def _column_exists(bind, table: str, column: str) -> bool:
    from sqlalchemy import inspect
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return False
    cols = {c["name"] for c in inspector.get_columns(table)}
    return column in cols


def upgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, TABLE_NAME, COLUMN_NAME):
        return

    dialect = _dialect_name(bind)
    if dialect == "postgresql":
        op.execute(
            f"ALTER TYPE parserunstatus ADD VALUE IF NOT EXISTS '{NEW_VALUE}'"
        )
        return

    if dialect == "sqlite":
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.alter_column(
                COLUMN_NAME,
                existing_type=sa.Enum(*ENUM_VALUES_ORIGINAL, name="parserunstatus"),
                type_=sa.String(length=50),
                existing_nullable=False,
            )
        return

    op.alter_column(
        TABLE_NAME, COLUMN_NAME,
        existing_type=sa.Enum(*ENUM_VALUES_ORIGINAL, name="parserunstatus"),
        type_=sa.String(length=50),
        existing_nullable=False,
        existing_server_default=None,
        postgresql_using=f"{COLUMN_NAME}::text",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, TABLE_NAME, COLUMN_NAME):
        return

    # 把 interrupted 行回退为 failed（最接近的旧终态），避免违反旧 CHECK 约束
    op.execute(
        f"UPDATE {TABLE_NAME} SET {COLUMN_NAME} = 'failed' "
        f"WHERE {COLUMN_NAME} = '{NEW_VALUE}'"
    )

    dialect = _dialect_name(bind)
    if dialect == "postgresql":
        # PostgreSQL 枚举不能移除值，仅规范化数据。保留 interrupted 值无害。
        return

    if dialect == "sqlite":
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.alter_column(
                COLUMN_NAME,
                existing_type=sa.String(length=50),
                type_=sa.Enum(*ENUM_VALUES_ORIGINAL, name="parserunstatus"),
                existing_nullable=False,
            )
        return

    op.alter_column(
        TABLE_NAME, COLUMN_NAME,
        existing_type=sa.String(length=50),
        type_=sa.Enum(*ENUM_VALUES_ORIGINAL, name="parserunstatus"),
        existing_nullable=False,
        existing_server_default=None,
    )
