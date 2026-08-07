"""Backfill ``platform.admin`` assignments for global admin accounts.

Revision ID: 0044
Revises: 0043

Platform enforcement reads ``platform_permission_assignments`` (see
``course_access_service.require_platform_permission``) while the admin panel
and ``init_users`` only guarantee ``users.role``.  This corrective, re-entrant
migration makes the two sources consistent:

- grant ``ADMIN`` to every active ``ADMIN`` account missing it;
- revoke stale ``ADMIN`` grants on accounts that are no longer ``ADMIN``
  (previously demoted through the admin panel without revoking the grant).

Course memberships and their ``CourseRole.TEACHER`` semantics are untouched.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

BACKFILL_BATCH = "backfill-admin-role-v1"


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _normalize_admin_grants(bind) -> None:
    if not _table_exists(bind, "platform_permission_assignments"):
        return
    # Grant ADMIN to global admin accounts that lack an active grant.
    bind.execute(
        sa.text(
            """
            INSERT INTO platform_permission_assignments
                (user_id, permission, granted_by_user_id, granted_at, migration_batch_id)
            SELECT u.id, 'ADMIN', u.id, CURRENT_TIMESTAMP, :batch
            FROM users u
            WHERE UPPER(CAST(u.role AS TEXT)) = 'ADMIN'
              AND NOT EXISTS (
                  SELECT 1 FROM platform_permission_assignments p
                  WHERE p.user_id = u.id
                    AND UPPER(CAST(p.permission AS TEXT)) IN ('ADMIN', 'PLATFORM.ADMIN')
                    AND p.revoked_at IS NULL
              )
            """
        ),
        {"batch": BACKFILL_BATCH},
    )
    # Revoke stale ADMIN grants left by the previous admin-panel behaviour that
    # only toggled users.role.  Explicit non-admin grants are not invented here.
    bind.execute(
        sa.text(
            """
            UPDATE platform_permission_assignments
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE UPPER(CAST(permission AS TEXT)) IN ('ADMIN', 'PLATFORM.ADMIN')
              AND revoked_at IS NULL
              AND user_id NOT IN (
                  SELECT u.id FROM users u
                  WHERE UPPER(CAST(u.role AS TEXT)) = 'ADMIN'
              )
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "users"):
        return
    _normalize_admin_grants(bind)


def downgrade() -> None:
    """Remove only grants recorded by this corrective migration.

    Revocations and previously-existing grants are intentionally not reversed;
    restoring them would recreate the inconsistent double source of truth.
    """
    bind = op.get_bind()
    if _table_exists(bind, "platform_permission_assignments"):
        bind.execute(
            sa.text(
                "DELETE FROM platform_permission_assignments WHERE migration_batch_id = :batch"
            ),
            {"batch": BACKFILL_BATCH},
        )
