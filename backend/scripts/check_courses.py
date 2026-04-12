"""检查课程状态"""
from sqlmodel import Session, text
from app.models.database import engine

with Session(engine) as session:
    result = session.execute(text("SELECT id, title, status, teacher_id FROM courses WHERE status = 'PUBLISHED'")).fetchall()
    print('=== 已发布课程 ===')
    if not result:
        print('没有已发布的课程!')
        all_status = session.execute(text("SELECT status, COUNT(*) as cnt FROM courses GROUP BY status")).fetchall()
        print('\n=== 课程状态分布 ===')
        for row in all_status:
            print(f'{row[0]}: {row[1]}个')
    else:
        for row in result:
            print(f'ID: {row[0]}, Title: {row[1]}, Teacher: {row[3]}')
