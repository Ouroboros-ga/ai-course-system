"""Privacy-minimized continuity adapter for TeachingAgent sessions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from app.core.time_utils import utcnow_naive


SESSION_TTL_MINUTES = 30
CONTEXT_POLICY_VERSION = "agent-session-context/1"


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only bounded, deterministic fields safe to reuse as context."""
    scalar_keys = ("current_concept_id", "last_intent", "last_teaching_action", "pending_action")
    normalized = {key: str(context[key])[:128] for key in scalar_keys if context.get(key) is not None}
    normalized["warnings"] = sorted({str(value)[:64] for value in context.get("warnings", [])})[:12]
    normalized["reason_codes"] = sorted({str(value)[:64] for value in context.get("reason_codes", [])})[:12]
    return normalized


class SessionScopedConversationContextPort:
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    async def load_context(self, *, student_id: str, course_id: str, session_id: str) -> Mapping[str, Any] | None:
        student = _safe_int(student_id)
        course = _safe_int(course_id)
        if student is None or course is None:
            return None

        def _read() -> Mapping[str, Any] | None:
            from sqlmodel import select
            from app.models.agent_log import AgentConversationSession
            with self._session_factory() as session:
                record = session.exec(select(AgentConversationSession).where(
                    AgentConversationSession.student_id == student,
                    AgentConversationSession.course_id == course,
                    AgentConversationSession.session_id == str(session_id),
                ).order_by(AgentConversationSession.updated_at.desc())).first()
                if record is None or record.updated_at < utcnow_naive() - timedelta(minutes=SESSION_TTL_MINUTES):
                    return None
                try:
                    return normalize_context(json.loads(record.context_data))
                except (TypeError, ValueError, json.JSONDecodeError):
                    return None
        return await asyncio.to_thread(_read)

    async def save_context(self, *, student_id: str, course_id: str, session_id: str, context: Mapping[str, Any]) -> None:
        student = _safe_int(student_id)
        course = _safe_int(course_id)
        if student is None or course is None:
            return
        payload = json.dumps(normalize_context(context), ensure_ascii=False, sort_keys=True)

        def _write() -> None:
            from sqlmodel import select
            from app.models.agent_log import AgentConversationSession
            with self._session_factory() as session:
                record = session.exec(select(AgentConversationSession).where(
                    AgentConversationSession.student_id == student,
                    AgentConversationSession.course_id == course,
                    AgentConversationSession.session_id == str(session_id),
                )).first()
                if record is None:
                    record = AgentConversationSession(student_id=student, course_id=course, session_id=str(session_id))
                record.context_data = payload
                record.updated_at = utcnow_naive()
                session.add(record)
                session.commit()
        await asyncio.to_thread(_write)


def make_session_scoped_conversation_context_port(session_factory: Callable[[], Any]) -> SessionScopedConversationContextPort:
    return SessionScopedConversationContextPort(session_factory)
