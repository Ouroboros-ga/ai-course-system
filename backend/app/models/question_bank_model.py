"""Phase B 题库与题源映射数据模型。

核心数据契约：
- QuestionBankItem: 题目、答案、选项、难度、题型、课程归属、知识点、先修、状态、版本
- QuestionSourceMapping: 题目↔课件资源的映射，含OCR证据、图谱节点、AI理由、置信度、版本、内容哈希

状态流转：
  unassigned -> auto_accepted -> teacher_edited -> (published | rejected | stale)

Excel 导入的题目默认 unassigned，不可被学生检索或推荐。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class QuestionType(str, Enum):
    """题型"""
    SHORT_ANSWER = "short_answer"   # 简答题（Excel标准问答的主要类型）
    SINGLE_CHOICE = "single_choice"  # 单选
    MULTI_CHOICE = "multi_choice"    # 多选
    TRUE_FALSE = "true_false"        # 判断
    FILL_BLANK = "fill_blank"        # 填空
    ESSAY = "essay"                  # 论述


class QuestionDifficulty(str, Enum):
    """难度等级"""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuestionStatus(str, Enum):
    """题目状态

    - unassigned: 导入后待归属，无课程绑定，学生不可见
    - auto_accepted: EduAgent 自动映射生成，默认可信可发布
    - teacher_edited: 教师已手动编辑映射
    - published: 已发布到课程题库，学生可检索
    - rejected: 教师拒绝
    - stale: 课件或题目改动后需复核
    - draft: AI受约束生成的草稿，待教师审核
    """
    UNASSIGNED = "unassigned"
    AUTO_ACCEPTED = "auto_accepted"
    TEACHER_EDITED = "teacher_edited"
    PUBLISHED = "published"
    REJECTED = "rejected"
    STALE = "stale"
    DRAFT = "draft"


class MappingStatus(str, Enum):
    """题源映射状态

    - unassigned: 无映射
    - auto_accepted: OCR+EduAgent 自动生成，默认可信
    - teacher_edited: 教师已编辑
    - rejected: 教师拒绝
    - stale: 内容哈希变化后标记待复核
    - locked: 教师锁定，EduAgent重跑不可覆盖
    """
    UNASSIGNED = "unassigned"
    AUTO_ACCEPTED = "auto_accepted"
    TEACHER_EDITED = "teacher_edited"
    REJECTED = "rejected"
    STALE = "stale"
    LOCKED = "locked"


class QuestionBankItem(SQLModel, table=True):
    """题库题目表

    从 Excel 导入的题目默认 status=unassigned，course_id=None。
    教师将其分配到课程后，status 变为 auto_accepted 或 teacher_edited，
    最终 published 后学生可检索。
    每次教师修改生成新版本，旧版本通过 prev_version_id 链可追溯。
    """

    __tablename__ = "question_bank_items"

    id: Optional[int] = Field(default=None, primary_key=True)

    # 题目内容
    question_text: str = Field(description="题目内容")
    answer: str = Field(default="", description="标准答案")
    options: dict = Field(default_factory=dict, sa_column=Column(JSON), description="选项(选择题用)")
    similar_questions: list = Field(default_factory=list, sa_column=Column(JSON), description="相似问法列表")

    # 分类与元数据
    question_type: QuestionType = Field(default=QuestionType.SHORT_ANSWER, index=True)
    difficulty: QuestionDifficulty = Field(default=QuestionDifficulty.MEDIUM, index=True)
    category: str = Field(default="", index=True, description="规则分类(来自Excel)")
    match_mode: str = Field(default="", description="匹配模式(来自Excel)")
    rule_status: str = Field(default="", description="规则状态(来自Excel)")

    # 课程归属
    course_id: Optional[int] = Field(default=None, foreign_key="courses.id", index=True, description="课程ID(未归属为NULL)")
    knowledge_node_ids: list = Field(default_factory=list, sa_column=Column(JSON), description="知识点节点ID列表")
    prerequisite_node_ids: list = Field(default_factory=list, sa_column=Column(JSON), description="先修知识点ID列表")

    # 状态与版本
    status: QuestionStatus = Field(default=QuestionStatus.UNASSIGNED, index=True)
    version: int = Field(default=1, description="版本号，教师修改后递增")
    prev_version_id: Optional[int] = Field(default=None, description="前一版本的ID")
    is_latest: bool = Field(default=True, index=True, description="是否为最新版本")

    # 来源信息
    import_batch_id: Optional[str] = Field(default=None, index=True, description="导入批次ID")
    source_row_index: Optional[int] = Field(default=None, description="Excel行号")
    generated_by: str = Field(default="excel_import", description="来源: excel_import/ai_constrained/teacher_manual")
    generation_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON), description="AI生成元数据(六维适配理由等)")

    # 审计
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = Field(default=None, description="发布时间")
    published_by: Optional[int] = Field(default=None, foreign_key="users.id", description="发布人")


class QuestionSourceMapping(SQLModel, table=True):
    """题源映射表：题目↔课件资源的映射关系

    EduAgent 基于题目、答案、OCR页块、课程图谱生成映射候选。
    默认 status=auto_accepted，教师可编辑、锁定、拒绝或重跑。
    内容哈希用于检测课件或题目改动后自动标记 stale。
    """

    __tablename__ = "question_source_mappings"

    id: Optional[int] = Field(default=None, primary_key=True)

    # 关联
    question_id: int = Field(foreign_key="question_bank_items.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    document_id: Optional[str] = Field(default=None, index=True, description="课件文档ID(DocumentArtifact.document_id)")

    # 课件定位
    slide_file_name: Optional[str] = Field(default=None, description="课件文件名")
    page_start: Optional[int] = Field(default=None, description="起始页码")
    page_end: Optional[int] = Field(default=None, description="结束页码")

    # OCR 证据
    ocr_evidence: list = Field(default_factory=list, sa_column=Column(JSON), description="OCR证据片段列表")
    evidence_refs: list = Field(default_factory=list, sa_column=Column(JSON), description="证据引用引用(refs)")

    # 知识图谱
    knowledge_node_ids: list = Field(default_factory=list, sa_column=Column(JSON), description="关联图谱节点ID列表")

    # AI 映射理由
    mapping_reason: str = Field(default="", description="EduAgent映射理由")
    confidence: float = Field(default=0.0, description="置信度0-1")

    # 版本追踪
    model_version: str = Field(default="", description="EduAgent模型版本")
    ocr_version: str = Field(default="", description="OCR引擎版本")
    graph_version: str = Field(default="", description="图谱版本")
    content_hash: str = Field(default="", index=True, description="题目+课件内容哈希，用于检测stale")

    # 状态
    status: MappingStatus = Field(default=MappingStatus.AUTO_ACCEPTED, index=True)
    version: int = Field(default=1)
    prev_version_id: Optional[int] = Field(default=None, description="前一版本ID")
    is_latest: bool = Field(default=True, index=True)

    # 审计
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    locked_by: Optional[int] = Field(default=None, foreign_key="users.id", description="锁定人")
    locked_at: Optional[datetime] = Field(default=None, description="锁定时间")


class QuestionAttempt(SQLModel, table=True):
    """学生答题记录表（用于六维认知和推荐训练）"""

    __tablename__ = "question_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="question_bank_items.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    source_event_id: str = Field(
        default_factory=lambda: f"qe_{uuid.uuid4().hex}",
        index=True,
        unique=True,
        description="稳定来源事件ID",
    )
    measurement_role: str = Field(
        default="scored_performance",
        index=True,
        description="证据测量角色；交互状态不得写入表现轴",
    )
    question_version: int = Field(default=1, description="作答时题目版本快照")
    question_content_hash: str = Field(default="", description="作答时题干与答案版本哈希")

    student_answer: str = Field(default="")
    is_correct: Optional[bool] = Field(default=None, description="是否正确(None=待评判)")
    score: Optional[float] = Field(default=None, description="得分0-1")

    # 六维上下文快照
    cognitive_context: dict = Field(default_factory=dict, sa_column=Column(JSON), description="答题时的六维认知快照")

    # 评判
    judged_by: str = Field(default="teacher", description="评判方式: teacher/auto/peer")
    judge_feedback: str = Field(default="")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    judged_at: Optional[datetime] = Field(default=None)
