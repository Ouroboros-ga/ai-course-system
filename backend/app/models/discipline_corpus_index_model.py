"""CR1 语料向量缓存与版本成员模型（discipline_corpus_*）。

- ``discipline_corpus_vectors``：按 ``(model_fingerprint, input_hash)``
  唯一缓存向量；**模型与预处理均相同才能复用**（同维不同模型绝不混算）。
  ``embedding`` 存 JSON 浮点数组，保证 SQLite 单测可建表；PG 上的 ANN
  向量列/HNSW 由 CR3 以方言感知的追加迁移实现，本表不动。
- ``discipline_corpus_index_members``：版本冻结成员（release 内 chunk
  清单 + 展示元数据快照），构建中不被查询。
- 索引取舍（不重复建已被唯一索引覆盖的）：
  ``uq_corpus_member_release_chunk`` 已覆盖 release 前缀与
  (release, chunk) 查询；另建 ``(chunk_id, release_id)``（chunk 优先
  反查）与 ``(embedding_id, release_id)``（向量反向关联 + EXPLAIN 验证）；
  不假定外键自动建索引。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Index, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class DisciplineCorpusVector(SQLModel, table=True):
    """向量缓存行：一次计算，多构建复用；key 含完整模型处理指纹。"""

    __tablename__ = "discipline_corpus_vectors"
    __table_args__ = (
        UniqueConstraint(
            "model_fingerprint", "input_hash",
            name="uq_corpus_vector_model_input",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    embedding_id: str = Field(unique=True, index=True, max_length=64)
    model_fingerprint: str = Field(index=True, max_length=128)
    input_hash: str = Field(index=True, max_length=64)
    dimension: int = Field(default=0)
    embedding: list = Field(default_factory=list, sa_column=Column(JSON))
    token_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineCorpusIndexMember(SQLModel, table=True):
    """版本成员：某 release 包含的 chunk 及其冻结展示元数据。"""

    __tablename__ = "discipline_corpus_index_members"
    __table_args__ = (
        UniqueConstraint(
            "release_id", "chunk_id",
            name="uq_corpus_member_release_chunk",
        ),
        Index("ix_corpus_member_chunk_release", "chunk_id", "release_id"),
        Index("ix_corpus_member_embedding_release", "embedding_id", "release_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    release_id: str = Field(index=True, max_length=64)
    chunk_id: str = Field(index=True, max_length=64)
    embedding_id: Optional[str] = Field(default=None, max_length=64)
    display_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow_aware)


__all__ = [
    "DisciplineCorpusIndexMember",
    "DisciplineCorpusVector",
]
