"""CR1 语料 RAG 存储改造：文档标题/元数据哈希、分块 token 实数与区段、
构建管线种类、工作项分片单元，以及向量缓存与版本成员新表。

Revision ID: dk20260909v1
Revises: dk20260908v2
Create Date: 2026-09-08
Batch: dk20260909v1

- 保留 dk20260908v1/v2 与闲置概念表；已部署库仅追加兼容列/新表。
- SQLite 降级走 batch 模式；embedding 存 JSON（PG 的 ANN 向量列由
  CR3 以方言感知迁移追加，本次不动旧 discipline_corpus_embedding）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "dk20260909v1"
down_revision = "dk20260908v2"
branch_labels = None
depends_on = None

BATCH_ID = "dk20260909v1"


def upgrade() -> None:
    op.add_column(
        "discipline_document_versions",
        sa.Column("title", sa.String(length=1024), nullable=False, server_default=""),
    )
    op.add_column(
        "discipline_document_versions",
        sa.Column("metadata_hash", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "discipline_chunks",
        sa.Column("token_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "discipline_chunks",
        sa.Column("section_path", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "discipline_builds",
        sa.Column("pipeline_kind", sa.String(length=64), nullable=False,
                  server_default="legacy_extraction"),
    )
    op.create_index("ix_discipline_builds_pipeline_kind", "discipline_builds",
                    ["pipeline_kind"])
    op.add_column(
        "discipline_work_items",
        sa.Column("unit_kind", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "discipline_work_items",
        sa.Column("unit_key", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "discipline_work_items",
        sa.Column("payload_ref", sa.String(length=512), nullable=False, server_default=""),
    )
    op.create_index("ix_discipline_work_items_unit_key", "discipline_work_items",
                    ["unit_key"])

    op.create_table(
        "discipline_corpus_vectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("embedding_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("model_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("model_fingerprint", "input_hash",
                            name="uq_corpus_vector_model_input"),
    )
    op.create_index("ix_discipline_corpus_vectors_model_fp",
                    "discipline_corpus_vectors", ["model_fingerprint"])
    op.create_index("ix_discipline_corpus_vectors_input_hash",
                    "discipline_corpus_vectors", ["input_hash"])

    op.create_table(
        "discipline_corpus_index_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("embedding_id", sa.String(length=64), nullable=True),
        sa.Column("display_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("release_id", "chunk_id",
                            name="uq_corpus_member_release_chunk"),
    )
    op.create_index("ix_discipline_corpus_index_members_release_id",
                    "discipline_corpus_index_members", ["release_id"])
    op.create_index("ix_discipline_corpus_index_members_chunk_id",
                    "discipline_corpus_index_members", ["chunk_id"])
    op.create_index("ix_corpus_member_chunk_release",
                    "discipline_corpus_index_members", ["chunk_id", "release_id"])
    op.create_index("ix_corpus_member_embedding_release",
                    "discipline_corpus_index_members", ["embedding_id", "release_id"])


def downgrade() -> None:
    op.drop_table("discipline_corpus_index_members")
    op.drop_table("discipline_corpus_vectors")
    # 先删引用被删列的索引，再进 batch 删列（否则 SQLite 重建索引报缺列）。
    op.drop_index("ix_discipline_work_items_unit_key",
                  table_name="discipline_work_items")
    with op.batch_alter_table("discipline_work_items") as batch:
        batch.drop_column("payload_ref")
        batch.drop_column("unit_key")
        batch.drop_column("unit_kind")
    op.drop_index("ix_discipline_builds_pipeline_kind", table_name="discipline_builds")
    with op.batch_alter_table("discipline_builds") as batch:
        batch.drop_column("pipeline_kind")
    with op.batch_alter_table("discipline_chunks") as batch:
        batch.drop_column("section_path")
        batch.drop_column("token_count")
    with op.batch_alter_table("discipline_document_versions") as batch:
        batch.drop_column("metadata_hash")
        batch.drop_column("title")
