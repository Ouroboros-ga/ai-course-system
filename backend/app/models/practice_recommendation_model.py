"""阶段5 题库导入、AI 生成草稿、个性化练习推荐与正式学习证据链接 持久化模型

完成"题库优先检索 → 无匹配题则约束生成草稿 → 教师审核/发布"的编排链路。
将判分后的 Quiz/实验完成等写入正式 LearningEvent / LearningEvidence 契约（复用既有
LearningEvidenceRecord），本模块负责"推荐运行"和"证据链接"的额外追踪。

设计要点：
- `QuestionImportRun` 跟踪 Excel 导入批次，可审计、可回放、可失败恢复。
- `QuestionGenerationDraft` 保存 AI 约束生成草稿，**不可直接面向学生发布**，必须经教师审核
  升级为 QuestionBankItem 后才能进入推荐池。
- `QuestionRecommendationRun` / `QuestionRecommendationItem` 跟踪一次推荐运行的输入快照、
  推荐项与来源（bank|generated_draft），承载 `policy_version, reason_codes, evidence_refs,
  confidence, six_dimensions`，便于审计与回放。
- `AssessmentPolicy` 评分策略版本化，承载诊断题/补弱题/提示撤除题/解释后核验题的策略元数据。
- `LearningEvidenceLink` 将 LearningEvidenceRecord 链接到推荐运行、题目尝试、动作完成等上下文，
  便于"为什么这条证据被采纳"的追溯，不重复存储证据本体。

所有表按 course_id 严格隔离，绝不跨课程暴露。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_naive


# ---------------------------------------------------------------------------
# 题库导入运行
# ---------------------------------------------------------------------------


class ImportRunStatus(str, Enum):
    """导入运行状态机"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"
    CANCELLED = "cancelled"


class QuestionImportRun(SQLModel, table=True):
    """Excel 题库导入批次

    - 一次导入可产生多个 QuestionBankItem（status=auto_accepted 或 unassigned）
    - 导入失败可恢复：通过 task_id 关联任务中心，重试不重复入库
    - 导入批次ID写入 QuestionBankItem.import_batch_id 便于回溯
    """

    __tablename__ = "question_import_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(default_factory=lambda: "qir_" + __import__("uuid").uuid4().hex,
                        unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    task_id: Optional[str] = Field(default=None, index=True,
                                   description="关联 TaskRecord.task_id")
    source_file: str = Field(default="", description="Excel 文件名")
    source_object_key: str = Field(default="", description="本地/OSS 对象键")
    total_rows: int = Field(default=0, description="Excel 总行数")
    imported_count: int = Field(default=0)
    skipped_count: int = Field(default=0, description="重复/格式错误跳过数")
    failed_count: int = Field(default=0)
    status: ImportRunStatus = Field(default=ImportRunStatus.PENDING, index=True)
    error_code: str = Field(default="")
    error_message: str = Field(default="")
    failure_details: list = Field(default_factory=list, sa_column=Column(JSON),
                                  description="行级失败明细 [{row, reason}]")
    initiated_by: int = Field(foreign_key="users.id")
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# AI 约束生成草稿
# ---------------------------------------------------------------------------


class GenerationDraftStatus(str, Enum):
    """生成草稿状态：不可直接面向学生发布"""
    DRAFT = "draft"                  # 草稿，待教师审核
    APPROVED = "approved"            # 教师通过，已升级为 QuestionBankItem
    REJECTED = "rejected"            # 教师拒绝
    STALE = "stale"                  # 上下文（图谱/认知状态）变化后标记


class QuestionGenerationDraft(SQLModel, table=True):
    """AI 约束生成草稿

    严格规则：
    - **不可直接面向学生发布**，必须经教师审核升级为 QuestionBankItem
    - 升级时生成新 QuestionBankItem（status=published 或 teacher_edited）
    - 草稿保留生成时的认知快照、reason_codes、evidence_refs，便于审计
    - 上下文（图谱/认知状态）变化后标记为 stale，提示教师复核
    """

    __tablename__ = "question_generation_drafts"

    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: str = Field(default_factory=lambda: "qgd_" + __import__("uuid").uuid4().hex,
                          unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    node_id: Optional[int] = Field(default=None, index=True, description="目标知识点")
    question_type: str = Field(default="short_answer", index=True)
    question_text: str = Field(default="")
    answer: str = Field(default="")
    options: list = Field(default_factory=list, sa_column=Column(JSON))
    difficulty: str = Field(default="medium")
    category: str = Field(default="")
    generation_purpose: str = Field(default="diagnose",
                                    description="diagnose/remediation/hint_withdrawal/post_explanation")
    # 推荐上下文快照
    cognitive_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON),
                                     description="六维认知状态快照")
    six_dimensions: dict = Field(default_factory=dict, sa_column=Column(JSON),
                                 description="推荐时的六维诊断")
    reason_codes: list = Field(default_factory=list, sa_column=Column(JSON))
    evidence_refs: list = Field(default_factory=list, sa_column=Column(JSON))
    confidence: float = Field(default=0.0, description="生成置信度 0..1")
    policy_version: str = Field(default="recommendation-policy-v1.0")
    model_version: str = Field(default="question-gen-v1.0")
    # 审核流
    status: GenerationDraftStatus = Field(default=GenerationDraftStatus.DRAFT, index=True)
    reviewed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    reviewed_at: Optional[datetime] = Field(default=None)
    review_comment: str = Field(default="")
    upgraded_question_id: Optional[int] = Field(default=None, index=True,
                                                description="升级后生成的 QuestionBankItem.id")
    stale_reason: str = Field(default="")
    stale_at: Optional[datetime] = Field(default=None)
    generated_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# 推荐运行与推荐项
# ---------------------------------------------------------------------------


class RecommendationRunStatus(str, Enum):
    """推荐运行状态"""
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


class QuestionRecommendationRun(SQLModel, table=True):
    """一次推荐运行

    一次推荐运行可能产生多个推荐项（diagnose/remediation/hint_withdrawal/post_explanation）。
    承载 policy_version, six_dimensions, reason_codes, evidence_refs, confidence 等可解释字段。
    """

    __tablename__ = "question_recommendation_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(default_factory=lambda: "qrr_" + __import__("uuid").uuid4().hex,
                        unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    node_id: Optional[int] = Field(default=None, index=True, description="目标知识点，可空")
    recommendation_id: str = Field(unique=True, index=True,
                                   description="对外暴露的推荐ID，与 RecommendationRecord 对齐")
    purpose: str = Field(default="diagnose",
                         description="diagnose/remediation/hint_withdrawal/post_explanation")
    policy_version: str = Field(default="recommendation-policy-v1.0")
    six_dimensions: dict = Field(default_factory=dict, sa_column=Column(JSON))
    reason_codes: list = Field(default_factory=list, sa_column=Column(JSON))
    evidence_refs: list = Field(default_factory=list, sa_column=Column(JSON))
    confidence: float = Field(default=0.0)
    cognitive_state_id: Optional[int] = Field(default=None, index=True,
                                              description="关联 CognitiveState.id 快照")
    status: RecommendationRunStatus = Field(default=RecommendationRunStatus.PENDING, index=True)
    item_count: int = Field(default=0)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class QuestionSource(str, Enum):
    """推荐项题目来源"""
    BANK = "bank"                      # 题库命中
    GENERATED_DRAFT = "generated_draft"  # AI 生成草稿（不直接对学生发布）


class QuestionRecommendationItem(SQLModel, table=True):
    """推荐项：单道题的推荐明细

    - question_source=bank: 直接命中已发布题库题
    - question_source=generated_draft: AI 生成草稿，**不可直接面向学生发布**，
      教师审核升级后才转为正式题目进入学生可见池
    """

    __tablename__ = "question_recommendation_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: str = Field(default_factory=lambda: "qri_" + __import__("uuid").uuid4().hex,
                         unique=True, index=True)
    run_id: str = Field(foreign_key="question_recommendation_runs.run_id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    recommendation_id: str = Field(index=True, description="冗余运行ID便于查询")
    question_source: QuestionSource = Field(default=QuestionSource.BANK, index=True)
    question_id: Optional[int] = Field(default=None, index=True,
                                       description="已发布题库题ID")
    generation_draft_id: Optional[str] = Field(default=None, index=True,
                                               description="AI 草稿ID")
    node_id: Optional[int] = Field(default=None, index=True)
    reason_codes: list = Field(default_factory=list, sa_column=Column(JSON))
    evidence_refs: list = Field(default_factory=list, sa_column=Column(JSON))
    confidence: float = Field(default=0.0)
    order_index: int = Field(default=0)
    is_started: bool = Field(default=False, description="学生是否已开始作答")
    started_at: Optional[datetime] = Field(default=None)
    is_consumed: bool = Field(default=False, description="是否已转化成 attempt")
    consumed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# 评分策略版本化
# ---------------------------------------------------------------------------


class AssessmentPurpose(str, Enum):
    """评估目的：与六维认知诊断对齐"""
    DIAGNOSE = "diagnose"                       # 诊断题
    REMEDIATION = "remediation"                 # 补弱题
    HINT_WITHDRAWAL = "hint_withdrawal"         # 提示撤除题
    POST_EXPLANATION = "post_explanation"       # 解释后核验题
    SUMMATIVE = "summative"                     # 总结性评估


class AssessmentPolicy(SQLModel, table=True):
    """评分策略版本化

    - 不同 purpose 用不同策略（及格线、置信度阈值、是否写入正式证据）
    - 策略版本变化不破坏历史推荐；老推荐保留旧 policy_version
    - 仅 summative/diagnose 写入正式 LearningEvidence；hint_withdrawal 等仅记录交互
    - 按 course_id 严格隔离：课程 A 的策略不会出现在课程 B 列表中
    """

    __tablename__ = "assessment_policies"
    __table_args__ = (
        UniqueConstraint(
            "course_id", "purpose", "policy_version",
            name="uq_assessment_policy_course_purpose_version",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    policy_id: str = Field(default_factory=lambda: "ap_" + __import__("uuid").uuid4().hex,
                           unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True,
                           description="所属课程；策略与课程严格隔离")
    purpose: AssessmentPurpose = Field(index=True)
    policy_version: str = Field(default="assessment-policy-v1.0")
    passing_score: float = Field(default=0.6, description="及格分 0..1")
    confidence_threshold: float = Field(default=0.5, description="低置信度阈值")
    writes_formal_evidence: bool = Field(default=True,
                                         description="是否写入正式 LearningEvidence")
    max_attempts_per_node: int = Field(default=3)
    cooldown_minutes: int = Field(default=30, description="同节点推荐冷却")
    rules: dict = Field(default_factory=dict, sa_column=Column(JSON),
                        description="策略规则元数据")
    is_active: bool = Field(default=True, index=True)
    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# 学习证据链接
# ---------------------------------------------------------------------------


class EvidenceLinkContext(str, Enum):
    """证据链接上下文类型"""
    RECOMMENDATION = "recommendation"     # 推荐运行
    QUESTION_ATTEMPT = "question_attempt"  # 题目作答
    LEARNING_ACTION = "learning_action"    # 学习动作完成
    EXPERIMENT_FINALIZE = "experiment_finalize"  # 实验评分


class LearningEvidenceLink(SQLModel, table=True):
    """学习证据链接：将 LearningEvidenceRecord 链接到具体上下文

    用于"为什么这条证据被采纳"的追溯，不重复存储证据本体。
    一条 LearningEvidenceRecord 可被多个上下文引用。
    """

    __tablename__ = "learning_evidence_links"

    id: Optional[int] = Field(default=None, primary_key=True)
    link_id: str = Field(default_factory=lambda: "lel_" + __import__("uuid").uuid4().hex,
                         unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    evidence_id: str = Field(index=True, description="关联 LearningEvidenceRecord.evidence_id")
    context_type: EvidenceLinkContext = Field(index=True)
    context_id: str = Field(index=True, description="上下文实体ID（推荐ID/attemptID/actionID）")
    context_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON),
                                   description="上下文快照（reason_codes, score 等）")
    linked_at: datetime = Field(default_factory=utcnow_naive)
    created_at: datetime = Field(default_factory=utcnow_naive)
