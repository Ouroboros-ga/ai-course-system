from __future__ import annotations

from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

from app.core.time_utils import utcnow_naive


class FeedbackType(str, Enum):
    """反馈类型"""
    MISSING_CITATION = "missing_citation"
    MATERIAL_REQUEST = "material_request"
    ERROR_REPORT = "error_report"
    OTHER = "other"


class FeedbackStatus(str, Enum):
    """反馈状态"""
    OPEN = "open"
    ADDRESSED = "addressed"
    CLOSED = "closed"


class Feedback(SQLModel, table=True):
    """学生向教师反馈表"""

    __tablename__ = "feedbacks"

    id: Optional[int] = Field(default=None, primary_key=True)
    from_user_id: int = Field(foreign_key="users.id", index=True)
    to_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    course_id: int = Field(foreign_key="courses.id", index=True)
    node_id: Optional[int] = Field(default=None)
    feedback_type: FeedbackType = Field(default=FeedbackType.OTHER)
    content: str = Field(default="")
    status: FeedbackStatus = Field(default=FeedbackStatus.OPEN)
    teacher_reply: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
