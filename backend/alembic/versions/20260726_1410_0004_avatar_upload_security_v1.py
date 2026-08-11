"""avatar_upload_security_v1

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-26 14:10:00

P0-3 教师数字人素材上传与预处理安全链路：
- 为 avatar_profiles 增加 teacher_authorization_confirmed_at / revoked_at 字段
- 为 avatar_source_media 增加服务端探测与扫描字段
- 将 upload_status 枚举从 pending/uploaded/validated/invalid/expired 迁移到
  pending_upload/uploaded/verified/invalid/quarantined/withdrawn/expired

幂等性：所有 ALTER TABLE ADD COLUMN 使用 IF NOT EXISTS 风格的检查；
      upload_status 字符串值迁移通过 UPDATE 完成，重复执行不会改变已迁移的值。

downgrade 不恢复原始 upload_status 字符串值（语义已变更）。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind, table: str, column: str) -> bool:
    """检查列是否已存在（幂等 ADD COLUMN 支持）。"""
    from sqlalchemy import inspect
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _add_column_if_missing(bind, table: str, column: str, ddl: str) -> None:
    if _column_exists(bind, table, column):
        return
    bind.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def _timestamp_type(bind) -> str:
    """Return a portable raw-SQL timestamp type for this legacy migration."""
    if bind.dialect.name == "postgresql":
        return "TIMESTAMP WITH TIME ZONE"
    return "DATETIME"


def upgrade() -> None:
    bind = op.get_bind()
    timestamp_type = _timestamp_type(bind)

    # 1. avatar_profiles: 增加授权确认与撤销时间戳
    _add_column_if_missing(
        bind, "avatar_profiles", "teacher_authorization_confirmed_at",
        f"teacher_authorization_confirmed_at {timestamp_type} NULL",
    )
    _add_column_if_missing(
        bind, "avatar_profiles", "revoked_at",
        f"revoked_at {timestamp_type} NULL",
    )

    # 2. avatar_source_media: 增加服务端探测与扫描字段
    _add_column_if_missing(
        bind, "avatar_source_media", "server_mime_type",
        "server_mime_type VARCHAR DEFAULT ''",
    )
    _add_column_if_missing(
        bind, "avatar_source_media", "server_duration_ms",
        "server_duration_ms INTEGER NULL",
    )
    _add_column_if_missing(
        bind, "avatar_source_media", "server_size_bytes",
        "server_size_bytes INTEGER DEFAULT 0",
    )
    _add_column_if_missing(
        bind, "avatar_source_media", "server_content_sha256",
        "server_content_sha256 VARCHAR DEFAULT ''",
    )
    _add_column_if_missing(
        bind, "avatar_source_media", "scan_status",
        "scan_status VARCHAR DEFAULT 'not_scanned'",
    )
    _add_column_if_missing(
        bind, "avatar_source_media", "verified_at",
        f"verified_at {timestamp_type} NULL",
    )

    # 3. upload_status 字符串值迁移：
    #    - "pending" -> "pending_upload"
    #    - "validated" -> "verified"
    #    - "uploaded"/"invalid"/"expired" 保持不变
    #    - 新值 "quarantined"/"withdrawn" 不需要在迁移中产生
    bind.execute(
        sa.text(
            "UPDATE avatar_source_media SET upload_status = 'pending_upload' "
            "WHERE upload_status = 'pending'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE avatar_source_media SET upload_status = 'verified' "
            "WHERE upload_status = 'validated'"
        )
    )

    # 4. 为新增的 server_content_sha256 创建索引（幂等）
    from sqlalchemy import inspect as _inspect
    inspector = _inspect(bind)
    existing_indexes = {
        (i["column_names"][0] if i["column_names"] else "")
        for i in inspector.get_indexes("avatar_source_media")
    }
    if "server_content_sha256" not in existing_indexes:
        try:
            op.create_index(
                "ix_avatar_source_media_server_content_sha256",
                "avatar_source_media",
                ["server_content_sha256"],
                unique=False,
            )
        except Exception:
            # SQLite 旧版本或已存在索引时忽略
            pass


def downgrade() -> None:
    """回滚 0004：仅删除新增列与索引，不恢复 upload_status 字符串值。

    警告：旧应用代码可能无法识别新的 upload_status 值（pending_upload/verified）。
    回滚前必须同时回滚应用代码到能理解旧值的版本。
    """
    bind = op.get_bind()

    # 删除索引（如存在）
    from sqlalchemy import inspect as _inspect
    inspector = _inspect(bind)
    existing_indexes = {
        (i["column_names"][0] if i["column_names"] else "")
        for i in inspector.get_indexes("avatar_source_media")
    }
    if "server_content_sha256" in existing_indexes:
        try:
            op.drop_index(
                "ix_avatar_source_media_server_content_sha256",
                table_name="avatar_source_media",
            )
        except Exception:
            pass

    # SQLite 不支持 DROP COLUMN，需要重建表；这里只在 PostgreSQL 下删除列
    if not bind.dialect.name.startswith("sqlite"):
        for table, column in (
            ("avatar_source_media", "verified_at"),
            ("avatar_source_media", "scan_status"),
            ("avatar_source_media", "server_content_sha256"),
            ("avatar_source_media", "server_size_bytes"),
            ("avatar_source_media", "server_duration_ms"),
            ("avatar_source_media", "server_mime_type"),
            ("avatar_profiles", "revoked_at"),
            ("avatar_profiles", "teacher_authorization_confirmed_at"),
        ):
            if _column_exists(bind, table, column):
                bind.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN {column}"))

    # 注意：不恢复 upload_status 字符串值（语义已变更）
