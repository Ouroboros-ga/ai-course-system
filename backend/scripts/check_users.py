"""
检查数据库中的用户信息
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select
from app.models.database import engine
from app.models.user_model import User, UserRole


def check_users():
    """检查所有用户"""
    with Session(engine) as session:
        users = session.exec(select(User)).all()

        print("\n当前数据库中的用户:")
        print("=" * 70)
        print(f"{'ID':<5} {'用户名':<15} {'角色':<10} {'状态':<8} {'创建时间'}")
        print("=" * 70)

        for user in users:
            status = "激活" if user.is_active else "禁用"
            print(f"{user.id:<5} {user.username:<15} {user.role.value:<10} {status:<8} {user.created_at}")

        print("=" * 70)


if __name__ == "__main__":
    check_users()
