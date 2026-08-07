"""Promote historical global teacher accounts to platform administrators.

Revision ID: 0043
Revises: 0042

This is a corrective, re-entrant migration for deployments that already ran
the earlier platform-admin migration before it handled uppercase legacy enum
labels.  It deliberately changes only ``users.role`` and explicit platform
permission assignments; course memberships retain their independent
``CourseRole.TEACHER``/``CourseRole.OWNER`` semantics.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

LEGACY_TEACHER_ADMIN_BATCH = "legacy-teacher-role-admin-v1"


def _table_exists(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _ensure_user_enum_supports_current_roles(bind) -> None:
    if bind.dialect.name != "postgresql":
        return
    # A native PostgreSQL ``userrole`` from the legacy schema only contained
    # TEACHER/STUDENT/ADMIN.  ``USER`` must exist before rows can be rewritten.
    with op.get_context().autocommit_block():
        bind.execute(sa.text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'USER'"))


def _grant_promoted_teacher_admins(bind) -> None:
    if not _table_exists(bind, "platform_permission_assignments"):
        return
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


def _normalize_platform_permissions(bind) -> None:
    """Repair lowercase prototype grants before ORM enum decoding."""
    if not _table_exists(bind, "platform_permission_assignments") or bind.dialect.name == "postgresql":
        return
    aliases = (
        ("platform.admin", "ADMIN"),
        ("platform.course.create", "COURSE_CREATE"),
        ("platform.course.audit", "COURSE_AUDIT"),
        ("platform.user.manage", "USER_MANAGE"),
        ("platform.safety.manage", "SAFETY_MANAGE"),
        ("platform.capability.manage", "CAPABILITY_MANAGE"),
    )
    for legacy, canonical in aliases:
        bind.execute(
            sa.text(
                """
                DELETE FROM platform_permission_assignments
                WHERE LOWER(CAST(permission AS TEXT)) = :legacy
                  AND EXISTS (
                      SELECT 1 FROM platform_permission_assignments canonical
                      WHERE canonical.user_id = platform_permission_assignments.user_id
                        AND canonical.permission = :canonical
                  )
                """
            ),
            {"legacy": legacy, "canonical": canonical},
        )
        bind.execute(
            sa.text(
                """
                UPDATE platform_permission_assignments
                SET permission = :canonical
                WHERE LOWER(CAST(permission AS TEXT)) = :legacy
                """
            ),
            {"legacy": legacy, "canonical": canonical},
        )


def _normalize_roles(bind) -> None:
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
    bind = op.get_bind()
    if not _table_exists(bind, "users"):
        return
    _ensure_user_enum_supports_current_roles(bind)
    _normalize_platform_permissions(bind)
    _grant_promoted_teacher_admins(bind)
    _normalize_roles(bind)


def downgrade() -> None:
    """Remove only grants recorded by this corrective migration.

    The former TEACHER/STUDENT distinction cannot be safely reconstructed from
    a normalized account row, so global roles remain canonical on downgrade.
    Course-level teaching roles are never altered by this migration.
    """
    bind = op.get_bind()
    if _table_exists(bind, "platform_permission_assignments"):
        bind.execute(
            sa.text(
                "DELETE FROM platform_permission_assignments WHERE migration_batch_id = :batch"
            ),
            {"batch": LEGACY_TEACHER_ADMIN_BATCH},
        )
