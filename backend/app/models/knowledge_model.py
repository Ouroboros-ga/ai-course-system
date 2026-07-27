"""
知识库模型
多学科知识数据库的核心数据结构
"""

from __future__ import annotations

from sqlmodel import SQLModel, Field, JSON, Column, Text
from typing import Optional, List
from datetime import datetime
from enum import Enum

from app.core.time_utils import utcnow_aware


class SubjectType(str, Enum):
    """学科类型枚举"""
    MATH = "math"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    BIOLOGY = "biology"
    COMPUTER = "computer"
    CHINESE = "chinese"
    ENGLISH = "english"
    HISTORY = "history"
    GEOGRAPHY = "geography"
    POLITICS = "politics"
    GENERAL = "general"


class KnowledgeLevel(str, Enum):
    """知识难度等级"""
    PRIMARY = "primary"
    JUNIOR = "junior"
    SENIOR = "senior"
    COLLEGE = "college"
    GRADUATE = "graduate"


class KnowledgePointType(str, Enum):
    """知识点类型"""
    CONCEPT = "concept"
    FORMULA = "formula"
    THEOREM = "theorem"
    EXAMPLE = "example"
    EXERCISE = "exercise"
    SUMMARY = "summary"
    EXTENSION = "extension"


class KnowledgeBase(SQLModel, table=True):
    """
    知识库主表
    每个学科对应一个知识库
    """
    __tablename__ = "knowledge_bases"

    id: Optional[int] = Field(default=None, primary_key=True)

    name: str = Field(description="知识库名称", max_length=100)
    subject: SubjectType = Field(description="学科类型")
    description: Optional[str] = Field(default=None, description="知识库描述")

    level: KnowledgeLevel = Field(
        default=KnowledgeLevel.SENIOR,
        description="适用难度等级"
    )

    total_points: int = Field(default=0, description="知识点总数")
    total_relations: int = Field(default=0, description="知识点关系总数")

    is_active: bool = Field(default=True, description="是否启用")
    is_public: bool = Field(default=True, description="是否公开")

    created_by: Optional[int] = Field(default=None, description="创建者ID")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)

    config: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="知识库配置(JSON)"
    )


class KnowledgePoint(SQLModel, table=True):
    """
    知识点表
    存储具体的知识点内容
    """
    __tablename__ = "knowledge_points"

    id: Optional[int] = Field(default=None, primary_key=True)

    kb_id: int = Field(foreign_key="knowledge_bases.id", index=True, description="所属知识库ID")

    point_id: str = Field(
        unique=True,
        index=True,
        description="知识点唯一标识，如 KP_MATH_001",
        max_length=50
    )

    title: str = Field(description="知识点标题", max_length=200)
    content: str = Field(sa_column=Column(Text), description="知识点内容")

    point_type: KnowledgePointType = Field(
        default=KnowledgePointType.CONCEPT,
        description="知识点类型"
    )

    parent_id: Optional[int] = Field(
        default=None,
        foreign_key="knowledge_points.id",
        description="父知识点ID（支持层级结构）"
    )

    level: int = Field(default=1, description="知识点层级，1为顶级")

    keywords: str = Field(default="", description="关键词，逗号分隔")
    tags: str = Field(default="", description="标签，逗号分隔")

    difficulty: int = Field(default=3, ge=1, le=5, description="难度等级1-5")
    importance: int = Field(default=3, ge=1, le=5, description="重要程度1-5")

    examples: dict = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="示例列表(JSON)"
    )

    related_formulas: dict = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="相关公式(JSON)"
    )

    prerequisites: str = Field(
        default="",
        description="前置知识点ID列表，逗号分隔"
    )

    source: Optional[str] = Field(default=None, description="知识来源")
    source_url: Optional[str] = Field(default=None, description="来源URL")

    view_count: int = Field(default=0, description="查看次数")
    reference_count: int = Field(default=0, description="被引用次数")

    embedding: Optional[bytes] = Field(default=None, description="向量嵌入(序列化)")

    is_active: bool = Field(default=True, description="是否启用")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class KnowledgeRelation(SQLModel, table=True):
    """
    知识点关系表
    存储知识点之间的关联关系
    """
    __tablename__ = "knowledge_relations"

    id: Optional[int] = Field(default=None, primary_key=True)

    source_id: int = Field(
        foreign_key="knowledge_points.id",
        index=True,
        description="源知识点ID"
    )
    target_id: int = Field(
        foreign_key="knowledge_points.id",
        index=True,
        description="目标知识点ID"
    )

    relation_type: str = Field(
        description="关系类型: prerequisite/related/extends/applies_to"
    )

    weight: float = Field(default=1.0, ge=0, le=1, description="关系权重")

    description: Optional[str] = Field(default=None, description="关系描述")

    created_at: datetime = Field(default_factory=utcnow_aware)


class KnowledgeImportLog(SQLModel, table=True):
    """
    知识库导入日志表
    记录批量导入操作
    """
    __tablename__ = "knowledge_import_logs"

    id: Optional[int] = Field(default=None, primary_key=True)

    kb_id: int = Field(foreign_key="knowledge_bases.id", description="知识库ID")

    file_name: str = Field(description="导入文件名")
    file_path: Optional[str] = Field(default=None, description="文件路径")

    total_points: int = Field(default=0, description="导入知识点数量")
    success_count: int = Field(default=0, description="成功数量")
    fail_count: int = Field(default=0, description="失败数量")

    status: str = Field(default="pending", description="状态: pending/processing/completed/failed")
    error_message: Optional[str] = Field(default=None, description="错误信息")

    created_by: Optional[int] = Field(default=None, description="操作者ID")
    created_at: datetime = Field(default_factory=utcnow_aware)
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")


class KnowledgeSearchHistory(SQLModel, table=True):
    """
    知识搜索历史表
    记录用户搜索行为，用于优化检索
    """
    __tablename__ = "knowledge_search_history"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(index=True, description="用户ID")
    kb_id: Optional[int] = Field(default=None, foreign_key="knowledge_bases.id", description="知识库ID")

    query: str = Field(description="搜索查询", max_length=500)
    subject: Optional[SubjectType] = Field(default=None, description="学科")

    result_count: int = Field(default=0, description="结果数量")
    clicked_points: str = Field(default="", description="点击的知识点ID列表")

    created_at: datetime = Field(default_factory=utcnow_aware)
