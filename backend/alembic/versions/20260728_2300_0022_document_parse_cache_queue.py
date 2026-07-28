"""Add canonical parse cache identity and owner parser leases.

Revision ID: 0022
Revises: 0021
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("document_ir_versions", sa.Column("parser_profile", sa.String(40), nullable=False, server_default="standard"))
    op.add_column("document_ir_versions", sa.Column("cache_key", sa.String(128), nullable=False, server_default=""))
    op.create_index("ix_document_ir_versions_cache_key", "document_ir_versions", ["cache_key"])
    op.create_table(
        "document_parse_owner_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("task_id", sa.String(), nullable=False, server_default=""),
        sa.Column("lease_token", sa.String(), nullable=False, server_default=""),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_document_parse_owner_leases_task_id", "document_parse_owner_leases", ["task_id"])
    op.create_index("ix_document_parse_owner_leases_lease_token", "document_parse_owner_leases", ["lease_token"])
    op.create_index("ix_document_parse_owner_leases_lease_expires_at", "document_parse_owner_leases", ["lease_expires_at"])


def downgrade():
    op.drop_table("document_parse_owner_leases")
    op.drop_index("ix_document_ir_versions_cache_key", table_name="document_ir_versions")
    op.drop_column("document_ir_versions", "cache_key")
    op.drop_column("document_ir_versions", "parser_profile")
