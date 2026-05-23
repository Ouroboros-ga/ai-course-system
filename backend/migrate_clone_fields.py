"""添加声音复刻字段到teacher_assets表"""
import sqlite3
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "database", "smart_class.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(teacher_assets)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"Existing columns: {columns}")

    if "clone_voice_id" not in columns:
        cursor.execute("ALTER TABLE teacher_assets ADD COLUMN clone_voice_id VARCHAR DEFAULT NULL")
        print("Added clone_voice_id")

    if "clone_status" not in columns:
        cursor.execute("ALTER TABLE teacher_assets ADD COLUMN clone_status VARCHAR DEFAULT 'none'")
        print("Added clone_status")

    conn.commit()
    conn.close()
    print("Migration done")

if __name__ == "__main__":
    migrate()
