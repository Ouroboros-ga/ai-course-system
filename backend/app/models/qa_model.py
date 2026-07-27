from __future__ import annotations

from sqlmodel import SQLModel, Field, JSON, Column
from typing import Optional, List
from datetime import datetime
from enum import Enum

from app.core.time_utils import utcnow_aware


class MessageRole(str, Enum):
    """消息角色枚举"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class QASession(SQLModel, table=True):
    """
    问答会话表
    记录学生在某个课程下的完整问答对话会话
    """

    __tablename__ = "qa_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(foreign_key="users.id", index=True, description="学生ID")
    course_id: int = Field(foreign_key="courses.id", index=True, description="课程ID")
    script_id: Optional[int] = Field(
        default=None, foreign_key="course_scripts.id", description="关联的脚本ID"
    )

    current_node_id: Optional[int] = Field(
        default=None, description="当前问答所在的脚本节点ID"
    )
    current_timestamp: float = Field(default=0.0, description="当前视频/音频进度(秒)")
    current_page: int = Field(default=1, description="当前PPT页码")

    title: Optional[str] = Field(default=None, max_length=200, description="会话标题")
    is_active: bool = Field(default=True, description="会话是否活跃")

    created_at: datetime = Field(default_factory=utcnow_aware, description="创建时间")
    updated_at: datetime = Field(default_factory=utcnow_aware, description="更新时间")


class QAMessage(SQLModel, table=True):
    """
    问答消息表
    记录每一条具体的问答消息
    """

    __tablename__ = "qa_messages"

    id: Optional[int] = Field(default=None, primary_key=True)

    session_id: int = Field(
        foreign_key="qa_sessions.id", index=True, description="所属会话ID"
    )

    role: MessageRole = Field(description="消息角色: user/assistant/system")
    content: str = Field(description="消息内容")

    node_id: Optional[int] = Field(
        default=None, description="关联的脚本节点ID(用于上下文定位)"
    )
    timestamp: float = Field(default=0.0, description="消息时的视频/音频进度(秒)")
    page: int = Field(default=1, description="消息时的PPT页码")

    understanding_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="AI分析的理解程度(0-1)"
    )
    understanding_reason: Optional[str] = Field(
        default=None, description="理解程度分析原因"
    )

    tokens_used: int = Field(default=0, description="消耗的token数")
    response_time_ms: int = Field(default=0, description="响应时间(毫秒)")

    created_at: datetime = Field(default_factory=utcnow_aware, description="创建时间")


class QAContext(SQLModel, table=True):
    """
    问答上下文表
    存储用于RAG检索的课程内容片段
    """

    __tablename__ = "qa_contexts"

    id: Optional[int] = Field(default=None, primary_key=True)

    course_id: int = Field(foreign_key="courses.id", index=True, description="课程ID")
    script_id: Optional[int] = Field(
        default=None, foreign_key="course_scripts.id", description="脚本ID"
    )

    node_id: int = Field(description="脚本节点ID")
    node_type: str = Field(description="节点类型: lecture/question/summary等")
    content: str = Field(description="节点内容文本")

    page_start: int = Field(default=1, description="关联的PPT起始页")
    page_end: int = Field(default=1, description="关联的PPT结束页")
    timestamp_start: float = Field(default=0.0, description="视频起始时间(秒)")
    timestamp_end: float = Field(default=0.0, description="视频结束时间(秒)")

    embedding_vector: Optional[bytes] = Field(
        default=None, description="嵌入向量(序列化存储)"
    )

    created_at: datetime = Field(default_factory=utcnow_aware, description="创建时间")
