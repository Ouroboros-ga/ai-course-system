"""Repair Course Access enum values and make enrollments canonical.

Revision ID: 0032
Revises: 0031

The original access-control backfill wrote SQLAlchemy enum *values* (lowercase)
while the generated schema stores enum *names* (uppercase).  This left the
database unreadable through the ORM and also skipped platform grants because
the legacy user role comparison used lowercase values.

This migration normalizes existing rows, grants the explicit platform powers,
deduplicates legacy enrollment progress, and adds the missing learner/course
uniqueness constraint.  Data normalization is intentionally not reversed by
``downgrade``.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCH_ID = "course-access-data-repair-v1"
ENROLLMENT_UNIQUE_INDEX = "uq_student_enrollment_student_course"


def _table_exists(bind, name: str) -> bool:
    return name in sa.inspect(bind).get_table_names()


def _normalize_enum_columns(bind) -> None:
    # PostgreSQL columns are native ENUMs.  The broken lowercase migration
    # could not have committed invalid enum labels there, so normalization is
    # only required for SQLite/string-backed legacy databases.
    if bind.dialect.name == "postgresql":
        return
    # SQLite and PostgreSQL both support upper() for these VARCHAR/enum
    # representations.  Values are restricted to known application enums.
    for table, column in (
        ("users", "role"),
        ("course_memberships", "role"),
        ("course_memberships", "status"),
    ):
        if _table_exists(bind, table):
            bind.execute(sa.text(f"UPDATE {table} SET {column} = UPPER({column})"))
    if _table_exists(bind, "platform_permission_assignments"):
        # Remove legacy aliases only when the canonical permission already
        # exists for that user; this avoids a unique-key collision during
        # normalization while preserving one authoritative grant.
        for legacy, canonical in (
            ("platform.admin", "ADMIN"),
            ("platform.course.create", "COURSE_CREATE"),
            ("platform.course.audit", "COURSE_AUDIT"),
            ("platform.user.manage", "USER_MANAGE"),
            ("platform.safety.manage", "SAFETY_MANAGE"),
            ("platform.capability.manage", "CAPABILITY_MANAGE"),
        ):
            bind.execute(
                sa.text(
                    """
                    DELETE FROM platform_permission_assignments
                    WHERE permission = :legacy
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
                SET permission = CASE LOWER(permission)
                    WHEN 'platform.admin' THEN 'ADMIN'
                    WHEN 'platform.course.create' THEN 'COURSE_CREATE'
                    WHEN 'platform.course.audit' THEN 'COURSE_AUDIT'
                    WHEN 'platform.user.manage' THEN 'USER_MANAGE'
                    WHEN 'platform.safety.manage' THEN 'SAFETY_MANAGE'
                    WHEN 'platform.capability.manage' THEN 'CAPABILITY_MANAGE'
                    ELSE UPPER(permission)
                END
                """
            )
        )


def _repair_platform_assignments(bind) -> None:
    if not _table_exists(bind, "platform_permission_assignments"):
        return
    # Existing explicit grants are preserved.  The repair only fills the
    # grants implied by legacy global roles, using the same batch marker as
    # the migration ledger for auditability.
    bind.execute(
        sa.text(
            """
            INSERT INTO platform_permission_assignments
                (user_id, permission, granted_by_user_id, granted_at, migration_batch_id)
            SELECT u.id, :permission, u.id, CURRENT_TIMESTAMP, :batch
            FROM users u
            WHERE u.role = :role
              AND NOT EXISTS (
                  SELECT 1 FROM platform_permission_assignments p
                  WHERE p.user_id = u.id AND p.permission = :permission
              )
            """
        ),
        {"permission": "ADMIN", "role": "ADMIN", "batch": BATCH_ID},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO platform_permission_assignments
                (user_id, permission, granted_by_user_id, granted_at, migration_batch_id)
            SELECT u.id, :permission, u.id, CURRENT_TIMESTAMP, :batch
            FROM users u
            WHERE u.role = :role
              AND NOT EXISTS (
                  SELECT 1 FROM platform_permission_assignments p
                  WHERE p.user_id = u.id AND p.permission = :permission
              )
            """
        ),
        {"permission": "COURSE_CREATE", "role": "TEACHER", "batch": BATCH_ID},
    )


def _merge_enrollments(bind) -> None:
    if not _table_exists(bind, "student_enrollments"):
        return
    rows = bind.execute(
        sa.text(
            """
            SELECT id, student_id, course_id, enrolled_at,
                   total_nodes_completed, total_nodes_count,
                   overall_progress, avg_understanding_score,
                   avg_understanding_level, total_study_minutes,
                   last_study_time, is_active
            FROM student_enrollments
            ORDER BY student_id, course_id, id
            """
        )
    ).mappings().all()
    groups: dict[tuple[int, int], list[dict]] = {}
    for row in rows:
        groups.setdefault((int(row["student_id"]), int(row["course_id"])), []).append(dict(row))

    for (student_id, course_id), group in groups.items():
        if len(group) < 2:
            continue
        canonical = group[0]
        enrolled_at = min((r["enrolled_at"] for r in group if r["enrolled_at"] is not None), default=None)
        last_study = max((r["last_study_time"] for r in group if r["last_study_time"] is not None), default=None)
        best_level = max(group, key=lambda r: float(r["avg_understanding_score"] or 0))
        bind.execute(
            sa.text(
                """
                UPDATE student_enrollments
                SET enrolled_at = :enrolled_at,
                    total_nodes_completed = :completed,
                    total_nodes_count = :total,
                    overall_progress = :progress,
                    avg_understanding_score = :score,
                    avg_understanding_level = :level,
                    total_study_minutes = :minutes,
                    last_study_time = :last_study,
                    is_active = :active
                WHERE id = :id
                """
            ),
            {
                "id": canonical["id"],
                "enrolled_at": enrolled_at,
                "completed": max(int(r["total_nodes_completed"] or 0) for r in group),
                "total": max(int(r["total_nodes_count"] or 0) for r in group),
                "progress": max(float(r["overall_progress"] or 0) for r in group),
                "score": float(best_level["avg_understanding_score"] or 0),
                "level": best_level["avg_understanding_level"] or "unknown",
                "minutes": max(int(r["total_study_minutes"] or 0) for r in group),
                "last_study": last_study,
                "active": any(bool(r["is_active"]) for r in group),
            },
        )
        duplicate_ids = [r["id"] for r in group[1:]]
        bind.execute(
            sa.text("DELETE FROM student_enrollments WHERE id IN (%s)" % ",".join(str(int(i)) for i in duplicate_ids))
        )


def upgrade() -> None:
    bind = op.get_bind()
    _normalize_enum_columns(bind)
    _repair_platform_assignments(bind)
    _merge_enrollments(bind)

    if _table_exists(bind, "student_enrollments"):
        indexes = {item["name"] for item in sa.inspect(bind).get_indexes("student_enrollments")}
        constraints = {item["name"] for item in sa.inspect(bind).get_unique_constraints("student_enrollments")}
        if ENROLLMENT_UNIQUE_INDEX not in indexes and ENROLLMENT_UNIQUE_INDEX not in constraints:
            op.create_index(
                ENROLLMENT_UNIQUE_INDEX,
                "student_enrollments",
                ["student_id", "course_id"],
                unique=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "student_enrollments"):
        indexes = {item["name"] for item in sa.inspect(bind).get_indexes("student_enrollments")}
        if ENROLLMENT_UNIQUE_INDEX in indexes:
            op.drop_index(ENROLLMENT_UNIQUE_INDEX, table_name="student_enrollments")
