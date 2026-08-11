"""Repair the course-build lease index for PostgreSQL.

Revision ID: 0047
Revises: 0046

Revision 0029 originally supplied only ``sqlite_where``.  Alembic therefore
created a full unique index on PostgreSQL, which incorrectly allowed only one
historical course-build task for a course.  The lease is intended to constrain
only queued/running tasks.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


TABLE_NAME = "course_draft_build_tasks"
INDEX_NAME = "uq_course_draft_build_active_course"
PREDICATE = sa.text("status IN ('queued', 'running')")


def _table_exists(bind) -> bool:
    return TABLE_NAME in sa.inspect(bind).get_table_names()


def _drop_index_if_present(bind) -> None:
    index_names = {item["name"] for item in sa.inspect(bind).get_indexes(TABLE_NAME)}
    if INDEX_NAME in index_names:
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind):
        return
    _drop_index_if_present(bind)
    op.create_index(
        INDEX_NAME,
        TABLE_NAME,
        ["course_id"],
        unique=True,
        sqlite_where=PREDICATE,
        postgresql_where=PREDICATE,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind):
        return
    _drop_index_if_present(bind)
    if bind.dialect.name == "postgresql":
        # This mirrors the pre-0047 PostgreSQL schema.  It may fail if a
        # database contains more than one historical task for a course; that
        # is intentional because such a downgrade would be lossy/invalid.
        op.create_index(INDEX_NAME, TABLE_NAME, ["course_id"], unique=True)
        return
    op.create_index(
        INDEX_NAME,
        TABLE_NAME,
        ["course_id"],
        unique=True,
        sqlite_where=PREDICATE,
    )
