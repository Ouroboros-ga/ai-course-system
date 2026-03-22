from __future__ import annotations

from sqlmodel import SQLModel, Field, Relationship, JSON, Column
from typing import Optional, List
from datetime import datetime
from enum import Enum


class CourseStatus(str, Enum):
    """课程状态枚举"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ScriptNodeType(str, Enum):
    """脚本节点类型枚举"""

    LECTURE = "lecture"
    QUESTION = "question"
    BREAKPOINT = "breakpoint"
    SUMMARY = "summary"
    VIDEO = "video"
    INTERACTIVE = "interactive"


class Course(SQLModel, table=True):
    """课程主表：映射泛雅课程与本地智课"""

    __tablename__ = "courses"

    id: Optional[int] = Field(default=None, primary_key=True)

    fanya_course_id: str = Field(index=True, description="泛雅课程ID")
    fanya_course_name: str = Field(description="泛雅原始课程名称")

    title: str = Field(description="智课标题")
    description: Optional[str] = Field(default=None, description="课程描述")
    cover_image: Optional[str] = Field(default=None, description="封面图片URL")

    teacher_id: int = Field(foreign_key="users.id", index=True, description="所属教师ID")

    status: CourseStatus = Field(default=CourseStatus.DRAFT, description="课程状态")
    is_ai_generated: bool = Field(default=False, description="是否由AI生成")

    total_duration: int = Field(default=0, description="总时长(秒)")
    total_nodes: int = Field(default=0, description="脚本总节点数")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CourseScript(SQLModel, table=True):
    """AI生成的结构化脚本表"""

    __tablename__ = "course_scripts"

    id: Optional[int] = Field(default=None, primary_key=True)

    course_id: int = Field(
        foreign_key="courses.id", index=True, description="所属课程ID"
    )

    version: int = Field(default=1, description="脚本版本号")
    version_name: Optional[str] = Field(default=None, description="版本名称")

    script_content: dict = Field(
        ...,
        sa_column=Column(JSON, nullable=False),
        description="结构化脚本内容(JSON)",
    )

    summary_text: Optional[str] = Field(default=None, description="AI生成的课程摘要")
    keywords: Optional[str] = Field(default=None, description="关键词(JSON数组)")

    is_active: bool = Field(default=True, description="是否为当前激活版本")

    audio_url: Optional[str] = Field(default=None, description="合成音频URL")
    audio_duration: int = Field(default=0, description="音频时长(秒)")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: int = Field(foreign_key="users.id", description="创建者/教师ID")


class ScriptNode(SQLModel, table=True):
    """脚本节点表：存储每个节点的详细信息"""

    __tablename__ = "script_nodes"

    id: Optional[int] = Field(default=None, primary_key=True)

    script_id: int = Field(
        foreign_key="course_scripts.id", index=True, description="所属脚本ID"
    )

    node_index: int = Field(description="节点序号")
    node_type: ScriptNodeType = Field(description="节点类型")

    title: Optional[str] = Field(default=None, description="节点标题")
    content: str = Field(description="节点内容/讲解文本")

    page_start: int = Field(default=1, description="关联PPT起始页")
    page_end: int = Field(default=1, description="关联PPT结束页")

    timestamp_start: float = Field(default=0.0, description="音频起始时间(秒)")
    timestamp_end: float = Field(default=0.0, description="音频结束时间(秒)")

    duration: int = Field(default=0, description="节点时长(秒)")

    extra_data: Optional[dict] = Field(
        default=None, sa_column=Column(JSON), description="扩展元数据(JSON)"
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)
