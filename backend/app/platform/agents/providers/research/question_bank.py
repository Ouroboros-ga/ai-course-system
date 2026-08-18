"""QuestionBank port for the TeachingAgent.

Wraps the question bank read API (published items, filtered by course) behind
a port protocol so the LangGraph workflow can load practice items without
touching the database directly.

Course isolation: every call carries ``course_id``; the adapter only returns
questions whose ``course_id`` matches and whose status is ``published``.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from app.core.db_json import json_array_contains

from ...contracts import QuestionBankPort


class CallableQuestionBankPort:
    """Adapter that turns an awaitable callable into a ``QuestionBankPort``."""

    def __init__(
        self,
        list_questions: Callable[..., Awaitable[list[Mapping[str, Any]]]],
    ) -> None:
        self._list_questions = list_questions

    async def list_questions(
        self,
        *,
        course_id: str,
        node_id: str | None = None,
        limit: int = 10,
    ) -> list[Mapping[str, Any]]:
        return await self._list_questions(
            course_id=course_id, node_id=node_id, limit=limit,
        )


def make_session_scoped_question_bank_port(
    session_factory: Callable[[], Any],
) -> CallableQuestionBankPort:
    """Build a port whose callable opens a fresh Session per call.

    Returns only ``published`` questions for the given course (and optionally
    filtered by knowledge node). The port never returns unassigned/draft/
    rejected items.
    """
    from app.models.question_bank_model import (
        QuestionBankItem,
        QuestionStatus,
    )
    from sqlmodel import select

    async def _list_questions(
        *,
        course_id: str,
        node_id: str | None = None,
        limit: int = 10,
    ) -> list[Mapping[str, Any]]:
        try:
            course_id_int = int(course_id)
        except (TypeError, ValueError):
            return []
        node_id_int = _parse_node_id(node_id)
        with session_factory() as session:
            stmt = (
                select(QuestionBankItem)
                .where(
                    QuestionBankItem.course_id == course_id_int,
                    QuestionBankItem.is_latest == True,  # noqa: E712
                    QuestionBankItem.status == QuestionStatus.PUBLISHED,
                )
            )
            if node_id_int is not None:
                stmt = stmt.where(
                    json_array_contains(QuestionBankItem.knowledge_node_ids, node_id_int)
                )
            stmt = stmt.limit(max(1, min(int(limit or 10), 50)))
            items = session.exec(stmt).all()
            return [_serialize_question(item) for item in items]

    return CallableQuestionBankPort(_list_questions)


def _parse_node_id(node_id: str | None) -> int | None:
    if node_id is None or node_id == "":
        return None
    try:
        return int(node_id)
    except (TypeError, ValueError):
        return None


def _serialize_question(item: Any) -> Mapping[str, Any]:
    # P1-E4: 答案不进入 LLM context，仅暴露布尔标志 has_answer，避免 Prompt Injection 泄露标准答案。
    return {
        "question_id": item.id,
        "course_id": item.course_id,
        "question_type": item.question_type.value if item.question_type else None,
        "difficulty": item.difficulty.value if item.difficulty else None,
        "knowledge_node_ids": list(item.knowledge_node_ids or []),
        "question_text": item.question_text,
        "has_answer": bool(item.answer),
        "options": dict(item.options or {}),
        "status": item.status.value if item.status else None,
        "version": item.version,
    }
