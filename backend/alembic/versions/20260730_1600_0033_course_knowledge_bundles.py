"""Add GraphRAG runs, immutable knowledge bundles and vector index records.

Revision ID: 0033
Revises: 0032
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_default(value: str) -> sa.TextClause:
    return sa.text(f"'{value}'")


def upgrade() -> None:
    op.create_table(
        "graph_rag_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("corpus_snapshot_id", sa.String(), nullable=True),
        sa.Column("parent_run_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("method", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("prompt_policy_version", sa.String(), nullable=False),
        sa.Column("completion_provider", sa.String(80), nullable=False, server_default=""),
        sa.Column("completion_model", sa.String(160), nullable=False, server_default=""),
        sa.Column("embedding_provider", sa.String(80), nullable=False, server_default=""),
        sa.Column("embedding_model", sa.String(160), nullable=False, server_default=""),
        sa.Column("effective_config_hash", sa.String(), nullable=False, server_default=""),
        sa.Column("input_content_hash", sa.String(), nullable=False, server_default=""),
        sa.Column("input_chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relationship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("typed_relationship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifact_root_uri", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_manifest_uri", sa.Text(), nullable=False, server_default=""),
        sa.Column("output_manifest_uri", sa.Text(), nullable=False, server_default=""),
        sa.Column("report_uri", sa.Text(), nullable=False, server_default=""),
        sa.Column("regeneration_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("regeneration_instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_scope", sa.JSON(), nullable=False, server_default=_json_default("{}")),
        sa.Column("relation_profile", sa.JSON(), nullable=False, server_default=_json_default("[]")),
        sa.Column("token_usage", sa.JSON(), nullable=False, server_default=_json_default("{}")),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("draft_nodes", sa.JSON(), nullable=False, server_default=_json_default("[]")),
        sa.Column("draft_relations", sa.JSON(), nullable=False, server_default=_json_default("[]")),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=_json_default("[]")),
        sa.Column("error_code", sa.String(80), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("run_id", name="uq_graph_rag_run_id"),
    )
    for column in (
        "run_id", "course_id", "corpus_snapshot_id", "parent_run_id", "task_id",
        "status", "prompt_policy_version", "effective_config_hash", "input_content_hash",
    ):
        op.create_index(f"ix_graph_rag_runs_{column}", "graph_rag_runs", [column])

    op.create_table(
        "graph_rag_entity_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("graphrag_run_id", sa.String(), nullable=False),
        sa.Column("graphrag_entity_id", sa.String(), nullable=False),
        sa.Column("entity_title", sa.String(500), nullable=False, server_default=""),
        sa.Column("entity_type", sa.String(80), nullable=False, server_default="concept"),
        sa.Column("entity_fingerprint", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "knowledge_node_id", sa.Integer(),
            sa.ForeignKey("course_knowledge_nodes.id"), nullable=False,
        ),
        sa.Column("node_key", sa.String(), nullable=False),
        sa.Column("mapping_method", sa.String(80), nullable=False, server_default="new_identity"),
        sa.Column("mapping_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_text_unit_ids", sa.JSON(), nullable=False, server_default=_json_default("[]")),
        sa.Column("source_anchor_ids", sa.JSON(), nullable=False, server_default=_json_default("[]")),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=_json_default("[]")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "graphrag_run_id", "graphrag_entity_id",
            name="uq_graphrag_run_entity",
        ),
    )
    for column in (
        "course_id", "graphrag_run_id", "graphrag_entity_id",
        "entity_fingerprint", "knowledge_node_id", "node_key",
    ):
        op.create_index(
            f"ix_graph_rag_entity_mappings_{column}",
            "graph_rag_entity_mappings", [column],
        )

    op.create_table(
        "course_vector_indexes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vector_index_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("bundle_id", sa.String(), nullable=True),
        sa.Column("graphrag_run_id", sa.String(), nullable=True),
        sa.Column("graph_snapshot_id", sa.String(), nullable=False),
        sa.Column("retrieval_snapshot_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False, server_default="lancedb"),
        sa.Column("storage_uri", sa.Text(), nullable=False, server_default=""),
        sa.Column("manifest_uri", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding_provider", sa.String(80), nullable=False, server_default=""),
        sa.Column("embedding_model", sa.String(160), nullable=False, server_default=""),
        sa.Column("embedding_revision", sa.String(160), nullable=False, server_default=""),
        sa.Column("vector_dimension", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text_unit_row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entity_row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("validated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("vector_index_id", name="uq_course_vector_index_id"),
    )
    for column in (
        "vector_index_id", "course_id", "bundle_id", "graphrag_run_id",
        "graph_snapshot_id", "retrieval_snapshot_id", "content_hash", "status", "task_id",
    ):
        op.create_index(
            f"ix_course_vector_indexes_{column}", "course_vector_indexes", [column],
        )

    op.create_table(
        "course_knowledge_bundles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bundle_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prev_bundle_id", sa.String(), nullable=True),
        sa.Column("graphrag_run_id", sa.String(), nullable=True),
        sa.Column("corpus_snapshot_id", sa.String(), nullable=True),
        sa.Column("graph_snapshot_id", sa.String(), nullable=False),
        sa.Column("retrieval_snapshot_id", sa.String(), nullable=False),
        sa.Column("vector_index_id", sa.String(), nullable=True),
        sa.Column("approval_manifest_hash", sa.String(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="DRAFT"),
        sa.Column("label", sa.String(240), nullable=False, server_default=""),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("bundle_id", name="uq_course_knowledge_bundle_id"),
        sa.UniqueConstraint(
            "course_id", "version", name="uq_knowledge_bundle_course_version",
        ),
    )
    for column in (
        "bundle_id", "course_id", "prev_bundle_id", "graphrag_run_id",
        "corpus_snapshot_id", "graph_snapshot_id", "retrieval_snapshot_id",
        "vector_index_id", "approval_manifest_hash", "content_hash", "status",
    ):
        op.create_index(
            f"ix_course_knowledge_bundles_{column}",
            "course_knowledge_bundles", [column],
        )

    op.create_table(
        "course_knowledge_heads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("active_bundle_id", sa.String(), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_id", name="uq_course_knowledge_head_course"),
    )
    op.create_index("ix_course_knowledge_heads_course_id", "course_knowledge_heads", ["course_id"])
    op.create_index(
        "ix_course_knowledge_heads_active_bundle_id",
        "course_knowledge_heads", ["active_bundle_id"],
    )

    op.create_table(
        "course_knowledge_activations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("activation_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("bundle_id", sa.String(), nullable=False),
        sa.Column("previous_bundle_id", sa.String(), nullable=True),
        sa.Column("action", sa.String(32), nullable=False, server_default="publish"),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("activation_id", name="uq_course_knowledge_activation_id"),
    )
    for column in ("activation_id", "course_id", "bundle_id", "previous_bundle_id"):
        op.create_index(
            f"ix_course_knowledge_activations_{column}",
            "course_knowledge_activations", [column],
        )

    op.create_table(
        "course_knowledge_build_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("lease_kind", sa.String(32), nullable=False, server_default="graphrag"),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("lease_token", sa.String(), nullable=False, server_default=""),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "course_id", "lease_kind", name="uq_course_knowledge_build_lease",
        ),
    )
    for column in ("course_id", "lease_kind", "task_id", "lease_token", "lease_expires_at"):
        op.create_index(
            f"ix_course_knowledge_build_leases_{column}",
            "course_knowledge_build_leases", [column],
        )

    op.create_table(
        "learning_projection_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("question_attempts.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("knowledge_node_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_learning_projection_event_id"),
        sa.UniqueConstraint(
            "attempt_id", "knowledge_node_id", name="uq_projection_attempt_node",
        ),
    )
    for column in (
        "event_id", "attempt_id", "student_id", "course_id",
        "knowledge_node_id", "status",
    ):
        op.create_index(
            f"ix_learning_projection_outbox_{column}",
            "learning_projection_outbox", [column],
        )

    op.add_column("recommendation_records", sa.Column("knowledge_bundle_id", sa.String(), nullable=True))
    op.add_column("recommendation_records", sa.Column("vector_index_id", sa.String(), nullable=True))
    op.add_column(
        "recommendation_records",
        sa.Column("retrieved_citation_ids", sa.JSON(), nullable=False, server_default=_json_default("[]")),
    )
    op.add_column(
        "recommendation_records",
        sa.Column("retrieval_trace", sa.JSON(), nullable=False, server_default=_json_default("{}")),
    )
    op.add_column(
        "recommendation_records",
        sa.Column("degraded_reason", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_recommendation_records_knowledge_bundle_id",
        "recommendation_records", ["knowledge_bundle_id"],
    )
    op.create_index(
        "ix_recommendation_records_vector_index_id",
        "recommendation_records", ["vector_index_id"],
    )

    op.add_column("course_releases", sa.Column("knowledge_bundle_id", sa.String(), nullable=True))
    op.create_index(
        "ix_course_releases_knowledge_bundle_id",
        "course_releases", ["knowledge_bundle_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_course_releases_knowledge_bundle_id", table_name="course_releases")
    op.drop_column("course_releases", "knowledge_bundle_id")

    op.drop_index("ix_recommendation_records_vector_index_id", table_name="recommendation_records")
    op.drop_index("ix_recommendation_records_knowledge_bundle_id", table_name="recommendation_records")
    for column in (
        "degraded_reason", "retrieval_trace", "retrieved_citation_ids",
        "vector_index_id", "knowledge_bundle_id",
    ):
        op.drop_column("recommendation_records", column)

    for table in (
        "learning_projection_outbox",
        "course_knowledge_build_leases",
        "course_knowledge_activations",
        "course_knowledge_heads",
        "course_knowledge_bundles",
        "course_vector_indexes",
        "graph_rag_entity_mappings",
        "graph_rag_runs",
    ):
        op.drop_table(table)
