"""
数据库初始化脚本
创建预设的老师和学生账号
"""

import asyncio
from sqlmodel import Session, select
import bcrypt

from app.models.database import engine
from app.models.user_model import User, UserRole
from app.models.access_control_model import PlatformPermission, PlatformPermissionAssignment


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def ensure_platform_admin(session: Session, user: User) -> None:
    """平台管理员必须同时拥有显式 platform.admin 分配，否则管理端点会 403。

    平台权限解析只读取 platform_permission_assignments（见
    course_access_service.require_platform_permission），与 users.role 解耦。
    """
    if user.id is None:
        session.flush()
    assignment = session.exec(
        select(PlatformPermissionAssignment).where(
            PlatformPermissionAssignment.user_id == user.id,
            PlatformPermissionAssignment.permission == PlatformPermission.ADMIN,
        )
    ).first()
    if assignment is None:
        session.add(PlatformPermissionAssignment(
            user_id=user.id,
            permission=PlatformPermission.ADMIN,
            granted_by_user_id=user.id,
        ))


def init_users():
    """初始化预设用户"""
    with Session(engine) as session:
        existing_teacher = session.exec(
            select(User).where(User.username == "TTT")
        ).first()
        
        if not existing_teacher:
            teacher = User(
                username="TTT",
                real_name="平台管理员账号",
                hashed_password=get_password_hash("123456"),
                # 全局角色已收敛为 user/admin；原教师演示账号保留为平台管理员。
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(teacher)
            ensure_platform_admin(session, teacher)
            print("[OK] 创建平台管理员账号: TTT / 123456")
        else:
            ensure_platform_admin(session, existing_teacher)
            print("[INFO] 平台管理员账号 TTT 已存在")
        
        existing_student = session.exec(
            select(User).where(User.username == "SSS")
        ).first()
        
        if not existing_student:
            student = User(
                username="SSS",
                real_name="学生账号",
                hashed_password=get_password_hash("123456"),
                role=UserRole.STUDENT,
                is_active=True,
            )
            session.add(student)
            print("[OK] 创建学生账号: SSS / 123456")
        else:
            print("[INFO] 学生账号 SSS 已存在")
        
        session.commit()
        print("\n数据库初始化完成！")
        print("=" * 40)
        print("平台管理员账号: TTT / 密码: 123456")
        print("学生账号: SSS / 密码: 123456")
        print("=" * 40)


if __name__ == "__main__":
    init_users()
