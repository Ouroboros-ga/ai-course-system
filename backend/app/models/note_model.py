from __future__ import annotations

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
from typing import Optional
from datetime import datetime
from enum import Enum

from app.core.time_utils import utcnow_aware


class NoteTriggerSource(str, Enum):
    """笔记触发来源"""
    LEARN = "learn"
    UNDERSTAND = "understand"
    PRACTICE = "practice"
    CITATION = "citation"


class Note(SQLModel, table=True):
    """学生笔记表"""

    __tablename__ = "notes"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    script_id: Optional[int] = Field(default=None, foreign_key="course_scripts.id")
    node_id: Optional[int] = Field(default=None)
    node_index: Optional[int] = Field(default=None)
    page: Optional[int] = Field(default=None)
    timestamp: Optional[float] = Field(default=None)
    title: str = Field(default="")
    content: str = Field(default="")
    tags: list = Field(default=[], sa_column=Column(JSON))
    trigger_source: NoteTriggerSource = Field(default=NoteTriggerSource.LEARN)
    is_draft: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)
