"""Add safe, teacher-actionable initial-script coverage issues.

Revision ID: 0046
Revises: 0045

This stores only durable node identities and reason codes for scripts that
were omitted or rejected by evidence verification. Raw prompts, drafts, and
verifier findings intentionally remain outside this table.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


TABLE_NAME = "course_script_coverage_issues"


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE_NAME in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_id", sa.String(length=80), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("build_task_id", sa.String(length=120), nullable=True),
        sa.Column("script_version_id", sa.String(length=120), nullable=False),
        sa.Column("outline_node_id", sa.String(length=120), nullable=False),
        sa.Column("issue_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("issue_id", name="uq_course_script_coverage_issue_id"),
        sa.UniqueConstraint(
            "script_version_id", "outline_node_id",
            name="uq_script_coverage_issue_version_node",
        ),
    )
    op.create_index("ix_course_script_coverage_issues_issue_id", TABLE_NAME, ["issue_id"])
    op.create_index("ix_script_coverage_issue_course_status", TABLE_NAME, ["course_id", "status"])
    op.create_index("ix_script_coverage_issue_build_task", TABLE_NAME, ["build_task_id"])
    op.create_index("ix_course_script_coverage_issues_script_version_id", TABLE_NAME, ["script_version_id"])
    op.create_index("ix_course_script_coverage_issues_outline_node_id", TABLE_NAME, ["outline_node_id"])
    op.create_index("ix_course_script_coverage_issues_issue_code", TABLE_NAME, ["issue_code"])


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE_NAME in sa.inspect(bind).get_table_names():
        op.drop_table(TABLE_NAME)
