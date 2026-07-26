"""阶段2 成员、设置、加入申请与课程生命周期服务。

每个服务接收 Session（事务边界由路由层管理），不自行创建独立 session。
所有写入都通过 CourseAccessContext 校验权限，不依赖 User.role。
设置更新生成新版本；状态/角色变更写入审计事件。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.exceptions import (
    reject,
    reject_course_access_denied,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
    reject_version_conflict,
)
from app.core.time_utils import utcnow_naive
from app.models.access_control_model import (
    CourseMembership,
    CourseRole,
    MembershipStatus,
)
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
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    CourseAccessContext,
    activate_student_membership,
    require_course_permission,
)


# ---------------------------------------------------------------------------
# 加入申请状态机
# ---------------------------------------------------------------------------


_JOIN_TRANSITIONS: dict[JoinRequestStatus, set[JoinRequestStatus]] = {
    JoinRequestStatus.PENDING: {
        JoinRequestStatus.APPROVED,
        JoinRequestStatus.REJECTED,
        JoinRequestStatus.INFO_REQUESTED,
        JoinRequestStatus.CANCELLED,
        JoinRequestStatus.EXPIRED,
    },
    JoinRequestStatus.INFO_REQUESTED: {
        JoinRequestStatus.PENDING,    # 学生补充后重新提交
        JoinRequestStatus.REJECTED,
        JoinRequestStatus.CANCELLED,
        JoinRequestStatus.EXPIRED,
    },
    # 终态不可再转移
    JoinRequestStatus.APPROVED: set(),
    JoinRequestStatus.REJECTED: set(),
    JoinRequestStatus.CANCELLED: set(),
    JoinRequestStatus.EXPIRED: set(),
}


def _assert_join_transition(current: JoinRequestStatus, target: JoinRequestStatus) -> None:
    if target not in _JOIN_TRANSITIONS.get(current, set()):
        reject_state_conflict(
            f"加入申请状态 {current.value} 不能转移到 {target.value}",
            details={"current_status": current.value, "target_status": target.value},
        )


class JoinRequestService:
    """课程加入申请服务

    - 学生提交申请 -> status=pending
    - 教师审批 -> approved 时调用 activate_student_membership 激活成员关系
    - info_requested 后学生可补充说明重新提交 -> status=pending
    - 申请审批幂等：approved 终态不可重复审批
    """

    DEFAULT_EXPIRE_DAYS = 14

    def create_request(
        self,
        session: Session,
        *,
        course_id: int,
        applicant_user_id: int,
        apply_reason: str = "",
        channel: JoinChannel = JoinChannel.JOIN_REQUEST,
        expires_in_days: Optional[int] = None,
    ) -> CourseJoinRequest:
        """学生提交加入申请。

        - 课程必须为 PUBLISHED 状态
        - 学生未已经是成员（active membership）
        - 已有 pending/info_requested 申请时不重复创建，返回原申请
        """
        course = session.get(Course, course_id)
        if course is None:
            reject_resource_not_found("课程不存在")
        if course.status != CourseStatus.PUBLISHED:
            reject_validation_failed(
                f"课程当前状态为 {course.status.value}，不接受加入申请",
                details={"course_status": course.status.value},
            )

        # 已是 active 成员 -> 直接返回 already_enrolled
        existing_membership = session.exec(
            select(CourseMembership).where(
                CourseMembership.course_id == course_id,
                CourseMembership.user_id == applicant_user_id,
                CourseMembership.status == MembershipStatus.ACTIVE,
            )
        ).first()
        if existing_membership is not None:
            reject_state_conflict("已是课程成员，无需重复申请")

        # 已有 pending / info_requested 申请 -> 返回原申请
        existing_req = session.exec(
            select(CourseJoinRequest).where(
                CourseJoinRequest.course_id == course_id,
                CourseJoinRequest.applicant_user_id == applicant_user_id,
                CourseJoinRequest.status.in_([
                    JoinRequestStatus.PENDING,
                    JoinRequestStatus.INFO_REQUESTED,
                ]),
            )
        ).first()
        if existing_req is not None:
            return existing_req

        days = expires_in_days if expires_in_days is not None else self.DEFAULT_EXPIRE_DAYS
        expires_at = utcnow_naive() + timedelta(days=days) if days > 0 else None

        req = CourseJoinRequest(
            course_id=course_id,
            applicant_user_id=applicant_user_id,
            apply_reason=apply_reason,
            channel=channel,
            status=JoinRequestStatus.PENDING,
            expires_at=expires_at,
        )
        session.add(req)
        session.flush()
        return req

    def list_requests(
        self,
        session: Session,
        *,
        course_id: int,
        status_filter: Optional[JoinRequestStatus] = None,
    ) -> list[CourseJoinRequest]:
        """教师查看课程的所有加入申请。"""
        stmt = select(CourseJoinRequest).where(
            CourseJoinRequest.course_id == course_id
        ).order_by(CourseJoinRequest.created_at.desc())
        if status_filter is not None:
            stmt = stmt.where(CourseJoinRequest.status == status_filter)
        return list(session.exec(stmt).all())

    def get_request(
        self,
        session: Session,
        *,
        course_id: int,
        request_id: str,
    ) -> CourseJoinRequest:
        req = session.exec(
            select(CourseJoinRequest).where(
                CourseJoinRequest.course_id == course_id,
                CourseJoinRequest.request_id == request_id,
            )
        ).first()
        if req is None:
            reject_resource_not_found("加入申请不存在")
        return req

    def approve(
        self,
        session: Session,
        *,
        course_id: int,
        request_id: str,
        reviewer_user_id: int,
        review_comment: str = "",
    ) -> CourseJoinRequest:
        """教师通过申请：激活学生 membership + 写审计事件。"""
        req = self.get_request(session, course_id=course_id, request_id=request_id)
        _assert_join_transition(req.status, JoinRequestStatus.APPROVED)

        # 激活 membership（同时建立 StudentEnrollment，由 activate_student_membership 负责）
        activate_student_membership(
            session,
            course_id=course_id,
            student_user_id=req.applicant_user_id,
        )
        # 补充 StudentEnrollment 记录（如果尚未存在）
        existing_enr = session.exec(
            select(StudentEnrollment).where(
                StudentEnrollment.student_id == req.applicant_user_id,
                StudentEnrollment.course_id == course_id,
            )
        ).first()
        if existing_enr is None:
            course = session.get(Course, course_id)
            enr = StudentEnrollment(
                student_id=req.applicant_user_id,
                course_id=course_id,
                total_nodes_count=course.total_nodes if course else 0,
            )
            session.add(enr)

        req.status = JoinRequestStatus.APPROVED
        req.reviewer_user_id = reviewer_user_id
        req.review_comment = review_comment
        req.reviewed_at = utcnow_naive()
        req.updated_at = utcnow_naive()
        session.add(req)

        audit = CourseAuditEvent(
            course_id=course_id,
            event_type=AuditEventType.JOIN_REQUEST_APPROVE,
            actor_user_id=reviewer_user_id,
            target_user_id=req.applicant_user_id,
            target_resource_id=req.request_id,
            after={"status": JoinRequestStatus.APPROVED.value, "comment": review_comment},
        )
        session.add(audit)
        session.flush()
        return req

    def reject(
        self,
        session: Session,
        *,
        course_id: int,
        request_id: str,
        reviewer_user_id: int,
        review_comment: str = "",
    ) -> CourseJoinRequest:
        req = self.get_request(session, course_id=course_id, request_id=request_id)
        _assert_join_transition(req.status, JoinRequestStatus.REJECTED)
        req.status = JoinRequestStatus.REJECTED
        req.reviewer_user_id = reviewer_user_id
        req.review_comment = review_comment
        req.reviewed_at = utcnow_naive()
        req.updated_at = utcnow_naive()
        session.add(req)

        audit = CourseAuditEvent(
            course_id=course_id,
            event_type=AuditEventType.JOIN_REQUEST_REJECT,
            actor_user_id=reviewer_user_id,
            target_user_id=req.applicant_user_id,
            target_resource_id=req.request_id,
            after={"status": JoinRequestStatus.REJECTED.value, "comment": review_comment},
        )
        session.add(audit)
        session.flush()
        return req

    def request_info(
        self,
        session: Session,
        *,
        course_id: int,
        request_id: str,
        reviewer_user_id: int,
        review_comment: str = "",
    ) -> CourseJoinRequest:
        """教师请求学生补充信息：status pending → info_requested。"""
        req = self.get_request(session, course_id=course_id, request_id=request_id)
        _assert_join_transition(req.status, JoinRequestStatus.INFO_REQUESTED)
        req.status = JoinRequestStatus.INFO_REQUESTED
        req.reviewer_user_id = reviewer_user_id
        req.review_comment = review_comment
        req.reviewed_at = utcnow_naive()
        req.updated_at = utcnow_naive()
        session.add(req)
        session.flush()
        return req

    def supplement_info(
        self,
        session: Session,
        *,
        course_id: int,
        request_id: str,
        applicant_user_id: int,
        supplement_info: str,
    ) -> CourseJoinRequest:
        """学生补充信息后重新提交：info_requested → pending。"""
        req = self.get_request(session, course_id=course_id, request_id=request_id)
        if req.applicant_user_id != applicant_user_id:
            reject_course_access_denied("只能为自己的申请补充信息")
        _assert_join_transition(req.status, JoinRequestStatus.PENDING)
        req.status = JoinRequestStatus.PENDING
        req.supplement_info = supplement_info
        req.updated_at = utcnow_naive()
        session.add(req)
        session.flush()
        return req

    def cancel(
        self,
        session: Session,
        *,
        course_id: int,
        request_id: str,
        applicant_user_id: int,
    ) -> CourseJoinRequest:
        """学生撤销自己的申请。"""
        req = self.get_request(session, course_id=course_id, request_id=request_id)
        if req.applicant_user_id != applicant_user_id:
            reject_course_access_denied("只能撤销自己的申请")
        _assert_join_transition(req.status, JoinRequestStatus.CANCELLED)
        req.status = JoinRequestStatus.CANCELLED
        req.updated_at = utcnow_naive()
        session.add(req)
        session.flush()
        return req


join_request_service = JoinRequestService()


# ---------------------------------------------------------------------------
# 课程分组
# ---------------------------------------------------------------------------


class CourseGroupService:
    """课程分组服务（班级/小组/实验分组）

    - 分组不能改变课程角色
    - 删除分组不删除成员（仅解除 CourseGroupMember 关联）
    - 一个学生可属于多个分组
    """

    def list_groups(self, session: Session, *, course_id: int) -> list[CourseGroup]:
        return list(session.exec(
            select(CourseGroup).where(CourseGroup.course_id == course_id).order_by(CourseGroup.created_at)
        ).all())

    def get_group(self, session: Session, *, course_id: int, group_id: str) -> CourseGroup:
        g = session.exec(
            select(CourseGroup).where(
                CourseGroup.course_id == course_id,
                CourseGroup.group_id == group_id,
            )
        ).first()
        if g is None:
            reject_resource_not_found("分组不存在")
        return g

    def create_group(
        self,
        session: Session,
        *,
        course_id: int,
        name: str,
        description: str = "",
        group_type: str = "study",
        created_by: Optional[int] = None,
    ) -> CourseGroup:
        if not name.strip():
            reject_validation_failed("分组名称不能为空")
        g = CourseGroup(
            course_id=course_id,
            name=name.strip(),
            description=description,
            group_type=group_type,
            created_by=created_by,
        )
        session.add(g)
        session.flush()
        return g

    def update_group(
        self,
        session: Session,
        *,
        course_id: int,
        group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        group_type: Optional[str] = None,
    ) -> CourseGroup:
        g = self.get_group(session, course_id=course_id, group_id=group_id)
        if name is not None:
            if not name.strip():
                reject_validation_failed("分组名称不能为空")
            g.name = name.strip()
        if description is not None:
            g.description = description
        if group_type is not None:
            g.group_type = group_type
        g.updated_at = utcnow_naive()
        session.add(g)
        session.flush()
        return g

    def delete_group(self, session: Session, *, course_id: int, group_id: str) -> None:
        """删除分组：仅解除成员关联，不删除成员本身。"""
        g = self.get_group(session, course_id=course_id, group_id=group_id)
        # 先解除成员关联
        members = session.exec(
            select(CourseGroupMember).where(CourseGroupMember.group_id == group_id)
        ).all()
        for m in members:
            session.delete(m)
        session.delete(g)
        session.flush()

    def list_members(
        self,
        session: Session,
        *,
        course_id: int,
        group_id: str,
    ) -> list[CourseGroupMember]:
        # 校验分组属于该课程
        self.get_group(session, course_id=course_id, group_id=group_id)
        return list(session.exec(
            select(CourseGroupMember).where(
                CourseGroupMember.group_id == group_id,
                CourseGroupMember.course_id == course_id,
            ).order_by(CourseGroupMember.added_at)
        ).all())

    def add_member(
        self,
        session: Session,
        *,
        course_id: int,
        group_id: str,
        user_id: int,
        added_by: Optional[int] = None,
    ) -> CourseGroupMember:
        # 校验分组属于该课程
        self.get_group(session, course_id=course_id, group_id=group_id)
        # 校验用户是该课程成员
        membership = session.exec(
            select(CourseMembership).where(
                CourseMembership.course_id == course_id,
                CourseMembership.user_id == user_id,
                CourseMembership.status == MembershipStatus.ACTIVE,
            )
        ).first()
        if membership is None:
            reject_validation_failed("用户不是该课程的活跃成员")
        existing = session.exec(
            select(CourseGroupMember).where(
                CourseGroupMember.group_id == group_id,
                CourseGroupMember.user_id == user_id,
            )
        ).first()
        if existing is not None:
            return existing
        m = CourseGroupMember(
            group_id=group_id,
            course_id=course_id,
            user_id=user_id,
            added_by=added_by,
        )
        session.add(m)
        session.flush()
        return m

    def remove_member(
        self,
        session: Session,
        *,
        course_id: int,
        group_id: str,
        user_id: int,
    ) -> None:
        m = session.exec(
            select(CourseGroupMember).where(
                CourseGroupMember.group_id == group_id,
                CourseGroupMember.course_id == course_id,
                CourseGroupMember.user_id == user_id,
            )
        ).first()
        if m is None:
            reject_resource_not_found("分组中不存在该成员")
        session.delete(m)
        session.flush()


course_group_service = CourseGroupService()


# ---------------------------------------------------------------------------
# 课程设置版本化
# ---------------------------------------------------------------------------


# 受控字段白名单：教师只能修改这些字段；不允许通过 settings 接口绕过权限。
_PROFILE_FIELDS = {"title", "description", "cover_url", "subject", "term", "language"}
_PUBLISH_FIELDS = {
    "hall_visible", "join_mode", "invite_code", "require_review",
    "start_at", "end_at", "notify_on_publish", "allow_withdraw", "allow_chapter_jump",
}
_AGENT_POLICY_FIELDS = {
    "agent_name", "answer_scope", "require_citation", "no_evidence_behavior",
    "allowed_actions", "hint_strategy", "teacher_instructions", "experimental_enabled",
}
_SAFETY_FIELDS = {
    "preset", "blocked_topics", "must_cite_topics", "course_whitelist",
    "high_risk_confirm", "keyword_rules", "dry_run", "enabled",
}
_SANDBOX_FIELDS = {
    "preset", "languages", "network_mode", "file_mode",
    "package_whitelist", "cpu", "memory", "timeout_seconds",
}
_INTEGRATION_FIELDS = {"fanya_enabled", "fanya_source_course_id", "auto_sync"}


def _filter_fields(data: dict, allowed: set[str]) -> dict:
    return {k: v for k, v in data.items() if k in allowed}


class CourseSettingsService:
    """课程设置版本化服务

    - 每次保存生成新版本，旧版本标记 is_current=False
    - 支持版本冲突检测：传入 expected_version 与当前 current 版本对比
    - 受控字段白名单：不接受未在白名单内的字段
    - 所有变更写入审计事件
    """

    SETTING_SECTIONS = ("profile", "publish", "agent_policy", "safety", "sandbox", "integration")

    def get_current(self, session: Session, *, course_id: int) -> Optional[CourseSettingVersion]:
        return session.exec(
            select(CourseSettingVersion).where(
                CourseSettingVersion.course_id == course_id,
                CourseSettingVersion.is_current == True,  # noqa: E712
            ).order_by(CourseSettingVersion.version.desc())
        ).first()

    def list_versions(
        self,
        session: Session,
        *,
        course_id: int,
        limit: int = 20,
    ) -> list[CourseSettingVersion]:
        return list(session.exec(
            select(CourseSettingVersion).where(
                CourseSettingVersion.course_id == course_id,
            ).order_by(CourseSettingVersion.version.desc()).limit(limit)
        ).all())

    def update_section(
        self,
        session: Session,
        *,
        course_id: int,
        section: str,
        patch: dict,
        actor_user_id: int,
        expected_version: Optional[int] = None,
    ) -> CourseSettingVersion:
        """更新某一 section（profile/publish/agent_policy/safety/sandbox/integration）。

        - section 必须在 SETTING_SECTIONS 内
        - patch 仅接受该 section 白名单字段
        - expected_version 与当前版本不一致时抛 VERSION_CONFLICT
        - 生成新版本，旧版本 is_current=False
        """
        if section not in self.SETTING_SECTIONS:
            reject_validation_failed(
                f"未知的设置段：{section}",
                details={"allowed_sections": list(self.SETTING_SECTIONS)},
            )

        whitelist = {
            "profile": _PROFILE_FIELDS,
            "publish": _PUBLISH_FIELDS,
            "agent_policy": _AGENT_POLICY_FIELDS,
            "safety": _SAFETY_FIELDS,
            "sandbox": _SANDBOX_FIELDS,
            "integration": _INTEGRATION_FIELDS,
        }[section]
        filtered = _filter_fields(patch, whitelist)
        if not filtered:
            reject_validation_failed("没有可更新的字段（不在白名单内）")

        current = self.get_current(session, course_id=course_id)
        is_first_creation = current is None
        if is_first_creation:
            # 初始化首版（空设置），后续直接把 patch 合并进去，不再创建新版本
            current = CourseSettingVersion(
                course_id=course_id,
                version=1,
                is_current=True,
                profile={k: None for k in _PROFILE_FIELDS},
                publish={k: None for k in _PUBLISH_FIELDS},
                agent_policy={k: None for k in _AGENT_POLICY_FIELDS},
                safety={k: None for k in _SAFETY_FIELDS},
                sandbox={k: None for k in _SANDBOX_FIELDS},
                integration={k: None for k in _INTEGRATION_FIELDS},
                created_by=actor_user_id,
            )
            session.add(current)
            session.flush()

        if expected_version is not None and current.version != expected_version:
            reject_version_conflict(
                "课程设置版本已变更，请刷新后重试",
                details={"expected_version": expected_version, "current_version": current.version},
            )

        # 同步 profile 到 Course 表
        if section == "profile":
            course = session.get(Course, course_id)
            if course is not None:
                if "title" in filtered:
                    course.title = filtered["title"]
                if "description" in filtered and filtered["description"] is not None:
                    course.description = filtered["description"]
                if "cover_url" in filtered and filtered["cover_url"] is not None:
                    course.cover_url = filtered["cover_url"]
                course.updated_at = utcnow_naive()
                session.add(course)

        # 同步 publish.join_mode 到 Course.invite_code 等
        if section == "publish":
            course = session.get(Course, course_id)
            if course is not None and "invite_code" in filtered:
                new_code = filtered["invite_code"]
                if new_code and new_code != course.invite_code:
                    # 邀请码全局唯一性校验
                    existing = session.exec(
                        select(Course).where(
                            Course.invite_code == new_code,
                            Course.id != course_id,
                        )
                    ).first()
                    if existing is not None:
                        reject_state_conflict("邀请码已被其他课程占用")
                    course.invite_code = new_code
                    course.updated_at = utcnow_naive()
                    session.add(course)

        before_section = dict(getattr(current, section))
        merged = dict(before_section)
        merged.update(filtered)

        if is_first_creation:
            # 首版直接合并 patch，不创建新版本
            setattr(current, section, merged)
            session.add(current)
            new_version = current
        else:
            # 旧版本置为非 current
            current.is_current = False
            session.add(current)

            new_version = CourseSettingVersion(
                course_id=course_id,
                version=current.version + 1,
                is_current=True,
                prev_version_id=current.setting_version_id,
                profile=dict(current.profile),
                publish=dict(current.publish),
                agent_policy=dict(current.agent_policy),
                safety=dict(current.safety),
                sandbox=dict(current.sandbox),
                integration=dict(current.integration),
                created_by=actor_user_id,
            )
            setattr(new_version, section, merged)
            session.add(new_version)

        # 审计事件
        event_type_map = {
            "profile": AuditEventType.COURSE_PROFILE_UPDATE,
            "publish": AuditEventType.COURSE_PUBLISH_UPDATE,
            "agent_policy": AuditEventType.AGENT_POLICY_UPDATE,
            "safety": AuditEventType.SAFETY_UPDATE,
            "sandbox": AuditEventType.SANDBOX_UPDATE,
            "integration": AuditEventType.COURSE_PUBLISH_UPDATE,
        }
        audit = CourseAuditEvent(
            course_id=course_id,
            event_type=event_type_map[section],
            actor_user_id=actor_user_id,
            before=before_section if not is_first_creation else {},
            after=merged,
            note=f"version {new_version.version}" if is_first_creation else f"version {current.version} -> {new_version.version}",
        )
        session.add(audit)
        session.flush()
        return new_version

    def rollback(
        self,
        session: Session,
        *,
        course_id: int,
        target_version: int,
        actor_user_id: int,
    ) -> CourseSettingVersion:
        """回滚到指定版本：基于目标版本内容创建新版本（不破坏历史）。"""
        target = session.exec(
            select(CourseSettingVersion).where(
                CourseSettingVersion.course_id == course_id,
                CourseSettingVersion.version == target_version,
            )
        ).first()
        if target is None:
            reject_resource_not_found("目标设置版本不存在")

        current = self.get_current(session, course_id=course_id)
        if current is not None:
            current.is_current = False
            session.add(current)
            next_version_num = current.version + 1
        else:
            next_version_num = 1

        new_version = CourseSettingVersion(
            course_id=course_id,
            version=next_version_num,
            is_current=True,
            prev_version_id=current.setting_version_id if current else None,
            profile=dict(target.profile),
            publish=dict(target.publish),
            agent_policy=dict(target.agent_policy),
            safety=dict(target.safety),
            sandbox=dict(target.sandbox),
            integration=dict(target.integration),
            created_by=actor_user_id,
        )
        session.add(new_version)

        audit = CourseAuditEvent(
            course_id=course_id,
            event_type=AuditEventType.SETTING_ROLLBACK,
            actor_user_id=actor_user_id,
            before={"version": current.version} if current else {},
            after={"version": next_version_num, "rolled_back_to": target_version},
        )
        session.add(audit)
        session.flush()
        return new_version


course_settings_service = CourseSettingsService()


# ---------------------------------------------------------------------------
# 课程审计事件查询
# ---------------------------------------------------------------------------


class CourseAuditService:
    def list_events(
        self,
        session: Session,
        *,
        course_id: int,
        event_type: Optional[AuditEventType] = None,
        limit: int = 50,
    ) -> list[CourseAuditEvent]:
        stmt = select(CourseAuditEvent).where(
            CourseAuditEvent.course_id == course_id
        ).order_by(CourseAuditEvent.created_at.desc()).limit(limit)
        if event_type is not None:
            stmt = stmt.where(CourseAuditEvent.event_type == event_type)
        return list(session.exec(stmt).all())


course_audit_service = CourseAuditService()


# ---------------------------------------------------------------------------
# 泛雅同步运行
# ---------------------------------------------------------------------------


class FanyaSyncService:
    """泛雅同步服务

    - 同步前必须预览差异（added/removed/conflicts）
    - 教师确认后才执行；预览阶段不修改任何成员关系
    - 一次同步对应一个 task_id（统一任务中心）
    - 同步结果记录 applied_added/applied_removed/applied_skipped
    """

    def create_sync_run(
        self,
        session: Session,
        *,
        course_id: int,
        initiated_by: int,
        source_course_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> IntegrationSyncRun:
        run = IntegrationSyncRun(
            course_id=course_id,
            source_course_id=source_course_id,
            task_id=task_id,
            status=SyncRunStatus.PREVIEWING,
            initiated_by=initiated_by,
        )
        session.add(run)
        session.flush()
        return run

    def save_preview(
        self,
        session: Session,
        *,
        course_id: int,
        sync_run_id: str,
        added: list[dict],
        removed: list[dict],
        conflicts: list[dict],
        summary: Optional[dict] = None,
    ) -> IntegrationSyncRun:
        run = self._get_run(session, course_id=course_id, sync_run_id=sync_run_id)
        if run.status != SyncRunStatus.PREVIEWING:
            reject_state_conflict("同步运行已不在预览阶段")
        run.preview_added = added
        run.preview_removed = removed
        run.preview_conflicts = conflicts
        run.preview_summary = summary or {
            "added": len(added),
            "removed": len(removed),
            "conflicts": len(conflicts),
        }
        run.updated_at = utcnow_naive()
        session.add(run)
        session.flush()
        return run

    def confirm_apply(
        self,
        session: Session,
        *,
        course_id: int,
        sync_run_id: str,
        confirmed_by: int,
    ) -> IntegrationSyncRun:
        """教师确认执行同步：依据预览差异修改本地成员关系。"""
        run = self._get_run(session, course_id=course_id, sync_run_id=sync_run_id)
        if run.status != SyncRunStatus.PREVIEWING:
            reject_state_conflict("同步运行已不在预览阶段，无法确认")
        if not run.preview_added and not run.preview_removed:
            # 空差异直接成功
            run.status = SyncRunStatus.SUCCEEDED
            run.confirmed_by = confirmed_by
            run.confirmed_at = utcnow_naive()
            run.completed_at = utcnow_naive()
            session.add(run)
            session.flush()
            return run

        run.status = SyncRunStatus.RUNNING
        run.confirmed_by = confirmed_by
        run.confirmed_at = utcnow_naive()
        session.add(run)
        session.flush()

        applied_added = 0
        applied_removed = 0
        applied_skipped = 0
        try:
            for entry in run.preview_added:
                user_id = entry.get("user_id")
                if user_id is None:
                    applied_skipped += 1
                    continue
                activate_student_membership(
                    session,
                    course_id=course_id,
                    student_user_id=int(user_id),
                )
                # 补充 enrollment
                existing = session.exec(
                    select(StudentEnrollment).where(
                        StudentEnrollment.student_id == int(user_id),
                        StudentEnrollment.course_id == course_id,
                    )
                ).first()
                if existing is None:
                    session.add(StudentEnrollment(
                        student_id=int(user_id),
                        course_id=course_id,
                    ))
                applied_added += 1

            for entry in run.preview_removed:
                user_id = entry.get("user_id")
                if user_id is None:
                    applied_skipped += 1
                    continue
                membership = session.exec(
                    select(CourseMembership).where(
                        CourseMembership.course_id == course_id,
                        CourseMembership.user_id == int(user_id),
                        CourseMembership.status == MembershipStatus.ACTIVE,
                    )
                ).first()
                if membership is None:
                    applied_skipped += 1
                    continue
                if membership.role == CourseRole.OWNER:
                    applied_skipped += 1
                    continue
                membership.status = MembershipStatus.REMOVED
                membership.left_at = utcnow_naive()
                membership.updated_at = utcnow_naive()
                session.add(membership)
                applied_removed += 1

            run.applied_added = applied_added
            run.applied_removed = applied_removed
            run.applied_skipped = applied_skipped
            run.status = SyncRunStatus.SUCCEEDED
            run.completed_at = utcnow_naive()
            session.add(run)

            audit = CourseAuditEvent(
                course_id=course_id,
                event_type=AuditEventType.FANYA_SYNC_RUN,
                actor_user_id=confirmed_by,
                target_resource_id=run.sync_run_id,
                after={
                    "added": applied_added,
                    "removed": applied_removed,
                    "skipped": applied_skipped,
                },
            )
            session.add(audit)
            session.flush()
            return run
        except Exception as exc:
            run.status = SyncRunStatus.FAILED
            run.error_message = str(exc)
            run.completed_at = utcnow_naive()
            session.add(run)
            session.flush()
            raise

    def list_runs(
        self,
        session: Session,
        *,
        course_id: int,
        limit: int = 20,
    ) -> list[IntegrationSyncRun]:
        return list(session.exec(
            select(IntegrationSyncRun).where(
                IntegrationSyncRun.course_id == course_id,
            ).order_by(IntegrationSyncRun.created_at.desc()).limit(limit)
        ).all())

    def _get_run(
        self,
        session: Session,
        *,
        course_id: int,
        sync_run_id: str,
    ) -> IntegrationSyncRun:
        run = session.exec(
            select(IntegrationSyncRun).where(
                IntegrationSyncRun.course_id == course_id,
                IntegrationSyncRun.sync_run_id == sync_run_id,
            )
        ).first()
        if run is None:
            reject_resource_not_found("同步运行不存在")
        return run


fanya_sync_service = FanyaSyncService()
