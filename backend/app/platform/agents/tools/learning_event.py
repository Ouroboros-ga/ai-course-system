"""LearningEvent port for the TeachingAgent.

接通真实的 DB 持久化，使 workflow 末尾的 ``record_learning_event`` 与
``record_agent_trace`` 写入 ``AgentLearningEvent`` / ``AgentTraceRecord`` 表。

课程作用域：写入时强制 ``student_id`` + ``course_id`` 来自 event/trace dict，
且必须为有效整数（与端点 ``teaching_agent.respond`` 的 scope 校验一致）。
port 本身不做权限校验（那是端点职责），但拒绝写入缺失作用域的事件。
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
        event_type = str(event.get("event_type", "teaching_agent_response"))

        def _write() -> None:
            from app.models.agent_log import AgentLearningEvent
            with session_factory() as session:
                session.add(AgentLearningEvent(
                    trace_id=trace_id,
                    student_id=student_id,
                    course_id=course_id,
                    session_id=session_id,
                    event_type=event_type,
                    event_data=json.dumps(dict(event), ensure_ascii=False, default=str),
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

        def _write() -> None:
            from app.models.agent_log import AgentTraceRecord
            with session_factory() as session:
                session.add(AgentTraceRecord(
                    trace_id=trace_id,
                    student_id=student_id,
                    course_id=course_id,
                    trace_data=json.dumps(dict(trace), ensure_ascii=False, default=str),
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
