# app/api/v1/endpoints/user.py

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from datetime import timedelta

from app.core.config import settings
from app.core.security import (
    create_access_token,
    verify_password,
    get_password_hash,
    teacher_student_allowed,
    get_current_user
)
from app.schemas.common_schema import (
    UnifiedResponse,
    LoginRequest,
    LoginResponse,
    LoginResponseData
)
from app.core.exceptions import unified_response

from sqlmodel import Session, select
from app.models.database import get_session
from app.models.user_model import User   # 导入真实的 User 模型

router = APIRouter()

# 模拟数据库用户（实际项目替换为数据库查询）
# fake_users_db = {
#     "teacher1": {
#         "user_id": "tea20001",
#         "username": "teacher1",
#         "hashed_password": get_password_hash("123456"),
#         "role": "teacher",
#         "school_id": "sch10001"
#     },
#     "student1": {
#         "user_id": "stu20001",
#         "username": "student1",
#         "hashed_password": get_password_hash("123456"),
#         "role": "student",
#         "school_id": "sch10001"
#     }
# }

@router.post("/login", response_model=LoginResponse)
async def user_login(
    request: LoginRequest,
    session: Session = Depends(get_session)   # 注入数据库会话
):
    # 从数据库查询用户（根据 username 或 fanya_account_id，这里用 username）
    statement = select(User).where(User.username == request.username)
    user = session.exec(statement).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    # 验证密码（注意：使用 user.hashed_password）
    if not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    # 检查用户是否激活
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已禁用，请联系管理员"
        )

    # 生成 Token（payload 中需要包含必要信息，如 user.id, role, school_id）
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": str(user.id),               # 使用数据库主键 ID
            "username": user.username,
            "role": user.role.value if hasattr(user.role, 'value') else user.role,  # 枚举转字符串
            "school_id": user.school_id
        },
        expires_delta=access_token_expires
    )

    # 返回统一格式（internalUserId 可以使用 user.id 或 user.fanya_account_id，根据业务决定）
    return unified_response(
        code=200,
        msg="登录成功",
        data=LoginResponseData(
            internalUserId=str(user.id),        # 或 user.fanya_account_id
            syncStatus="success",
            authToken=access_token
        )
    )

@router.get("/me", response_model=UnifiedResponse)
async def get_my_info(current_user = Depends(teacher_student_allowed)):
    """获取当前用户信息（需登录）"""
    return unified_response(
        code=200,
        msg="获取成功",
        data=current_user
    )