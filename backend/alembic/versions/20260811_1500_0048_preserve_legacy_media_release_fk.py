"""Preserve stale historical media-release references during PostgreSQL transfer.

Revision ID: 0048
Revises: 0047
Create Date: 2026-08-11 15:00:00

媒体条目实际引用的脚本节点是 ``teaching_script_nodes``（新建设脚本体系），
不是遗留的 ``script_nodes``（旧 course_scripts 体系，迁移后为空表）。
历史 SQLite 数据中 media_release_items.node_id 即 teaching_script_nodes.id，
故 FK 目标表必须是 teaching_script_nodes；指向空表会在批量确认等新写入时
触发 FK violation（如 prep-agent / batch/confirm 500）。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def _media_release_node_foreign_keys(bind) -> list[str]:
    inspector = sa.inspect(bind)
    if "media_release_items" not in set(inspector.get_table_names()):
        return []
    return [
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys("media_release_items")
        if foreign_key.get("name")
        and foreign_key.get("referred_table") == "teaching_script_nodes"
        and list(foreign_key.get("constrained_columns") or []) == ["node_id"]
    ]


def _replace_media_release_node_constraint(*, not_valid: bool) -> None:
    bind = op.get_bind()
    for constraint_name in _media_release_node_foreign_keys(bind):
        op.drop_constraint(constraint_name, "media_release_items", type_="foreignkey")
    op.create_foreign_key(
        "fk_media_release_items_node_id_teaching_script_nodes",
        "media_release_items",
        "teaching_script_nodes",
        ["node_id"],
        ["id"],
        postgresql_not_valid=not_valid,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Existing SQLite data contains historical media release snapshots whose
    # original script-node rows were removed before FK enforcement existed.
    # NOT VALID retains those immutable records but still checks future writes.
    _replace_media_release_node_constraint(not_valid=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    _replace_media_release_node_constraint(not_valid=False)
