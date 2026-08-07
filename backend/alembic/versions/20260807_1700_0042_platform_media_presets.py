"""Add versioned platform voice/avatar registries and release snapshots.

Revision ID: 0042
Revises: 0041
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def _columns(inspector, table_name: str) -> set[str]:
    return {row["name"] for row in inspector.get_columns(table_name)}


def _indexes(inspector, table_name: str) -> set[str]:
    return {row["name"] for row in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "platform_voice_presets" not in tables:
        op.create_table(
            "platform_voice_presets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("preset_id", sa.String(100), nullable=False),
            sa.Column("version", sa.String(40), nullable=False, server_default="1.0.0"),
            sa.Column("display_name", sa.String(160), nullable=False, server_default="平台讲解音色"),
            sa.Column("provider_key", sa.String(100), nullable=False, server_default=""),
            sa.Column("resource_ref_hash", sa.String(128), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("content_hash", sa.String(128), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("preset_id", "version", name="uq_platform_voice_preset_version"),
        )
        op.create_index("ix_platform_voice_presets_preset_id", "platform_voice_presets", ["preset_id"])
        op.create_index("ix_platform_voice_presets_provider_key", "platform_voice_presets", ["provider_key"])
        op.create_index("ix_platform_voice_presets_status", "platform_voice_presets", ["status"])
        op.create_index("ix_platform_voice_presets_content_hash", "platform_voice_presets", ["content_hash"])

    if "platform_avatar_presets" not in tables:
        op.create_table(
            "platform_avatar_presets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("preset_id", sa.String(100), nullable=False),
            sa.Column("version", sa.String(40), nullable=False, server_default="1.0.0"),
            sa.Column("display_name", sa.String(160), nullable=False, server_default="平台 2D 讲师"),
            sa.Column("provider_key", sa.String(100), nullable=False, server_default="platform_sprite2d"),
            sa.Column("manifest_object_key", sa.String(500), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("content_hash", sa.String(128), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("preset_id", "version", name="uq_platform_avatar_preset_version"),
        )
        op.create_index("ix_platform_avatar_presets_preset_id", "platform_avatar_presets", ["preset_id"])
        op.create_index("ix_platform_avatar_presets_provider_key", "platform_avatar_presets", ["provider_key"])
        op.create_index("ix_platform_avatar_presets_status", "platform_avatar_presets", ["status"])
        op.create_index("ix_platform_avatar_presets_content_hash", "platform_avatar_presets", ["content_hash"])

    inspector = sa.inspect(bind)
    if "media_releases" in set(inspector.get_table_names()):
        present = _columns(inspector, "media_releases")
        with op.batch_alter_table("media_releases") as batch:
            if "voice_preset_id" not in present:
                batch.add_column(sa.Column("voice_preset_id", sa.String(100), nullable=True))
            if "voice_preset_version" not in present:
                batch.add_column(sa.Column("voice_preset_version", sa.String(40), nullable=True))
            if "avatar_preset_version" not in present:
                batch.add_column(sa.Column("avatar_preset_version", sa.String(40), nullable=True))

    inspector = sa.inspect(bind)
    if "media_build_batches" in set(inspector.get_table_names()):
        present = _columns(inspector, "media_build_batches")
        with op.batch_alter_table("media_build_batches") as batch:
            if "voice_preset_id" not in present:
                batch.add_column(sa.Column("voice_preset_id", sa.String(100), nullable=True))
            if "voice_preset_version" not in present:
                batch.add_column(sa.Column("voice_preset_version", sa.String(40), nullable=True))
            if "avatar_preset_id" not in present:
                batch.add_column(sa.Column("avatar_preset_id", sa.String(100), nullable=True))
            if "avatar_preset_version" not in present:
                batch.add_column(sa.Column("avatar_preset_version", sa.String(40), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "media_build_batches" in set(inspector.get_table_names()):
        present = _columns(inspector, "media_build_batches")
        with op.batch_alter_table("media_build_batches") as batch:
            for name in ("avatar_preset_version", "avatar_preset_id", "voice_preset_version", "voice_preset_id"):
                if name in present:
                    batch.drop_column(name)

    inspector = sa.inspect(bind)
    if "media_releases" in set(inspector.get_table_names()):
        present = _columns(inspector, "media_releases")
        with op.batch_alter_table("media_releases") as batch:
            for name in ("avatar_preset_version", "voice_preset_version", "voice_preset_id"):
                if name in present:
                    batch.drop_column(name)

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "platform_avatar_presets" in tables:
        for name in _indexes(inspector, "platform_avatar_presets"):
            op.drop_index(name, table_name="platform_avatar_presets")
        op.drop_table("platform_avatar_presets")
    if "platform_voice_presets" in tables:
        for name in _indexes(inspector, "platform_voice_presets"):
            op.drop_index(name, table_name="platform_voice_presets")
        op.drop_table("platform_voice_presets")
