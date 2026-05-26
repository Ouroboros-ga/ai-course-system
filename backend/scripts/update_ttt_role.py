"""
更新TTT账号的角色为teacher
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select
from app.models.database import engine
from app.models.user_model import User, UserRole


def update_ttt_role():
    """更新TTT账号角色为teacher"""
    with Session(engine) as session:
        # 查找TTT用户
        ttt = session.exec(select(User).where(User.username == "TTT")).first()

        if ttt:
            print(f"找到用户 TTT (ID: {ttt.id})")
            print(f"当前角色: {ttt.role.value}")

            # 更新角色为teacher
            ttt.role = UserRole.TEACHER
            session.add(ttt)
            session.commit()

            print("[OK] 角色已更新为: teacher")
        else:
            print("[ERROR] 未找到用户 TTT")


if __name__ == "__main__":
    update_ttt_role()
