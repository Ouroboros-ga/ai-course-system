"""G4 VisualizationPlan 持久化模型

每个动画可回放，并能关联课程、知识点和返回锚点。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_naive


class VisualizationStatus(str, Enum):
    """可视化计划状态"""
    DRAFT = "draft"        # 草稿，待验证
    VALIDATED = "validated"  # 已验证，可使用
    REJECTED = "rejected"    # 验证失败
    PUBLISHED = "published"  # 已发布给学生
    ARCHIVED = "archived"    # 已归档


class VisualizationPlanRecord(SQLModel, table=True):
    """可视化计划持久化表

    存储经过验证的 VisualizationPlan JSON，支持回放。
    关联课程和知识点，可返回锚点。
    """

    __tablename__ = "visualization_plan_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: str = Field(index=True, description="UUID计划ID")
    course_id: int = Field(foreign_key="courses.id", index=True)
    node_id: Optional[int] = Field(default=None, index=True, description="关联知识点节点ID")

    # 算法信息
    algorithm_id: str = Field(index=True, description="算法标识(白名单内)")
    algorithm_name: str = Field(default="", description="算法名称")

    # 计划内容（经过验证和净化的 JSON）
    plan_data: dict = Field(default_factory=dict, sa_column=Column(JSON), description="VisualizationPlan JSON")
    plan_version: str = Field(default="viz-plan-v1.0", description="计划版本")

    # 返回锚点
    return_anchor_node_id: Optional[int] = Field(default=None, description="返回锚点节点ID")
    return_anchor_label: str = Field(default="", description="返回锚点标签")

    # 状态
    status: VisualizationStatus = Field(default=VisualizationStatus.DRAFT, index=True)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
    published_at: Optional[datetime] = Field(default=None)

    # 回放统计
    play_count: int = Field(default=0, description="回放次数")
    last_played_at: Optional[datetime] = Field(default=None)
