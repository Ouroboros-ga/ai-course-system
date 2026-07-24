"""Course access and capability View Models used by the rebuilt frontend."""
from __future__ import annotations

from datetime import datetime

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
from app.models.user_model import User
from app.services.course_access_service import (
    ALL_PERMISSIONS,
    require_course_permission,
    serialize_access_context,
)

router = APIRouter()


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
        existing.left_at = datetime.utcnow() if payload.status in {MembershipStatus.REMOVED, MembershipStatus.WITHDRAWN} else None
        existing.updated_at = datetime.utcnow()
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
        capability.updated_at = datetime.utcnow()
    session.add(capability)
    session.commit()
    return unified_response(code=200, message="保存课程能力成功", data={"course_id": course_id, "capabilities": values})
