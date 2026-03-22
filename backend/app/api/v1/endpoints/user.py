from __future__ import annotations

from fastapi import APIRouter, Depends
from datetime import timedelta

from app.core.config import settings
from app.core.security import (
    create_access_token,
    verify_password,
    get_password_hash,
    teacher_student_allowed,
)
from app.schemas.common_schema import (
    UnifiedResponse,
    LoginRequest,
    LoginResponse,
    LoginResponseData,
    UserInfo,
    RegisterRequest,
)
from app.core.exceptions import unified_response

from sqlmodel import Session, select
from app.models.database import get_session
from app.models.user_model import User

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def user_login(request: LoginRequest, session: Session = Depends(get_session)):
    statement = select(User).where(User.username == request.username)
    user = session.exec(statement).first()

    if not user:
        return LoginResponse(code=401, message="用户名密码错误", data=None)

    if not verify_password(request.password, user.hashed_password):
        return LoginResponse(code=401, message="用户名密码错误", data=None)

    if not user.is_active:
        return LoginResponse(code=403, message="账户已禁用", data=None)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "role": user.role.value if hasattr(user.role, "value") else user.role,
            "school_id": user.school_id,
        },
        expires_delta=access_token_expires,
    )

    return LoginResponse(
        code=200,
        message="登录成功",
        data=LoginResponseData(token=access_token, userInfo=UserInfo(id=str(user.id))),
    )


@router.post("/register", response_model=LoginResponse)
async def user_register(
    request: RegisterRequest, session: Session = Depends(get_session)
):
    statement = select(User).where(User.username == request.username)
    existing_user = session.exec(statement).first()

    if existing_user:
        return LoginResponse(code=409, message="用户名已存在", data=None)

    hashed_password = get_password_hash(request.password)
    new_user = User(username=request.username, hashed_password=hashed_password)
    session.add(new_user)
    session.commit()
    session.refresh(new_user)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": str(new_user.id),
            "username": new_user.username,
            "role": new_user.role.value
            if hasattr(new_user.role, "value")
            else new_user.role,
            "school_id": new_user.school_id,
        },
        expires_delta=access_token_expires,
    )

    return LoginResponse(
        code=200,
        message="注册并登录成功",
        data=LoginResponseData(
            token=access_token, userInfo=UserInfo(id=str(new_user.id))
        ),
    )


@router.get("/me", response_model=UnifiedResponse)
async def get_my_info(current_user=Depends(teacher_student_allowed)):
    return unified_response(code=200, message="获取成功", data=current_user)
