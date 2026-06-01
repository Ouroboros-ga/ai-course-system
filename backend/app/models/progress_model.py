from __future__ import annotations

from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class LearningStatus(str, Enum):
    """学习状态枚举"""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"


class UnderstandingLevel(str, Enum):
    """理解程度枚举"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXCELLENT = "excellent"


class LearningProgress(SQLModel, table=True):
    """
    学习进度表
    记录学生在课程中的学习进度，支持断点续接
    """

    __tablename__ = "learning_progress"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(foreign_key="users.id", index=True, description="学生ID")
    course_id: int = Field(foreign_key="courses.id", index=True, description="课程ID")
    script_id: Optional[int] = Field(
        default=None, foreign_key="course_scripts.id", description="当前学习的脚本ID"
    )

    current_node_id: Optional[int] = Field(
        default=None, description="当前所在的脚本节点ID"
    )
    current_node_index: int = Field(default=0, description="当前节点索引(用于快速定位)")

    current_timestamp: float = Field(default=0.0, description="当前视频/音频进度(秒)")
    current_page: int = Field(default=1, description="当前PPT页码")

    total_nodes: int = Field(default=0, description="脚本总节点数")
    completed_nodes: int = Field(default=0, description="已完成节点数")

    completion_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="完成度 0.0-1.0"
    )

    status: LearningStatus = Field(
        default=LearningStatus.NOT_STARTED, description="学习状态"
    )

    total_learning_time: int = Field(default=0, description="累计学习时间(秒)")
    session_count: int = Field(default=0, description="学习次数")

    last_accessed_at: datetime = Field(
        default_factory=datetime.utcnow, description="最后访问时间"
    )
    started_at: Optional[datetime] = Field(default=None, description="首次开始学习时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成学习时间")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")


class NodeProgress(SQLModel, table=True):
    """
    节点进度表
    记录每个脚本节点的详细学习情况
    """

    __tablename__ = "node_progress"

    id: Optional[int] = Field(default=None, primary_key=True)

    progress_id: int = Field(
        foreign_key="learning_progress.id", index=True, description="关联的学习进度ID"
    )

    node_id: int = Field(description="脚本节点ID")
    node_index: int = Field(description="节点索引")

    is_completed: bool = Field(default=False, description="是否已完成")
    completion_count: int = Field(default=0, description="完成次数(可重复学习)")

    time_spent: int = Field(default=0, description="在该节点花费的时间(秒)")
    last_timestamp: float = Field(default=0.0, description="最后播放进度(秒)")

    understanding_level: Optional[UnderstandingLevel] = Field(
        default=None, description="AI分析的理解程度"
    )
    understanding_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="理解分数(0-1)"
    )

    question_count: int = Field(default=0, description="该节点提问次数")
    correct_answer_rate: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="正确回答率"
    )

    first_accessed_at: Optional[datetime] = Field(default=None, description="首次访问时间")
    last_accessed_at: Optional[datetime] = Field(default=None, description="最后访问时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")


class UnderstandingAnalysis(SQLModel, table=True):
    """
    理解度分析表
    记录AI对学生理解程度的分析结果
    """

    __tablename__ = "understanding_analysis"

    id: Optional[int] = Field(default=None, primary_key=True)

    progress_id: int = Field(
        foreign_key="learning_progress.id", index=True, description="关联的学习进度ID"
    )
    node_id: Optional[int] = Field(default=None, description="关联的节点ID")
    message_id: Optional[int] = Field(
        default=None, foreign_key="qa_messages.id", description="关联的问答消息ID"
    )

    understanding_level: UnderstandingLevel = Field(description="理解程度等级")
    understanding_score: float = Field(ge=0.0, le=1.0, description="理解分数(0-1)")

    analysis_reason: str = Field(description="分析原因")
    suggestions: Optional[str] = Field(default=None, description="学习建议")

    keywords_mastered: Optional[str] = Field(
        default=None, description="已掌握的关键词(JSON数组)"
    )
    keywords_weak: Optional[str] = Field(
        default=None, description="薄弱的关键词(JSON数组)"
    )

    created_at: datetime = Field(default_factory=datetime.utcnow, description="分析时间")


class LearningJumpHistory(SQLModel, table=True):
    """
    学习跳转历史表
    记录学生因前置知识缺陷而触发的知识点跳转，支持多层跳转和返回原位置
    """
    __tablename__ = "learning_jump_history"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(index=True, description="学生ID")
    course_id: int = Field(index=True, description="课程ID")
    session_id: str = Field(description="学习会话ID（用于关联一次学习会话）")

    from_node_id: int = Field(description="跳出的源节点ID")
    from_node_title: str = Field(default="", description="跳出节点标题")
    from_node_index: int = Field(default=0, description="跳出节点索引位置")
    
    to_node_id: int = Field(description="跳转到的目标节点ID")
    to_node_title: str = Field(default="", description="目标节点标题")
    to_node_index: int = Field(default=0, description="目标节点索引位置")

    trigger_type: str = Field(
        default="prerequisite_gap",
        description="触发类型: prerequisite_gap/weak_understanding/manual/recommendation"
    )
    trigger_question: str = Field(default="", description="触发跳转的学生问题内容")
    analysis_result: Optional[str] = Field(
        default=None,
        description="AI分析结果JSON字符串"
    )

    prerequisite_ids: str = Field(
        default="",
        description="涉及的前置知识点ID列表，逗号分隔"
    )
    prerequisite_titles: str = Field(
        default="",
        description="涉及的前置知识点标题列表，逗号分隔"
    )
    gap_description: str = Field(
        default="",
        description="知识缺陷描述（如'需要掌握极限定义才能理解洛必达法则'）"
    )
    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="AI判断的置信度(0-1)"
    )
    urgency_level: str = Field(
        default="medium",
        description="紧急程度: high/medium/low"
    )

    is_returned: bool = Field(default=False, description="是否已返回原位置")
    returned_at: Optional[datetime] = Field(default=None, description="返回原位置的时间")
    review_completed: bool = Field(default=False, description="是否完成复习")
    review_duration_seconds: int = Field(default=0, description="复习耗时（秒）")

    parent_jump_id: Optional[int] = Field(
        default=None,
        foreign_key="learning_jump_history.id",
        description="父级跳转ID（用于支持多层嵌套跳转）"
    )
    jump_depth: int = Field(default=1, ge=1, le=10, description="当前跳转层级深度")

    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
