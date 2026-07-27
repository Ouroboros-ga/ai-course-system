"""make CodingDiagnosis timestamps timezone-aware

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists() -> bool:
    return "coding_diagnosis_records" in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Use TIMESTAMP WITH TIME ZONE on PostgreSQL and preserve data on SQLite."""
    if not _table_exists():
        return
    # batch_alter_table recreates the table on SQLite (which has no ALTER
    # COLUMN TYPE) and emits ALTER TYPE on PostgreSQL/MySQL-compatible engines.
    with op.batch_alter_table("coding_diagnosis_records", recreate="always") as batch:
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
        )
        batch.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
        )


def downgrade() -> None:
    if not _table_exists():
        return
    with op.batch_alter_table("coding_diagnosis_records", recreate="always") as batch:
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=False,
        )
        batch.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=False,
        )
