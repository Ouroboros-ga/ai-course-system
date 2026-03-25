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


class DoclingLabel(str, Enum):
    """Docling 文档元素标签枚举"""

    SECTION = "section"
    TABLE = "table"
    TEXT = "text"
    PICTURE = "picture"
    CODE = "code"
    LIST = "list"
    TITLE = "title"
    PARAGRAPH = "paragraph"


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

    source_file_name: Optional[str] = Field(default=None, description="原始文件名")
    source_file_path: Optional[str] = Field(default=None, description="原始文件存储路径")
    source_mimetype: Optional[str] = Field(default=None, description="原始文件MIME类型")
    total_pages: int = Field(default=0, description="总页数")

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


class DoclingDocument(SQLModel, table=True):
    """
    Docling 解析文档主表
    存储一次文档解析生成的结构化数据
    """

    __tablename__ = "docling_documents"

    id: Optional[int] = Field(default=None, primary_key=True)

    course_id: Optional[int] = Field(
        default=None, foreign_key="courses.id", index=True, description="关联的课程ID"
    )

    schema_name: str = Field(default="DoclingDocument", description="文档schema名称")
    version: str = Field(default="1.10.0", description="Docling版本")

    doc_name: str = Field(description="文档名称")

    origin_filename: Optional[str] = Field(default=None, description="原始文件名")
    origin_mimetype: Optional[str] = Field(default=None, description="原始文件MIME类型")
    origin_binary_hash: Optional[int] = Field(default=None, description="文件二进制哈希")

    source_file_path: Optional[str] = Field(default=None, description="原始文件存储路径")

    status: ParseStatus = Field(default=ParseStatus.PENDING, description="解析状态")

    total_groups: int = Field(default=0, description="分组数量")
    total_tables: int = Field(default=0, description="表格数量")
    total_texts: int = Field(default=0, description="文本数量")
    total_pictures: int = Field(default=0, description="图片数量")

    raw_json: Optional[dict] = Field(
        default=None, sa_column=Column(JSON), description="原始解析JSON完整数据"
    )

    error_message: Optional[str] = Field(default=None, description="解析失败时的错误信息")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")


class DoclingGroup(SQLModel, table=True):
    """
    Docling 文档分组表
    存储 groups 数据（如 Excel 的 sheet）
    """

    __tablename__ = "docling_groups"

    id: Optional[int] = Field(default=None, primary_key=True)

    doc_id: int = Field(
        foreign_key="docling_documents.id", index=True, description="所属文档ID"
    )

    self_ref: str = Field(description="自引用路径，如#/groups/0")

    parent_ref: Optional[str] = Field(default=None, description="父节点引用")

    name: str = Field(description="分组名称，如sheet名称")
    label: str = Field(default="section", description="标签类型")

    content_layer: str = Field(default="body", description="内容层级")

    sort_order: int = Field(default=0, description="排序序号")

    extra_data: Optional[dict] = Field(
        default=None, sa_column=Column(JSON), description="扩展数据(JSON)"
    )

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")


class DoclingTable(SQLModel, table=True):
    """
    Docling 表格数据表
    存储解析出的表格数据
    """

    __tablename__ = "docling_tables"

    id: Optional[int] = Field(default=None, primary_key=True)

    doc_id: int = Field(
        foreign_key="docling_documents.id", index=True, description="所属文档ID"
    )

    group_id: Optional[int] = Field(
        default=None, foreign_key="docling_groups.id", description="所属分组ID"
    )

    self_ref: str = Field(description="自引用路径，如#/tables/0")

    label: str = Field(default="table", description="标签类型")

    page_no: int = Field(default=1, description="所在页码")

    bbox_l: float = Field(default=0.0, description="边界框左")
    bbox_t: float = Field(default=0.0, description="边界框上")
    bbox_r: float = Field(default=0.0, description="边界框右")
    bbox_b: float = Field(default=0.0, description="边界框下")

    num_rows: int = Field(default=0, description="表格行数")
    num_cols: int = Field(default=0, description="表格列数")

    table_data: Optional[dict] = Field(
        default=None, sa_column=Column(JSON), description="表格数据(JSON)"
    )

    captions: Optional[dict] = Field(
        default=None, sa_column=Column(JSON), description="表格标题(JSON)"
    )

    sort_order: int = Field(default=0, description="排序序号")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")


class DoclingTableCell(SQLModel, table=True):
    """
    Docling 表格单元格表
    扁平化存储表格单元格数据，便于查询
    """

    __tablename__ = "docling_table_cells"

    id: Optional[int] = Field(default=None, primary_key=True)

    table_id: int = Field(
        foreign_key="docling_tables.id", index=True, description="所属表格ID"
    )

    row_idx: int = Field(description="行索引")
    col_idx: int = Field(description="列索引")

    row_span: int = Field(default=1, description="行跨度")
    col_span: int = Field(default=1, description="列跨度")

    text: str = Field(default="", description="单元格文本内容")

    is_column_header: bool = Field(default=False, description="是否为列标题")
    is_row_header: bool = Field(default=False, description="是否为行标题")
    is_row_section: bool = Field(default=False, description="是否为行分区")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")


class DoclingText(SQLModel, table=True):
    """
    Docling 文本内容表
    存储解析出的文本内容
    """

    __tablename__ = "docling_texts"

    id: Optional[int] = Field(default=None, primary_key=True)

    doc_id: int = Field(
        foreign_key="docling_documents.id", index=True, description="所属文档ID"
    )

    group_id: Optional[int] = Field(
        default=None, foreign_key="docling_groups.id", description="所属分组ID"
    )

    self_ref: str = Field(description="自引用路径")

    label: str = Field(default="text", description="标签类型")

    text: str = Field(description="文本内容")

    page_no: int = Field(default=1, description="所在页码")

    sort_order: int = Field(default=0, description="排序序号")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")


class DoclingPicture(SQLModel, table=True):
    """
    Docling 图片表
    存储解析出的图片信息
    """

    __tablename__ = "docling_pictures"

    id: Optional[int] = Field(default=None, primary_key=True)

    doc_id: int = Field(
        foreign_key="docling_documents.id", index=True, description="所属文档ID"
    )

    group_id: Optional[int] = Field(
        default=None, foreign_key="docling_groups.id", description="所属分组ID"
    )

    self_ref: str = Field(description="自引用路径")

    label: str = Field(default="picture", description="标签类型")

    image_url: Optional[str] = Field(default=None, description="图片URL或存储路径")

    page_no: int = Field(default=1, description="所在页码")

    bbox_l: float = Field(default=0.0, description="边界框左")
    bbox_t: float = Field(default=0.0, description="边界框上")
    bbox_r: float = Field(default=0.0, description="边界框右")
    bbox_b: float = Field(default=0.0, description="边界框下")

    captions: Optional[dict] = Field(
        default=None, sa_column=Column(JSON), description="图片标题(JSON)"
    )

    sort_order: int = Field(default=0, description="排序序号")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
