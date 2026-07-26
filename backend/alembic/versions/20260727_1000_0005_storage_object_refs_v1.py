"""storage_object_refs_v1

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-27 10:00:00

G5 对象存储引用登记表：
- 创建 storage_object_refs 表，作为 GC / 回读校验 / 迁移对账的唯一账本
- 列：object_key 唯一索引、content_sha256 索引、soft_deleted_at 索引、
       last_verify_status 索引
- 幂等：表已存在时跳过 CREATE TABLE
- 双方言：SQLite 与 PostgreSQL 共用同一 DDL（仅用通用类型）
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "storage_object_refs"


def _table_exists(bind, table: str) -> bool:
    from sqlalchemy import inspect
    inspector = inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, TABLE_NAME):
        # 幂等：表已存在则只补索引
        return

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("object_key", sa.String, nullable=False),
        sa.Column("content_sha256", sa.String, nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mime_type", sa.String, nullable=False, server_default=""),
        sa.Column("source_backend", sa.String, nullable=False, server_default=""),
        sa.Column("referenced_by", sa.String, nullable=False, server_default=""),
        sa.Column("soft_deleted_at", sa.DateTime, nullable=True),
        sa.Column("soft_delete_reason", sa.String, nullable=False, server_default=""),
        sa.Column("last_verified_at", sa.DateTime, nullable=True),
        sa.Column(
            "last_verify_status",
            sa.String,
            nullable=False,
            server_default="not_verified",
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_index(
        f"ix_{TABLE_NAME}_object_key",
        TABLE_NAME,
        ["object_key"],
        unique=True,
    )
    op.create_index(
        f"ix_{TABLE_NAME}_content_sha256",
        TABLE_NAME,
        ["content_sha256"],
        unique=False,
    )
    op.create_index(
        f"ix_{TABLE_NAME}_soft_deleted_at",
        TABLE_NAME,
        ["soft_deleted_at"],
        unique=False,
    )
    op.create_index(
        f"ix_{TABLE_NAME}_last_verify_status",
        TABLE_NAME,
        ["last_verify_status"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        return
    for index_name in (
        f"ix_{TABLE_NAME}_last_verify_status",
        f"ix_{TABLE_NAME}_soft_deleted_at",
        f"ix_{TABLE_NAME}_content_sha256",
        f"ix_{TABLE_NAME}_object_key",
    ):
        try:
            op.drop_index(index_name, table_name=TABLE_NAME)
        except Exception:
            pass
    op.drop_table(TABLE_NAME)
