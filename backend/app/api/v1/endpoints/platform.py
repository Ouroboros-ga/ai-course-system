from __future__ import annotations

import httpx
import hashlib
import time
import logging
from app.core.time_utils import utcnow_naive
from typing import Optional

from fastapi import APIRouter, Query, Depends, Request, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import create_access_token, get_current_user, get_password_hash, verify_password
from app.models.user_model import User, UserRole
from app.models.access_control_model import PlatformPermission, PlatformPermissionAssignment
from app.models.course_model import Course, StudentEnrollment
from app.models.database import get_session
from app.core.exceptions import unified_response
from app.services.course_access_service import CourseAccessContext, course_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["泛雅平台对接"])


def _sync_platform_permissions(session: Session, user: User) -> None:
    """Persist platform abilities granted by the trusted upstream sync policy."""
    if user.role != UserRole.TEACHER:
        return
    assignment = session.exec(select(PlatformPermissionAssignment).where(
        PlatformPermissionAssignment.user_id == user.id,
        PlatformPermissionAssignment.permission == PlatformPermission.COURSE_CREATE,
    )).first()
    if assignment is None:
        session.add(PlatformPermissionAssignment(
            user_id=user.id,
            permission=PlatformPermission.COURSE_CREATE,
            granted_by_user_id=user.id,
        ))


class FanyaSSOCallbackRequest(BaseModel):
    ticket: str = Field(..., description="泛雅SSO票据")
    timestamp: str = Field(..., description="时间戳")
    sign: str = Field(..., description="签名")


class FanyaSyncUserRequest(BaseModel):
    fanya_user_id: str = Field(..., description="泛雅用户ID(学号/工号)")
    username: str = Field(..., description="用户名")
    real_name: Optional[str] = Field(None, description="真实姓名")
    email: Optional[str] = Field(None, description="邮箱")
    role: str = Field(default="student", description="角色: teacher/student")
    school_id: Optional[str] = Field(None, description="学校ID")


class FanyaSyncCourseRequest(BaseModel):
    fanya_course_id: str = Field(..., description="泛雅课程ID")
    fanya_course_name: str = Field(..., description="课程名称")
    teacher_fanya_id: str = Field(..., description="教师泛雅ID")
    course_description: Optional[str] = Field(None, description="课程描述")
    student_list: Optional[list] = Field(default=[], description="学生泛雅ID列表")


class FanyaSyncEnrollmentRequest(BaseModel):
    fanya_course_id: str = Field(..., description="泛雅课程ID")
    student_fanya_ids: list = Field(..., description="学生泛雅ID列表")


class FanyaProgressCallbackRequest(BaseModel):
    fanya_user_id: str = Field(..., description="学生泛雅ID")
    fanya_course_id: str = Field(..., description="泛雅课程ID")
    node_id: Optional[str] = Field(None, description="学习节点ID")
    understanding_score: float = Field(default=0.0, description="理解度分数(0-1)")
    study_minutes: int = Field(default=0, description="学习时长(分钟)")
    progress_percent: float = Field(default=0.0, description="进度百分比")


def _verify_fanya_sign(data: dict, sign: str) -> bool:
    if not settings.FANYA_APP_SECRET:
        return True
    sorted_str = "&".join(f"{k}={v}" for k, v in sorted(data.items()) if v)
    raw = f"{sorted_str}{settings.FANYA_APP_SECRET}"
    expected = hashlib.md5(raw.encode()).hexdigest().upper()
    return expected == sign.upper()


@router.get("/sso/callback")
async def sso_callback(
    ticket: str = Query(..., description="泛雅SSO票据"),
    redirect_url: Optional[str] = Query(None, description="登录成功后的跳转地址"),
    session: Session = Depends(get_session),
):
    """泛雅平台SSO单点登录回调接口"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            verify_resp = await client.get(
                settings.FANYA_SSO_VERIFY_URL,
                params={"ticket": ticket, "appId": settings.FANYA_APP_ID},
            )
            verify_data = verify_resp.json()

        if not verify_data.get("success"):
            return unified_response(code=401, message="泛雅票据验证失败", data=None)

        user_info = verify_data.get("data", {})
        fanya_id = user_info.get("userId") or user_info.get("fanyaUserId")

        statement = select(User).where(User.fanya_account_id == fanya_id)
        existing_user = session.exec(statement).first()

        if existing_user:
            if not existing_user.is_active:
                return unified_response(code=403, message="账号已被禁用", data=None)
            token_data = {
                "user_id": existing_user.id,
                "username": existing_user.username,
                "role": existing_user.role.value,
                "fanya_verified": True,
            }
        else:
            username = user_info.get("username") or f"fanya_{fanya_id}"
            real_name = user_info.get("realName") or user_info.get("name")
            role_str = user_info.get("role", "student")
            role = UserRole.TEACHER if role_str == "teacher" else UserRole.STUDENT

            new_user = User(
                username=username,
                hashed_password=get_password_hash(f"fanya_sso_{fanya_id}"),
                fanya_account_id=fanya_id,
                is_fanya_verified=True,
                role=role,
                real_name=real_name,
                school_id=user_info.get("schoolId"),
                is_active=True,
            )
            session.add(new_user)
            session.commit()
            session.refresh(new_user)

            token_data = {
                "user_id": new_user.id,
                "username": new_user.username,
                "role": new_user.role.value,
                "fanya_verified": True,
            }

        access_token = create_access_token(token_data)

        return unified_response(
            code=200,
            message="SSO登录成功",
            data={
                "token": access_token,
                "redirectUrl": redirect_url or "/",
                "userInfo": {
                    "fanyaId": fanya_id,
                    "username": token_data["username"],
                    "role": token_data["role"],
                    "isNewUser": existing_user is None,
                },
            },
        )
    except Exception as e:
        logger.error(f"SSO回调异常: {e}")
        return unified_response(code=500, message=f"SSO处理异常: {str(e)}", data=None)


@router.post("/syncUser")
async def sync_user(
    request: FanyaSyncUserRequest,
    session: Session = Depends(get_session),
):
    """泛雅平台推送同步用户信息"""
    try:
        statement = select(User).where(User.fanya_account_id == request.fanya_user_id)
        existing_user = session.exec(statement).first()

        if existing_user:
            if request.real_name:
                existing_user.real_name = request.real_name
            if request.email:
                existing_user.email = request.email
            if request.role and request.role in ["teacher", "student"]:
                existing_user.role = UserRole(request.role)
            existing_user.is_fanya_verified = True
            _sync_platform_permissions(session, existing_user)
            session.add(existing_user)
            session.commit()
            session.refresh(existing_user)

            return unified_response(
                code=200,
                message="用户信息更新成功",
                data={
                    "localId": existing_user.id,
                    "username": existing_user.username,
                    "action": "updated",
                },
            )

        username = request.username or f"fanya_{request.fanya_user_id}"
        role = UserRole.TEACHER if request.role == "teacher" else UserRole.STUDENT

        new_user = User(
            username=username,
            hashed_password=get_password_hash(f"fanya_sync_{request.fanya_user_id}"),
            fanya_account_id=request.fanya_user_id,
            is_fanya_verified=True,
            role=role,
            real_name=request.real_name,
            email=request.email,
            school_id=request.school_id,
            is_active=True,
        )
        session.add(new_user)
        session.commit()
        session.refresh(new_user)
        _sync_platform_permissions(session, new_user)
        session.commit()

        return unified_response(
            code=200,
            message="用户同步成功",
            data={
                "localId": new_user.id,
                "username": new_user.username,
                "action": "created",
            },
        )
    except Exception as e:
        logger.error(f"用户同步异常: {e}")
        return unified_response(code=500, message=f"同步失败: {str(e)}", data=None)


@router.post("/syncCourse")
async def sync_course(
    request: FanyaSyncCourseRequest,
    session: Session = Depends(get_session),
):
    """泛雅平台推送同步课程信息"""
    try:
        teacher_stmt = select(User).where(
            User.fanya_account_id == request.teacher_fanya_id
        )
        teacher = session.exec(teacher_stmt).first()

        if not teacher:
            return unified_response(
                code=404,
                message=f"未找到泛雅ID为 {request.teacher_fanya_id} 的教师",
                data=None,
            )

        course_stmt = select(Course).where(
            Course.fanya_course_id == request.fanya_course_id
        )
        existing_course = session.exec(course_stmt).first()

        if existing_course:
            existing_course.fanya_course_name = request.fanya_course_name
            existing_course.title = request.fanya_course_name
            if request.course_description:
                existing_course.description = request.course_description
            existing_course.updated_at = utcnow_naive()
            session.add(existing_course)
            session.commit()
            session.refresh(existing_course)

            if request.student_list:
                _sync_enrollments(session, existing_course.id, request.student_list)

            return unified_response(
                code=200,
                message="课程更新成功",
                data={
                    "localCourseId": existing_course.id,
                    "fanyaCourseId": existing_course.fanya_course_id,
                    "action": "updated",
                },
            )

        new_course = Course(
            fanya_course_id=request.fanya_course_id,
            fanya_course_name=request.fanya_course_name,
            title=request.fanya_course_name,
            description=request.course_description,
            teacher_id=teacher.id,
            status="draft",
        )
        session.add(new_course)
        session.commit()
        session.refresh(new_course)
        from app.services.course_access_service import establish_course_access_baseline
        establish_course_access_baseline(session, new_course.id, teacher.id)
        session.commit()

        if request.student_list:
            _sync_enrollments(session, new_course.id, request.student_list)

        return unified_response(
            code=200,
            message="课程同步成功",
            data={
                "localCourseId": new_course.id,
                "fanyaCourseId": new_course.fanya_course_id,
                "action": "created",
            },
        )
    except Exception as e:
        logger.error(f"课程同步异常: {e}")
        return unified_response(code=500, message=f"同步失败: {str(e)}", data=None)


@router.post("/syncEnrollment")
async def sync_enrollment(
    request: FanyaSyncEnrollmentRequest,
    session: Session = Depends(get_session),
):
    """同步选课关系"""
    try:
        course_stmt = select(Course).where(
            Course.fanya_course_id == request.fanya_course_id
        )
        course = session.exec(course_stmt).first()

        if not course:
            return unified_response(
                code=404,
                message=f"未找到泛雅课程ID为 {request.fanya_course_id} 的课程",
                data=None,
            )

        synced_count = _sync_enrollments(session, course.id, request.student_fanya_ids)

        return unified_response(
            code=200,
            message=f"选课同步完成，共{synced_count}人",
            data={
                "courseId": course.id,
                "syncedCount": synced_count,
            },
        )
    except Exception as e:
        logger.error(f"选课同步异常: {e}")
        return unified_response(code=500, message=f"同步失败: {str(e)}", data=None)


def _sync_enrollments(
    session: Session, course_id: int, student_fanya_ids: list
) -> int:
    """内部方法：批量同步选课关系，返回新增数量"""
    count = 0
    for fanya_id in student_fanya_ids:
        stmt = select(User).where(User.fanya_account_id == fanya_id)
        student = session.exec(stmt).first()
        if not student:
            continue

        exist_stmt = select(StudentEnrollment).where(
            StudentEnrollment.student_id == student.id,
            StudentEnrollment.course_id == course_id,
        )
        existing = session.exec(exist_stmt).first()
        if existing:
            continue

        enrollment = StudentEnrollment(
            student_id=student.id,
            course_id=course_id,
        )
        session.add(enrollment)
        from app.services.course_access_service import activate_student_membership
        activate_student_membership(session, course_id, student.id)
        count += 1

    if count > 0:
        session.commit()
    return count


@router.post("/callback/progress")
async def callback_progress(
    request: FanyaProgressCallbackRequest,
    session: Session = Depends(get_session),
):
    """接收学习进度（本系统→泛雅回传的逆向接口，或泛雅主动查询）"""
    try:
        stmt = select(User).where(User.fanya_account_id == request.fanya_user_id)
        student = session.exec(stmt).first()
        if not student:
            return unified_response(code=404, message="学生不存在", data=None)

        course_stmt = select(Course).where(
            Course.fanya_course_id == request.fanya_course_id
        )
        course = session.exec(course_stmt).first()
        if not course:
            return unified_response(code=404, message="课程不存在", data=None)

        enroll_stmt = select(StudentEnrollment).where(
            StudentEnrollment.student_id == student.id,
            StudentEnrollment.course_id == course.id,
        )
        enrollment = session.exec(enroll_stmt).first()

        if enrollment:
            enrollment.total_study_minutes += request.study_minutes
            enrollment.overall_progress = max(
                enrollment.overall_progress, request.progress_percent
            )
            if request.understanding_score > 0:
                total = enrollment.avg_understanding_score * (
                    enrollment.total_nodes_completed or 1
                ) + request.understanding_score
                enrollment.total_nodes_completed += 1
                enrollment.avg_understanding_score = total / max(
                    enrollment.total_nodes_completed, 1
                )
            enrollment.last_study_time = utcnow_naive()
            session.add(enrollment)
            session.commit()

        if settings.FANYA_CALLBACK_URL:
            _async_push_to_fanya(request.dict())

        return unified_response(
            code=200,
            message="进度记录成功",
            data={
                "studentId": student.id,
                "courseId": course.id,
                "progress": request.progress_percent,
            },
        )
    except Exception as e:
        logger.error(f"进度回调异常: {e}")
        return unified_response(code=500, message=f"记录失败: {str(e)}", data=None)


async def _async_push_to_fanya(progress_data: dict):
    """异步将学习数据推送到泛雅平台"""
    if not settings.FANYA_CALLBACK_URL or not settings.FANYA_APP_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            payload = {**progress_data, "appId": settings.FANYA_APP_ID}
            await client.post(settings.FANYA_CALLBACK_URL, json=payload)
    except Exception as e:
        logger.warning(f"推送到泛雅失败: {e}")


@router.get("/bind/status/{course_id}")
async def get_bind_status(
    course_id: int,
    _access: CourseAccessContext = Depends(course_permission("course.edit")),
    session: Session = Depends(get_session),
):
    """查询课程的泛雅绑定状态"""
    stmt = select(Course).where(Course.id == course_id)
    course = session.exec(stmt).first()
    if not course:
        return unified_response(code=404, message="课程不存在", data=None)

    is_bound = bool(course.fanya_course_id and course.fanya_course_id != f"local_{course_id}")

    enroll_stmt = select(StudentEnrollment).where(
        StudentEnrollment.course_id == course_id
    )
    enrollments = session.exec(enroll_stmt).all()

    bound_students = []
    for enr in enrollments:
        user_stmt = select(User).where(User.id == enr.student_id)
        user = session.exec(user_stmt).first()
        if user and user.is_fanya_verified:
            bound_students.append({
                "localId": user.id,
                "fanyaId": user.fanya_account_id,
                "username": user.username,
            })

    return unified_response(
        code=200,
        message="获取成功",
        data={
            "isBound": is_bound,
            "fanyaCourseId": course.fanya_course_id if is_bound else None,
            "fanyaCourseName": course.fanya_course_name if is_bound else None,
            "boundStudentCount": len(bound_students),
            "boundStudents": bound_students[:20],
        },
    )


@router.delete("/unbind/{course_id}")
async def unbind_course(
    course_id: int,
    _access: CourseAccessContext = Depends(course_permission("course.edit")),
    session: Session = Depends(get_session),
):
    """解除课程的泛雅绑定"""
    stmt = select(Course).where(Course.id == course_id)
    course = session.exec(stmt).first()
    if not course:
        return unified_response(code=404, message="课程不存在", data=None)

    old_fanya_id = course.fanya_course_id
    course.fanya_course_id = f"local_{course_id}"
    course.fanya_course_name = course.title or "本地课程"
    course.updated_at = utcnow_naive()
    session.add(course)
    session.commit()

    return unified_response(
        code=200,
        message="解除绑定成功",
        data={
            "courseId": course_id,
            "previousFanyaId": old_fanya_id,
        },
    )


@router.get("/status")
async def platform_status():
    """检查泛雅平台连接状态"""
    fanya_configured = bool(
        settings.FANYA_APP_ID
        and settings.FANYA_SSO_VERIFY_URL
    )
    callback_configured = bool(settings.FANYA_CALLBACK_URL)

    return unified_response(
        code=200,
        message="ok",
        data={
            "fanyaConfigured": fanya_configured,
            "callbackConfigured": callback_configured,
            "ssoEnabled": fanya_configured,
            "appInfo": {
                "appId": settings.FANYA_APP_ID[:8] + "..." if settings.FANYA_APP_ID else None,
            } if settings.FANYA_APP_ID else None,
        },
    )
