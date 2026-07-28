"""Remove legacy page mappings created for non-slide source materials.

Revision ID: 0020
Revises: 0019
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SLIDE_MIME_TYPES = (
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not {"course_ppt_mappings", "source_material_versions"}.issubset(inspector.get_table_names()):
        return
    placeholders = ", ".join(f":mime_{index}" for index in range(len(_SLIDE_MIME_TYPES)))
    params = {f"mime_{index}": mime for index, mime in enumerate(_SLIDE_MIME_TYPES)}
    bind.execute(sa.text(f"""
        DELETE FROM course_ppt_mappings
        WHERE material_version_id IN (
            SELECT version_id FROM source_material_versions
            WHERE mime_type NOT IN ({placeholders})
        )
    """), params)


def downgrade() -> None:
    # Deleted draft mappings are projections and must be rebuilt from the
    # immutable parse output; recreating them here would reintroduce bad data.
    pass
