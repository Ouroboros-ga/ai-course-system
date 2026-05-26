import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "smart_class.db")

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}, skipping migration")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(courses)")
    columns = [row[1] for row in cursor.fetchall()]

    if "pdf_file_path" not in columns:
        cursor.execute("ALTER TABLE courses ADD COLUMN pdf_file_path VARCHAR DEFAULT NULL")
        conn.commit()
        print("Added 'pdf_file_path' column to courses table")
    else:
        print("'pdf_file_path' column already exists in courses table")

    conn.close()
    print("Migration completed successfully")

if __name__ == "__main__":
    migrate()
