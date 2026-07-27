"""coding diagnosis records

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "coding_diagnosis_records" in inspector.get_table_names():
        return
    op.create_table(
        "coding_diagnosis_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("diagnosis_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("outcome", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("error_class", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("column", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("debug_steps", sa.JSON(), nullable=False),
        sa.Column("hints", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(length=128), nullable=False),
        sa.Column("generated_by", sa.String(length=64), nullable=False, server_default="coding-rules"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.UniqueConstraint("diagnosis_id", name="uq_coding_diagnosis_records_diagnosis_id"),
        sa.UniqueConstraint("run_id", name="uq_coding_diagnosis_run_id"),
    )
    op.create_index("ix_coding_diagnosis_records_run_id", "coding_diagnosis_records", ["run_id"])
    op.create_index("ix_coding_diagnosis_records_course_id", "coding_diagnosis_records", ["course_id"])
    op.create_index("ix_coding_diagnosis_records_student_id", "coding_diagnosis_records", ["student_id"])
    op.create_index("ix_coding_diagnosis_records_outcome", "coding_diagnosis_records", ["outcome"])


def downgrade() -> None:
    bind = op.get_bind()
    if "coding_diagnosis_records" not in sa.inspect(bind).get_table_names():
        return
    op.drop_index("ix_coding_diagnosis_records_outcome", table_name="coding_diagnosis_records")
    op.drop_index("ix_coding_diagnosis_records_student_id", table_name="coding_diagnosis_records")
    op.drop_index("ix_coding_diagnosis_records_course_id", table_name="coding_diagnosis_records")
    op.drop_index("ix_coding_diagnosis_records_run_id", table_name="coding_diagnosis_records")
    op.drop_table("coding_diagnosis_records")
