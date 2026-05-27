import sqlite3
import os
import logging

from app.models.database import DATABASE_DIR

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(DATABASE_DIR, "smart_class.db")

MIGRATIONS = {
    "courses": {
        "pdf_file_path": "ALTER TABLE courses ADD COLUMN pdf_file_path VARCHAR DEFAULT NULL",
    },
    "script_nodes": {
        "audio_url": "ALTER TABLE script_nodes ADD COLUMN audio_url VARCHAR DEFAULT NULL",
        "audio_duration": "ALTER TABLE script_nodes ADD COLUMN audio_duration FLOAT DEFAULT 0.0",
    },
    "course_scripts": {
        "audio_url": "ALTER TABLE course_scripts ADD COLUMN audio_url VARCHAR DEFAULT NULL",
        "audio_duration": "ALTER TABLE course_scripts ADD COLUMN audio_duration FLOAT DEFAULT 0.0",
    },
}


def run_migrations():
    if not os.path.exists(DB_PATH):
        logger.info("Database not found, will be created by create_tables()")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    applied = 0
    for table_name, columns in MIGRATIONS.items():
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_cols = {row[1] for row in cursor.fetchall()}

            for col_name, alter_sql in columns.items():
                if col_name not in existing_cols:
                    cursor.execute(alter_sql)
                    logger.info(f"Migration: added '{col_name}' to {table_name}")
                    applied += 1
        except Exception as e:
            logger.warning(f"Migration check for {table_name} failed: {e}")

    if applied > 0:
        conn.commit()
        logger.info(f"Applied {applied} database migration(s)")
    else:
        logger.info("Database schema is up to date")

    conn.close()
