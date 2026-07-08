import sqlite3, os

db = r"E:\smartcarb\ai-course-system\database\smart_class.db"
print("DB path:", db)
print("DB exists:", os.path.exists(db))
if not os.path.exists(db):
    print("!! 生产库不存在 -> 先启动一次后端触发 create_tables 建库，再跑 init_users / seed_smoke_course")
    raise SystemExit(0)

conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print("\n表清单 (%d):" % len(tables))
for t in tables:
    print("   ", t)

def q(sql):
    try:
        cur.execute(sql)
        return cur.fetchall()
    except Exception as e:
        return [("ERR", str(e))]

print("\n== 行数概览 ==")
for t in tables:
    print("  %-28s %s" % (t, q("SELECT COUNT(*) FROM '%s'" % t)[0][0]))

print("\n== 用户 ==")
if "users" in tables:
    for r in q("SELECT id, username, role, is_active FROM users LIMIT 30"):
        print("  ", r)

print("\n== 课程 ==")
if "courses" in tables:
    for r in q("SELECT id, title, teacher_id, status, source_file_path, pdf_file_path FROM courses LIMIT 30"):
        print("  ", r)

print("\n== 脚本(看 is_active) ==")
if "course_scripts" in tables:
    for r in q("SELECT id, course_id, version, is_active, audio_duration FROM course_scripts LIMIT 30"):
        print("  ", r)

print("\n== 脚本节点 ==")
if "script_nodes" in tables:
    for r in q("SELECT id, script_id, node_index, node_type, title FROM script_nodes LIMIT 10"):
        print("  ", r)

print("\n== 已完成视频任务 ==")
vid_tables = [t for t in tables if "video" in t and "task" in t]
for vt in vid_tables:
    print("  表:", vt)
    try:
        cur.execute("SELECT COUNT(*) FROM '%s' WHERE status='completed'" % vt)
        print("    completed:", cur.fetchone()[0])
        cur.execute("SELECT node_id, dh_video_path FROM '%s' WHERE status='completed' LIMIT 10" % vt)
        for r in cur.fetchall():
            print("   ", r)
    except Exception as e:
        print("    ERR:", e)
if not vid_tables:
    print("  (无视频任务表)")

conn.close()
