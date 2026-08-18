"""Align media_release_cues.node_id FK with the teaching-script node system.

Revision ID: 0066
Revises: 0065
Create Date: 2026-08-18 12:00:00

媒体发布冻结 Cue 快照的 ``node_id`` 在模型中声明指向 ``teaching_script_nodes``
（P4 批量媒体建设体系），但数据库外键仍指向遗留的 ``script_nodes``
（旧 G8 course_scripts 体系）。0048 迁移只修正了 ``media_release_items``，
遗漏了 ``media_release_cues``，导致 P4 构建的课程（如课程5）无法写入
MediaReleaseCue 冻结快照，回顾跳转（learning adjustment）依赖的表恒为空。

本迁移把该外键对齐到模型声明（teaching_script_nodes），NOT VALID 保留
任何历史行（当前全库该表为空，无数据影响）。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def _cue_node_foreign_keys(bind) -> list[str]:
    inspector = sa.inspect(bind)
    if "media_release_cues" not in set(inspector.get_table_names()):
        return []
    return [
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys("media_release_cues")
        if foreign_key.get("name")
        and foreign_key.get("referred_table") == "script_nodes"
        and list(foreign_key.get("constrained_columns") or []) == ["node_id"]
    ]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for constraint_name in _cue_node_foreign_keys(bind):
        op.drop_constraint(constraint_name, "media_release_cues", type_="foreignkey")
    op.create_foreign_key(
        "fk_media_release_cues_node_id_teaching_script_nodes",
        "media_release_cues",
        "teaching_script_nodes",
        ["node_id"],
        ["id"],
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_constraint(
        "fk_media_release_cues_node_id_teaching_script_nodes",
        "media_release_cues",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "media_release_cues_node_id_fkey",
        "media_release_cues",
        "script_nodes",
        ["node_id"],
        ["id"],
    )
