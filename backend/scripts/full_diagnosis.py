"""全面诊断：用户、课程、选课数据"""
import sys
sys.path.insert(0, '.')

from sqlmodel import Session, text
from app.models.database import engine

with Session(engine) as session:
    print("=" * 60)
    print("1. 用户表 (users)")
    print("=" * 60)
    users = session.execute(text("SELECT id, username, role, is_active FROM users")).fetchall()
    for u in users:
        print(f"  ID={u[0]}  用户名={u[1]}  角色={u[2]}  状态={'激活' if u[3] else '禁用'}")
    
    if not users:
        print("  [空表]")
    
    print("\n" + "=" * 60)
    print("2. 课程表 (courses) - 最新10条")
    print("=" * 60)
    courses = session.execute(text(
        "SELECT id, title, status, teacher_id, total_nodes FROM courses ORDER BY id DESC LIMIT 10"
    )).fetchall()
    for c in courses:
        print(f"  ID={c[0]}  标题={c[1][:30] if c[1] else 'NULL'}...  状态={c[2]}  老师ID={c[3]}  节点数={c[4]}")
    
    if not courses:
        print("  [空表]")
    
    print("\n" + "=" * 60)
    print("3. 选课表 (student_enrollments)")
    print("=" * 60)
    enrollments = session.execute(text(
        "SELECT id, student_id, course_id, is_active, overall_progress FROM student_enrollments"
    )).fetchall()
    for e in enrollments:
        print(f"  ID={e[0]}  学生ID={e[1]}  课程ID={e[2]}  活跃={e[3]}  进度={e[4]}%")
    
    if not enrollments:
        print("  [空表]")
    
    # 验证关联
    print("\n" + "=" * 60)
    print("4. 关联验证")
    print("=" * 60)
    
    user_ids = {u[0]: u[1] for u in users}
    teacher_ids_in_courses = set(c[3] for c in courses)
    
    print(f"  用户数: {len(users)}")
    print(f"  课程数: {len(courses)}")
    print(f"  选课记录: {len(enrollments)}")
    
    ttt_found = any(u[1] == "TTT" for u in users)
    sss_found = any(u[1] == "SSS" for u in users)
    published_count = sum(1 for c in courses if c[2] == "published")
    
    print(f"\n  TTT账号存在: {'YES' if ttt_found else 'NO'}")
    print(f"  SSS账号存在: {'YES' if sss_found else 'NO'}")
    print(f"  已发布课程: {published_count}个")
    
    if users and courses:
        ttt_id = next((u[0] for u in users if u[1] == "TTT"), None)
        sss_id = next((u[0] for u in users if u[1] == "SSS"), None)
        
        if ttt_id:
            ttt_courses = [c for c in courses if c[3] == ttt_id]
            print(f"\n  TTT(ID={ttt_id}) 创建的课程: {len(ttt_courses)}个")
            for tc in ttt_courses[:5]:
                print(f"    - [{tc[2]}] ID={tc[0]}")
        
        if sss_id:
            sss_enrollments = [e for e in enrollments if e[1] == sss_id]
            print(f"\n  SSS(ID={sss_id}) 的选课记录: {len(sss_enrollments)}个")
