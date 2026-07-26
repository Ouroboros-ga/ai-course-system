from __future__ import annotations

from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

from app.core.time_utils import utcnow_naive


class ConfirmationType(str, Enum):
    """确认类型"""
    STRUCTURE = "structure"
    MAPPING = "mapping"
    CITATION = "citation"


class ConfirmationStatus(str, Enum):
    """确认状态"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class CourseConfirmation(SQLModel, table=True):
    """课程确认记录表"""

    __tablename__ = "course_confirmations"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    confirmation_type: ConfirmationType = Field(default=ConfirmationType.MAPPING)
    target_id: Optional[int] = Field(default=None, description="被确认对象的ID（如node_id/map_id）")
    status: ConfirmationStatus = Field(default=ConfirmationStatus.PENDING)
    confirmed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    confirmed_at: Optional[datetime] = Field(default=None)
    notes: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
