"""学科知识库自动化构建 V1（DK1）持久化模型。

全局参考库：保存可审计的学科参考陈述（机器整理身份），不写课程
GraphSnapshot、LearningEvidence 与 nexus_checkpoints。所有表均带
``discipline_`` 前缀，由 Backend Alembic 显式迁移管理（SQLite 仅本地
Demo/测试）。

身份约定（实施计划 §3）：
- ``chunk_id = hash(version_id + chunker_version + locator + content_hash)``；
- ``concept_id`` 首次登记生成，legacy seed 旧 ID 存 ``legacy_id`` 保留映射；
- 支持关系绑定文档版本，不以 ``corpus_paragraph.rowid`` 作永久引用；
- ``start/end`` 恒指 ``normalized_text`` 的 Python code-point 半开区间。

状态字符串 intentionally 使用普通 ``String`` 列而非 PG ENUM：
新增状态不做 ``ALTER TYPE``（见 0068 迁移注释的同一事务约束），
取值由 ``knowledge_data/pipeline/ontology.json`` 与服务层校验。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


# ---------------------------------------------------------------------------
# 文档登记与分块
# ---------------------------------------------------------------------------


class DisciplineDocumentVersion(SQLModel, table=True):
    """已登记文档版本：来源元数据 + 哈希 + 对象存储指针。"""

    __tablename__ = "discipline_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "source_kind", "external_id", "raw_hash", "normalizer_version",
            name="uq_discipline_doc_version",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    version_id: str = Field(unique=True, index=True, max_length=64)
    source_kind: str = Field(index=True, max_length=32)
    external_id: str = Field(index=True, max_length=512)
    title: str = Field(default="", max_length=1024)
    source_url: str = Field(default="", max_length=2048)
    source_family_id: str = Field(default="", index=True, max_length=512)
    language: str = Field(default="", max_length=16)
    domains: list = Field(default_factory=list, sa_column=Column(JSON))
    license_code: str = Field(default="", max_length=64)
    raw_hash: str = Field(default="", index=True, max_length=64)
    normalized_hash: str = Field(default="", max_length=64)
    metadata_hash: str = Field(default="", max_length=64)
    normalizer_version: str = Field(default="norm/1", max_length=32)
    object_key: str = Field(default="", max_length=1024)
    status: str = Field(default="active", index=True, max_length=32)
    char_count: int = Field(default=0)
    token_estimate: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineChunk(SQLModel, table=True):
    """稳定片段：同一 (version_id, chunker_version, locator) 恒对同一 chunk_id。"""

    __tablename__ = "discipline_chunks"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "chunker_version", "locator",
            name="uq_discipline_chunk_locator",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    chunk_id: str = Field(unique=True, index=True, max_length=64)
    version_id: str = Field(index=True, max_length=64)
    chunker_version: str = Field(default="chunk/1", max_length=32)
    chunk_no: int = Field(default=0)
    locator: str = Field(default="", max_length=128)
    content_hash: str = Field(default="", max_length=64)
    text_object_key: str = Field(default="", max_length=1024)
    char_start: int = Field(default=0)
    char_end: int = Field(default=0)
    char_count: int = Field(default=0)
    token_estimate: int = Field(default=0)
    token_count: Optional[int] = Field(default=None)
    section_path: str = Field(default="", max_length=512)
    created_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 概念 / 别名 / 提及 / 陈述 / 支持
# ---------------------------------------------------------------------------


class DisciplineConcept(SQLModel, table=True):
    """规范概念：concept_id 不随改名/重新嵌入改变；合并不删除 mention。"""

    __tablename__ = "discipline_concepts"

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: str = Field(unique=True, index=True, max_length=64)
    canonical_name: str = Field(index=True, max_length=512)
    domain: str = Field(default="", index=True, max_length=128)
    node_type: str = Field(default="concept", index=True, max_length=64)
    status: str = Field(default="candidate", index=True, max_length=32)
    legacy_id: Optional[str] = Field(default=None, unique=True, index=True, max_length=128)
    revision: int = Field(default=1)
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineAlias(SQLModel, table=True):
    """别名：同字符串允许映射到不同消歧概念（行级唯一键含 concept_id）。"""

    __tablename__ = "discipline_aliases"
    __table_args__ = (
        UniqueConstraint(
            "concept_id", "language", "normalized_alias",
            name="uq_discipline_alias",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: str = Field(index=True, max_length=64)
    language: str = Field(default="", max_length=16)
    normalized_alias: str = Field(index=True, max_length=512)
    raw_alias: str = Field(default="", max_length=512)
    domain: str = Field(default="", max_length=128)
    basis: str = Field(default="", max_length=64)
    created_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineMention(SQLModel, table=True):
    """原始提及：合并不删除本行，只改 decision/concept_id。"""

    __tablename__ = "discipline_mentions"

    id: Optional[int] = Field(default=None, primary_key=True)
    mention_id: str = Field(unique=True, index=True, max_length=64)
    chunk_id: str = Field(index=True, max_length=64)
    char_start: int = Field(default=0)
    char_end: int = Field(default=0)
    surface_text: str = Field(default="", max_length=512)
    domain: str = Field(default="", max_length=128)
    node_type: str = Field(default="", max_length=64)
    context: str = Field(default="", max_length=2048)
    concept_id: Optional[str] = Field(default=None, index=True, max_length=64)
    run_id: str = Field(default="", index=True, max_length=64)
    decision: str = Field(default="undecided", max_length=32)
    created_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineAssertion(SQLModel, table=True):
    """可核验陈述：literal 与 object_id 至少一个有效（DDL 硬约束）。"""

    __tablename__ = "discipline_assertions"
    __table_args__ = (
        CheckConstraint(
            "object_id IS NOT NULL OR literal IS NOT NULL",
            name="ck_discipline_assertion_endpoint",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    assertion_id: str = Field(unique=True, index=True, max_length=64)
    subject_id: str = Field(index=True, max_length=64)
    predicate: str = Field(index=True, max_length=64)
    object_id: Optional[str] = Field(default=None, index=True, max_length=64)
    literal: Optional[str] = Field(default=None)
    qualifiers: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="extracted", index=True, max_length=32)
    revision: int = Field(default=1)
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineSupport(SQLModel, table=True):
    """原文证据：可支持/可反驳，同一陈述允许多份来源。"""

    __tablename__ = "discipline_supports"

    id: Optional[int] = Field(default=None, primary_key=True)
    support_id: str = Field(unique=True, index=True, max_length=64)
    assertion_id: str = Field(index=True, max_length=64)
    chunk_id: str = Field(index=True, max_length=64)
    char_start: int = Field(default=0)
    char_end: int = Field(default=0)
    quote_hash: str = Field(default="", max_length=64)
    stance: str = Field(default="supports", max_length=32)
    validation_state: str = Field(default="unreviewed", index=True, max_length=32)
    run_id: str = Field(default="", index=True, max_length=64)
    created_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 构建 / 工作项 / 决策审计
# ---------------------------------------------------------------------------


class DisciplineBuild(SQLModel, table=True):
    """一次有限范围构建：一个批次映射一条构建记录，细粒度状态放 work_items。"""

    __tablename__ = "discipline_builds"

    id: Optional[int] = Field(default=None, primary_key=True)
    build_id: str = Field(unique=True, index=True, max_length=64)
    task_id: Optional[str] = Field(default=None, index=True, max_length=64)
    pipeline_kind: str = Field(default="legacy_extraction", index=True, max_length=64)
    scope_manifest_key: str = Field(default="", max_length=1024)
    scope: dict = Field(default_factory=dict, sa_column=Column(JSON))
    stages: list = Field(default_factory=list, sa_column=Column(JSON))
    extractor_version: str = Field(default="", max_length=128)
    model_version: str = Field(default="", max_length=128)
    prompt_version: str = Field(default="", max_length=128)
    schema_version: str = Field(default="", max_length=64)
    config_hash: str = Field(default="", index=True, max_length=64)
    budget: dict = Field(default_factory=dict, sa_column=Column(JSON))
    counters: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="queued", index=True, max_length=32)
    error_code: str = Field(default="", max_length=80)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineWorkItem(SQLModel, table=True):
    """可续跑的工作项：同 build 内 (stage, fingerprint) 重跑复用结果。

    CR2 起幂等键为 build 级 ``(build_id, stage, fingerprint)``：每批次
    拥有自己的工作项；跨批次复用走向量缓存，不走工作项复用。
    """

    __tablename__ = "discipline_work_items"
    __table_args__ = (
        UniqueConstraint(
            "build_id", "stage", "fingerprint",
            name="uq_discipline_work_build_stage_fp",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: str = Field(unique=True, index=True, max_length=64)
    build_id: str = Field(index=True, max_length=64)
    chunk_id: str = Field(index=True, max_length=64)
    stage: str = Field(index=True, max_length=32)
    unit_kind: str = Field(default="", max_length=32)
    unit_key: str = Field(default="", index=True, max_length=128)
    payload_ref: str = Field(default="", max_length=512)
    fingerprint: str = Field(index=True, max_length=128)
    status: str = Field(default="pending", index=True, max_length=32)
    attempts: int = Field(default=0)
    lease_token: str = Field(default="", max_length=128)
    lease_until: Optional[datetime] = Field(default=None)
    result_ref: str = Field(default="", max_length=512)
    error_code: str = Field(default="", max_length=80)
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineDecision(SQLModel, table=True):
    """追加式决策审计：模型裁决、自动隔离、可选纠错与撤销均为事件。"""

    __tablename__ = "discipline_decisions"

    id: Optional[int] = Field(default=None, primary_key=True)
    decision_id: str = Field(unique=True, index=True, max_length=64)
    target_type: str = Field(index=True, max_length=32)
    target_id: str = Field(index=True, max_length=128)
    expected_revision: int = Field(default=0)
    decision: str = Field(default="", max_length=32)
    reason_codes: list = Field(default_factory=list, sa_column=Column(JSON))
    actor_type: str = Field(default="", max_length=32)
    actor_ref: str = Field(default="", max_length=256)
    before_ref: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    after_ref: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 发布版本与当前指针
# ---------------------------------------------------------------------------


class DisciplineRelease(SQLModel, table=True):
    """冻结发布版本：READY 后内容不可变（由 release_items 承载）。"""

    __tablename__ = "discipline_releases"

    id: Optional[int] = Field(default=None, primary_key=True)
    release_id: str = Field(unique=True, index=True, max_length=64)
    scope: str = Field(index=True, max_length=128)
    status: str = Field(default="building", index=True, max_length=32)
    parent_id: Optional[str] = Field(default=None, max_length=64)
    manifest_key: str = Field(default="", max_length=1024)
    source_policy_version: str = Field(default="", max_length=64)
    counts: dict = Field(default_factory=dict, sa_column=Column(JSON))
    published_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineReleaseItem(SQLModel, table=True):
    """版本内知识卡/关系的确定内容快照，不引用可变最新描述。"""

    __tablename__ = "discipline_release_items"
    __table_args__ = (
        UniqueConstraint(
            "release_id", "item_type", "stable_id",
            name="uq_discipline_release_item",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    release_id: str = Field(index=True, max_length=64)
    item_type: str = Field(default="", max_length=32)
    stable_id: str = Field(default="", max_length=128)
    content_hash: str = Field(default="", max_length=64)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow_aware)


class DisciplineHead(SQLModel, table=True):
    """当前发布指针：按 scope 比较并交换（CAS）更新。"""

    __tablename__ = "discipline_heads"

    id: Optional[int] = Field(default=None, primary_key=True)
    scope: str = Field(unique=True, index=True, max_length=128)
    release_id: str = Field(default="", max_length=64)
    revision: int = Field(default=1)
    updated_at: datetime = Field(default_factory=utcnow_aware)


__all__ = [
    "DisciplineAssertion",
    "DisciplineAlias",
    "DisciplineBuild",
    "DisciplineChunk",
    "DisciplineConcept",
    "DisciplineDecision",
    "DisciplineDocumentVersion",
    "DisciplineHead",
    "DisciplineMention",
    "DisciplineRelease",
    "DisciplineReleaseItem",
    "DisciplineSupport",
    "DisciplineWorkItem",
]
