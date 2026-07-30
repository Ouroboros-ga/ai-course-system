"""Cognition port for the TeachingAgent.

Exposes ``app.services.cognitive_service`` (six-dimension state + recommendation)
through a port protocol so the LangGraph workflow can read the student's
cognitive state without touching the database directly.

Course isolation: every call carries ``course_id``; the service layer enforces
per-student/per-course scoping. The port is read-only from the workflow's
perspective: it returns the latest state and the active recommendation but
does not create new records.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from ...contracts import CognitionPort


class CallableCognitionPort:
    """Adapter that turns awaitable callables into a ``CognitionPort``."""

    def __init__(
        self,
        get_state: Callable[..., Awaitable[Mapping[str, Any] | None]],
        get_recommendation: Callable[..., Awaitable[Mapping[str, Any] | None]],
    ) -> None:
        self._get_state = get_state
        self._get_recommendation = get_recommendation

    async def get_state(
        self,
        *,
        student_id: str,
        course_id: str,
        node_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        return await self._get_state(
            student_id=student_id, course_id=course_id, node_id=node_id,
        )

    async def get_recommendation(
        self,
        *,
        student_id: str,
        course_id: str,
        node_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        return await self._get_recommendation(
            student_id=student_id, course_id=course_id, node_id=node_id,
        )


def make_session_scoped_cognition_port(
    session_factory: Callable[[], Any],
) -> CallableCognitionPort:
    """Build a port whose callables open a fresh Session per call.

    The port reads the latest CognitiveState and the most recent
    RecommendationRecord for the (student, course, node) tuple. It never
    writes; ``generate_recommendation`` is intentionally NOT invoked here so
    the workflow cannot trigger recommendation regeneration as a side effect.
    """
    from app.services.cognitive_service import get_latest_cognitive_state

    async def _get_state(
        *,
        student_id: str,
        course_id: str,
        node_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        try:
            student_id_int = int(student_id)
            course_id_int = int(course_id)
        except (TypeError, ValueError):
            return None
        node_id_int = _parse_node_id(node_id)
        with session_factory() as session:
            state = get_latest_cognitive_state(
                session, student_id_int, course_id_int, node_id_int,
            )
            if state is None:
                return None
            return _serialize_state(state)

    async def _get_recommendation(
        *,
        student_id: str,
        course_id: str,
        node_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        try:
            student_id_int = int(student_id)
            course_id_int = int(course_id)
        except (TypeError, ValueError):
            return None
        node_id_int = _parse_node_id(node_id)
        with session_factory() as session:
            from app.models.cognitive_state_model import RecommendationRecord
            from sqlmodel import select
            stmt = select(RecommendationRecord).where(
                RecommendationRecord.student_id == student_id_int,
                RecommendationRecord.course_id == course_id_int,
            )
            if node_id_int is None:
                stmt = stmt.where(RecommendationRecord.node_id.is_(None))
            else:
                stmt = stmt.where(RecommendationRecord.node_id == node_id_int)
            stmt = stmt.order_by(RecommendationRecord.created_at.desc()).limit(1)
            record = session.exec(stmt).first()
            if record is None:
                return None
            return _serialize_recommendation(record)

    return CallableCognitionPort(_get_state, _get_recommendation)


def _parse_node_id(node_id: str | None) -> int | None:
    if node_id is None or node_id == "":
        return None
    try:
        return int(node_id)
    except (TypeError, ValueError):
        return None


def _serialize_state(state: Any) -> Mapping[str, Any]:
    return {
        "student_id": state.student_id,
        "course_id": state.course_id,
        "node_id": state.node_id,
        "observed_performance_score": state.observed_performance_score,
        "evidence_confidence": state.evidence_confidence,
        "confusion_risk": state.confusion_risk,
        "inquiry_depth": state.inquiry_depth,
        "hint_dependency": state.hint_dependency,
        "explanation_need": state.explanation_need,
        "mastery_level": state.mastery_level,
        "mastery_score": state.mastery_score,
        "policy_version": state.policy_version,
        "sample_size": state.sample_size,
        "reason_codes": list(state.reason_codes or []),
        "evidence_refs": list(state.evidence_refs or []),
        "computed_at": state.computed_at.isoformat() if state.computed_at else None,
    }


def _serialize_recommendation(record: Any) -> Mapping[str, Any]:
    return {
        "recommendation_id": record.recommendation_id,
        "recommendation_type": record.recommendation_type,
        "priority": record.priority,
        "title": record.title,
        "description": record.description,
        "policy_version": record.policy_version,
        "reason_codes": list(record.reason_codes or []),
        "evidence_refs": list(record.evidence_refs or []),
        "question_id": record.question_id,
        "knowledge_node_ids": list(record.knowledge_node_ids or []),
        "consumed": record.consumed,
        "is_locked": record.is_locked,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
