"""调试课程列表查询"""
import sys
sys.path.insert(0, '.')

from sqlmodel import Session, select, or_
from app.models.database import engine
from app.models.course_model import Course, CourseStatus

with Session(engine) as session:
    # 模拟老师查询 (user_id=6 是TTT)
    user_id = 6
    user_role = "teacher"

    statement = select(Course)

    if user_role == "student":
        statement = statement.where(Course.status == CourseStatus.PUBLISHED)
    else:
        statement = statement.where(
            or_(
                Course.teacher_id == user_id,
                Course.status == CourseStatus.PUBLISHED
            )
        )

    statement = statement.order_by(Course.created_at.desc())
    courses = session.exec(statement).all()

    print(f"Query returned: {len(courses)} courses")
    for c in courses[:5]:
        print(f"  ID={c.id} status={c.status.value} teacher={c.teacher_id} title={c.title}")
