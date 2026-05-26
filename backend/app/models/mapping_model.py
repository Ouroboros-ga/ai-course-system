"""
知识点↔PPT页面映射数据模型
建立知识点与PPT页面的双向对应关系
"""

from __future__ import annotations

from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class KnowledgePageMap(SQLModel, table=True):
    """
    知识点↔PPT页面映射表
    记录每个脚本节点（知识点）与PPT页面的对应关系
    """

    __tablename__ = "knowledge_page_maps"

    id: Optional[int] = Field(default=None, primary_key=True)

    course_id: int = Field(
        foreign_key="courses.id", index=True, description="所属课程ID"
    )

    script_id: int = Field(
        foreign_key="course_scripts.id", index=True, description="所属脚本ID"
    )

    node_id: int = Field(
        foreign_key="script_nodes.id", index=True, description="关联的脚本节点ID（知识点）"
    )

    page_start: int = Field(description="PPT起始页码（从1开始）")
    page_end: int = Field(description="PPT结束页码")

    confidence: float = Field(
        default=0.0, description="AI匹配置信度(0-1)，手动调整后设为1.0"
    )

    is_manual: bool = Field(
        default=False, description="是否经过手动调整"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="创建时间"
    )

    updated_at: Optional[datetime] = Field(
        default=None, description="最后更新时间"
    )
