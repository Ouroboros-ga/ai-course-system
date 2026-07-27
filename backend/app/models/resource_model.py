"""阶段7 资源库、平台实验室与任务中心 持久化模型

完成通用资源库（文件版本、标签、课程引用、回收站、下游影响与权限）和平台实验
大厅读模型（catalog、course-tasks、my-experiments、records）。

设计要点：
- `ResourceItem`：通用资源项，按 owner_user_id 与 course_id（可选）隔离；
  软删除进入 RecycleBinEntry，恢复时检查下游影响。
- `ResourceVersion`：不可变版本，content_hash + object_key 双轨；
  版本演进不破坏历史引用。
- `ResourceTag`：标签索引，按 owner_user_id 隔离。
- `ResourceReference`：资源引用记录（课程/节点/实验等），删除资源时返回下游影响。
- `ResourceAclEntry`：资源访问控制，默认仅 owner 可访问；可显式授权给其他用户/课程。
- `RecycleBinEntry`：回收站条目，记录软删除时间、过期时间、可恢复期限。
- `LabCatalogEntry`：平台实验室目录项，与课程实验共享沙箱能力；
  平台实验与课程实验均可回写课程证据和 return anchor。

所有表按 owner_user_id / course_id 严格隔离，绝不跨用户/课程暴露。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


# ---------------------------------------------------------------------------
# 通用资源库
# ---------------------------------------------------------------------------


class ResourceScope(str, Enum):
    """资源作用域"""
    USER = "user"          # 个人资源
    COURSE = "course"      # 课程资源
    PLATFORM = "platform"  # 平台公共资源


class ResourceItemType(str, Enum):
    """资源类型"""
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    CODE = "code"
    DATASET = "dataset"
    OTHER = "other"


class ResourceItem(SQLModel, table=True):
    """通用资源项

    - 按 owner_user_id 与 course_id（可选）隔离
    - 软删除：is_deleted=True 后进入回收站，可恢复
    - 版本演进不破坏历史引用
    """

    __tablename__ = "resource_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    resource_id: str = Field(
        default_factory=lambda: "res_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    owner_user_id: int = Field(foreign_key="users.id", index=True)
    course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True)
    scope: ResourceScope = Field(default=ResourceScope.USER, index=True)

    name: str = Field(default="", max_length=200)
    description: str = Field(default="")
    resource_type: ResourceItemType = Field(default=ResourceItemType.OTHER, index=True)
    mime_type: str = Field(default="")
    file_size: int = Field(default=0)

    current_version_id: Optional[str] = Field(default=None, index=True)
    is_deleted: bool = Field(default=False, index=True)
    deleted_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class ResourceVersion(SQLModel, table=True):
    """资源版本（不可变）

    - content_hash + object_key 双轨
    - 版本演进不破坏历史引用
    """

    __tablename__ = "resource_versions"
    __table_args__ = (
        UniqueConstraint(
            "resource_id", "version_number",
            name="uq_resource_version_number",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    version_id: str = Field(
        default_factory=lambda: "resv_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    resource_id: str = Field(index=True, description="关联 ResourceItem.resource_id")
    owner_user_id: int = Field(foreign_key="users.id", index=True)
    course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True)

    version_number: int = Field(default=1, ge=1)
    label: str = Field(default="", max_length=100)
    object_key: str = Field(default="", description="本地/OSS 对象键")
    content_hash: str = Field(default="", index=True, description="内容哈希用于去重")
    file_size: int = Field(default=0)
    mime_type: str = Field(default="")

    is_active: bool = Field(default=False, index=True, description="当前激活版本")
    uploaded_by: int = Field(foreign_key="users.id")
    uploaded_at: datetime = Field(default_factory=utcnow_aware)


class ResourceTag(SQLModel, table=True):
    """资源标签索引"""

    __tablename__ = "resource_tags"
    __table_args__ = (
        UniqueConstraint(
            "resource_id", "tag",
            name="uq_resource_tag",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    resource_id: str = Field(index=True)
    tag: str = Field(default="", max_length=50, index=True)
    owner_user_id: int = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=utcnow_aware)


class ResourceReference(SQLModel, table=True):
    """资源引用记录

    删除资源时返回下游影响（哪些课程/节点/实验引用了该资源）。
    """

    __tablename__ = "resource_references"

    id: Optional[int] = Field(default=None, primary_key=True)
    reference_id: str = Field(
        default_factory=lambda: "ref_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    resource_id: str = Field(index=True)
    version_id: Optional[str] = Field(default=None, index=True, description="特定版本；空表示最新版")
    owner_user_id: int = Field(foreign_key="users.id", index=True)

    # 引用上下文
    target_type: str = Field(default="", index=True, description="course|node|experiment|lab")
    target_course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True)
    target_node_id: Optional[int] = Field(default=None)
    target_experiment_id: Optional[str] = Field(default=None)
    target_lab_id: Optional[str] = Field(default=None)

    reference_note: str = Field(default="", max_length=500)
    created_at: datetime = Field(default_factory=utcnow_aware)


class ResourceAclEntry(SQLModel, table=True):
    """资源访问控制条目

    默认仅 owner 可访问；可显式授权给其他用户/课程。
    """

    __tablename__ = "resource_acl_entries"
    __table_args__ = (
        UniqueConstraint(
            "resource_id", "grantee_user_id", "grantee_course_id",
            name="uq_resource_acl_grantee",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    acl_id: str = Field(
        default_factory=lambda: "acl_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    resource_id: str = Field(index=True)
    owner_user_id: int = Field(foreign_key="users.id", index=True)

    grantee_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    grantee_course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True)
    permission: str = Field(default="read", description="read|write|admin")
    granted_by: int = Field(foreign_key="users.id")
    granted_at: datetime = Field(default_factory=utcnow_aware)
    expires_at: Optional[datetime] = Field(default=None)


class RecycleBinEntry(SQLModel, table=True):
    """回收站条目

    - 软删除后进入回收站，记录过期时间
    - 过期后由清理任务彻底删除
    - 恢复时检查下游影响
    """

    __tablename__ = "recycle_bin_entries"

    id: Optional[int] = Field(default=None, primary_key=True)
    entry_id: str = Field(
        default_factory=lambda: "rcb_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    resource_id: str = Field(index=True, description="被回收的资源")
    owner_user_id: int = Field(foreign_key="users.id", index=True)
    course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True)

    deleted_by: int = Field(foreign_key="users.id")
    deleted_at: datetime = Field(default_factory=utcnow_aware)
    expires_at: datetime = Field(default_factory=utcnow_aware)

    # 恢复时的下游影响摘要（删除时的快照）
    affected_references: list = Field(
        default_factory=list, sa_column=Column(JSON),
        description="删除时受影响的引用列表快照",
    )
    restorable: bool = Field(default=True)
    restored_at: Optional[datetime] = Field(default=None)
    purged_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# 平台实验室目录
# ---------------------------------------------------------------------------


class LabCatalogVisibility(str, Enum):
    """实验室目录可见性"""
    PUBLIC = "public"
    COURSE_ONLY = "course_only"
    PRIVATE = "private"


class LabCatalogEntry(SQLModel, table=True):
    """平台实验室目录项

    - 平台实验与课程实验共享沙箱能力
    - 课程实验可回写课程证据和 return anchor
    - 按 visibility 控制发现范围
    """

    __tablename__ = "lab_catalog_entries"

    id: Optional[int] = Field(default=None, primary_key=True)
    lab_id: str = Field(
        default_factory=lambda: "lab_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    owner_user_id: int = Field(foreign_key="users.id", index=True)
    course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True,
                                     description="课程级实验室；空表示平台级")
    experiment_id: Optional[str] = Field(default=None, index=True,
                                          description="关联课程实验（课程级）")

    title: str = Field(default="", max_length=200, index=True)
    description: str = Field(default="")
    statement_object_key: str = Field(default="")
    language_whitelist: list = Field(default_factory=list, sa_column=Column(JSON))

    visibility: LabCatalogVisibility = Field(
        default=LabCatalogVisibility.COURSE_ONLY, index=True,
    )
    is_published: bool = Field(default=False, index=True)

    # 共享沙箱能力
    cpu_time_limit: int = Field(default=5)
    memory_limit: int = Field(default=128_000)
    wall_time_limit: int = Field(default=10)

    knowledge_node_ids: list = Field(default_factory=list, sa_column=Column(JSON))

    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)
    published_at: Optional[datetime] = Field(default=None)


class LabEnrollment(SQLModel, table=True):
    """学生在平台实验室的参与记录

    用于"我的实验"页面：列出当前学生参与的所有平台/课程实验室。
    """

    __tablename__ = "lab_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "lab_id", "student_id",
            name="uq_lab_enrollment",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    lab_id: str = Field(index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True)

    enrolled_at: datetime = Field(default_factory=utcnow_aware)
    last_active_at: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True, index=True)

    # 最新的尝试锚点
    last_attempt_id: Optional[str] = Field(default=None, index=True)


class LabRecord(SQLModel, table=True):
    """学生实验记录（实验记录页）

    汇总学生在平台/课程实验室的最终记录。
    """

    __tablename__ = "lab_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    record_id: str = Field(
        default_factory=lambda: "rec_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    lab_id: str = Field(index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True)

    attempt_id: Optional[str] = Field(default=None, index=True, description="关联 ExperimentAttempt.attempt_id")
    final_score: Optional[float] = Field(default=None)
    passed: Optional[bool] = Field(default=None)
    evidence_id: Optional[str] = Field(default=None, index=True)

    return_anchor: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)
