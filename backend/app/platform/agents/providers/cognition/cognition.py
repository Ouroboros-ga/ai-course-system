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

from collections.abc import Awaitable, Callable, Mapping
from typing import Any


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
        with session_factory() as session:
            node_id_int = _resolve_node_id_int(session, course_id_int, node_id)
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
        with session_factory() as session:
            from sqlmodel import select

            from app.models.cognitive_state_model import RecommendationRecord

            node_id_int = _resolve_node_id_int(session, course_id_int, node_id)
            stmt = select(RecommendationRecord).where(
                RecommendationRecord.student_id == student_id_int,
                RecommendationRecord.course_id == course_id_int,
            )
            if node_id_int is None:
                # 课程级读取：取该学生在本课程最近一条推荐，不限 node 作用域。
                # 前置复习（prereq_review）推荐挂在当前知识点 node 上，若只查
                # node_id IS NULL 会永远取不到，导致 weak_concepts 恒为空，
                # 教学策略的 prerequisite_review 分支不可达。
                pass
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


def _resolve_node_id_int(
    session: Any, course_id: int, node_id: str | None
) -> int | None:
    """Resolve a workflow-supplied node reference to a course-local numeric id.

    数字字符串/整数直接使用；node_key（如 ``kn_xxx``）经课程身份表解析，
    解析失败（含身份表缺失）回退 None（课程级读取），不抛错。
    """
    if node_id is None or node_id == "":
        return None
    if isinstance(node_id, int) or (isinstance(node_id, str) and node_id.isdigit()):
        return int(node_id)
    from app.services.knowledge_node_identity_service import resolve_node_id

    return resolve_node_id(session, course_id, node_id)


def _serialize_state(state: Any) -> Mapping[str, Any]:
    # M2：证据时间衰减（读取投影，不落库）。computed_at 距今越久，
    # 置信度与掌握度按半衰期衰减，reason_codes 追加 evidence_decayed，
    # 使教学 Agent 看到的是"当前可信度"而非历史快照。
    from app.services.cognitive_decay_service import (
        DECAY_MARK_THRESHOLD,
        project_time_decay,
    )

    decayed_conf, decayed_mastery, decay_factor = project_time_decay(state)
    reason_codes = list(state.reason_codes or [])
    if decay_factor <= DECAY_MARK_THRESHOLD:
        reason_codes.append("evidence_decayed")
    return {
        "student_id": state.student_id,
        "course_id": state.course_id,
        "node_id": state.node_id,
        "observed_performance_score": state.observed_performance_score,
        "evidence_confidence": decayed_conf,
        "confusion_risk": state.confusion_risk,
        "inquiry_depth": state.inquiry_depth,
        "hint_dependency": state.hint_dependency,
        "explanation_need": state.explanation_need,
        "mastery_level": state.mastery_level,
        "mastery_score": decayed_mastery,
        "policy_version": state.policy_version,
        "sample_size": state.sample_size,
        "reason_codes": reason_codes,
        "evidence_refs": list(state.evidence_refs or []),
        "computed_at": state.computed_at.isoformat() if state.computed_at else None,
    }


def _serialize_recommendation(record: Any) -> Mapping[str, Any]:
    # 批次3的 prereq_review 推荐把薄弱前置节点编码在 reason_codes 里
    # （weak_prerequisite_node={graph_node_key}），这里还原为结构化集合，
    # 供 StudentModelingPort.get_weak_concepts 直接消费。
    weak_prerequisite_set: list[dict[str, str]] = []
    for code in record.reason_codes or []:
        if str(code).startswith("weak_prerequisite_node="):
            node_id = str(code).split("=", 1)[1]
            if node_id:
                weak_prerequisite_set.append({"concept_id": node_id})
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
        "confirmed_weak_prerequisite_set": weak_prerequisite_set,
        "cognitive_snapshot": dict(record.cognitive_snapshot or {}),
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
