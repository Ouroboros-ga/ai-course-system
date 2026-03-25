from __future__ import annotations

from sqlmodel import SQLModel, Field, JSON, Column
from typing import Optional
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


class ParseStatus(str, Enum):
    """解析状态枚举"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


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

    source_file_name: Optional[str] = Field(default=None, description="原始PPT文件名")
    source_file_path: Optional[str] = Field(default=None, description="原始PPT存储路径")
    total_pages: int = Field(default=0, description="PPT总页数")

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

    chapter_id: Optional[str] = Field(
        default=None, index=True, description="关联的知识点ID，如chap001_02_03"
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

    is_key_point: bool = Field(default=False, description="是否为重点知识点")

    extra_data: Optional[dict] = Field(
        default=None, sa_column=Column(JSON), description="扩展元数据(JSON)"
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)


class KnowledgeTree(SQLModel, table=True):
    """
    知识点树主表
    存储一次PPT解析生成的知识点树元数据
    """

    __tablename__ = "knowledge_trees"

    id: Optional[int] = Field(default=None, primary_key=True)

    parse_id: str = Field(unique=True, index=True, description="解析ID，如parse20240520001")

    course_id: Optional[int] = Field(
        default=None, foreign_key="courses.id", index=True, description="关联的课程ID"
    )

    course_name: Optional[str] = Field(default=None, description="课程名称")

    source_file_name: Optional[str] = Field(default=None, description="原始PPT文件名")
    source_file_path: Optional[str] = Field(default=None, description="原始PPT存储路径")

    total_pages: int = Field(default=0, description="PPT总页数")
    total_chapters: int = Field(default=0, description="知识点总数")

    status: ParseStatus = Field(default=ParseStatus.PENDING, description="解析状态")

    raw_json: Optional[dict] = Field(
        default=None, sa_column=Column(JSON), description="原始解析JSON完整数据"
    )

    error_message: Optional[str] = Field(default=None, description="解析失败时的错误信息")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")


class KnowledgeChapter(SQLModel, table=True):
    """
    知识点章节表
    扁平化存储知识点树的每个节点，通过 parent_id 维护层级关系
    """

    __tablename__ = "knowledge_chapters"

    id: Optional[int] = Field(default=None, primary_key=True)

    tree_id: int = Field(
        foreign_key="knowledge_trees.id", index=True, description="所属知识点树ID"
    )

    chapter_id: str = Field(index=True, description="章节ID，如chap001_02_03")

    parent_id: Optional[int] = Field(
        default=None, foreign_key="knowledge_chapters.id", description="父节点ID"
    )

    chapter_name: str = Field(description="知识点名称")

    level: int = Field(description="层级深度(1=章,2=节,3=知识点,4=子知识点)")

    is_key_point: bool = Field(default=False, description="是否为重点知识点")

    page_range: Optional[str] = Field(default=None, description="对应PPT页码范围，如'27-40'")

    page_start: Optional[int] = Field(default=None, description="起始页码")

    page_end: Optional[int] = Field(default=None, description="结束页码")

    description: Optional[str] = Field(default=None, description="知识点简要描述")

    sort_order: int = Field(default=0, description="同层级排序序号")

    extra_data: Optional[dict] = Field(
        default=None, sa_column=Column(JSON), description="扩展数据(JSON)"
    )

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")


class CourseParseRecord(SQLModel, table=True):
    """
    课程解析记录表
    记录课程与知识点解析的关联关系
    """

    __tablename__ = "course_parse_records"

    id: Optional[int] = Field(default=None, primary_key=True)

    course_id: int = Field(
        foreign_key="courses.id", index=True, description="课程ID"
    )

    tree_id: int = Field(
        foreign_key="knowledge_trees.id", index=True, description="知识点树ID"
    )

    is_current: bool = Field(default=True, description="是否为当前使用的解析版本")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
