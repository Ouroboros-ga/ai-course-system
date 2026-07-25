"""Tests for the access-control operations CLI (preflight/backup/restore/rollback/drill).

批次0要求：跑 access_control_preflight，补齐迁移、回滚、备份恢复演练。
"""
import sqlite3

from app.common.db_migrator import (
    ACCESS_CONTROL_MIGRATION_BATCH,
    _backfill_access_control,
    access_control_preflight,
)
from app.scripts.access_control_ops import (
    cmd_backup,
    cmd_drill,
    cmd_preflight,
    cmd_restore,
    cmd_rollback_backfill,
)


def _legacy_access_db(path):
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, is_active INTEGER NOT NULL, role VARCHAR NOT NULL);
        CREATE TABLE courses (id INTEGER PRIMARY KEY, teacher_id INTEGER, created_at TIMESTAMP);
        CREATE TABLE student_enrollments (course_id INTEGER, student_id INTEGER, is_active INTEGER, enrolled_at TIMESTAMP);
        CREATE TABLE course_capabilities (
          course_id INTEGER UNIQUE, learning INTEGER, course_building INTEGER, knowledge_graph INTEGER,
          evidence INTEGER, experiment INTEGER, coding_sandbox INTEGER, cognitive_analysis INTEGER,
          safety_policy INTEGER, updated_at TIMESTAMP, migration_batch_id VARCHAR
        );
        CREATE TABLE course_memberships (
          user_id INTEGER, course_id INTEGER, role VARCHAR, status VARCHAR, permission_overrides VARCHAR,
          analytics_excluded INTEGER, joined_at TIMESTAMP, updated_at TIMESTAMP, migration_batch_id VARCHAR,
          UNIQUE(user_id, course_id)
        );
        CREATE TABLE platform_permission_assignments (
          user_id INTEGER, permission VARCHAR, granted_by_user_id INTEGER, granted_at TIMESTAMP,
          migration_batch_id VARCHAR, UNIQUE(user_id, permission)
        );
    """)
    cursor.execute("INSERT INTO users VALUES (1, 1, 'teacher')")
    cursor.execute("INSERT INTO users VALUES (2, 1, 'student')")
    cursor.execute("INSERT INTO courses VALUES (10, 1, CURRENT_TIMESTAMP)")
    cursor.execute("INSERT INTO student_enrollments VALUES (10, 2, 1, CURRENT_TIMESTAMP)")
    # backfill so rollback has rows to remove
    _backfill_access_control(cursor)
    conn.commit()
    return conn


def test_preflight_cli_reports_ok(tmp_path):
    path = tmp_path / "legacy.sqlite"
    conn = _legacy_access_db(path)
    conn.close()

    import argparse
    rc = cmd_preflight(argparse.Namespace(database=str(path)))
    assert rc == 0


def test_preflight_cli_reports_failure_for_orphan(tmp_path):
    path = tmp_path / "orphan.sqlite"
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, is_active INTEGER NOT NULL, role VARCHAR NOT NULL);
        CREATE TABLE courses (id INTEGER PRIMARY KEY, teacher_id INTEGER, created_at TIMESTAMP);
        CREATE TABLE student_enrollments (course_id INTEGER, student_id INTEGER, is_active INTEGER, enrolled_at TIMESTAMP);
    """)
    cursor.execute("INSERT INTO users VALUES (1, 1, 'teacher')")
    cursor.execute("INSERT INTO courses VALUES (10, 999, CURRENT_TIMESTAMP)")
    conn.commit()
    conn.close()

    import argparse
    rc = cmd_preflight(argparse.Namespace(database=str(path)))
    assert rc == 1


def test_backup_and_restore_roundtrip(tmp_path):
    path = tmp_path / "legacy.sqlite"
    conn = _legacy_access_db(path)
    conn.close()

    import argparse
    dest_dir = str(tmp_path / "backups")
    rc = cmd_backup(argparse.Namespace(database=str(path), dest_dir=dest_dir))
    assert rc == 0

    backups = list((tmp_path / "backups").glob("*.db"))
    assert len(backups) == 1
    backup_file = str(backups[0])

    # corrupt the original then restore
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM course_memberships")
    conn.commit()
    conn.close()
    assert access_control_preflight(str(path))["ok"] is True  # still ok, just empty

    rc = cmd_restore(argparse.Namespace(backup_file=backup_file, database=str(path), force=True))
    assert rc == 0
    # restored data should have the backfilled memberships back
    conn = sqlite3.connect(path)
    count = conn.execute(
        "SELECT COUNT(*) FROM course_memberships WHERE migration_batch_id = ?",
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    ).fetchone()[0]
    conn.close()
    assert count == 2  # owner + student


def test_rollback_backfill_cli_deletes_batch_rows(tmp_path):
    path = tmp_path / "legacy.sqlite"
    conn = _legacy_access_db(path)
    conn.close()

    import argparse
    rc = cmd_rollback_backfill(argparse.Namespace(database=str(path)))
    assert rc == 0
    conn = sqlite3.connect(path)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM course_memberships WHERE migration_batch_id = ?",
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    ).fetchone()[0]
    conn.close()
    assert remaining == 0


def test_drill_runs_full_cycle(tmp_path):
    path = tmp_path / "legacy.sqlite"
    conn = _legacy_access_db(path)
    conn.close()

    import argparse
    dest_dir = str(tmp_path / "backups")
    rc = cmd_drill(argparse.Namespace(database=str(path), dest_dir=dest_dir))
    assert rc == 0
    # after drill+restore, backfill rows should be restored
    conn = sqlite3.connect(path)
    count = conn.execute(
        "SELECT COUNT(*) FROM course_memberships WHERE migration_batch_id = ?",
        (ACCESS_CONTROL_MIGRATION_BATCH,),
    ).fetchone()[0]
    conn.close()
    assert count == 2
