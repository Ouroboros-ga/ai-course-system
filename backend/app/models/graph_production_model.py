"""G9 Evidence 与课程知识图谱生产化 持久化模型

将已授权课件材料转换为可校验 Evidence，并发布教师可治理、学生可读的课程级 GraphSnapshot。

每个图谱关系可回溯 Evidence 或教师确认记录。
图谱、Evidence、引用和推荐均按课程隔离。
课件重新解析或删除时，历史引用不会静默指向错误内容。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


class SnapshotStatus(str, Enum):
    """快照状态"""
    DRAFT = "draft"
    PUBLISHED = "published"     # 学生可读
    SUPERSEDED = "superseded"   # 被新快照替代
    ROLLED_BACK = "rolled_back"


class EvidenceStatus(str, Enum):
    """证据状态"""
    ACTIVE = "active"
    STALE = "stale"             # 课件重新解析后标记为 stale
    ORPHANED = "orphaned"       # 课件删除后标记为 orphaned


class CourseEvidenceRecord(SQLModel, table=True):
    """课程证据持久化表

    将已授权课件材料转换为可校验 Evidence。
    包含页码/文本定位、版本和 stale 语义。
    每个图谱关系可回溯到此 Evidence 或教师确认记录。
    """

    __tablename__ = "course_evidence_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    evidence_id: str = Field(unique=True, index=True, description="UUID证据ID")
    course_id: int = Field(foreign_key="courses.id", index=True)

    # 来源信息
    document_id: Optional[str] = Field(default=None, index=True, description="课件文档UUID")
    source_file: str = Field(default="", description="来源文件名")

    # 定位信息（页码/文本定位）
    page_number: Optional[int] = Field(default=None, description="页码")
    char_start: Optional[int] = Field(default=None, description="字符起始位置")
    char_end: Optional[int] = Field(default=None, description="字符结束位置")
    text_snippet: str = Field(default="", description="原文片段(用于校验)")

    # 证据类型
    evidence_type: str = Field(default="document_extract", description="证据类型")

    # 版本与 stale 语义
    content_hash: str = Field(default="", index=True, description="内容哈希")
    status: EvidenceStatus = Field(default=EvidenceStatus.ACTIVE, index=True)
    stale_reason: str = Field(default="", description="stale原因(课件重新解析/删除)")
    stale_at: Optional[datetime] = Field(default=None, description="标记stale时间")

    # 审核
    reviewed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    reviewed_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow)


class GraphSnapshotRecord(SQLModel, table=True):
    """课程知识图谱快照

    发布不可变 GraphSnapshot，支持版本差异与回滚。
    学生只读已发布快照；内部检索轨迹继续受控。
    """

    __tablename__ = "graph_snapshot_records"
    __table_args__ = (
        UniqueConstraint(
            "course_id", "version", name="uq_graph_snapshot_course_version"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: str = Field(unique=True, index=True, description="UUID快照ID")
    course_id: int = Field(foreign_key="courses.id", index=True)

    # 快照内容（不可变 JSON）
    nodes: list = Field(default_factory=list, sa_column=Column(JSON), description="节点列表")
    relations: list = Field(default_factory=list, sa_column=Column(JSON), description="关系列表")

    # 版本
    version: int = Field(default=1, description="快照版本号")
    ontology_version: str = Field(default="edu-graph/1.0")
    prev_snapshot_id: Optional[str] = Field(default=None, description="前一版本快照ID")

    # 状态
    status: SnapshotStatus = Field(default=SnapshotStatus.DRAFT, index=True)
    is_active: bool = Field(default=False, index=True, description="是否为当前活跃快照")

    # 元数据
    label: str = Field(default="", description="快照标签")
    node_count: int = Field(default=0)
    relation_count: int = Field(default=0)

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = Field(default=None)


class GraphNodeReview(SQLModel, table=True):
    """图谱节点教师审核记录

    教师审核知识点、别名、映射、先修关系和冲突。
    每个图谱关系可回溯 Evidence 或教师确认记录。
    """

    __tablename__ = "graph_node_reviews"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    snapshot_id: Optional[str] = Field(default=None, index=True)

    # 审核目标
    target_id: str = Field(index=True, description="节点ID或关系ID")
    target_type: str = Field(default="node", description="node 或 relation")
    target_content_hash: str = Field(
        default="",
        index=True,
        description="审核时目标内容哈希，防止复用旧决定授权已变更关系",
    )

    # 审核决策
    decision: str = Field(default="proposed", description="proposed/accepted/rejected/needs_review")
    reviewer: Optional[int] = Field(default=None, foreign_key="users.id")
    review_comment: str = Field(default="")

    # 证据引用（accepted 节点必须有至少一个）
    evidence_ids: list = Field(default_factory=list, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=datetime.utcnow)
