"""学习轨迹模型：每学生每课程追加型事件记录（M7）。

设计约束（AGENTS.md §5.1 / M7）：
- 追加型：只新增不更新，保留窗口内可审计；
- 只存数值 / 枚举 / ID / 简短快照，**绝不存问答原文、完整提示词或对话内容**
  （原文仍走 Conversation Domain）；
- ``dedup_key`` 支持幂等追加（如 trace_id / 事件唯一键）；
- ``payload`` 为 JSON 快照（只放数值指标与 ID）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class TrajectoryEventType(str):
    """学习轨迹事件类型（追加型，只增不改）。"""

    TEACHING_RESPONSE = "teaching_response"          # 教学问答完成（含教学动作/意图）
    QUESTION_ANSWERED = "question_answered"          # 答题完成（含正确性/表现）
    RECOMMENDATION_ISSUED = "recommendation_issued"  # 推荐下发（含类型/优先级）
    COGNITION_REFRESHED = "cognition_refreshed"      # 认知状态刷新（含六维快照）


class LearningTrajectoryRecord(SQLModel, table=True):
    __tablename__ = "learning_trajectory_records"

    id: int | None = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="users.id", index=True, description="学习者 ID")
    course_id: int = Field(foreign_key="courses.id", index=True, description="课程 ID")
    event_type: str = Field(index=True, description="事件类型（TrajectoryEventType）")
    concept_id: str | None = Field(
        default=None, index=True, description="关联知识点（node_key，可为空=课程级）"
    )
    dedup_key: str | None = Field(
        default=None, index=True, description="幂等键（如 trace_id）；重复追加时跳过"
    )
    payload: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="数值/枚举/ID 快照（不含原文）",
    )
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)


__all__ = ["LearningTrajectoryRecord", "TrajectoryEventType"]
