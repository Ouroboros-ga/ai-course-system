"""统一课程建设九步实施计划 Step 1：课程树、讲稿与备课 Agent 提案模型。

本文件固化 [统一课程建设九步实施计划](../../../docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md)
Step 1 的数据地基。核心原则：

- 课程树表示"教学目录与顺序"（chapter/section/knowledge_point/example/practice_suggestion）；
  与知识图谱（prerequisite/related/extends/... 网络关系）**绝不共用一张父子关系表**。
- 课程树节点是真正的有序树：``parent_node_id`` 是 FK 自引用，
  区别于旧 ``ScriptNode.chapter_id`` 字符串编码的伪层级。
- 教师修改生成新的草稿版本，不覆写已发布版本。
- 教师锁定内容后，AI 只能提建议（PatchProposal），不能覆盖。

所有表按 course_id 严格隔离；草稿与发布版本分离。
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
# 课程目录树：版本 + 节点
# ---------------------------------------------------------------------------


class OutlineLifecycleStatus(str, Enum):
    """课程目录版本生命周期。草稿与发布分离，发布不可变。"""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class OutlineNodeType(str, Enum):
    """课程目录节点类型（冻结为 5 种）。"""
    CHAPTER = "chapter"
    SECTION = "section"
    KNOWLEDGE_POINT = "knowledge_point"
    EXAMPLE = "example"
    PRACTICE_SUGGESTION = "practice_suggestion"


class CourseOutlineVersion(SQLModel, table=True):
    """课程目录版本：一个课程可同时存在草稿目录与已发布目录。

    教师每次确认/发布产生新版本；旧版本标记 archived，不删除。
    ``source_parse_run_id`` 追溯该版本由哪次解析产出。
    """

    __tablename__ = "course_outline_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    outline_version_id: str = Field(
        default_factory=lambda: f"ov_{uuid.uuid4().hex}",
        unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    version: int = Field(default=1, ge=1, description="该课程内递增的目录版本号")
    lifecycle_status: OutlineLifecycleStatus = Field(
        default=OutlineLifecycleStatus.DRAFT, index=True,
    )
    source_parse_run_id: Optional[str] = Field(
        default=None, index=True, description="产出该目录草稿的 DocumentParseRun.run_id",
    )
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)


class CourseOutlineNode(SQLModel, table=True):
    """课程目录节点：真正的有序树节点（区别于旧扁平 ScriptNode）。

    ``parent_node_id`` 为 FK 自引用，构成 chapter -> section -> knowledge_point 树。
    ``source_block_refs`` 保存该节点来源于哪些 DocumentBlock（可审计 Evidence 来源）。
    锁定后（locked_by 非空），AI Agent 不可覆盖该节点。
    """

    __tablename__ = "course_outline_nodes"
    __table_args__ = (
        UniqueConstraint(
            "outline_version_id", "order_index", "parent_node_id",
            name="uq_outline_node_order_within_parent",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    outline_node_id: str = Field(
        default_factory=lambda: f"on_{uuid.uuid4().hex}",
        unique=True, index=True,
    )
    outline_version_id: str = Field(
        index=True, description="关联 CourseOutlineVersion.outline_version_id",
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    parent_node_id: Optional[str] = Field(
        default=None, index=True,
        description="父节点 outline_node_id（FK 自引用，NULL=顶层章）",
    )
    node_type: OutlineNodeType = Field(default=OutlineNodeType.KNOWLEDGE_POINT, index=True)
    title: str = Field(default="", max_length=300)
    order_index: int = Field(default=0, description="同一父级下的显示顺序")

    # 可审计来源
    knowledge_graph_node_id: Optional[str] = Field(
        default=None, index=True, description="关联知识图谱节点（如有）",
    )
    source_block_refs: Optional[list] = Field(
        default=None, sa_column=Column(JSON),
        description="[DocumentBlock.block_id, ...] 节点内容来源",
    )
    page_range: Optional[str] = Field(default=None, max_length=64, description="如 3-5")
    generation_reason: str = Field(default="", description="AI 生成时的理由说明")
    confidence: float = Field(default=0.0, description="生成置信度 0..1")
    content_hash: str = Field(default="", index=True, description="节点内容哈希")

    # 教师锁定：锁定后 AI 不可覆盖
    locked_by: Optional[int] = Field(default=None, foreign_key="users.id")
    locked_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class CoursePptMapping(SQLModel, table=True):
    """课程树节点与某一份 PPT 材料版本的独立映射。

    ``CourseOutlineNode.page_range`` 仅保留为兼容/摘要字段；正式学生播放、
    教师审核和发布快照均以本表为准。一个节点可以对应多个不连续页面。
    """

    __tablename__ = "course_ppt_mappings"

    id: Optional[int] = Field(default=None, primary_key=True)
    mapping_id: str = Field(default_factory=lambda: f"pm_{uuid.uuid4().hex}", unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    outline_node_id: str = Field(index=True)
    material_version_id: Optional[str] = Field(default=None, index=True)
    page_start: int = Field(default=1, ge=1)
    page_end: int = Field(default=1, ge=1)
    page_refs: list = Field(default_factory=list, sa_column=Column(JSON))
    confidence: float = Field(default=0.0, ge=0, le=1)
    source_block_refs: list = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="draft", index=True, description="draft|published|stale|rejected")
    teacher_locked: bool = Field(default=False, index=True)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    updated_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 讲授脚本：版本 + 节点（按课程树组织，非旧扁平 ScriptNode）
# ---------------------------------------------------------------------------


class TeachingScriptVersion(SQLModel, table=True):
    """讲授脚本版本：与 CourseOutlineVersion 对齐。

    目录与讲稿的发布状态必须一致：学生只读已发布版本。
    """

    __tablename__ = "teaching_script_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    script_version_id: str = Field(
        default_factory=lambda: f"tsv_{uuid.uuid4().hex}",
        unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    outline_version_id: str = Field(
        index=True, description="对齐的 CourseOutlineVersion.outline_version_id",
    )
    version: int = Field(default=1, ge=1)
    lifecycle_status: OutlineLifecycleStatus = Field(
        default=OutlineLifecycleStatus.DRAFT, index=True,
    )
    source_parse_run_id: Optional[str] = Field(default=None, index=True)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)


class TeachingScriptNode(SQLModel, table=True):
    """讲授脚本节点：按 CourseOutlineNode 组织。

    一个课程树节点对应一段讲稿；锁定后 AI 不可覆盖。
    ``evidence_refs`` / ``source_block_refs`` 保留可审计引用。
    """

    __tablename__ = "teaching_script_nodes"

    id: Optional[int] = Field(default=None, primary_key=True)
    script_node_id: str = Field(
        default_factory=lambda: f"tsn_{uuid.uuid4().hex}",
        unique=True, index=True,
    )
    script_version_id: str = Field(index=True, description="关联 TeachingScriptVersion.script_version_id")
    course_id: int = Field(foreign_key="courses.id", index=True)
    outline_node_id: str = Field(
        index=True, description="关联 CourseOutlineNode.outline_node_id",
    )

    content: str = Field(default="", description="讲稿正文（Markdown）")
    style: str = Field(default="", max_length=64, description="解释风格，如 beginner/academic/concise")

    evidence_refs: Optional[list] = Field(
        default=None, sa_column=Column(JSON),
        description="[EvidenceSpan.span_id, ...] 引用的证据",
    )
    source_block_refs: Optional[list] = Field(
        default=None, sa_column=Column(JSON),
        description="[DocumentBlock.block_id, ...] 内容来源",
    )
    content_hash: str = Field(default="", index=True)

    # 教师锁定
    locked_by: Optional[int] = Field(default=None, foreign_key="users.id")
    locked_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 备课 Agent 提案：PatchProposal + 操作
# ---------------------------------------------------------------------------


class PatchProposalStatus(str, Enum):
    """提案状态：教师接受/拒绝前为 pending。"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIALLY_ACCEPTED = "partially_accepted"
    EXPIRED = "expired"


class PatchOperation(str, Enum):
    """提案操作类型。"""
    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"
    MOVE = "move"
    REORDER = "reorder"


class PatchProposal(SQLModel, table=True):
    """备课 Agent 提案：Agent 不直接 UPDATE 课程表/脚本表，只产 Proposal。

    教师逐项或批量接受/拒绝；接受后写入新草稿版本。
    WebSearch 内容必须带"外部补充资料"标识，不能成为课程 Evidence。
    """

    __tablename__ = "patch_proposals"

    id: Optional[int] = Field(default=None, primary_key=True)
    proposal_id: str = Field(
        default_factory=lambda: f"pp_{uuid.uuid4().hex}",
        unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    tool_name: str = Field(default="", max_length=64, index=True,
                           description="OutlineProposalTool/ScriptProposalTool/...")
    policy_version: str = Field(default="", max_length=32, description="生成时的策略版本")
    status: PatchProposalStatus = Field(
        default=PatchProposalStatus.PENDING, index=True,
    )
    reason: str = Field(default="", description="提案整体理由")
    created_by: Optional[int] = Field(default=None, foreign_key="users.id", description="发起 Agent 关联的用户")
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)
    decided_by: Optional[int] = Field(default=None, foreign_key="users.id")
    decided_at: Optional[datetime] = Field(default=None)


class PatchProposalOperation(SQLModel, table=True):
    """提案操作项：每个 Proposal 含若干结构化操作。

    ``before``/``after`` 用于前端 Diff（新增绿框、删除红框、修改 before/after）。
    ``evidence_refs`` 必须指向课程 Evidence；外网资料不得进入此字段。
    """

    __tablename__ = "patch_proposal_operations"

    id: Optional[int] = Field(default=None, primary_key=True)
    op_id: str = Field(
        default_factory=lambda: f"po_{uuid.uuid4().hex}",
        unique=True, index=True,
    )
    proposal_id: str = Field(
        index=True, description="关联 PatchProposal.proposal_id",
    )
    course_id: int = Field(foreign_key="courses.id", index=True)

    operation: PatchOperation = Field(default=PatchOperation.REPLACE, index=True)
    target: str = Field(default="", max_length=300,
                        description="操作目标，如 outline_node_12.title 或 script_node_12.content")
    before: str = Field(default="", description="原内容（Diff 用，JSON 字符串）")
    after: str = Field(default="", description="建议内容（Diff 用，JSON 字符串）")
    reason: str = Field(default="", description="单项理由")
    evidence_refs: Optional[list] = Field(
        default=None, sa_column=Column(JSON),
        description="[EvidenceSpan.span_id, ...] 仅课程 Evidence，不含外网资料",
    )
    external_ref: Optional[str] = Field(
        default=None, max_length=300,
        description="若依据外网资料，记录其 URL 并标'外部补充资料'，不进入 evidence_refs",
    )
    policy_version: str = Field(default="", max_length=32)

    accepted: Optional[bool] = Field(default=None, description="教师对该操作的逐项决定（NULL=未决）")
    decided_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_aware)
