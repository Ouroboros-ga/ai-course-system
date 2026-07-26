"""阶段2 成员、设置、加入申请与课程生命周期 API 路由。

路由前缀：
- /api/v1/course-access/courses/{course_id}/join-requests     加入申请
- /api/v1/course-groups/course/{course_id}/groups             课程分组
- /api/v1/course-settings/course/{course_id}/...              课程设置
- /api/v1/integrations/fanya/course/{course_id}/sync          泛雅同步

每个课程接口使用 Course Access v1 校验权限，不依赖 User.role。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.access_control_model import CourseMembership, MembershipStatus
from app.models.course_lifecycle_model import (
    AuditEventType,
    CourseAuditEvent,
    CourseGroup,
    CourseGroupMember,
    CourseJoinRequest,
    CourseSettingVersion,
    IntegrationSyncRun,
    JoinChannel,
    JoinRequestStatus,
    SyncRunStatus,
)
from app.models.course_model import Course
from app.models.database import get_session
from app.models.user_model import User
from app.services.course_access_service import require_course_permission
from app.services.course_lifecycle_service import (
    course_audit_service,
    course_group_service,
    course_settings_service,
    fanya_sync_service,
    join_request_service,
)


# ---------------------------------------------------------------------------
# 加入申请路由
# ---------------------------------------------------------------------------


join_requests_router = APIRouter()


class JoinRequestCreateRequest(BaseModel):
    apply_reason: str = Field(default="", max_length=500)
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=90)


class JoinRequestReviewRequest(BaseModel):
    review_comment: str = Field(default="", max_length=500)


class JoinRequestSupplementRequest(BaseModel):
    supplement_info: str = Field(default="", max_length=500)


@join_requests_router.post("/courses/{course_id}/join-requests")
async def create_join_request(
    course_id: int,
    payload: JoinRequestCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生提交加入课程申请。"""
    user_id = int(current_user["user_id"])
    req = join_request_service.create_request(
        session,
        course_id=course_id,
        applicant_user_id=user_id,
        apply_reason=payload.apply_reason,
        expires_in_days=payload.expires_in_days,
    )
    session.commit()
    return unified_response(
        code=201,
        message="加入申请已提交",
        data=_serialize_join_request(req),
    )


@join_requests_router.get("/courses/{course_id}/join-requests")
async def list_join_requests(
    course_id: int,
    status: Optional[str] = Query(None, description="按状态过滤：pending/approved/rejected/info_requested"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师查看课程的加入申请列表。"""
    require_course_permission(session, current_user, course_id, "membership.view")
    status_filter = JoinRequestStatus(status) if status else None
    items = join_request_service.list_requests(
        session, course_id=course_id, status_filter=status_filter
    )
    return unified_response(
        code=200,
        message="获取加入申请列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_join_request(r) for r in items],
            "total": len(items),
        },
    )


@join_requests_router.post("/courses/{course_id}/join-requests/{request_id}/approve")
async def approve_join_request(
    course_id: int,
    request_id: str,
    payload: JoinRequestReviewRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师通过加入申请：激活学生 membership。"""
    context = require_course_permission(session, current_user, course_id, "membership.role.change")
    req = join_request_service.approve(
        session,
        course_id=course_id,
        request_id=request_id,
        reviewer_user_id=context.user_id,
        review_comment=payload.review_comment,
    )
    session.commit()
    return unified_response(code=200, message="加入申请已通过", data=_serialize_join_request(req))


@join_requests_router.post("/courses/{course_id}/join-requests/{request_id}/reject")
async def reject_join_request(
    course_id: int,
    request_id: str,
    payload: JoinRequestReviewRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师拒绝加入申请。"""
    context = require_course_permission(session, current_user, course_id, "membership.role.change")
    req = join_request_service.reject(
        session,
        course_id=course_id,
        request_id=request_id,
        reviewer_user_id=context.user_id,
        review_comment=payload.review_comment,
    )
    session.commit()
    return unified_response(code=200, message="加入申请已拒绝", data=_serialize_join_request(req))


@join_requests_router.post("/courses/{course_id}/join-requests/{request_id}/request-info")
async def request_info_join_request(
    course_id: int,
    request_id: str,
    payload: JoinRequestReviewRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师请求学生补充信息。"""
    context = require_course_permission(session, current_user, course_id, "membership.role.change")
    req = join_request_service.request_info(
        session,
        course_id=course_id,
        request_id=request_id,
        reviewer_user_id=context.user_id,
        review_comment=payload.review_comment,
    )
    session.commit()
    return unified_response(code=200, message="已请求补充信息", data=_serialize_join_request(req))


@join_requests_router.post("/courses/{course_id}/join-requests/{request_id}/supplement")
async def supplement_join_request(
    course_id: int,
    request_id: str,
    payload: JoinRequestSupplementRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生补充信息后重新提交。"""
    user_id = int(current_user["user_id"])
    req = join_request_service.supplement_info(
        session,
        course_id=course_id,
        request_id=request_id,
        applicant_user_id=user_id,
        supplement_info=payload.supplement_info,
    )
    session.commit()
    return unified_response(code=200, message="已补充信息并重新提交", data=_serialize_join_request(req))


@join_requests_router.post("/courses/{course_id}/join-requests/{request_id}/cancel")
async def cancel_join_request(
    course_id: int,
    request_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生撤销自己的加入申请。"""
    user_id = int(current_user["user_id"])
    req = join_request_service.cancel(
        session,
        course_id=course_id,
        request_id=request_id,
        applicant_user_id=user_id,
    )
    session.commit()
    return unified_response(code=200, message="加入申请已撤销", data=_serialize_join_request(req))


def _serialize_join_request(req: CourseJoinRequest) -> dict:
    return {
        "request_id": req.request_id,
        "course_id": req.course_id,
        "applicant_user_id": req.applicant_user_id,
        "apply_reason": req.apply_reason,
        "supplement_info": req.supplement_info,
        "channel": req.channel.value,
        "status": req.status.value,
        "reviewer_user_id": req.reviewer_user_id,
        "review_comment": req.review_comment,
        "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
    }


# ---------------------------------------------------------------------------
# 课程分组路由
# ---------------------------------------------------------------------------


course_groups_router = APIRouter()


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    group_type: str = Field(default="study")


class GroupUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=500)
    group_type: Optional[str] = None


class GroupMemberAddRequest(BaseModel):
    user_id: int


@course_groups_router.get("/course/{course_id}/groups")
async def list_groups(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程的所有分组。"""
    require_course_permission(session, current_user, course_id, "course.view")
    groups = course_group_service.list_groups(session, course_id=course_id)
    return unified_response(
        code=200,
        message="获取课程分组列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_group(g) for g in groups],
            "total": len(groups),
        },
    )


@course_groups_router.post("/course/{course_id}/groups")
async def create_group(
    course_id: int,
    payload: GroupCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建课程分组。"""
    context = require_course_permission(session, current_user, course_id, "membership.invite")
    g = course_group_service.create_group(
        session,
        course_id=course_id,
        name=payload.name,
        description=payload.description,
        group_type=payload.group_type,
        created_by=context.user_id,
    )
    session.commit()
    return unified_response(code=201, message="分组已创建", data=_serialize_group(g))


@course_groups_router.put("/course/{course_id}/groups/{group_id}")
async def update_group(
    course_id: int,
    group_id: str,
    payload: GroupUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新分组信息。"""
    require_course_permission(session, current_user, course_id, "membership.invite")
    g = course_group_service.update_group(
        session,
        course_id=course_id,
        group_id=group_id,
        name=payload.name,
        description=payload.description,
        group_type=payload.group_type,
    )
    session.commit()
    return unified_response(code=200, message="分组已更新", data=_serialize_group(g))


@course_groups_router.delete("/course/{course_id}/groups/{group_id}")
async def delete_group(
    course_id: int,
    group_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """删除分组：仅解除成员关联，不删除成员本身。"""
    require_course_permission(session, current_user, course_id, "membership.invite")
    course_group_service.delete_group(session, course_id=course_id, group_id=group_id)
    session.commit()
    return unified_response(code=200, message="分组已删除", data={"course_id": course_id, "group_id": group_id})


@course_groups_router.get("/course/{course_id}/groups/{group_id}/members")
async def list_group_members(
    course_id: int,
    group_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出分组的成员。"""
    require_course_permission(session, current_user, course_id, "course.view")
    members = course_group_service.list_members(session, course_id=course_id, group_id=group_id)
    return unified_response(
        code=200,
        message="获取分组成员列表成功",
        data={
            "course_id": course_id,
            "group_id": group_id,
            "items": [_serialize_group_member(m) for m in members],
            "total": len(members),
        },
    )


@course_groups_router.post("/course/{course_id}/groups/{group_id}/members")
async def add_group_member(
    course_id: int,
    group_id: str,
    payload: GroupMemberAddRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """添加成员到分组。"""
    context = require_course_permission(session, current_user, course_id, "membership.invite")
    m = course_group_service.add_member(
        session,
        course_id=course_id,
        group_id=group_id,
        user_id=payload.user_id,
        added_by=context.user_id,
    )
    session.commit()
    return unified_response(code=201, message="成员已添加到分组", data=_serialize_group_member(m))


@course_groups_router.delete("/course/{course_id}/groups/{group_id}/members/{user_id}")
async def remove_group_member(
    course_id: int,
    group_id: str,
    user_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """从分组移除成员。"""
    require_course_permission(session, current_user, course_id, "membership.invite")
    course_group_service.remove_member(
        session, course_id=course_id, group_id=group_id, user_id=user_id,
    )
    session.commit()
    return unified_response(
        code=200,
        message="成员已从分组移除",
        data={"course_id": course_id, "group_id": group_id, "user_id": user_id},
    )


def _serialize_group(g: CourseGroup) -> dict:
    return {
        "group_id": g.group_id,
        "course_id": g.course_id,
        "name": g.name,
        "description": g.description,
        "group_type": g.group_type,
        "created_by": g.created_by,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
    }


def _serialize_group_member(m: CourseGroupMember) -> dict:
    return {
        "group_id": m.group_id,
        "course_id": m.course_id,
        "user_id": m.user_id,
        "added_by": m.added_by,
        "added_at": m.added_at.isoformat() if m.added_at else None,
    }


# ---------------------------------------------------------------------------
# 课程设置路由
# ---------------------------------------------------------------------------


course_settings_router = APIRouter()


class SectionUpdateRequest(BaseModel):
    patch: dict = Field(default_factory=dict, description="待合并到当前 section 的字段")
    expected_version: Optional[int] = Field(default=None, description="乐观锁：当前版本号")


class RollbackRequest(BaseModel):
    target_version: int = Field(ge=1)


@course_settings_router.get("/course/{course_id}/settings")
async def get_course_settings(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取课程当前设置（聚合读模型）。"""
    require_course_permission(session, current_user, course_id, "course.view")
    current = course_settings_service.get_current(session, course_id=course_id)
    if current is None:
        # 初始化默认空设置
        return unified_response(
            code=200,
            message="获取课程设置成功",
            data={
                "course_id": course_id,
                "version": None,
                "setting_version_id": None,
                "profile": {},
                "publish": {},
                "agent_policy": {},
                "safety": {},
                "sandbox": {},
                "integration": {},
            },
        )
    return unified_response(
        code=200,
        message="获取课程设置成功",
        data=_serialize_setting(current),
    )


@course_settings_router.get("/course/{course_id}/settings/versions")
async def list_setting_versions(
    course_id: int,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程设置的历史版本。"""
    require_course_permission(session, current_user, course_id, "course.view")
    versions = course_settings_service.list_versions(session, course_id=course_id, limit=limit)
    return unified_response(
        code=200,
        message="获取课程设置版本列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_setting(v) for v in versions],
            "total": len(versions),
        },
    )


@course_settings_router.put("/course/{course_id}/profile")
async def update_profile(
    course_id: int,
    payload: SectionUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新课程基础信息（profile）。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    v = course_settings_service.update_section(
        session,
        course_id=course_id,
        section="profile",
        patch=payload.patch,
        actor_user_id=context.user_id,
        expected_version=payload.expected_version,
    )
    session.commit()
    return unified_response(code=200, message="课程基础信息已更新", data=_serialize_setting(v))


@course_settings_router.put("/course/{course_id}/publish")
async def update_publish(
    course_id: int,
    payload: SectionUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新课程加入与发布设置。"""
    context = require_course_permission(session, current_user, course_id, "course.publish")
    v = course_settings_service.update_section(
        session,
        course_id=course_id,
        section="publish",
        patch=payload.patch,
        actor_user_id=context.user_id,
        expected_version=payload.expected_version,
    )
    session.commit()
    return unified_response(code=200, message="加入与发布设置已更新", data=_serialize_setting(v))


@course_settings_router.put("/course/{course_id}/agent-policy")
async def update_agent_policy(
    course_id: int,
    payload: SectionUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新课程智能体策略。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    v = course_settings_service.update_section(
        session,
        course_id=course_id,
        section="agent_policy",
        patch=payload.patch,
        actor_user_id=context.user_id,
        expected_version=payload.expected_version,
    )
    session.commit()
    return unified_response(code=200, message="智能体策略已更新", data=_serialize_setting(v))


@course_settings_router.put("/course/{course_id}/safety")
async def update_safety(
    course_id: int,
    payload: SectionUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新课程安全与合规策略。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    v = course_settings_service.update_section(
        session,
        course_id=course_id,
        section="safety",
        patch=payload.patch,
        actor_user_id=context.user_id,
        expected_version=payload.expected_version,
    )
    session.commit()
    return unified_response(code=200, message="安全与合规策略已更新", data=_serialize_setting(v))


@course_settings_router.put("/course/{course_id}/sandbox")
async def update_sandbox(
    course_id: int,
    payload: SectionUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新课程沙箱权限策略。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    v = course_settings_service.update_section(
        session,
        course_id=course_id,
        section="sandbox",
        patch=payload.patch,
        actor_user_id=context.user_id,
        expected_version=payload.expected_version,
    )
    session.commit()
    return unified_response(code=200, message="沙箱权限策略已更新", data=_serialize_setting(v))


@course_settings_router.put("/course/{course_id}/integration")
async def update_integration(
    course_id: int,
    payload: SectionUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新课程平台集成设置。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    v = course_settings_service.update_section(
        session,
        course_id=course_id,
        section="integration",
        patch=payload.patch,
        actor_user_id=context.user_id,
        expected_version=payload.expected_version,
    )
    session.commit()
    return unified_response(code=200, message="平台集成设置已更新", data=_serialize_setting(v))


@course_settings_router.post("/course/{course_id}/settings/rollback")
async def rollback_settings(
    course_id: int,
    payload: RollbackRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """回滚课程设置到指定版本（生成新版本，不破坏历史）。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    v = course_settings_service.rollback(
        session,
        course_id=course_id,
        target_version=payload.target_version,
        actor_user_id=context.user_id,
    )
    session.commit()
    return unified_response(code=200, message="设置已回滚", data=_serialize_setting(v))


def _serialize_setting(v: CourseSettingVersion) -> dict:
    return {
        "course_id": v.course_id,
        "setting_version_id": v.setting_version_id,
        "version": v.version,
        "is_current": v.is_current,
        "prev_version_id": v.prev_version_id,
        "profile": v.profile,
        "publish": v.publish,
        "agent_policy": v.agent_policy,
        "safety": v.safety,
        "sandbox": v.sandbox,
        "integration": v.integration,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


# ---------------------------------------------------------------------------
# 泛雅同步路由
# ---------------------------------------------------------------------------


integrations_router = APIRouter()


class SyncCreateRequest(BaseModel):
    source_course_id: Optional[str] = None


class SyncPreviewRequest(BaseModel):
    added: list[dict] = Field(default_factory=list)
    removed: list[dict] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    summary: Optional[dict] = None


@integrations_router.post("/fanya/course/{course_id}/sync")
async def create_fanya_sync(
    course_id: int,
    payload: SyncCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建一次泛雅同步运行（进入预览阶段，不修改成员关系）。"""
    context = require_course_permission(session, current_user, course_id, "membership.invite")
    run = fanya_sync_service.create_sync_run(
        session,
        course_id=course_id,
        initiated_by=context.user_id,
        source_course_id=payload.source_course_id,
    )
    session.commit()
    return unified_response(code=201, message="同步运行已创建（预览阶段）", data=_serialize_sync_run(run))


@integrations_router.put("/fanya/course/{course_id}/sync/{sync_run_id}/preview")
async def save_sync_preview(
    course_id: int,
    sync_run_id: str,
    payload: SyncPreviewRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """保存同步差异预览。"""
    require_course_permission(session, current_user, course_id, "membership.invite")
    run = fanya_sync_service.save_preview(
        session,
        course_id=course_id,
        sync_run_id=sync_run_id,
        added=payload.added,
        removed=payload.removed,
        conflicts=payload.conflicts,
        summary=payload.summary,
    )
    session.commit()
    return unified_response(code=200, message="预览差异已保存", data=_serialize_sync_run(run))


@integrations_router.post("/fanya/course/{course_id}/sync/{sync_run_id}/confirm")
async def confirm_sync(
    course_id: int,
    sync_run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师确认执行同步：依据预览差异修改本地成员关系。"""
    context = require_course_permission(session, current_user, course_id, "membership.invite")
    run = fanya_sync_service.confirm_apply(
        session,
        course_id=course_id,
        sync_run_id=sync_run_id,
        confirmed_by=context.user_id,
    )
    session.commit()
    return unified_response(code=200, message="同步已完成", data=_serialize_sync_run(run))


@integrations_router.get("/fanya/course/{course_id}/sync/runs")
async def list_sync_runs(
    course_id: int,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程的同步运行记录。"""
    require_course_permission(session, current_user, course_id, "membership.view")
    runs = fanya_sync_service.list_runs(session, course_id=course_id, limit=limit)
    return unified_response(
        code=200,
        message="获取同步运行列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_sync_run(r) for r in runs],
            "total": len(runs),
        },
    )


def _serialize_sync_run(run: IntegrationSyncRun) -> dict:
    return {
        "sync_run_id": run.sync_run_id,
        "course_id": run.course_id,
        "integration": run.integration,
        "source_course_id": run.source_course_id,
        "task_id": run.task_id,
        "status": run.status.value,
        "preview_summary": run.preview_summary,
        "preview_added": run.preview_added,
        "preview_removed": run.preview_removed,
        "preview_conflicts": run.preview_conflicts,
        "applied_added": run.applied_added,
        "applied_removed": run.applied_removed,
        "applied_skipped": run.applied_skipped,
        "error_message": run.error_message,
        "initiated_by": run.initiated_by,
        "confirmed_by": run.confirmed_by,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "confirmed_at": run.confirmed_at.isoformat() if run.confirmed_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


# ---------------------------------------------------------------------------
# 审计事件路由
# ---------------------------------------------------------------------------


audit_router = APIRouter()


@audit_router.get("/course/{course_id}/audit-events")
async def list_audit_events(
    course_id: int,
    event_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程审计事件。"""
    require_course_permission(session, current_user, course_id, "course.view")
    et = AuditEventType(event_type) if event_type else None
    events = course_audit_service.list_events(
        session, course_id=course_id, event_type=et, limit=limit,
    )
    return unified_response(
        code=200,
        message="获取审计事件列表成功",
        data={
            "course_id": course_id,
            "items": [
                {
                    "audit_id": e.audit_id,
                    "course_id": e.course_id,
                    "event_type": e.event_type.value,
                    "actor_user_id": e.actor_user_id,
                    "target_user_id": e.target_user_id,
                    "target_resource_id": e.target_resource_id,
                    "before": e.before,
                    "after": e.after,
                    "note": e.note,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
            "total": len(events),
        },
    )
