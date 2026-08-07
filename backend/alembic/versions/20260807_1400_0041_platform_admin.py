"""Platform integration settings, admin audit, and role/auth compatibility."""
from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

LEGACY_TEACHER_ADMIN_BATCH = "legacy-teacher-role-admin-v1"


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _upgrade_legacy_global_roles(bind) -> None:
    """Map the historical global roles to the current enum labels.

    SQLAlchemy persists enum *names* for ``UserRole``.  Consequently the
    current two-role enum expects ``USER``/``ADMIN``, rather than the Python
    string values ``user``/``admin``.  Older installations still contain
    ``TEACHER`` and ``STUDENT``.  A legacy teacher becomes a platform
    administrator by product decision; course-scoped teacher memberships are
    intentionally untouched.
    """
    if not _table_exists(bind, "users"):
        return

    if bind.dialect.name == "postgresql":
        # ``USER`` was not part of the original native enum.  PostgreSQL only
        # permits a newly-added enum label to be used after the DDL transaction
        # commits, hence Alembic's autocommit block.
        with op.get_context().autocommit_block():
            bind.execute(sa.text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'USER'"))

    if _table_exists(bind, "platform_permission_assignments"):
        # Grant before overwriting TEACHER so this is both retry-safe and able
        # to identify the accounts that must be promoted.  The predicate also
        # tolerates a previous SQLite prototype row using the enum value.
        bind.execute(
            sa.text(
                """
                INSERT INTO platform_permission_assignments
                    (user_id, permission, granted_by_user_id, granted_at, migration_batch_id)
                SELECT u.id, 'ADMIN', u.id, CURRENT_TIMESTAMP, :batch
                FROM users u
                WHERE UPPER(CAST(u.role AS TEXT)) = 'TEACHER'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM platform_permission_assignments p
                      WHERE p.user_id = u.id
                        AND UPPER(CAST(p.permission AS TEXT)) IN ('ADMIN', 'PLATFORM.ADMIN')
                  )
                """
            ),
            {"batch": LEGACY_TEACHER_ADMIN_BATCH},
        )

    # Do not write lowercase values: native PostgreSQL enum columns and the
    # ORM both use the member names.  Keeping ``ADMIN`` canonical also repairs
    # early SQLite prototypes that persisted a lowercase role string.
    bind.execute(
        sa.text(
            """
            UPDATE users
            SET role = CASE UPPER(CAST(role AS TEXT))
                WHEN 'TEACHER' THEN 'ADMIN'
                WHEN 'STUDENT' THEN 'USER'
                WHEN 'USER' THEN 'USER'
                WHEN 'ADMIN' THEN 'ADMIN'
                ELSE role
            END
            WHERE UPPER(CAST(role AS TEXT)) IN ('TEACHER', 'STUDENT', 'USER', 'ADMIN')
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        "platform_integration_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("integration_key", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("model_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("api_key_last4", sa.String(4), nullable=False, server_default=""),
        sa.Column("extra_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("health_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("health_message", sa.String(500), nullable=False, server_default=""),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("integration_key", name="uq_platform_integration_key"),
    )
    op.create_index("ix_platform_integration_configs_integration_key", "platform_integration_configs", ["integration_key"])
    op.create_table(
        "platform_admin_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_platform_admin_audit_events_actor_user_id", "platform_admin_audit_events", ["actor_user_id"])
    op.create_index("ix_platform_admin_audit_events_action", "platform_admin_audit_events", ["action"])
    op.create_index("ix_platform_admin_audit_events_created_at", "platform_admin_audit_events", ["created_at"])
    # Existing deployments may already have this column from a prototype.
    bind = op.get_bind()
    cols = {row["name"] for row in sa.inspect(bind).get_columns("users")}
    if "auth_version" not in cols:
        op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"))
        op.create_index("ix_users_auth_version", "users", ["auth_version"])
    _upgrade_legacy_global_roles(bind)


def downgrade() -> None:
    op.drop_index("ix_platform_admin_audit_events_created_at", table_name="platform_admin_audit_events")
    op.drop_index("ix_platform_admin_audit_events_action", table_name="platform_admin_audit_events")
    op.drop_index("ix_platform_admin_audit_events_actor_user_id", table_name="platform_admin_audit_events")
    op.drop_table("platform_admin_audit_events")
    op.drop_index("ix_platform_integration_configs_integration_key", table_name="platform_integration_configs")
    op.drop_table("platform_integration_configs")
    bind = op.get_bind()
    cols = {row["name"] for row in sa.inspect(bind).get_columns("users")}
    if "auth_version" in cols:
        op.drop_index("ix_users_auth_version", table_name="users")
        op.drop_column("users", "auth_version")
    # Historical versions only understand student/teacher/admin. The old role
    # distinction cannot be reconstructed after normalization, so user rolls
    # back to the least-privileged historical value.
    op.execute("UPDATE users SET role='STUDENT' WHERE role='USER'")
