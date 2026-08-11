"""Add immutable Canonical DocumentIR versions and relational projections.

Revision ID: 0015
Revises: 0014
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _drop_block_foreign_key(table: sa.Table) -> None:
    """Prepare a batch copy that no longer requires globally unique block IDs."""
    for constraint in list(table.constraints):
        if isinstance(constraint, sa.ForeignKeyConstraint) and any(
            element.target_fullname.startswith("document_blocks.")
            for element in constraint.elements
        ):
            table.constraints.remove(constraint)


def _drop_postgresql_legacy_block_foreign_keys(bind) -> None:
    """Release the legacy parent unique index before it is replaced.

    PostgreSQL makes a foreign key depend on the unique index that proves its
    parent key.  SQLite permits the historical order, but PostgreSQL must drop
    the old ``evidence_spans.block_id`` foreign key before making ``block_id``
    non-unique.  The later batch rebuild installs the scoped composite key.
    """
    if bind.dialect.name != "postgresql" or "evidence_spans" not in sa.inspect(bind).get_table_names():
        return
    for foreign_key in sa.inspect(bind).get_foreign_keys("evidence_spans"):
        referred_table = foreign_key.get("referred_table")
        constrained_columns = set(foreign_key.get("constrained_columns") or ())
        if referred_table == "document_blocks" and "block_id" in constrained_columns:
            name = foreign_key.get("name")
            if name:
                op.drop_constraint(name, "evidence_spans", type_="foreignkey")


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "document_parse_runs")
    if "document_ir_version_id" not in existing:
        op.add_column("document_parse_runs", sa.Column("document_ir_version_id", sa.String(length=64), nullable=True))
        op.create_index("ix_document_parse_runs_document_ir_version_id", "document_parse_runs", ["document_ir_version_id"])
    if "reparse_applied" not in existing:
        op.add_column(
            "document_parse_runs",
            sa.Column("reparse_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index("ix_document_parse_runs_reparse_applied", "document_parse_runs", ["reparse_applied"])
    if "parse_profile" not in existing:
        op.add_column(
            "document_parse_runs",
            sa.Column("parse_profile", sa.String(length=40), nullable=False, server_default="standard"),
        )
        op.create_index("ix_document_parse_runs_parse_profile", "document_parse_runs", ["parse_profile"])
    if "reparse_scope" not in existing:
        op.add_column(
            "document_parse_runs",
            sa.Column("reparse_scope", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )

    existing = _columns(bind, "document_blocks")
    for name, column in (
        ("unit_id", sa.String(length=128)),
        ("document_ir_version_id", sa.String(length=64)),
    ):
        if name not in existing:
            op.add_column("document_blocks", sa.Column(name, column, nullable=True))
            op.create_index(f"ix_document_blocks_{name}", "document_blocks", [name])

    _drop_postgresql_legacy_block_foreign_keys(bind)

    # Canonical block IDs are source locators, not database row IDs.  Versions
    # retain the same locator across a reparse, so uniqueness must be scoped
    # by immutable IR version instead of the whole table.
    indexes = {item["name"]: item for item in sa.inspect(bind).get_indexes("document_blocks")}
    legacy_block_index = indexes.get("ix_document_blocks_block_id")
    if legacy_block_index and legacy_block_index.get("unique"):
        op.drop_index("ix_document_blocks_block_id", table_name="document_blocks")
        op.create_index("ix_document_blocks_block_id", "document_blocks", ["block_id"])
    unique_names = {item.get("name") for item in sa.inspect(bind).get_unique_constraints("document_blocks")}
    if "uq_document_blocks_ir_block" not in unique_names:
        with op.batch_alter_table("document_blocks") as batch:
            batch.create_unique_constraint(
                "uq_document_blocks_ir_block", ["document_ir_version_id", "block_id"],
            )

    tables = set(sa.inspect(bind).get_table_names())
    if "document_ir_versions" not in tables:
        op.create_table(
            "document_ir_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("ir_version_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("material_version_id", sa.String(length=64)),
            sa.Column("run_id", sa.String(length=64), sa.ForeignKey("document_parse_runs.run_id"), nullable=False, unique=True),
            sa.Column("document_id", sa.String(length=128), nullable=False),
            sa.Column("artifact_id", sa.String(length=128), nullable=False),
            sa.Column("source_sha256", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("schema_version", sa.String(length=32), nullable=False, server_default="document-ir/1.0"),
            sa.Column("object_key", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("content_hash", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("parser_versions", sa.JSON(), nullable=False),
            sa.Column("quality", sa.JSON(), nullable=False),
            sa.Column("quality_verdict", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("parse_outcome", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prev_ir_version_id", sa.String(length=64)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("ir_version_id", "course_id", "material_version_id", "run_id", "document_id", "artifact_id", "source_sha256", "content_hash", "quality_verdict", "parse_outcome", "needs_review", "prev_ir_version_id"):
            op.create_index(f"ix_document_ir_versions_{column}", "document_ir_versions", [column])

    # The historical schema used a single-column FK to document_blocks.block_id.
    # Rebuild it without that FK, then scope it to (IR version, canonical ID).
    # Existing rows remain readable with a null ir_version_id; new projections
    # always supply it and therefore receive referential validation.
    existing = _columns(bind, "evidence_spans")
    if "evidence_spans" in tables and "ir_version_id" not in existing:
        metadata = sa.MetaData()
        source = sa.Table("evidence_spans", metadata, autoload_with=bind)
        _drop_block_foreign_key(source)
        with op.batch_alter_table("evidence_spans", recreate="always", copy_from=source) as batch:
            batch.add_column(sa.Column("ir_version_id", sa.String(length=64), nullable=True))
            batch.create_index("ix_evidence_spans_ir_version_id", ["ir_version_id"])
            batch.create_foreign_key(
                "fk_evidence_spans_ir_block",
                "document_blocks",
                ["ir_version_id", "block_id"],
                ["document_ir_version_id", "block_id"],
            )
    if "evidence_anchors" not in tables:
        op.create_table(
            "evidence_anchors",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("anchor_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("ir_version_id", sa.String(length=64), sa.ForeignKey("document_ir_versions.ir_version_id"), nullable=False),
            sa.Column("run_id", sa.String(length=64), sa.ForeignKey("document_parse_runs.run_id"), nullable=False),
            sa.Column("document_id", sa.String(length=128), nullable=False),
            sa.Column("unit_id", sa.String(length=128)),
            sa.Column("block_id", sa.String(length=128), nullable=False),
            sa.Column("page_or_slide", sa.Integer()),
            sa.Column("char_start", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("char_end", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("text", sa.Text(), nullable=False, server_default=""),
            sa.Column("content_hash", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("bbox", sa.JSON()),
            sa.Column("provenance", sa.JSON()),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="candidate"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("ir_version_id", "block_id", "char_start", "char_end", name="uq_evidence_anchor_span"),
            sa.ForeignKeyConstraint(
                ["ir_version_id", "block_id"],
                ["document_blocks.document_ir_version_id", "document_blocks.block_id"],
                name="fk_evidence_anchors_ir_block",
            ),
        )
        for column in ("anchor_id", "course_id", "ir_version_id", "run_id", "document_id", "unit_id", "block_id", "page_or_slide", "content_hash", "status"):
            op.create_index(f"ix_evidence_anchors_{column}", "evidence_anchors", [column])
    if "retrieval_chunks" not in tables:
        op.create_table(
            "retrieval_chunks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("chunk_id", sa.String(length=128), nullable=False, unique=True),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("ir_version_id", sa.String(length=64), sa.ForeignKey("document_ir_versions.ir_version_id"), nullable=False),
            sa.Column("document_id", sa.String(length=128), nullable=False),
            sa.Column("unit_id", sa.String(length=128)),
            sa.Column("block_ids", sa.JSON(), nullable=False),
            sa.Column("anchor_ids", sa.JSON(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False, server_default=""),
            sa.Column("content_hash", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("chunk_id", "course_id", "ir_version_id", "document_id", "unit_id", "content_hash", "status"):
            op.create_index(f"ix_retrieval_chunks_{column}", "retrieval_chunks", [column])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    # Never delete canonical objects from object storage here.  A deployment
    # rollback only removes schema support after the application is rolled back.
    for table in ("retrieval_chunks", "evidence_anchors", "document_ir_versions"):
        if table in tables:
            op.drop_table(table)
    if "document_blocks" in tables:
        with op.batch_alter_table("document_blocks") as batch:
            for column in ("document_ir_version_id", "unit_id"):
                try:
                    batch.drop_column(column)
                except Exception:
                    pass
    if "document_parse_runs" in tables:
        with op.batch_alter_table("document_parse_runs") as batch:
            for column in ("reparse_scope", "parse_profile", "reparse_applied", "document_ir_version_id"):
                try:
                    batch.drop_column(column)
                except Exception:
                    pass
