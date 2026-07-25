"""TeachingAgent 运行时日志模型。

持久化两类数据：
- ``AgentLearningEvent``：workflow 末尾记录的教学响应事件（teaching_agent_response），
  对齐 ``workflows/teaching.py`` 中 ``record_learning_event(event=...)`` 的 shape。
- ``AgentTraceRecord``：workflow 的完整执行 trace（replay），用于审计与回放，
  对齐 ``workflows/teaching.py`` 中 ``record_agent_trace(trace=...)`` 的 shape。

课程作用域：两张表都带 ``student_id`` + ``course_id`` 列，便于按课程隔离查询。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Field, SQLModel


class AgentLearningEvent(SQLModel, table=True):
    """TeachingAgent 教学响应事件（一条 respond 请求对应一条事件）。"""

    __tablename__ = "agent_learning_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True, max_length=128)
    student_id: int = Field(index=True)
    course_id: int = Field(index=True)
    session_id: str = Field(max_length=128)
    event_type: str = Field(default="teaching_agent_response", max_length=64)
    # 完整 event dict（含 teaching_action/warnings/errors/final_answer 等）
    event_data: str = Field(default="{}", description="JSON: 完整事件负载")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentTraceRecord(SQLModel, table=True):
    """TeachingAgent workflow 执行 trace（用于审计与回放）。"""

    __tablename__ = "agent_trace_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True, max_length=128)
    student_id: int = Field(index=True)
    course_id: int = Field(index=True)
    # 完整 trace dict（含 input/intent/concept_id/evidence/answer/citations/...）
    trace_data: str = Field(default="{}", description="JSON: 完整 trace 负载")
    created_at: datetime = Field(default_factory=datetime.utcnow)
