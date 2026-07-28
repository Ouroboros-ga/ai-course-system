"""document_block_parse_provenance

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-27 21:30:00

统一课程建设九步实施计划 Step 1（配合 Step 3 组合式解析）：
给 ``document_blocks`` 增加 5 个解析溯源字段，使组合式解析（原生文本 + OCR
经 Reconciler 合并）能保留来源/坐标/置信度/Provider 版本/材料版本：

- ``material_version_id``：产出该块的 SourceMaterialVersion.version_id（解析溯源）
- ``page_or_slide``：通用页/幻灯片序号（PPTX=slide，PDF/image=page）
- ``source_kind``：native|ocr|reconciled，块文本来源
- ``confidence``：来源置信度 0..1（OCR 块）
- ``provider_version``：产出该块的 Provider 版本

SQLite 支持 ADD COLUMN；PostgreSQL 用标准 ALTER TABLE ADD COLUMN。
幂等：列已存在时跳过。见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §5。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "document_blocks"

# (column_name, column_obj) - 顺序与模型定义一致
NEW_COLUMNS = [
    ("material_version_id", sa.String(length=64)),
    ("page_or_slide", sa.Integer()),
    ("source_kind", sa.String(length=32)),
    ("confidence", sa.Float()),
    ("provider_version", sa.String(length=64)),
]
# 新增索引列
INDEXED_NEW_COLUMNS = {"material_version_id", "page_or_slide", "source_kind"}


def _column_exists(bind, table: str, column: str) -> bool:
    from sqlalchemy import inspect
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return False
    cols = {c["name"] for c in inspector.get_columns(table)}
    return column in cols


def upgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(bind)
    if TABLE_NAME not in inspector.get_table_names():
        # 表不存在：legacy_schema_baseline 应已建表；此处防御性跳过
        return

    for col_name, col_type in NEW_COLUMNS:
        if _column_exists(bind, TABLE_NAME, col_name):
            continue
        # 新列均可空（旧块无来源信息），避免 NOT NULL 破坏历史数据
        op.add_column(
            TABLE_NAME,
            sa.Column(col_name, col_type, nullable=True),
        )
        if col_name in INDEXED_NEW_COLUMNS:
            op.create_index(
                op.f(f"ix_{TABLE_NAME}_{col_name}"),
                TABLE_NAME,
                [col_name],
            )


def downgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(bind)
    if TABLE_NAME not in inspector.get_table_names():
        return

    for col_name, _ in reversed(NEW_COLUMNS):
        if not _column_exists(bind, TABLE_NAME, col_name):
            continue
        if col_name in INDEXED_NEW_COLUMNS:
            try:
                op.drop_index(op.f(f"ix_{TABLE_NAME}_{col_name}"), table_name=TABLE_NAME)
            except Exception:
                pass
        # SQLite 不支持 DROP COLUMN 原地操作；用 batch mode 重建表剔除该列。
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.drop_column(col_name)
