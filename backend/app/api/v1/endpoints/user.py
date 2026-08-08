from __future__ import annotations

from fastapi import APIRouter, Depends
from datetime import timedelta

from app.core.config import settings
from app.core.security import (
    create_access_token,
    verify_password,
    get_password_hash,
    teacher_student_allowed,
    admin_only,
    get_current_user,
)
from app.schemas.common_schema import (
    UnifiedResponse,
    LoginRequest,
    LoginResponse,
    LoginResponseData,
    UserInfo,
    RegisterRequest,
    ModifyUserRequest,
    ProfileUpdateRequest,
)
from app.core.exceptions import unified_response

from sqlmodel import Session, select
from app.models.database import get_session
from app.models.user_model import User, UserRole
from app.models.access_control_model import PlatformPermissionAssignment

router = APIRouter()


def _platform_permissions(session: Session, user_id: int) -> list[str]:
    assignments = session.exec(
        select(PlatformPermissionAssignment).where(
            PlatformPermissionAssignment.user_id == user_id,
            PlatformPermissionAssignment.revoked_at.is_(None),
        )
    ).all()
    return sorted({
        getattr(assignment.permission, "value", str(assignment.permission))
        for assignment in assignments
    })


def _nickname(user: User) -> str:
    return user.real_name or user.username


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
            "auth_version": user.auth_version,
        },
        expires_delta=access_token_expires,
    )

    return LoginResponse(
        code=200,
        message="登录成功",
        data=LoginResponseData(
            token=access_token,
            userInfo=UserInfo(
                id=str(user.id),
                username=user.username,
                nickname=_nickname(user),
                role=user.role.value if hasattr(user.role, "value") else user.role,
                platform_permissions=_platform_permissions(session, int(user.id)),
            ),
        ),
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
            "auth_version": new_user.auth_version,
        },
        expires_delta=access_token_expires,
    )

    return LoginResponse(
        code=200,
        message="注册并登录成功",
        data=LoginResponseData(
            token=access_token,
            userInfo=UserInfo(
                id=str(new_user.id),
                username=new_user.username,
                nickname=_nickname(new_user),
                role=new_user.role.value if hasattr(new_user.role, "value") else new_user.role,
                platform_permissions=_platform_permissions(session, int(new_user.id)),
            ),
        ),
    )


@router.get("/me", response_model=UnifiedResponse)
async def get_my_info(
    current_user=Depends(teacher_student_allowed),
    session: Session = Depends(get_session),
):
    """Return identity plus explicit platform permissions for capability views."""
    db_user = session.get(User, int(current_user["user_id"]))
    data = {
        **current_user,
        "username": db_user.username if db_user else current_user.get("username", ""),
        "nickname": _nickname(db_user) if db_user else current_user.get("username", ""),
        "role": "admin" if current_user.get("role") == "admin" else "user",
        "platform_permissions": _platform_permissions(session, int(current_user["user_id"])),
    }
    return unified_response(code=200, message="获取成功", data=data)


@router.patch("/me/profile", response_model=UnifiedResponse)
async def update_my_profile(
    request: ProfileUpdateRequest,
    current_user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Change the display nickname and/or password for the logged-in user.

    The account ID and login username are immutable here.  Password changes
    are fail-closed and require verification of the existing password.
    """
    user = session.get(User, int(current_user["user_id"]))
    if user is None:
        return unified_response(code=404, message="用户不存在", data=None)

    changing_password = request.new_password is not None and request.new_password != ""
    changing_nickname = request.nickname is not None
    if not changing_password and not changing_nickname:
        return unified_response(code=400, message="没有可保存的资料变更", data=None)
    if changing_password:
        if not request.current_password or not verify_password(request.current_password, user.hashed_password):
            return unified_response(code=401, message="原密码验证失败", data=None)
        user.hashed_password = get_password_hash(request.new_password)
        user.auth_version += 1
    if changing_nickname:
        nickname = request.nickname.strip()
        if not nickname:
            return unified_response(code=422, message="昵称不能为空", data=None)
        user.real_name = nickname
    session.add(user)
    session.commit()
    session.refresh(user)

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "role": user.role.value if hasattr(user.role, "value") else user.role,
            "school_id": user.school_id,
            "auth_version": user.auth_version,
        },
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return unified_response(code=200, message="资料已更新", data={
        "token": access_token,
        "userInfo": UserInfo(
            id=str(user.id), username=user.username, nickname=_nickname(user),
            role=user.role.value if hasattr(user.role, "value") else user.role,
            platform_permissions=_platform_permissions(session, int(user.id)),
        ).model_dump(),
    })


@router.post("/modify", response_model=LoginResponse)
async def user_modify(
    request: ModifyUserRequest, session: Session = Depends(get_session)
):
    """用户信息修改接口"""
    # 1. 查找用户
    statement = select(User).where(User.id == int(request.id))
    user = session.exec(statement).first()

    if not user:
        return LoginResponse(code=404, message="用户不存在", data=None)

    # 2. 验证当前用户名和密码
    if user.username != request.username:
        return LoginResponse(code=401, message="用户名不匹配", data=None)

    if not verify_password(request.password, user.hashed_password):
        return LoginResponse(code=401, message="密码错误", data=None)

    # 登录名是稳定的账号标识，不再通过兼容接口修改。昵称请使用
    # PATCH /user/me/profile；保留本接口仅用于旧客户端的密码更新。
    if request.newUsername and request.newUsername != user.username:
        return LoginResponse(code=400, message="登录名不可修改，请修改个人昵称", data=None)

    # 4. 修改密码
    if request.newPassword:
        user.hashed_password = get_password_hash(request.newPassword)
        user.auth_version += 1

    # 5. 保存修改
    session.add(user)
    session.commit()
    session.refresh(user)

    # 6. 生成新Token（使旧Token失效）
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "role": user.role.value if hasattr(user.role, "value") else user.role,
            "school_id": user.school_id,
            "auth_version": user.auth_version,
        },
        expires_delta=access_token_expires,
    )

    return LoginResponse(
        code=200,
        message="修改成功",
        data=LoginResponseData(
            token=access_token,
            userInfo=UserInfo(id=str(user.id), username=user.username, nickname=_nickname(user)),
        ),
    )


@router.get("/list", response_model=UnifiedResponse, deprecated=True)
async def list_users(
    current_user=Depends(admin_only),
    session: Session = Depends(get_session),
):
    statement = select(User)
    users = session.exec(statement).all()
    user_list = []
    for u in users:
        user_list.append({
            "id": u.id,
            "username": u.username,
            "role": u.role.value if hasattr(u.role, "value") else u.role,
            "isActive": u.is_active,
            "createdAt": u.created_at.isoformat() if u.created_at else None,
        })
    return unified_response(code=200, message="获取成功", data={"users": user_list})


@router.put("/role", response_model=UnifiedResponse, deprecated=True)
async def change_user_role(
    request: dict,
    current_user=Depends(admin_only),
    session: Session = Depends(get_session),
):
    target_user_id = request.get("userId")
    new_role = request.get("role")

    if not target_user_id or not new_role:
        return unified_response(code=400, message="缺少userId或role参数", data=None)

    valid_roles = [r.value for r in UserRole]
    if new_role not in valid_roles:
        return unified_response(code=400, message=f"无效角色，可选: {valid_roles}", data=None)

    if int(target_user_id) == int(current_user["user_id"]):
        return unified_response(code=403, message="不能修改自己的角色", data=None)

    statement = select(User).where(User.id == int(target_user_id))
    user = session.exec(statement).first()

    if not user:
        return unified_response(code=404, message="用户不存在", data=None)

    user.role = UserRole(new_role)
    session.add(user)
    session.commit()
    session.refresh(user)

    return unified_response(
        code=200,
        message="角色修改成功",
        data={
            "id": user.id,
            "username": user.username,
            "role": user.role.value,
        },
    )


@router.get("/stats", response_model=UnifiedResponse)
async def get_teacher_stats(
    current_user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from app.models.course_model import Course, StudentEnrollment

    user_id = int(current_user["user_id"])
    user_role = current_user["role"]

    if user_role == "teacher":
        course_count = len(session.exec(select(Course).where(Course.teacher_id == user_id)).all())
        student_ids = session.exec(
            select(StudentEnrollment.student_id).distinct()
        ).all()
        student_count = len(set(student_ids))
    else:
        course_count = len(session.exec(select(Course)).all())
        student_ids = session.exec(
            select(StudentEnrollment.student_id).distinct()
        ).all()
        student_count = len(set(student_ids))

    return unified_response(
        code=200,
        message="获取成功",
        data={
            "courseCount": course_count,
            "studentCount": student_count,
        },
    )
