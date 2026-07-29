"""Persist formal Evidence/Citation provenance for the review-to-source chain.

Revision ID: 0028
Revises: 0027
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    evidence_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("course_evidence_records")
    }
    evidence_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("course_evidence_records")
    }
    with op.batch_alter_table("course_evidence_records") as batch:
        if "run_id" not in evidence_columns:
            batch.add_column(sa.Column("run_id", sa.String(), nullable=True))
        if "span_id" not in evidence_columns:
            batch.add_column(sa.Column("span_id", sa.String(), nullable=True))
        if "node_id" not in evidence_columns:
            batch.add_column(sa.Column("node_id", sa.Integer(), nullable=True))
        if "source_anchor_ids" not in evidence_columns:
            batch.add_column(sa.Column("source_anchor_ids", sa.JSON(), nullable=True))
        for name, column in (
            ("ix_course_evidence_records_run_id", "run_id"),
            ("ix_course_evidence_records_span_id", "span_id"),
            ("ix_course_evidence_records_node_id", "node_id"),
        ):
            if name not in evidence_indexes:
                batch.create_index(name, [column])

    citation_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("evidence_citations")
    }
    citation_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("evidence_citations")
    }
    with op.batch_alter_table("evidence_citations") as batch:
        if "run_id" not in citation_columns:
            batch.add_column(sa.Column("run_id", sa.String(), nullable=True))
        if "source_anchor_ids" not in citation_columns:
            batch.add_column(sa.Column("source_anchor_ids", sa.JSON(), nullable=True))
        if "ix_evidence_citations_run_id" not in citation_indexes:
            batch.create_index("ix_evidence_citations_run_id", ["run_id"])


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("evidence_citations") as batch:
        for name in ("ix_evidence_citations_run_id",):
            try:
                batch.drop_index(name)
            except Exception:
                pass
        for column in ("source_anchor_ids", "run_id"):
            try:
                batch.drop_column(column)
            except Exception:
                pass
    with op.batch_alter_table("course_evidence_records") as batch:
        for name in (
            "ix_course_evidence_records_node_id",
            "ix_course_evidence_records_span_id",
            "ix_course_evidence_records_run_id",
        ):
            try:
                batch.drop_index(name)
            except Exception:
                pass
        for column in ("source_anchor_ids", "node_id", "span_id", "run_id"):
            try:
                batch.drop_column(column)
            except Exception:
                pass
