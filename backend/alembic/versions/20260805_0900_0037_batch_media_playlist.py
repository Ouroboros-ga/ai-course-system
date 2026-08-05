"""Add batch media build records and course audio playlist items.

Revision ID: 0037
Revises: 0036
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def _has_column(inspector, table, column):
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "audio_playlist_object_key" not in {c["name"] for c in inspector.get_columns("media_releases")}:
        with op.batch_alter_table("media_releases") as batch:
            batch.add_column(sa.Column("audio_playlist_object_key", sa.String(), nullable=True))
            batch.add_column(sa.Column("audio_playlist_sha256", sa.String(), nullable=False, server_default=""))
            batch.add_column(sa.Column("avatar_preset_id", sa.String(length=100), nullable=True))
    tables = set(inspector.get_table_names())
    if "media_build_batches" not in tables:
        op.create_table(
            "media_build_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("batch_id", sa.String(128), nullable=False),
            sa.Column("course_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.String(128), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column("idempotency_key", sa.String(256), nullable=False, server_default=""),
            sa.Column("node_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("node_snapshot", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("estimate", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("voice_config", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_code", sa.String(128), nullable=False, server_default=""),
            sa.Column("error_message_safe", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.UniqueConstraint("batch_id", name="uq_media_build_batches_batch_id"),
            sa.UniqueConstraint("course_id", "idempotency_key", name="uq_media_batch_idempotency"),
        )
        op.create_index("ix_media_build_batches_course_id", "media_build_batches", ["course_id"])
        op.create_index("ix_media_build_batches_status", "media_build_batches", ["status"])
        op.create_index("ix_media_build_batches_release_id", "media_build_batches", ["release_id"])
    if "media_release_items" not in tables:
        op.create_table(
            "media_release_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("item_id", sa.String(128), nullable=False),
            sa.Column("release_id", sa.String(128), nullable=False),
            sa.Column("course_id", sa.Integer(), nullable=False),
            sa.Column("node_id", sa.Integer(), nullable=False),
            sa.Column("outline_node_id", sa.String(128), nullable=True),
            sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("script_hash", sa.String(128), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("audio_object_key", sa.String(), nullable=True),
            sa.Column("audio_sha256", sa.String(128), nullable=False, server_default=""),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("subtitle_manifest_object_key", sa.String(), nullable=True),
            sa.Column("avatar_cues_object_key", sa.String(), nullable=True),
            sa.Column("ppt_mapping_snapshot", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("tts_job_id", sa.String(128), nullable=True),
            sa.Column("error_code", sa.String(128), nullable=False, server_default=""),
            sa.Column("error_message_safe", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
            sa.ForeignKeyConstraint(["node_id"], ["script_nodes.id"]),
            sa.UniqueConstraint("item_id", name="uq_media_release_items_item_id"),
            sa.UniqueConstraint("release_id", "node_id", name="uq_media_release_item_node"),
        )
        op.create_index("ix_media_release_items_release_id", "media_release_items", ["release_id"])
        op.create_index("ix_media_release_items_course_id", "media_release_items", ["course_id"])
        op.create_index("ix_media_release_items_node_id", "media_release_items", ["node_id"])
        op.create_index("ix_media_release_items_status", "media_release_items", ["status"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "media_release_items" in set(inspector.get_table_names()):
        op.drop_table("media_release_items")
    if "media_build_batches" in set(inspector.get_table_names()):
        op.drop_table("media_build_batches")
    inspector = sa.inspect(op.get_bind())
    if "media_releases" in set(inspector.get_table_names()):
        with op.batch_alter_table("media_releases") as batch:
            if _has_column(inspector, "media_releases", "avatar_preset_id"):
                batch.drop_column("avatar_preset_id")
            if _has_column(inspector, "media_releases", "audio_playlist_sha256"):
                batch.drop_column("audio_playlist_sha256")
            if _has_column(inspector, "media_releases", "audio_playlist_object_key"):
                batch.drop_column("audio_playlist_object_key")
