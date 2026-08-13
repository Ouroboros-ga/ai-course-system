"""Bounded read-only selector over the learner-facing Conversation Domain."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from sqlmodel import select

from app.core.time_utils import utcnow_aware
from app.models.conversation_model import ConversationMessage


@dataclass(frozen=True, slots=True)
class _Turn:
    trace_id: str
    session_id: str
    user: str
    assistant: str
    concept_id: str | None
    resource_id: str | None
    created_at: Any

    @property
    def char_count(self) -> int:
        return len(self.user) + len(self.assistant)

    def as_dict(self) -> dict[str, Any]:
        return {
            "user": self.user,
            "assistant": self.assistant,
            "concept_id": self.concept_id,
            "resource_id": self.resource_id,
            "source_session_id": self.session_id,
        }


def _complete_turns(rows: Sequence[ConversationMessage]) -> list[_Turn]:
    grouped: dict[str, dict[str, ConversationMessage]] = {}
    for row in rows:
        if row.role not in {"user", "assistant"} or not row.trace_id:
            continue
        bucket = grouped.setdefault(row.trace_id, {})
        bucket.setdefault(row.role, row)
    turns: list[_Turn] = []
    for trace_id, pair in grouped.items():
        user = pair.get("user")
        assistant = pair.get("assistant")
        if user is None or assistant is None or not user.content or not assistant.content:
            continue
        turns.append(
            _Turn(
                trace_id=trace_id,
                session_id=user.session_id,
                user=str(user.content),
                assistant=str(assistant.content),
                concept_id=user.concept_id or assistant.concept_id,
                resource_id=user.resource_id or assistant.resource_id,
                created_at=max(user.created_at, assistant.created_at),
            )
        )
    return sorted(turns, key=lambda turn: turn.created_at, reverse=True)


def select_bounded_turns(
    turns: Sequence[_Turn],
    *,
    session_id: str,
    concept_id: str | None,
    resource_id: str | None,
    max_chars: int,
) -> list[dict[str, Any]]:
    """Select at most six whole turns using the fixed relevance precedence."""

    selected: list[_Turn] = []
    seen: set[str] = set()

    def add(candidates: Sequence[_Turn], limit: int) -> None:
        added = 0
        for turn in candidates:
            if turn.trace_id in seen or len(selected) >= 6 or added >= limit:
                continue
            seen.add(turn.trace_id)
            selected.append(turn)
            added += 1

    add([turn for turn in turns if turn.session_id == session_id], 2)
    if concept_id:
        add([turn for turn in turns if turn.concept_id == concept_id], 3)
    if resource_id:
        add([turn for turn in turns if turn.resource_id == resource_id], 2)
    add(list(turns), 6)

    budget = max(0, min(int(max_chars), 3_600))
    kept: list[_Turn] = []
    used = 0
    for turn in selected:
        if turn.char_count > budget - used:
            continue
        kept.append(turn)
        used += turn.char_count
    # Prompt continuity reads naturally oldest-to-newest after relevance
    # selection, while never splitting a user/assistant pair.
    return [turn.as_dict() for turn in reversed(kept)]


class SessionScopedConversationHistoryPort:
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    async def select_relevant_turns(
        self,
        *,
        student_id: str,
        course_id: str,
        session_id: str,
        message: str,
        concept_id: str | None,
        resource_id: str | None,
        max_chars: int,
    ) -> Sequence[Mapping[str, Any]]:
        del message  # Deterministic v1 deliberately performs no semantic LLM call.

        def _read() -> list[dict[str, Any]]:
            now = utcnow_aware()
            with self._session_factory() as session:
                rows = list(
                    session.exec(
                        select(ConversationMessage)
                        .where(
                            ConversationMessage.student_id == int(student_id),
                            ConversationMessage.course_id == int(course_id),
                            (
                                ConversationMessage.retention_until.is_(None)
                                | (ConversationMessage.retention_until >= now)
                            ),
                        )
                        .order_by(ConversationMessage.created_at.desc())
                        .limit(200)
                    ).all()
                )
            return select_bounded_turns(
                _complete_turns(rows),
                session_id=session_id,
                concept_id=concept_id,
                resource_id=resource_id,
                max_chars=max_chars,
            )

        return await asyncio.to_thread(_read)


def make_session_scoped_conversation_history_port(
    session_factory: Callable[[], Any],
) -> SessionScopedConversationHistoryPort:
    return SessionScopedConversationHistoryPort(session_factory)


__all__ = [
    "SessionScopedConversationHistoryPort",
    "make_session_scoped_conversation_history_port",
    "select_bounded_turns",
]
