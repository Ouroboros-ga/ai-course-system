"""阶段2 成员、设置、加入申请与课程生命周期 持久化模型。

承载路线图 §5：
- 加入申请状态机：pending → approved | rejected | info_requested | cancelled | expired
- 课程分组与成员分配（不改课程角色，删组不删成员）
- 课程设置版本化：基本信息 / 加入与发布 / Agent 策略 / 安全 / 沙箱 / 平台集成
- 审计事件：所有受控字段变更写入 audit_events，可追溯
- 泛雅同步运行：异步任务 + 预览差异 + 同步结果摘要

所有表按 course_id 严格隔离；写入设置时生成新版本，旧版本可回溯。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


# ---------------------------------------------------------------------------
# 加入申请
# ---------------------------------------------------------------------------


class JoinRequestStatus(str, Enum):
    """加入申请状态

    状态机：
        pending → approved | rejected | info_requested | cancelled | expired
        info_requested → pending（学生补充信息后重新提交）| rejected
        approved → 终态（已激活 membership）
    不可从终态再转移。
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INFO_REQUESTED = "info_requested"
    CANCELLED = "cancelled"        # 学生主动撤销
    EXPIRED = "expired"            # 教师未在有效期内处理


class JoinChannel(str, Enum):
    """加入来源"""
    INVITE_CODE = "invite_code"    # 已有的邀请码通道（不在此表）
    JOIN_REQUEST = "join_request"  # 申请审核
    FANYA_SYNC = "fanya_sync"      # 泛雅同步带入
    OWNER_IMPORT = "owner_import"  # 教师导入


class CourseJoinRequest(SQLModel, table=True):
    """课程加入申请记录

    学生提交申请 -> 教师审批 -> approved 时由服务层调用 activate_student_membership。
    每个申请必须记录审核者与时间；info_requested 后学生可补充说明重新提交。
    """

    __tablename__ = "course_join_requests"

    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: str = Field(
        default_factory=lambda: f"jr_{uuid.uuid4().hex}",
        unique=True,
        index=True,
        description="稳定申请 ID",
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    applicant_user_id: int = Field(foreign_key="users.id", index=True)

    # 申请内容
    apply_reason: str = Field(default="", description="申请说明")
    supplement_info: str = Field(default="", description="教师请求补充后的学生补充信息")
    channel: JoinChannel = Field(default=JoinChannel.JOIN_REQUEST, index=True)

    # 状态
    status: JoinRequestStatus = Field(default=JoinRequestStatus.PENDING, index=True)

    # 审核
    reviewer_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    review_comment: str = Field(default="", description="教师审核备注")
    reviewed_at: Optional[datetime] = Field(default=None)

    # 过期
    expires_at: Optional[datetime] = Field(default=None, description="申请过期时间")

    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 课程分组
# ---------------------------------------------------------------------------


class CourseGroup(SQLModel, table=True):
    """课程分组（班级/小组/实验分组）

    分组不能改变课程角色；删除分组不删除成员（仅解除关联）。
    一个学生可属于多个分组，仅业务允许时。
    """

    __tablename__ = "course_groups"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: str = Field(
        default_factory=lambda: f"cg_{uuid.uuid4().hex}",
        unique=True,
        index=True,
        description="稳定分组 ID",
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    name: str = Field(default="", description="分组名称")
    description: str = Field(default="", description="分组说明")
    group_type: str = Field(default="study", description="study|class|experiment|lab")

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class CourseGroupMember(SQLModel, table=True):
    """课程分组成员关联

    仅记录分组归属，不影响 CourseMembership 的角色与权限。
    """

    __tablename__ = "course_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_course_group_member"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: str = Field(index=True, description="CourseGroup.group_id")
    course_id: int = Field(foreign_key="courses.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)

    added_by: Optional[int] = Field(default=None, foreign_key="users.id")
    added_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 课程设置版本化
# ---------------------------------------------------------------------------


class CourseSettingVersion(SQLModel, table=True):
    """课程设置版本记录

    每次保存生成新版本；当前活跃设置由 is_current=True 标记。
    支持版本冲突检测（version 字段 + updated_at），可回滚到指定版本。
    聚合包含：profile / publish / agent_policy / safety / sandbox / integration。
    """

    __tablename__ = "course_setting_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    setting_version_id: str = Field(
        default_factory=lambda: f"csv_{uuid.uuid4().hex}",
        unique=True,
        index=True,
        description="稳定设置版本 ID",
    )
    course_id: int = Field(foreign_key="courses.id", index=True)

    # 版本
    version: int = Field(default=1, description="版本号，自增")
    is_current: bool = Field(default=True, index=True)
    prev_version_id: Optional[str] = Field(default=None, description="前一版本 setting_version_id")

    # 聚合内容（JSON）
    profile: dict = Field(default_factory=dict, sa_column=Column(JSON), description="基础信息")
    publish: dict = Field(default_factory=dict, sa_column=Column(JSON), description="加入与发布")
    agent_policy: dict = Field(default_factory=dict, sa_column=Column(JSON), description="智能体策略")
    safety: dict = Field(default_factory=dict, sa_column=Column(JSON), description="安全与合规")
    sandbox: dict = Field(default_factory=dict, sa_column=Column(JSON), description="沙箱权限")
    integration: dict = Field(default_factory=dict, sa_column=Column(JSON), description="平台集成")

    # 审计
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 审计事件
# ---------------------------------------------------------------------------


class AuditEventType(str, Enum):
    """审计事件类型"""
    COURSE_CLOSE = "course.close"
    COURSE_REOPEN = "course.reopen"
    COURSE_PROFILE_UPDATE = "course.profile.update"
    COURSE_PUBLISH_UPDATE = "course.publish.update"
    AGENT_POLICY_UPDATE = "course.agent_policy.update"
    SAFETY_UPDATE = "course.safety.update"
    SANDBOX_UPDATE = "course.sandbox.update"
    MEMBER_ROLE_CHANGE = "course.member.role_change"
    MEMBER_REMOVE = "course.member.remove"
    MEMBER_INVITE = "course.member.invite"
    JOIN_REQUEST_APPROVE = "course.join_request.approve"
    JOIN_REQUEST_REJECT = "course.join_request.reject"
    SETTING_ROLLBACK = "course.setting.rollback"
    FANYA_SYNC_RUN = "course.fanya_sync.run"


class CourseAuditEvent(SQLModel, table=True):
    """课程审计事件

    所有受控字段（设置/状态/角色/邀请/同步）变更必须写入审计表。
    可按 course_id + event_type + actor_user_id 检索。
    """

    __tablename__ = "course_audit_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    audit_id: str = Field(
        default_factory=lambda: f"ae_{uuid.uuid4().hex}",
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    event_type: AuditEventType = Field(index=True)

    actor_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    target_user_id: Optional[int] = Field(default=None, foreign_key="users.id", description="被影响的用户")
    target_resource_id: Optional[str] = Field(default=None, index=True, description="被影响的资源 ID")

    # 变更详情
    before: dict = Field(default_factory=dict, sa_column=Column(JSON))
    after: dict = Field(default_factory=dict, sa_column=Column(JSON))
    note: str = Field(default="")

    created_at: datetime = Field(default_factory=utcnow_aware, index=True)


# ---------------------------------------------------------------------------
# 泛雅同步运行
# ---------------------------------------------------------------------------


class SyncRunStatus(str, Enum):
    """同步运行状态"""
    PENDING = "pending"
    PREVIEWING = "previewing"      # 已生成差异预览，等待教师确认
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IntegrationSyncRun(SQLModel, table=True):
    """泛雅同步运行记录

    同步前必须预览变化；预览生成 added/removed/conflicts 列表，教师确认后才执行。
    一次同步对应一个 task_id（统一任务中心），并记录差异摘要。
    """

    __tablename__ = "integration_sync_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    sync_run_id: str = Field(
        default_factory=lambda: f"fsr_{uuid.uuid4().hex}",
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)

    # 来源
    integration: str = Field(default="fanya", index=True, description="集成类型")
    source_course_id: Optional[str] = Field(default=None, description="来源平台课程 ID")
    task_id: Optional[str] = Field(default=None, index=True, description="统一任务中心 task_id")

    # 预览差异
    preview_added: list = Field(default_factory=list, sa_column=Column(JSON))
    preview_removed: list = Field(default_factory=list, sa_column=Column(JSON))
    preview_conflicts: list = Field(default_factory=list, sa_column=Column(JSON))
    preview_summary: dict = Field(default_factory=dict, sa_column=Column(JSON))

    # 执行结果
    applied_added: int = Field(default=0)
    applied_removed: int = Field(default=0)
    applied_skipped: int = Field(default=0)
    error_message: str = Field(default="")

    status: SyncRunStatus = Field(default=SyncRunStatus.PENDING, index=True)

    initiated_by: Optional[int] = Field(default=None, foreign_key="users.id")
    confirmed_by: Optional[int] = Field(default=None, foreign_key="users.id")

    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)
    confirmed_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
