"""Add persisted developer-mode task concurrency settings."""
from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_task_concurrency_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_key", sa.String(length=32), nullable=False, server_default="default"),
        sa.Column("developer_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_total", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("document_parse", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("course_draft_build", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("graphrag", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("vector_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("config_key", name="uq_platform_task_concurrency_config_key"),
    )
    op.execute(sa.text(
        "INSERT INTO platform_task_concurrency_configs "
        "(config_key, developer_mode, max_total, document_parse, course_draft_build, graphrag, vector_index, updated_at, created_at) "
        "VALUES ('default', FALSE, 1, 1, 1, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    ))


def downgrade() -> None:
    op.drop_table("platform_task_concurrency_configs")
