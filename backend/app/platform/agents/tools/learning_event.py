"""Sanitized audit adapter for TeachingAgent.

Despite their legacy names, ``AgentLearningEvent`` and ``AgentTraceRecord``
are not formal ``LearningEvent`` or scoring ``LearningEvidence``. They never
change mastery or cognition. Raw messages, answers, prompts and model traces
are excluded before persistence.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from ..contracts import LearningEventPort


class CallableLearningEventPort:
    """Adapter that turns awaitable callables into a ``LearningEventPort``."""

    def __init__(
        self,
        record_event: Callable[..., Any],
        record_trace: Callable[..., Any],
    ) -> None:
        self._record_event = record_event
        self._record_trace = record_trace

    async def record_learning_event(self, **kwargs: Any) -> None:
        await self._record_event(**kwargs)

    async def record_agent_trace(self, **kwargs: Any) -> None:
        await self._record_trace(**kwargs)


def make_session_scoped_learning_event_port(
    session_factory: Callable[[], Any],
) -> CallableLearningEventPort:
    """Build a port that persists events/traces to the DB.

    每次调用打开一个新 Session。写入失败不抛出（学习事件记录不应阻塞
    教学响应主流程），但会通过 logging 记录错误。
    """
    import logging
    logger = logging.getLogger(__name__)

    async def _record_event(*, event: Mapping[str, Any]) -> None:
        student_id = _safe_int(event.get("student_id"))
        course_id = _safe_int(event.get("course_id"))
        if student_id is None or course_id is None:
            logger.warning("record_learning_event: missing student_id/course_id, skipped.")
            return
        trace_id = str(event.get("trace_id", ""))
        session_id = str(event.get("session_id", ""))
        event_type = str(event.get("event_type", "teaching_agent_response"))[:64]
        sanitized = _sanitize_event(event)

        def _write() -> None:
            from app.models.agent_log import AgentLearningEvent
            with session_factory() as session:
                session.add(AgentLearningEvent(
                    trace_id=trace_id,
                    student_id=student_id,
                    course_id=course_id,
                    session_id=session_id,
                    event_type=event_type,
                    event_data=json.dumps(sanitized, ensure_ascii=False, sort_keys=True),
                ))
                session.commit()

        try:
            import asyncio
            await asyncio.to_thread(_write)
        except Exception as err:  # noqa: BLE001 -- 不阻塞主流程
            logger.warning("record_learning_event failed (non-blocking): %s: %s", type(err).__name__, err)

    async def _record_trace(*, trace: Mapping[str, Any]) -> None:
        student_id = _safe_int(trace.get("student_id"))
        course_id = _safe_int(trace.get("course_id"))
        if student_id is None or course_id is None:
            logger.warning("record_agent_trace: missing student_id/course_id, skipped.")
            return
        trace_id = str(trace.get("trace_id", ""))
        session_id = str(trace.get("session_id", ""))[:128]
        sanitized = _sanitize_trace(trace)

        def _write() -> None:
            from app.models.agent_log import AgentTraceRecord
            with session_factory() as session:
                session.add(AgentTraceRecord(
                    trace_id=trace_id,
                    student_id=student_id,
                    course_id=course_id,
                    session_id=session_id,
                    trace_data=json.dumps(sanitized, ensure_ascii=False, sort_keys=True),
                ))
                session.commit()

        try:
            import asyncio
            await asyncio.to_thread(_write)
        except Exception as err:  # noqa: BLE001 -- 不阻塞主流程
            logger.warning("record_agent_trace failed (non-blocking): %s: %s", type(err).__name__, err)

    return CallableLearningEventPort(_record_event, _record_trace)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _codes(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({str(item)[:64] for item in value})[:20]


def _sanitize_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Persist only deterministic identifiers and operational outcome codes."""
    return {
        "concept_id": str(event.get("concept_id", ""))[:128],
        "event_type": str(event.get("event_type", "teaching_agent_response"))[:64],
        "reason_codes": _codes(event.get("reason_codes", [])),
        "teaching_action": str(event.get("teaching_action", ""))[:64],
        "warnings": _codes(event.get("warnings", [])),
        "errors": _codes(event.get("errors", [])),
    }


def _sanitize_trace(trace: Mapping[str, Any]) -> dict[str, Any]:
    """Store node names and codes, never message/answer/evidence text."""
    nodes = []
    for item in trace.get("nodes", []):
        if isinstance(item, Mapping) and item.get("node"):
            nodes.append(str(item["node"])[:64])
    evidence_ids = []
    for item in trace.get("retrieved_evidence", []):
        if isinstance(item, Mapping) and item.get("evidence_id"):
            evidence_ids.append(str(item["evidence_id"])[:128])
    return {
        "concept_id": str(trace.get("concept_id", ""))[:128],
        "degraded_services": _codes(trace.get("degraded_services", [])),
        "evidence_ids": sorted(set(evidence_ids))[:20],
        "errors": _codes(trace.get("errors", [])),
        "intent": str(trace.get("intent", ""))[:64],
        "nodes": nodes[:30],
        "warnings": _codes(trace.get("warnings", [])),
    }
