"""course_ppt_mappings

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "course_ppt_mappings" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "course_ppt_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mapping_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("outline_node_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("material_version_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("page_refs", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_block_refs", sa.JSON(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("teacher_locked", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_course_ppt_mappings_mapping_id", "course_ppt_mappings", ["mapping_id"], unique=True)
    op.create_index("ix_course_ppt_mappings_course_id", "course_ppt_mappings", ["course_id"])
    op.create_index("ix_course_ppt_mappings_outline_node_id", "course_ppt_mappings", ["outline_node_id"])
    op.create_index("ix_course_ppt_mappings_material_version_id", "course_ppt_mappings", ["material_version_id"])
    op.create_index("ix_course_ppt_mappings_status", "course_ppt_mappings", ["status"])
    op.create_index("ix_course_ppt_mappings_teacher_locked", "course_ppt_mappings", ["teacher_locked"])


def downgrade() -> None:
    bind = op.get_bind()
    if "course_ppt_mappings" not in sa.inspect(bind).get_table_names():
        return
    for name in (
        "ix_course_ppt_mappings_teacher_locked",
        "ix_course_ppt_mappings_status",
        "ix_course_ppt_mappings_material_version_id",
        "ix_course_ppt_mappings_outline_node_id",
        "ix_course_ppt_mappings_course_id",
        "ix_course_ppt_mappings_mapping_id",
    ):
        op.drop_index(name, table_name="course_ppt_mappings")
    op.drop_table("course_ppt_mappings")
