"""CR3 修复：discipline_corpus_vectors 增加 pgvector 列（SQL 侧 <=> 排序）。

Revision ID: dk20260909v5
Revises: dk20260909v4
Create Date: 2026-09-09
Batch: dk20260909v5

背景：检索向量通道原先把 release 内**全部**向量行拉到 Python 打分
（3899 块实测 2.0s/查询，占总耗时 90%）。新增 ``embedding_vec vector(512)``
后改为 ``ORDER BY embedding_vec <=> CAST(:q AS vector) LIMIT k``，数据库
只回传 top-k 行；同时为后续 HNSW 索引（扩量前置）铺好列。

- PG：``CREATE EXTENSION IF NOT EXISTS vector`` ＋ 加列 ＋ 从 JSON 列回填
  （仅 dimension=512 且非空的行，避免维度不符的行 cast 失败）；
- SQLite：batch 模式加 TEXT 列（本机测试路径，读取走 Python 兜底）；
- downgrade：删列（扩展与 JSON 列保留，不影响旧路径）。

回退说明：旧代码只读 ``embedding``（JSON）列，删掉 ``embedding_vec`` 即回到
原精确扫描路径；不删扩展（可能被其它域共享，见 research 工作区迁移）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "dk20260909v5"
down_revision = "dk20260909v4"
branch_labels = None
depends_on = None

BATCH_ID = "dk20260909v5"

VECTOR_DIMENSION = 512


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        op.execute(sa.text(
            "ALTER TABLE discipline_corpus_vectors "
            f"ADD COLUMN IF NOT EXISTS embedding_vec vector({VECTOR_DIMENSION})"))
        op.execute(sa.text(
            "UPDATE discipline_corpus_vectors SET embedding_vec = embedding::text::vector "
            "WHERE embedding_vec IS NULL AND dimension = :dim "
            "AND jsonb_typeof(embedding::jsonb) = 'array' "
            "AND jsonb_array_length(embedding::jsonb) = :dim"
        ).bindparams(dim=VECTOR_DIMENSION))
    else:
        with op.batch_alter_table("discipline_corpus_vectors") as batch_op:
            batch_op.add_column(sa.Column("embedding_vec", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(
            "ALTER TABLE discipline_corpus_vectors DROP COLUMN IF EXISTS embedding_vec"))
    else:
        with op.batch_alter_table("discipline_corpus_vectors") as batch_op:
            batch_op.drop_column("embedding_vec")
