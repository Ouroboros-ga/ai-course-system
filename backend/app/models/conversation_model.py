"""Conversation Domain: student-facing teaching-agent chat transcript.

This is a **product-experience domain**, intentionally independent from the
Agent Runtime Context / Audit tables in ``agent_log.py``.  Those audit tables
(``agent_learning_events`` / ``agent_trace_records`` / ``agent_conversation_sessions``)
still apply data-minimization and never carry raw messages, answers, prompts
or full traces -- see AGENTS.md §5.1.

The Conversation Domain may persist full user and teaching-agent messages so
the learner can resume a conversation after refresh / re-entry.  It carries its
own data policy version, retention window and (future) deletion strategy, and
is never consumed directly by learning analysis: question-derived weak signals
must be projected into structured ``LearningEvidence`` first.

Retention: ``retention_until`` is stamped on insert by ``conversation_service``
(default 90 days).  A pruning helper removes expired rows; learning analysis
reads only structured projections, never these raw rows.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware

CONVERSATION_DATA_POLICY_VERSION = "conversation-domain/1"
DEFAULT_CONVERSATION_RETENTION_DAYS = 90


class ConversationMessage(SQLModel, table=True):
    """A single user or teaching-agent message in a learner conversation.

    ``role`` is ``"user"`` (learner question) or ``"assistant"`` (teaching-agent
    answer).  A question/answer turn shares the same ``trace_id``; the user
    message is written first, then the assistant message once the agent has
    produced a ``final_answer``.
    """

    __tablename__ = "conversation_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    session_id: str = Field(index=True, max_length=128)
    trace_id: str = Field(default="", index=True, max_length=128)
    role: str = Field(max_length=16)  # "user" | "assistant"
    content: str  # raw message text (user question or agent answer)
    message_kind: str = Field(default="qa", index=True, max_length=32)
    concept_id: str | None = Field(default=None, max_length=128, index=True)
    resource_id: str | None = Field(default=None, max_length=128)
    citations: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    data_policy_version: str = Field(default=CONVERSATION_DATA_POLICY_VERSION, max_length=64)
    retention_until: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)
