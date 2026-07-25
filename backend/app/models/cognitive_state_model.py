"""G2 六维认知状态与学习证据持久化模型

六维冻结为：
  observed_performance_score  -- 评分型显性证据聚合（不含提问次数/观看时长）
  evidence_confidence          -- 证据置信度（基于样本量）
  confusion_risk               -- 困惑风险（重复错误/纠正频率）
  inquiry_depth                -- 提问深度（不计入表现分）
  hint_dependency              -- 提示依赖度
  explanation_need             -- 解释需求度

复用已有领域模型：
  - app.domain.learning.evidence.LearningEvidence (内存计算)
  - app.domain.learning.mastery_state.MasteryState (内存计算)
  - app.domain.learning.recommendation.Recommendation (内存计算)
  - app.platform.mastery.rule_baseline.RuleBasedMasteryProvider (计算引擎)

本文件仅负责DB持久化，不重复领域模型定义。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


# 策略版本号，每次推荐策略变更时递增
COGNITIVE_POLICY_VERSION = "cognitive-policy-v1.1"


class CognitiveDimension(str, Enum):
    """六维认知维度枚举"""
    OBSERVED_PERFORMANCE = "observed_performance_score"
    EVIDENCE_CONFIDENCE = "evidence_confidence"
    CONFUSION_RISK = "confusion_risk"
    INQUIRY_DEPTH = "inquiry_depth"
    HINT_DEPENDENCY = "hint_dependency"
    EXPLANATION_NEED = "explanation_need"


class CognitiveStateValue(str, Enum):
    """认知维度值的定性标签"""
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CognitiveState(SQLModel, table=True):
    """学生六维认知状态表（课程+节点级）

    每次重新计算时生成新记录，旧记录保留用于趋势分析。
    数据不足时输出 unknown。
    不跨学生、课程读取或写入状态。
    """

    __tablename__ = "cognitive_states"

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    node_id: Optional[int] = Field(default=None, index=True, description="节点ID(空=课程级)")

    # 六维状态值 (0.0-1.0, None=数据不足/unknown)
    observed_performance_score: Optional[float] = Field(default=None, description="评分型显性表现")
    evidence_confidence: Optional[float] = Field(default=None, description="证据置信度")
    confusion_risk: Optional[float] = Field(default=None, description="困惑风险")
    inquiry_depth: Optional[float] = Field(default=None, description="提问深度(不计入表现分)")
    hint_dependency: Optional[float] = Field(default=None, description="提示依赖度")
    explanation_need: Optional[float] = Field(default=None, description="解释需求度")

    # 元数据
    mastery_level: str = Field(default="unknown", description="掌握度等级")
    mastery_score: Optional[float] = Field(default=None, description="掌握度分数0-1")
    policy_version: str = Field(default=COGNITIVE_POLICY_VERSION, description="计算策略版本")
    evidence_refs: list = Field(default_factory=list, sa_column=Column(JSON), description="支撑证据ID列表")
    reason_codes: list = Field(default_factory=list, sa_column=Column(JSON), description="计算原因码")
    sample_size: int = Field(default=0, description="样本量(答题数)")

    is_latest: bool = Field(default=True, index=True, description="是否为最新状态")
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LearningEvidenceRecord(SQLModel, table=True):
    """学习证据持久化表

    答题结果形成评分型 LearningEvidence，与交互状态分离。
    复用 app.domain.learning.evidence.EvidenceType 枚举值。
    """

    __tablename__ = "learning_evidence_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    evidence_id: str = Field(index=True, description="UUID证据ID(与领域模型一致)")
    student_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    node_id: Optional[int] = Field(default=None, index=True)

    evidence_type: str = Field(index=True, description="证据类型(EvidenceType枚举值)")
    value: Optional[float] = Field(default=None, description="数值(如正确率0.85)")
    confidence: float = Field(default=0.0, description="置信度0-1")
    label: str = Field(default="")
    description: str = Field(default="")
    source: str = Field(default="cognitive_service", description="来源组件")

    # 关联
    question_attempt_id: Optional[int] = Field(default=None, foreign_key="question_attempts.id", description="关联答题记录")
    event_refs: list = Field(default_factory=list, sa_column=Column(JSON), description="事件引用")

    policy_version: str = Field(default=COGNITIVE_POLICY_VERSION)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RecommendationRecord(SQLModel, table=True):
    """推荐记录持久化表

    每次推荐带 policy_version、reason_codes、evidence_refs。
    复用 app.domain.learning.recommendation.RecommendationType 枚举值。
    """

    __tablename__ = "recommendation_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    recommendation_id: str = Field(index=True, description="UUID推荐ID")
    student_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    node_id: Optional[int] = Field(default=None)

    recommendation_type: str = Field(index=True, description="推荐类型(RecommendationType枚举值)")
    priority: str = Field(default="low")
    title: str = Field(default="")
    description: str = Field(default="")

    # 可解释性
    policy_version: str = Field(default=COGNITIVE_POLICY_VERSION)
    reason_codes: list = Field(default_factory=list, sa_column=Column(JSON), description="推荐原因码")
    evidence_refs: list = Field(default_factory=list, sa_column=Column(JSON), description="支撑证据ID列表")

    # 推荐目标
    question_id: Optional[int] = Field(default=None, foreign_key="question_bank_items.id", description="推荐题目ID")
    knowledge_node_ids: list = Field(default_factory=list, sa_column=Column(JSON))

    # 六维上下文快照
    cognitive_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON), description="推荐时的六维状态快照")

    source: str = Field(default="recommendation_service")
    source_version: str = Field(default="1.0")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    consumed: bool = Field(default=False, description="学生是否已消费(答题/查看)")
    consumed_at: Optional[datetime] = Field(default=None)
