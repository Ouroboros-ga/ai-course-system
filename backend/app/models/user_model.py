from sqlmodel import SQLModel, Field, Relationship
from pydantic import field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum
import re

class UserRole(str, Enum):
    """
    用户角色枚举
    对应赛题要求：
    TEACHER: 负责上传课件、编辑脚本、生成智课
    STUDENT: 负责观看智课、实时问答、进度续接
    """
    TEACHER = "teacher"
    STUDENT = "student"

class User(SQLModel, table=True):
    """
    用户数据库表模型
    作为系统的身份核心，连接泛雅平台与 AI 功能模块
    """
    __tablename__ = "users" #或者使用 tablename: str = "users"

    # --- 主键 ---
    id: Optional[int] = Field(default=None, primary_key=True, description="系统内部唯一用户ID")

    # --- 基础身份信息 ---
    username: str = Field(
        index=True,
        unique=True,
        min_length=3,
        max_length=50,
        description="用户名 (支持泛雅账号同步或自定义)"
    )

    real_name: Optional[str] = Field(default=None, max_length=50, description="真实姓名 (用于教学管理)")

    email: Optional[str] = Field(
        default=None,
        sa_column_kwargs={
            "unique": True,
            "index": True
        },
        description="联系邮箱（支持教育机构邮箱如.edu.cn）"
    )

    # --- 泛雅平台集成关键字段 ---
    # 对应超星泛雅平台的原始用户ID (如学号/工号)，用于单点登录或数据同步
    fanya_account_id: Optional[str] = Field(
        default=None,
        index=True,
        unique=True,
        description="泛雅平台原始账号ID (学号/工号)"
    )

    # 标记该账号是否已通过泛雅平台验证
    is_fanya_verified: bool = Field(default=False, description="是否已通过泛雅平台身份认证")

    # --- 业务角色 ---
    role: UserRole = Field(
        default=UserRole.STUDENT,
        description="用户角色：teacher (课件生产者) 或 student (消费者)"
    )

    # --- 状态控制 ---
    is_active: bool = Field(default=True, description="账号是否激活 (软删除/封禁)")

    # --- 业务上下文辅助字段 (优化体验) ---
    # 记录用户最后学习的课程ID，用于"进度智能续接"功能的快速入口
    last_active_course_id: Optional[int] = Field(default=None, description="最后活跃的课程ID")

    # 记录用户最后学习的章节/节点，用于精确进度续接
    last_learning_node: Optional[str] = Field(default=None, description="最后学习的课件节点")

    # --- 时间戳 ---
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow(), description="账号创建时间")
    updated_at: Optional[datetime] = Field(default=None, description="最后更新时间")

    progress_records: List["LearningProgress"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"lazy": "selectin"}  # 可选：优化查询性能
    )

    # ==========================================
    # 3. 关系定义 (Relationships)
    # ==========================================
    # 教师创建的课件/智课列表 (一对多)
    # created_courses: List["Course"] = Relationship(back_populates="creator")

    # 学生的学习进度记录 (一对多)
    # learning_progresses: List["LearningProgress"] = Relationship(back_populates="student")

    # 学生的问答历史记录 (一对多)
    # qa_sessions: List["QASession"] = Relationship(back_populates="student")

    # ==========================================
    # 4. 业务逻辑方法
    # ==========================================


    @field_validator('email')
    def validate_email(cls, v):
        """验证邮箱格式（支持教育机构邮箱）"""
        if v is None:
            return v

        # 教育场景优化：支持.edu.cn等教育机构域名
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.(?:[a-zA-Z]{2,}|edu\.cn|com\.cn|net\.cn|org\.cn)$'
        if not re.match(pattern, v, re.IGNORECASE):
            raise ValueError('邮箱格式不正确，请使用有效的邮箱地址（支持教育机构邮箱如.edu.cn）')
        return v.lower()  # 统一转换为小写存储

    # def is_teacher(self) -> bool:
    #     """判断是否为教师 (权限控制用)"""
    #     return self.role == UserRole.TEACHER
    #
    # def is_student(self) -> bool:
    #     """判断是否为学生 (权限控制用)"""
    #     return self.role == UserRole.STUDENT
    #
    # def can_edit_script(self) -> bool:
    #     """
    #     业务规则：只有教师可以编辑智课脚本
    #     对应需求：提供教师脚本编辑功能
    #     """
    #     return self.is_teacher() and self.is_active
    #
    # def can_ask_question(self) -> bool:
    #     """
    #     业务规则：激活的学生可以发起实时问答
    #     对应需求：多模态实时问答
    #     """
    #     return self.is_student() and self.is_active
    #
    # def can_generate_intelligent_course(self) -> bool:
    #     """
    #     业务规则：只有教师可以生成智课
    #     对应需求：智课生成模块
    #     """
    #     return self.is_teacher() and self.is_active
    #
    # def can_access_course_content(self) -> bool:
    #     """
    #     业务规则：激活的学生可以访问课程内容
    #     对应需求：观看智课
    #     """
    #     return self.is_student() and self.is_active
    #
    # def get_user_type_display(self) -> str:
    #     """获取用户类型显示名称"""
    #     return "教师" if self.is_teacher() else "学生"
    #
    # def update_last_learning_position(self, course_id: int, node: str):
    #     """更新最后学习位置，用于进度续接功能"""
    #     self.last_active_course_id = course_id
    #     self.last_learning_node = node
    #     self.updated_at = datetime.utcnow()
