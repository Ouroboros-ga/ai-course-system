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

import json
import math
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, Index, JSON, UniqueConstraint
from sqlalchemy.types import UserDefinedType
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class CorpusVectorType(UserDefinedType):
    """pgvector 列（``vector(N)``）；SQLite 降级存 ``[x,y,...]`` 文本。

    与 ``research_workspace_model.PgVectorType`` 同构，但**带维度**——
    HNSW 索引要求固定维度。依赖由迁移显式 ``CREATE EXTENSION`` 安装。
    """

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = int(dimension)

    def get_col_spec(self, **kw: Any) -> str:
        return f"VECTOR({self.dimension})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, CorpusVectorType) \
            and other.dimension == self.dimension

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(("CorpusVectorType", self.dimension))

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            vector = [float(component) for component in value]
            if not vector or any(not math.isfinite(c) for c in vector):
                raise ValueError("corpus vector must be finite and non-empty")
            return json.dumps(vector, ensure_ascii=True, separators=(",", ":"))

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None or isinstance(value, list):
                return value
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return [float(component) for component in json.loads(str(value))]

        return process


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
    # pgvector 列（dk20260909v5）：SQL 侧 `<=>` 排序只取 top-k 行，
    # 替代"拉全量 JSON 向量到 Python"（实测 2.0s/查询）。SQLite 存文本。
    embedding_vec: Optional[list] = Field(
        default=None,
        sa_column=Column("embedding_vec", CorpusVectorType(512), nullable=True))
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
