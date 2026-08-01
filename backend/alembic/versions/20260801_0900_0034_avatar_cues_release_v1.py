"""Add release-scoped avatar-cues/v1 object reference.

The cue asset is immutable and tied to a concrete TTS audio SHA.  It is kept
separate from ``digital_human_manifest_object_key`` because avatar packages
are reusable while timing data belongs to exactly one media release.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "media_releases",
        sa.Column("avatar_cues_object_key", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("media_releases", "avatar_cues_object_key")
