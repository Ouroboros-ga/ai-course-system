"""resource_lifecycle_visibility

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-27 21:40:00

统一课程建设九步实施计划 Step 1：给资源库模型增加草稿/发布生命周期与解析溯源。

``resource_items``：
- ``lifecycle_status``：draft|published|archived（草稿仅建设角色可读，发布版对有效课程成员开放）
- ``visibility``：teachers|course_members

``resource_versions``：
- ``material_version_id``：生成该版本的 SourceMaterialVersion.version_id
- ``parse_run_id``：生成该版本的 DocumentParseRun.run_id
- ``source_block_refs``：Markdown 段落对应的源块引用（JSON）

幂等：列已存在时跳过。见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §5。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ITEM_TABLE = "resource_items"
VERSION_TABLE = "resource_versions"

ITEM_NEW_COLUMNS = [
    # (name, type, server_default, indexed)
    ("lifecycle_status", sa.String(length=32), "draft", True),
    ("visibility", sa.String(length=32), "teachers", True),
]
VERSION_NEW_COLUMNS = [
    ("material_version_id", sa.String(length=64), None, True),
    ("parse_run_id", sa.String(length=64), None, True),
    ("source_block_refs", sa.JSON(), None, False),
]


def _column_exists(bind, table: str, column: str) -> bool:
    from sqlalchemy import inspect
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return False
    cols = {c["name"] for c in inspector.get_columns(table)}
    return column in cols


def _add_columns(table: str, columns: list, bind) -> None:
    for name, col_type, default, indexed in columns:
        if _column_exists(bind, table, name):
            continue
        op.add_column(
            table,
            sa.Column(name, col_type, nullable=True, server_default=default),
        )
        if indexed:
            op.create_index(op.f(f"ix_{table}_{name}"), table, [name])


def _drop_columns(table: str, columns: list, bind) -> None:
    for name, _col_type, _default, indexed in reversed(columns):
        if not _column_exists(bind, table, name):
            continue
        if indexed:
            try:
                op.drop_index(op.f(f"ix_{table}_{name}"), table_name=table)
            except Exception:
                pass
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column(name)


def upgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(bind)
    if ITEM_TABLE in inspector.get_table_names():
        _add_columns(ITEM_TABLE, ITEM_NEW_COLUMNS, bind)
    if VERSION_TABLE in inspector.get_table_names():
        _add_columns(VERSION_TABLE, VERSION_NEW_COLUMNS, bind)


def downgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(bind)
    if VERSION_TABLE in inspector.get_table_names():
        _drop_columns(VERSION_TABLE, VERSION_NEW_COLUMNS, bind)
    if ITEM_TABLE in inspector.get_table_names():
        _drop_columns(ITEM_TABLE, ITEM_NEW_COLUMNS, bind)
