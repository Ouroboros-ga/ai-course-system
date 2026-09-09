"""DK1 学科知识库持久化表（discipline_*，13 张）。

Revision ID: dk20260908v1
Revises: 0068
Create Date: 2026-09-08
Batch: dk20260908v1

学科知识库自动化构建 V1（docs/phase1/2026-09-08_学科知识库自动化构建
实施计划.md，DK1）：全局参考库的数据结构与稳定身份，不写课程
GraphSnapshot、LearningEvidence 与 nexus_checkpoints。

- 状态列使用普通 String（不引入 PG ENUM，避免 0068 注释所述的
  ALTER TYPE 同一事务约束）；取值见 knowledge_data/pipeline/ontology.json。
- downgrade 只删除本次新表；部署回滚优先关功能/回切版本保留数据。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "dk20260908v1"
down_revision = "0068"
branch_labels = None
depends_on = None

BATCH_ID = "dk20260908v1"


def upgrade() -> None:
    op.create_table(
        "discipline_document_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("source_family_id", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("language", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("domains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("license_code", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("raw_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("normalized_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("normalizer_version", sa.String(length=32), nullable=False, server_default="norm/1"),
        sa.Column("object_key", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_kind", "external_id", "raw_hash", "normalizer_version",
            name="uq_discipline_doc_version",
        ),
    )
    op.create_index("ix_discipline_document_versions_source_kind", "discipline_document_versions", ["source_kind"])
    op.create_index("ix_discipline_document_versions_external_id", "discipline_document_versions", ["external_id"])
    op.create_index("ix_discipline_document_versions_family", "discipline_document_versions", ["source_family_id"])
    op.create_index("ix_discipline_document_versions_status", "discipline_document_versions", ["status"])

    op.create_table(
        "discipline_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chunk_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("chunker_version", sa.String(length=32), nullable=False, server_default="chunk/1"),
        sa.Column("chunk_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locator", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("text_object_key", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("char_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "version_id", "chunker_version", "locator",
            name="uq_discipline_chunk_locator",
        ),
    )
    op.create_index("ix_discipline_chunks_version_id", "discipline_chunks", ["version_id"])

    op.create_table(
        "discipline_concepts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("concept_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("canonical_name", sa.String(length=512), nullable=False),
        sa.Column("domain", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("node_type", sa.String(length=64), nullable=False, server_default="concept"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="candidate"),
        sa.Column("legacy_id", sa.String(length=128), nullable=True, unique=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discipline_concepts_canonical_name", "discipline_concepts", ["canonical_name"])
    op.create_index("ix_discipline_concepts_domain", "discipline_concepts", ["domain"])
    op.create_index("ix_discipline_concepts_status", "discipline_concepts", ["status"])

    op.create_table(
        "discipline_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("concept_id", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("normalized_alias", sa.String(length=512), nullable=False),
        sa.Column("raw_alias", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("domain", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("basis", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "concept_id", "language", "normalized_alias",
            name="uq_discipline_alias",
        ),
    )
    op.create_index("ix_discipline_aliases_concept_id", "discipline_aliases", ["concept_id"])
    op.create_index("ix_discipline_aliases_normalized", "discipline_aliases", ["normalized_alias"])

    op.create_table(
        "discipline_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mention_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("surface_text", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("concept_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("decision", sa.String(length=32), nullable=False, server_default="undecided"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discipline_mentions_chunk_id", "discipline_mentions", ["chunk_id"])
    op.create_index("ix_discipline_mentions_run_id", "discipline_mentions", ["run_id"])

    op.create_table(
        "discipline_assertions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assertion_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("predicate", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=True),
        sa.Column("literal", sa.Text(), nullable=True),
        sa.Column("qualifiers", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="extracted"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "object_id IS NOT NULL OR literal IS NOT NULL",
            name="ck_discipline_assertion_endpoint",
        ),
    )
    op.create_index("ix_discipline_assertions_subject_id", "discipline_assertions", ["subject_id"])
    op.create_index("ix_discipline_assertions_predicate", "discipline_assertions", ["predicate"])
    op.create_index("ix_discipline_assertions_status", "discipline_assertions", ["status"])

    op.create_table(
        "discipline_supports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("support_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("assertion_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quote_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("stance", sa.String(length=32), nullable=False, server_default="supports"),
        sa.Column("validation_state", sa.String(length=32), nullable=False, server_default="unreviewed"),
        sa.Column("run_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discipline_supports_assertion_id", "discipline_supports", ["assertion_id"])
    op.create_index("ix_discipline_supports_chunk_id", "discipline_supports", ["chunk_id"])
    op.create_index("ix_discipline_supports_validation", "discipline_supports", ["validation_state"])

    op.create_table(
        "discipline_builds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("build_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("scope_manifest_key", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("extractor_version", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("model_version", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("prompt_version", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("schema_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("config_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("budget", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("counters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("error_code", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discipline_builds_config_hash", "discipline_builds", ["config_hash"])
    op.create_index("ix_discipline_builds_status", "discipline_builds", ["status"])

    op.create_table(
        "discipline_work_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_ref", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("error_code", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stage", "fingerprint", name="uq_discipline_work_stage_fp"),
    )
    op.create_index("ix_discipline_work_items_build_id", "discipline_work_items", ["build_id"])
    op.create_index("ix_discipline_work_items_status", "discipline_work_items", ["status"])

    op.create_table(
        "discipline_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("decision", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("reason_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("actor_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("actor_ref", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("before_ref", sa.JSON(), nullable=True),
        sa.Column("after_ref", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discipline_decisions_target", "discipline_decisions", ["target_type", "target_id"])

    op.create_table(
        "discipline_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="building"),
        sa.Column("parent_id", sa.String(length=64), nullable=True),
        sa.Column("manifest_key", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("source_policy_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("counts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discipline_releases_scope", "discipline_releases", ["scope"])
    op.create_index("ix_discipline_releases_status", "discipline_releases", ["status"])

    op.create_table(
        "discipline_release_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.String(length=64), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("stable_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "release_id", "item_type", "stable_id",
            name="uq_discipline_release_item",
        ),
    )
    op.create_index("ix_discipline_release_items_release_id", "discipline_release_items", ["release_id"])

    op.create_table(
        "discipline_heads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=128), nullable=False, unique=True),
        sa.Column("release_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    # 只删除本次新表；部署回滚优先关功能/回切版本保留数据。
    for table in (
        "discipline_heads",
        "discipline_release_items",
        "discipline_releases",
        "discipline_decisions",
        "discipline_work_items",
        "discipline_builds",
        "discipline_supports",
        "discipline_assertions",
        "discipline_mentions",
        "discipline_aliases",
        "discipline_concepts",
        "discipline_chunks",
        "discipline_document_versions",
    ):
        op.drop_table(table)
