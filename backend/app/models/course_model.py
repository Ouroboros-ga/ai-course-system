from sqlmodel import SQLModel, Field, Relationship, JSON
from typing import Optional, List
from datetime import datetime
from enum import Enum
from sqlalchemy import Column

# --- 枚举定义 ---

class CourseStatus(str, Enum):
    """课程状态枚举"""
    DRAFT = "draft"  # 草稿
    PUBLISHED = "published"  # 已发布
    ARCHIVED = "archived"  # 已归档


class ScriptNodeType(str, Enum):
    """脚本节点类型枚举 (建议使用字符串以便 JSON 可读)"""
    LECTURE = "lecture"  # 讲解
    QUESTION = "question"  # 提问
    BREAKPOINT = "breakpoint"  # 断点
    SUMMARY = "summary"  # 总结
    VIDEO = "video"  # 视频


# --- 数据模型 ---

class Course(SQLModel, table=True):
    """课程主表：映射泛雅课程与本地智课"""
    __tablename__ = "courses"

    id: Optional[int] = Field(default=None, primary_key=True)

    # 泛雅平台映射字段
    fanya_course_id: str = Field(index=True, description="泛雅课程ID")
    fanya_course_name: str = Field(description="泛雅原始课程名称")

    # 本地智课字段
    title: str = Field(description="智课标题")
    description: Optional[str] = Field(default=None, description="课程描述")
    teacher_id: int = Field(foreign_key="users.id", description="所属教师ID")

    # 状态管理
    status: CourseStatus = Field(default=CourseStatus.DRAFT, description="课程状态")
    is_ai_generated: bool = Field(default=False, description="是否由AI生成")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # 关系定义
    scripts: List["CourseScript"] = Relationship(back_populates="course")
    progress_records: List["LearningProgress"] = Relationship(back_populates="course")


class CourseScript(SQLModel, table=True):
    """AI生成的结构化脚本表 (核心互动逻辑)"""
    __tablename__ = "course_scripts"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True, description="所属课程ID")

    version: int = Field(default=1, description="脚本版本号")

    # 核心：存储结构化 JSON 数据
    # 示例结构: [{"node_id": 1, "type": "lecture", "content": "...", "ppt_page": 1}, ...]
    script_content: dict = Field(
        ...,
        sa_column=Column(JSON,nullable=False),  # 关键！映射到数据库 JSON 类型
        description="结构化脚本内容"
    )

    summary_text: Optional[str] = Field(default=None, description="AI生成的课程摘要")
    is_active: bool = Field(default=True, description="是否为当前激活版本")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: int = Field(foreign_key="users.id", description="创建者/教师ID")

    # 关系定义
    course: Optional[Course] = Relationship(back_populates="scripts")


class LearningProgress(SQLModel, table=True):
    """学生学习进度追踪表 (断点续接核心)"""
    __tablename__ = "learning_progress"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(foreign_key="users.id", index=True, description="学生ID")
    course_id: int = Field(foreign_key="courses.id", index=True, description="课程ID")

    # 断点信息
    current_node_id: Optional[int] = Field(default=None, description="当前所在的脚本节点ID")
    current_timestamp: float = Field(default=0.0, description="当前视频/音频进度 (秒)")
    current_page: int = Field(default=1, description="当前PPT页码")

    # 统计信息
    completion_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="完成度 0.0-1.0")
    last_accessed_at: datetime = Field(default_factory=datetime.utcnow, description="最后访问时间")

    # 关系定义
    user: Optional["User"] = Relationship(back_populates="progress_records")  # 注意：这里引用了 User，需确保 user_model 已定义或处理循环导入
    course: Optional[Course] = Relationship(back_populates="progress_records")

# --- 注意：循环导入处理 ---
# 由于 LearningProgress 引用了 "User"，而 User 可能引用了 LearningProgress
# 最佳实践是将 Relationship 中的类型写为字符串 "User"，并在 user_model.py 中做同样处理。
# 如果 user_model.py 还没定义 progress_records 关系，请先暂时注释掉上面 LearningProgress 中的 user 关系，
# 或者在 user_model.py 中补全关系。