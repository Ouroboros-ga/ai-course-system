"""document block semantic hints for deterministic course structure generation."""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_blocks" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("document_blocks")}
    columns = (
        ("heading_level", sa.Integer()),
        ("semantic_role", sa.String(length=40)),
        ("style_hints", sa.JSON()),
        ("parent_block_id", sa.String(length=128)),
        ("reading_order", sa.Integer()),
        ("visual_description", sa.Text()),
    )
    for name, column_type in columns:
        if name not in existing:
            op.add_column("document_blocks", sa.Column(name, column_type, nullable=True if name != "reading_order" else False, server_default="0" if name == "reading_order" else None))
    for name in ("heading_level", "semantic_role", "parent_block_id"):
        index_name = f"ix_document_blocks_{name}"
        if name not in existing:
            op.create_index(index_name, "document_blocks", [name])


def downgrade() -> None:
    bind = op.get_bind()
    if "document_blocks" not in sa.inspect(bind).get_table_names():
        return
    for name in ("heading_level", "semantic_role", "style_hints", "parent_block_id", "reading_order", "visual_description"):
        with op.batch_alter_table("document_blocks") as batch:
            try:
                batch.drop_column(name)
            except Exception:
                pass
