"""
创建教师和学生测试账号
教师账号: TTT / 123456
学生账号: SSS / 123456
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select
from app.models.database import engine
from app.models.user_model import User, UserRole
from app.core.security import get_password_hash


def create_test_users():
    """创建测试用户"""
    with Session(engine) as session:
        # 检查用户是否已存在
        existing_ttt = session.exec(select(User).where(User.username == "TTT")).first()
        existing_sss = session.exec(select(User).where(User.username == "SSS")).first()

        # 创建教师账号 TTT
        if not existing_ttt:
            teacher = User(
                username="TTT",
                hashed_password=get_password_hash("123456"),
                role=UserRole.TEACHER,
                is_active=True,
            )
            session.add(teacher)
            print("[OK] 教师账号创建成功: TTT / 123456 (角色: teacher)")
        else:
            print("[WARN] 教师账号 TTT 已存在")

        # 创建学生账号 SSS
        if not existing_sss:
            student = User(
                username="SSS",
                hashed_password=get_password_hash("123456"),
                role=UserRole.STUDENT,
                is_active=True,
            )
            session.add(student)
            print("[OK] 学生账号创建成功: SSS / 123456 (角色: student)")
        else:
            print("[WARN] 学生账号 SSS 已存在")

        session.commit()
        print("\n账号创建完成!")
        print("=" * 50)
        print("教师账号: TTT / 123456")
        print("学生账号: SSS / 123456")
        print("=" * 50)


if __name__ == "__main__":
    create_test_users()
