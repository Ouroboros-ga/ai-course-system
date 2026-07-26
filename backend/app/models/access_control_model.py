"""Course-scoped access-control persistence models.

The legacy application stores a single global role on ``User`` and a
``teacher_id`` on ``Course``. These additive models provide the course-level
relationship required for permission resolution without changing either
legacy field or an existing public API.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_naive


class CourseRole(str, Enum):
    OWNER = "owner"
    TEACHER = "teacher"
    TEACHING_ASSISTANT = "teaching_assistant"
    STUDENT = "student"
    OBSERVER = "observer"


class MembershipStatus(str, Enum):
    INVITED = "invited"
    PENDING = "pending"
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    REMOVED = "removed"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class PlatformPermission(str, Enum):
    ADMIN = "platform.admin"
    COURSE_CREATE = "platform.course.create"
    COURSE_AUDIT = "platform.course.audit"
    USER_MANAGE = "platform.user.manage"
    SAFETY_MANAGE = "platform.safety.manage"
    CAPABILITY_MANAGE = "platform.capability.manage"


class ParticipationMode(str, Enum):
    LEARNER = "learner"
    TEACHER_PREVIEW = "teacher_preview"
    STAFF_TEST = "staff_test"
    OBSERVER = "observer"


class CourseMembership(SQLModel, table=True):
    """A user's course role, status and narrowly-scoped overrides."""

    __tablename__ = "course_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_course_membership_user_course"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    role: CourseRole = Field(index=True)
    status: MembershipStatus = Field(default=MembershipStatus.ACTIVE, index=True)
    permission_overrides: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    analytics_excluded: bool = Field(default=False)
    joined_at: datetime = Field(default_factory=utcnow_naive)
    left_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow_naive)
    migration_batch_id: Optional[str] = Field(default=None, index=True)


class CourseCapability(SQLModel, table=True):
    """Product capability switches for one course, distinct from permissions."""

    __tablename__ = "course_capabilities"
    __table_args__ = (UniqueConstraint("course_id", name="uq_course_capabilities_course"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    learning: bool = Field(default=True)
    course_building: bool = Field(default=True)
    knowledge_graph: bool = Field(default=False)
    evidence: bool = Field(default=False)
    experiment: bool = Field(default=False)
    coding_sandbox: bool = Field(default=False)
    cognitive_analysis: bool = Field(default=False)
    safety_policy: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=utcnow_naive)
    migration_batch_id: Optional[str] = Field(default=None, index=True)


class PlatformPermissionAssignment(SQLModel, table=True):
    """Explicit cross-course authority; never inferred during normal access."""

    __tablename__ = "platform_permission_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "permission", name="uq_platform_permission_user_permission"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    permission: PlatformPermission = Field(index=True)
    granted_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    granted_at: datetime = Field(default_factory=utcnow_naive)
    revoked_at: Optional[datetime] = Field(default=None)
    migration_batch_id: Optional[str] = Field(default=None, index=True)
