# app/api/v1/endpoints/user.py
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

router = APIRouter()

# 模拟数据库用户（实际项目替换为数据库查询）
fake_users_db = {
    "teacher1": {
        "user_id": "tea20001",
        "username": "teacher1",
        "hashed_password": get_password_hash("123456"),
        "role": "teacher",
        "school_id": "sch10001"
    },
    "student1": {
        "user_id": "stu20001",
        "username": "student1",
        "hashed_password": get_password_hash("123456"),
        "role": "student",
        "school_id": "sch10001"
    }
}

@router.post("/login", response_model=LoginResponse)
async def user_login(request: LoginRequest):
    """用户登录接口（获取Token）"""
    # 查用户
    user = fake_users_db.get(request.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    # 验密码
    if not verify_password(request.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    # 生成Token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "school_id": user["school_id"]
        },
        expires_delta=access_token_expires
    )
    # 返回规范格式
    return unified_response(
        code=200,
        msg="登录成功",
        data=LoginResponseData(
            internalUserId=user["user_id"],
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