"""学习轨迹端口（M7）：Session-backed TrajectoryPort 实现。

复用 ``learning_trajectory_service``（幂等追加 / 紧凑上下文 / 保留窗口），
通过注入的 ``session_factory`` 访问数据库；对外只暴露数值/枚举/ID 快照。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlmodel import Session

from app.services.learning_trajectory_service import (
    MAX_CONTEXT_RECORDS,
    append_event,
    compact_context,
    get_recent,
)


class SessionTrajectoryPort:
    """Session-backed trajectory port (M7)."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def get_compact_history(
        self,
        *,
        student_id: str,
        course_id: str,
        concept_id: str | None = None,
    ) -> Mapping[str, Any]:
        with self._session_factory() as session:
            records = get_recent(
                session,
                student_id=int(student_id),
                course_id=int(course_id),
                concept_id=concept_id,
                limit=MAX_CONTEXT_RECORDS,
            )
            rows = compact_context(records)
            return {
                "status": "available",
                "source": "learning_trajectory",
                "count": len(rows),
                "records": rows,
            }

    async def append(
        self,
        *,
        student_id: str,
        course_id: str,
        event_type: str,
        concept_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        dedup_key: str | None = None,
    ) -> None:
        with self._session_factory() as session:
            append_event(
                session,
                student_id=int(student_id),
                course_id=int(course_id),
                event_type=event_type,
                concept_id=concept_id,
                payload=payload,
                dedup_key=dedup_key,
            )


__all__ = ["SessionTrajectoryPort"]
