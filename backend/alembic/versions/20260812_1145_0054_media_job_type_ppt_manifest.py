"""Add PPT_MANIFEST to media_generation_jobs.job_type enum.

Revision ID: 0054
Revises: 0053
Create Date: 2026-08-12 11:45:00

The baseline (0001) created ``mediagenerationjobtype`` with
``TTS/SUBTITLE/AVATAR_PREPROCESS/DH_RENDER/VIDEO_PACKAGE/TIMELINE_PUBLISH``.
``MediaGenerationJobType.PPT_MANIFEST`` was added later in the PPT mapping
coverage work (d2f78b74) but never shipped a migration, so PostgreSQL rejected
the INSERT with ``invalid input value for enum mediagenerationjobtype:
"PPT_MANIFEST"`` and ``POST .../ppt-manifest`` returned 500.

Dialect handling:
- PostgreSQL: ``ALTER TYPE mediagenerationjobtype ADD VALUE IF NOT EXISTS 'PPT_MANIFEST'``
- SQLite: SQLModel/SQLAlchemy ``Enum`` columns are stored as VARCHAR with a
  CHECK constraint; application-level validation via the
  ``MediaGenerationJobType`` enum already allows the new value, so no DDL is
  required.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUM_NAME = "mediagenerationjobtype"
NEW_VALUE = "PPT_MANIFEST"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite stores Enum columns as VARCHAR; nothing to do.
        return
    # PostgreSQL disallows ALTER TYPE ... ADD VALUE inside a transaction in
    # some versions; run it as an autocommit-guarded raw statement. IF NOT
    # EXISTS keeps the migration re-entrant for already-patched databases.
    op.execute(
        f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS '{NEW_VALUE}'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # PostgreSQL enums cannot have values removed; leave the value in place.
    # No row data needs normalization because no production rows used the
    # missing value before this migration.
    return
