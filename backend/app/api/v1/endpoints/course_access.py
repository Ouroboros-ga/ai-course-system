"""Course access and capability View Models used by the rebuilt frontend."""
from __future__ import annotations

import logging
import secrets
import string
from app.core.time_utils import utcnow_aware

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
)
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.user_model import User
from app.services.course_access_service import (
    ALL_PERMISSIONS,
    activate_student_membership,
    require_course_permission,
    serialize_access_context,
)

router = APIRouter()

# P3 §四.3：课程状态变更审计日志器
# 课程关闭/重开是重要的状态变更，需要可追溯。采用结构化日志记录，
# 字段：actor_user_id / course_id / action / previous_status / new_status / timestamp
audit_logger = logging.getLogger("course_access_audit")


def _generate_invite_code() -> str:
    """Generate a random 8-character uppercase alphanumeric invite code."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


class MembershipUpsertRequest(BaseModel):
    role: CourseRole
    status: MembershipStatus = MembershipStatus.ACTIVE
    permission_overrides: dict = Field(default_factory=dict)


class CapabilityUpdateRequest(BaseModel):
    learning: bool
    course_building: bool
    knowledge_graph: bool
    evidence: bool
    experiment: bool
    coding_sandbox: bool
    cognitive_analysis: bool
    safety_policy: bool


@router.get("/courses/{course_id}/access")
async def get_course_access(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "course.view")
    return unified_response(
        code=200,
        message="获取课程权限成功",
        data=serialize_access_context(context, ALL_PERMISSIONS),
    )


@router.get("/courses/{course_id}/capabilities")
async def get_course_capabilities(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "course.view")
    return unified_response(
        code=200,
        message="获取课程能力成功",
        data={
            "course_id": course_id,
            "course_role": context.role.value if context.role else None,
            "membership_status": context.membership_status.value if context.membership_status else None,
            "capabilities": context.capabilities,
            "allowed": {
                "course_building": context.allows("course.edit"),
                "knowledge_graph": context.allows("knowledge.view"),
                "experiment": context.allows("experiment.run"),
                "analytics": context.allows("analytics.view_course"),
            },
        },
    )


@router.get("/courses/{course_id}/members")
async def list_course_members(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "membership.view")
    memberships = session.exec(
        select(CourseMembership)
        .where(CourseMembership.course_id == course_id)
        .order_by(CourseMembership.role, CourseMembership.user_id)
    ).all()
    return unified_response(
        code=200,
        message="获取课程成员成功",
        data={
            "course_id": course_id,
            "members": [
                {
                    "user_id": item.user_id,
                    "role": item.role.value,
                    "status": item.status.value,
                    "analytics_excluded": item.analytics_excluded,
                    "joined_at": item.joined_at.isoformat() if item.joined_at else None,
                    "left_at": item.left_at.isoformat() if item.left_at else None,
                }
                for item in memberships
            ],
        },
    )


@router.put("/courses/{course_id}/members/{member_user_id}")
async def upsert_course_member(
    course_id: int,
    member_user_id: int,
    payload: MembershipUpsertRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "membership.role.change")
    target_user = session.get(User, member_user_id)
    if target_user is None or not target_user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target user is not active")
    if payload.role == CourseRole.OWNER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="课程所有者只能通过所有权转移流程变更")
    existing = session.exec(
        select(CourseMembership).where(
            CourseMembership.course_id == course_id,
            CourseMembership.user_id == member_user_id,
        )
    ).first()
    if existing is None:
        existing = CourseMembership(
            course_id=course_id,
            user_id=member_user_id,
            role=payload.role,
            status=payload.status,
            permission_overrides=payload.permission_overrides,
            analytics_excluded=payload.role != CourseRole.STUDENT,
        )
        session.add(existing)
    else:
        if existing.role == CourseRole.OWNER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不能通过成员接口修改课程所有者")
        existing.role = payload.role
        existing.status = payload.status
        existing.permission_overrides = payload.permission_overrides
        existing.analytics_excluded = payload.role != CourseRole.STUDENT
        existing.left_at = utcnow_aware() if payload.status in {MembershipStatus.REMOVED, MembershipStatus.WITHDRAWN} else None
        existing.updated_at = utcnow_aware()
        session.add(existing)
    session.commit()
    session.refresh(existing)
    return unified_response(
        code=200,
        message="保存课程成员成功",
        data={
            "course_id": course_id,
            "user_id": existing.user_id,
            "role": existing.role.value,
            "status": existing.status.value,
            "analytics_excluded": existing.analytics_excluded,
            "updated_by": context.user_id,
        },
    )


@router.put("/courses/{course_id}/capabilities")
async def update_course_capabilities(
    course_id: int,
    payload: CapabilityUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "permission.manage")
    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    values = payload.model_dump()
    if capability is None:
        capability = CourseCapability(course_id=course_id, **values)
    else:
        for name, value in values.items():
            setattr(capability, name, value)
        capability.updated_at = utcnow_aware()
    session.add(capability)
    session.commit()
    return unified_response(code=200, message="保存课程能力成功", data={"course_id": course_id, "capabilities": values})


# ---------------------------------------------------------------------------
# 批次1：邀请码入课与课程关闭语义
# ---------------------------------------------------------------------------


class InviteCodeRequest(BaseModel):
    invite_code: str | None = Field(default=None, min_length=4, max_length=32, description="自定义邀请码；不传则自动生成")


class JoinByCodeRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=32)


@router.post("/courses/{course_id}/invite-code")
async def set_invite_code(
    course_id: int,
    payload: InviteCodeRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师设置或更新课程邀请码（需要 membership.invite 权限）。"""
    require_course_permission(session, current_user, course_id, "membership.invite")
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
    if course.status != CourseStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="课程仍是草稿或未开放状态；发布后才能设置邀请码",
        )

    code = payload.invite_code or _generate_invite_code()
    # 确保邀请码全局唯一
    existing = session.exec(select(Course).where(Course.invite_code == code, Course.id != course_id)).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邀请码已被其他课程占用")
    course.invite_code = code
    course.updated_at = utcnow_aware()
    session.add(course)
    session.commit()
    return unified_response(code=200, message="邀请码已设置", data={"course_id": course_id, "invite_code": code})


@router.delete("/courses/{course_id}/invite-code")
async def clear_invite_code(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师清除邀请码，关闭邀请码入课通道。"""
    require_course_permission(session, current_user, course_id, "membership.invite")
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
    course.invite_code = None
    course.updated_at = utcnow_aware()
    session.add(course)
    session.commit()
    return unified_response(code=200, message="邀请码已清除", data={"course_id": course_id})


@router.post("/courses/join-by-code")
async def join_by_code(
    payload: JoinByCodeRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """通过邀请码加入课程。

    - 任何活跃平台用户（含管理员）可调用；管理员同样拥有学习课程的权限。
    - 课程必须为 PUBLISHED 状态（CLOSED/DRAFT/ARCHIVED 拒绝新加入）。
    - 邀请码必须匹配。
    - 重复加入返回 already_enrolled；退课后重新加入返回 reactivated。
    """
    user_id = int(current_user["user_id"])
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户不存在或已停用")

    course = session.exec(select(Course).where(Course.invite_code == payload.invite_code)).first()
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请码无效或课程不存在")
    if course.status != CourseStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"课程当前状态为 {course.status.value}，不接受新成员加入",
        )

    # 检查是否已加入
    existing = session.exec(
        select(StudentEnrollment).where(
            StudentEnrollment.student_id == user_id,
            StudentEnrollment.course_id == course.id,
        )
    ).first()

    activate_student_membership(session, course_id=course.id, student_user_id=user_id)

    if existing and existing.is_active:
        session.commit()
        return unified_response(code=200, message="已加入该课程", data={"course_id": course.id, "already_enrolled": True})
    elif existing and not existing.is_active:
        existing.is_active = True
        existing.enrolled_at = utcnow_aware()
        session.add(existing)
        session.commit()
        return unified_response(code=200, message="重新加入课程成功", data={"course_id": course.id, "reactivated": True})
    else:
        enrollment = StudentEnrollment(
            student_id=user_id,
            course_id=course.id,
            total_nodes_count=course.total_nodes,
        )
        session.add(enrollment)
        session.commit()
        return unified_response(code=200, message="加入课程成功", data={"course_id": course.id, "enrolled": True})


@router.post("/courses/{course_id}/close")
async def close_course(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师关闭课程：拒绝新成员加入，已加入成员可继续学习。"""
    require_course_permission(session, current_user, course_id, "course.publish")
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
    if course.status == CourseStatus.CLOSED:
        return unified_response(code=200, message="课程已处于关闭状态", data={"course_id": course_id, "status": "closed"})
    previous_status = course.status.value
    course.status = CourseStatus.CLOSED
    course.updated_at = utcnow_aware()
    session.add(course)
    session.commit()
    # P3 §四.3：课程关闭审计日志
    audit_logger.warning(
        "course_status_change actor_user_id=%s course_id=%s action=close previous_status=%s new_status=closed timestamp=%s",
        int(current_user["user_id"]),
        course_id,
        previous_status,
        utcnow_aware().isoformat(),
        extra={
            "actor_user_id": int(current_user["user_id"]),
            "course_id": course_id,
            "action": "close",
            "previous_status": previous_status,
            "new_status": "closed",
        },
    )
    return unified_response(code=200, message="课程已关闭，不再接受新成员", data={"course_id": course_id, "status": "closed"})


@router.post("/courses/{course_id}/reopen")
async def reopen_course(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师重新开放已关闭的课程。"""
    require_course_permission(session, current_user, course_id, "course.publish")
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")
    if course.status != CourseStatus.CLOSED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"课程当前状态为 {course.status.value}，仅 CLOSED 状态可重新开放")
    previous_status = course.status.value
    course.status = CourseStatus.PUBLISHED
    course.updated_at = utcnow_aware()
    session.add(course)
    session.commit()
    # P3 §四.3：课程重开审计日志
    audit_logger.warning(
        "course_status_change actor_user_id=%s course_id=%s action=reopen previous_status=%s new_status=published timestamp=%s",
        int(current_user["user_id"]),
        course_id,
        previous_status,
        utcnow_aware().isoformat(),
        extra={
            "actor_user_id": int(current_user["user_id"]),
            "course_id": course_id,
            "action": "reopen",
            "previous_status": previous_status,
            "new_status": "published",
        },
    )
    return unified_response(code=200, message="课程已重新开放", data={"course_id": course_id, "status": "published"})
