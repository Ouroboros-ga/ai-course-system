"""Add stable course knowledge-node identities and candidate review bridge fields.

Revision ID: 0027
Revises: 0026
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "course_knowledge_nodes" not in tables:
        op.create_table(
            "course_knowledge_nodes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("course_id", sa.Integer(), nullable=False),
            sa.Column("node_key", sa.String(), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
            sa.Column("kind", sa.String(length=80), nullable=False, server_default="concept"),
            sa.Column("status", sa.String(), nullable=False, server_default="candidate"),
            sa.Column("source_candidate_id", sa.String(), nullable=True),
            sa.Column("canonical_node_id", sa.Integer(), nullable=True),
            sa.Column("source_batch_id", sa.String(), nullable=True),
            sa.Column("source_anchor_ids", sa.JSON(), nullable=True),
            sa.Column("extra_data", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
            sa.ForeignKeyConstraint(["canonical_node_id"], ["course_knowledge_nodes.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "course_id", "node_key", name="uq_course_knowledge_node_key"
            ),
            sa.UniqueConstraint(
                "course_id", "source_candidate_id",
                name="uq_course_knowledge_node_source_candidate",
            ),
        )
        op.create_index(
            "ix_course_knowledge_nodes_course_id", "course_knowledge_nodes", ["course_id"]
        )
        op.create_index(
            "ix_course_knowledge_nodes_node_key", "course_knowledge_nodes", ["node_key"]
        )
        op.create_index(
            "ix_course_knowledge_nodes_status", "course_knowledge_nodes", ["status"]
        )
        op.create_index(
            "ix_course_knowledge_nodes_source_candidate_id",
            "course_knowledge_nodes", ["source_candidate_id"],
        )
        op.create_index(
            "ix_course_knowledge_nodes_canonical_node_id",
            "course_knowledge_nodes", ["canonical_node_id"],
        )
        op.create_index(
            "ix_course_knowledge_nodes_source_batch_id",
            "course_knowledge_nodes", ["source_batch_id"],
        )

    review_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("graph_node_reviews")
    }
    with op.batch_alter_table("graph_node_reviews") as batch:
        if "candidate_batch_id" not in review_columns:
            batch.add_column(sa.Column("candidate_batch_id", sa.String(), nullable=True))
        if "candidate_id" not in review_columns:
            batch.add_column(sa.Column("candidate_id", sa.String(), nullable=True))
        if "source_candidate_id" not in review_columns:
            batch.add_column(sa.Column("source_candidate_id", sa.String(), nullable=True))
        if "target_candidate_id" not in review_columns:
            batch.add_column(sa.Column("target_candidate_id", sa.String(), nullable=True))
        if "identity_node_id" not in review_columns:
            batch.add_column(sa.Column("identity_node_id", sa.Integer(), nullable=True))
        if "target_content" not in review_columns:
            batch.add_column(sa.Column("target_content", sa.JSON(), nullable=True))
        if "candidate_batch_id" not in review_columns:
            batch.create_index("ix_graph_node_reviews_candidate_batch_id", ["candidate_batch_id"])
        if "candidate_id" not in review_columns:
            batch.create_index("ix_graph_node_reviews_candidate_id", ["candidate_id"])
        if "source_candidate_id" not in review_columns:
            batch.create_index("ix_graph_node_reviews_source_candidate_id", ["source_candidate_id"])
        if "target_candidate_id" not in review_columns:
            batch.create_index("ix_graph_node_reviews_target_candidate_id", ["target_candidate_id"])
        if "identity_node_id" not in review_columns:
            batch.create_index("ix_graph_node_reviews_identity_node_id", ["identity_node_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "graph_node_reviews" in sa.inspect(bind).get_table_names():
        with op.batch_alter_table("graph_node_reviews") as batch:
            for name in (
                "ix_graph_node_reviews_identity_node_id",
                "ix_graph_node_reviews_target_candidate_id",
                "ix_graph_node_reviews_source_candidate_id",
                "ix_graph_node_reviews_candidate_id",
                "ix_graph_node_reviews_candidate_batch_id",
            ):
                try:
                    batch.drop_index(name)
                except Exception:
                    pass
            for column in (
                "target_content", "identity_node_id", "target_candidate_id",
                "source_candidate_id", "candidate_id", "candidate_batch_id",
            ):
                batch.drop_column(column)
    if "course_knowledge_nodes" in sa.inspect(bind).get_table_names():
        op.drop_table("course_knowledge_nodes")
