import sqlite3
import os
import logging
from typing import Any

from app.models.database import DATABASE_DIR, DATABASE_URL

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(DATABASE_DIR, "smart_class.db")
ACCESS_CONTROL_MIGRATION_BATCH = "access-control-v1"
AGENT_LOG_MIGRATION_BATCH = "agent-log-minimization-v1"

MIGRATIONS = {
    "courses": {
        "pdf_file_path": "ALTER TABLE courses ADD COLUMN pdf_file_path VARCHAR DEFAULT NULL",
        "invite_code": "ALTER TABLE courses ADD COLUMN invite_code VARCHAR DEFAULT NULL",
    },
    "script_nodes": {
        "audio_url": "ALTER TABLE script_nodes ADD COLUMN audio_url VARCHAR DEFAULT NULL",
        "audio_duration": "ALTER TABLE script_nodes ADD COLUMN audio_duration FLOAT DEFAULT 0.0",
    },
    "course_scripts": {
        "audio_url": "ALTER TABLE course_scripts ADD COLUMN audio_url VARCHAR DEFAULT NULL",
        "audio_duration": "ALTER TABLE course_scripts ADD COLUMN audio_duration FLOAT DEFAULT 0.0",
    },
    "course_memberships": {
        "migration_batch_id": "ALTER TABLE course_memberships ADD COLUMN migration_batch_id VARCHAR DEFAULT NULL",
    },
    "course_capabilities": {
        "migration_batch_id": "ALTER TABLE course_capabilities ADD COLUMN migration_batch_id VARCHAR DEFAULT NULL",
    },
    "platform_permission_assignments": {
        "migration_batch_id": "ALTER TABLE platform_permission_assignments ADD COLUMN migration_batch_id VARCHAR DEFAULT NULL",
    },
    "media_assets": {
        "course_id": "ALTER TABLE media_assets ADD COLUMN course_id INTEGER REFERENCES courses(id)",
    },
    "media_timeline_cues": {
        "is_active": "ALTER TABLE media_timeline_cues ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
    },
    "web_research_results": {
        "failure_reason": "ALTER TABLE web_research_results ADD COLUMN failure_reason VARCHAR NOT NULL DEFAULT ''",
    },
    "question_attempts": {
        "source_event_id": "ALTER TABLE question_attempts ADD COLUMN source_event_id VARCHAR",
        "measurement_role": "ALTER TABLE question_attempts ADD COLUMN measurement_role VARCHAR NOT NULL DEFAULT 'scored_performance'",
        "question_version": "ALTER TABLE question_attempts ADD COLUMN question_version INTEGER NOT NULL DEFAULT 1",
        "question_content_hash": "ALTER TABLE question_attempts ADD COLUMN question_content_hash VARCHAR NOT NULL DEFAULT ''",
    },
    "graph_node_reviews": {
        "target_content_hash": "ALTER TABLE graph_node_reviews ADD COLUMN target_content_hash VARCHAR NOT NULL DEFAULT ''",
    },
    "learning_evidence_records": {
        "timestamp": "ALTER TABLE learning_evidence_records ADD COLUMN timestamp VARCHAR DEFAULT ''",
    },
    "agent_learning_events": {
        "data_policy_version": "ALTER TABLE agent_learning_events ADD COLUMN data_policy_version VARCHAR NOT NULL DEFAULT 'agent-log-minimization/1'",
        "migration_batch_id": "ALTER TABLE agent_learning_events ADD COLUMN migration_batch_id VARCHAR DEFAULT NULL",
    },
    "agent_trace_records": {
        "session_id": "ALTER TABLE agent_trace_records ADD COLUMN session_id VARCHAR NOT NULL DEFAULT ''",
        "data_policy_version": "ALTER TABLE agent_trace_records ADD COLUMN data_policy_version VARCHAR NOT NULL DEFAULT 'agent-log-minimization/1'",
        "migration_batch_id": "ALTER TABLE agent_trace_records ADD COLUMN migration_batch_id VARCHAR DEFAULT NULL",
    },
}


def _sqlite_database_path() -> str:
    """Return the configured local SQLite path, or reject unsupported stores."""
    if not DATABASE_URL.startswith("sqlite:///"):
        raise RuntimeError("当前迁移器仅支持 SQLite；生产数据库必须使用专用迁移器")
    return DATABASE_URL.removeprefix("sqlite:///")


def _required_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def access_control_preflight(database_path: str | None = None) -> dict[str, Any]:
    """Validate legacy authority sources before changing any access records.

    The report is deterministic and intentionally failure-closed: orphaned
    legacy rows would produce memberships that cannot be interpreted safely,
    so callers must repair them before the cutover runs.
    """
    path = database_path or _sqlite_database_path()
    if not os.path.exists(path):
        return {"ok": True, "issues": [], "counts": {}}
    conn = sqlite3.connect(path)
    try:
        cursor = conn.cursor()
        required = {
            "users": {"id", "is_active", "role"},
            "courses": {"id", "teacher_id"},
            "student_enrollments": {"course_id", "student_id", "is_active"},
        }
        issues: list[str] = []
        for table_name, columns in required.items():
            existing = _required_columns(cursor, table_name)
            missing = columns - existing
            if missing:
                issues.append(f"{table_name} missing columns: {', '.join(sorted(missing))}")
        if issues:
            return {"ok": False, "issues": issues, "counts": {}}

        cursor.execute("""
            SELECT COUNT(*) FROM courses c
            LEFT JOIN users u ON u.id = c.teacher_id
            WHERE c.teacher_id IS NULL OR u.id IS NULL OR u.is_active = 0
        """)
        orphan_owners = cursor.fetchone()[0]
        cursor.execute("""
            SELECT COUNT(*) FROM student_enrollments e
            LEFT JOIN courses c ON c.id = e.course_id
            LEFT JOIN users u ON u.id = e.student_id
            WHERE e.is_active = 1 AND (c.id IS NULL OR u.id IS NULL OR u.is_active = 0)
        """)
        orphan_enrolments = cursor.fetchone()[0]
        counts = {"orphan_course_owners": orphan_owners, "orphan_active_enrolments": orphan_enrolments}
        if orphan_owners:
            issues.append(f"{orphan_owners} course owner records refer to missing or inactive users")
        if orphan_enrolments:
            issues.append(f"{orphan_enrolments} active enrollment records refer to missing/inactive users or courses")
        return {"ok": not issues, "issues": issues, "counts": counts}
    finally:
        conn.close()


def rollback_access_control_backfill(database_path: str | None = None) -> dict[str, int]:
    """Remove only rows inserted by this migration batch.

    This is a deployment rollback companion, not a runtime escape hatch. The
    application must be rolled back to code that still understands legacy
    access before invoking it.
    """
    path = database_path or _sqlite_database_path()
    conn = sqlite3.connect(path)
    try:
        cursor = conn.cursor()
        deleted: dict[str, int] = {}
        for table_name in ("platform_permission_assignments", "course_memberships", "course_capabilities"):
            cursor.execute(f"DELETE FROM {table_name} WHERE migration_batch_id = ?", (ACCESS_CONTROL_MIGRATION_BATCH,))
            deleted[table_name] = max(cursor.rowcount, 0)
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def agent_log_preflight(database_path: str | None = None) -> dict[str, Any]:
    """Report whether an existing SQLite database can receive log minimization.

    Existing raw rows are deliberately *not* copied into a rollback table.  The
    migration replaces them with redacted metadata, so a privacy-safe rollback
    can only remove the migration marker, not restore content that should no
    longer be retained.
    """
    path = database_path or _sqlite_database_path()
    if not os.path.exists(path):
        return {"ok": True, "issues": [], "counts": {}}
    conn = sqlite3.connect(path)
    try:
        cursor = conn.cursor()
        counts: dict[str, int] = {}
        issues: list[str] = []
        for table_name in ("agent_learning_events", "agent_trace_records"):
            if not _table_exists(cursor, table_name):
                counts[table_name] = 0
                continue
            required = {"id", "student_id", "course_id", "trace_id"}
            missing = required - _required_columns(cursor, table_name)
            if missing:
                issues.append(f"{table_name} missing columns: {', '.join(sorted(missing))}")
                continue
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            counts[table_name] = int(cursor.fetchone()[0])
        return {"ok": not issues, "issues": issues, "counts": counts}
    finally:
        conn.close()


def rollback_agent_log_minimization(database_path: str | None = None) -> dict[str, int]:
    """Remove only the migration ledger; raw content is intentionally unrecoverable.

    This is an operational rollback companion, not a restoration path for
    previously over-collected student content.
    """
    path = database_path or _sqlite_database_path()
    conn = sqlite3.connect(path)
    try:
        cursor = conn.cursor()
        if not _table_exists(cursor, "agent_log_migration_records"):
            return {"agent_log_migration_records": 0}
        cursor.execute("DELETE FROM agent_log_migration_records WHERE batch_id = ?", (AGENT_LOG_MIGRATION_BATCH,))
        conn.commit()
        return {"agent_log_migration_records": max(cursor.rowcount, 0)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _minimize_agent_logs(cursor: sqlite3.Cursor) -> tuple[int, int]:
    """Redact legacy raw payloads once, retaining identifiers and error metadata."""
    if not _table_exists(cursor, "agent_log_migration_records"):
        return (0, 0)
    cursor.execute("SELECT 1 FROM agent_log_migration_records WHERE batch_id = ?", (AGENT_LOG_MIGRATION_BATCH,))
    if cursor.fetchone() is not None:
        return (0, 0)

    event_rows = trace_rows = 0
    if _table_exists(cursor, "agent_learning_events"):
        cursor.execute(
            "UPDATE agent_learning_events SET event_data = ?, data_policy_version = ?, migration_batch_id = ?",
            ('{"reason_codes":["LEGACY_RAW_PAYLOAD_REDACTED"]}', "agent-log-minimization/1", AGENT_LOG_MIGRATION_BATCH),
        )
        event_rows = max(cursor.rowcount, 0)
    if _table_exists(cursor, "agent_trace_records"):
        cursor.execute(
            "UPDATE agent_trace_records SET trace_data = ?, data_policy_version = ?, migration_batch_id = ?",
            ('{"reason_codes":["LEGACY_RAW_PAYLOAD_REDACTED"]}', "agent-log-minimization/1", AGENT_LOG_MIGRATION_BATCH),
        )
        trace_rows = max(cursor.rowcount, 0)
    cursor.execute(
        "INSERT INTO agent_log_migration_records (batch_id, applied_at, redacted_event_rows, redacted_trace_rows) VALUES (?, CURRENT_TIMESTAMP, ?, ?)",
        (AGENT_LOG_MIGRATION_BATCH, event_rows, trace_rows),
    )
    return (event_rows, trace_rows)


def _backfill_access_control(cursor: sqlite3.Cursor) -> int:
    """Convert legacy authority into explicit, idempotent access records.

    This is migration-only code. Runtime authorization never reads the legacy
    role, teacher_id, or enrollment tables after the access-control cutover.
    """
    statements = (
        """
        INSERT OR IGNORE INTO course_capabilities
            (course_id, learning, course_building, knowledge_graph, evidence,
             experiment, coding_sandbox, cognitive_analysis, safety_policy, updated_at, migration_batch_id)
        SELECT id, 1, 1, 0, 0, 0, 0, 1, 0, CURRENT_TIMESTAMP, 'access-control-v1' FROM courses
        """,
        """
        INSERT OR IGNORE INTO course_memberships
            (user_id, course_id, role, status, permission_overrides,
             analytics_excluded, joined_at, updated_at, migration_batch_id)
        SELECT teacher_id, id, 'owner', 'active', '{}', 1,
               COALESCE(created_at, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP, 'access-control-v1'
        FROM courses
        """,
        """
        INSERT OR IGNORE INTO course_memberships
            (user_id, course_id, role, status, permission_overrides,
             analytics_excluded, joined_at, updated_at, migration_batch_id)
        SELECT student_id, course_id, 'student', 'active', '{}', 0,
               COALESCE(enrolled_at, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP, 'access-control-v1'
        FROM student_enrollments WHERE is_active = 1
        """,
        """
        INSERT OR IGNORE INTO platform_permission_assignments
            (user_id, permission, granted_by_user_id, granted_at, migration_batch_id)
        SELECT id, 'platform.admin', id, CURRENT_TIMESTAMP, 'access-control-v1'
        FROM users WHERE role = 'admin'
        """,
        """
        INSERT OR IGNORE INTO platform_permission_assignments
            (user_id, permission, granted_by_user_id, granted_at, migration_batch_id)
        SELECT id, 'platform.course.create', id, CURRENT_TIMESTAMP, 'access-control-v1'
        FROM users WHERE role = 'teacher'
        """,
    )
    applied = 0
    for statement in statements:
        cursor.execute(statement)
        applied += max(cursor.rowcount, 0)
    return applied


def run_migrations():
    database_path = _sqlite_database_path()
    if not os.path.exists(database_path):
        logger.info("Database not found, will be created by create_tables()")
        return

    report = access_control_preflight(database_path)
    if not report["ok"]:
        raise RuntimeError("Access-control preflight failed: " + "; ".join(report["issues"]))

    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()

    applied = 0
    for table_name, columns in MIGRATIONS.items():
        try:
            # New installations create these tables from SQLModel after this
            # compatibility migrator runs. Never execute ALTER/UPDATE against
            # a table that is not present in an older partial installation.
            if not _table_exists(cursor, table_name):
                continue
            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_cols = {row[1] for row in cursor.fetchall()}

            for col_name, alter_sql in columns.items():
                if col_name not in existing_cols:
                    cursor.execute(alter_sql)
                    logger.info(f"Migration: added '{col_name}' to {table_name}")
                    applied += 1
        except Exception as e:
            logger.warning(f"Migration check for {table_name} failed: {e}")

    try:
        if _table_exists(cursor, "question_attempts"):
            cursor.execute(
                """
                UPDATE question_attempts
                SET source_event_id = 'legacy_qe_' || id
                WHERE source_event_id IS NULL OR source_event_id = ''
                """
            )
            if cursor.rowcount > 0:
                applied += cursor.rowcount
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                uq_question_attempts_source_event_id
                ON question_attempts(source_event_id)
                """
            )
        access_tables = {
            "platform_permission_assignments",
            "course_memberships",
            "course_capabilities",
        }
        if all(_table_exists(cursor, table) for table in access_tables):
            applied += _backfill_access_control(cursor)
        log_preflight = agent_log_preflight(database_path)
        if not log_preflight["ok"]:
            raise RuntimeError("Agent-log preflight failed: " + "; ".join(log_preflight["issues"]))
        if _table_exists(cursor, "agent_log_migration_records"):
            redacted_events, redacted_traces = _minimize_agent_logs(cursor)
            applied += redacted_events + redacted_traces
        conn.commit()
        logger.info("Applied %s migration/backfill operation(s)", applied)
    except Exception:
        conn.rollback()
        logger.exception("Access-control migration failed; refusing partial migration")
        raise
    finally:
        conn.close()
