"""学习轨迹服务：每学生每课程追加型事件（M7）。

- ``append_event``：幂等追加（``dedup_key`` 已存在则跳过并返回 None）；
- ``get_recent``：按 (student_id, course_id) 倒序取最近记录，可按 concept 过滤；
- ``compact_context``：只保留数值/枚举/ID 白名单字段的紧凑上下文（供 LLM 注入，
  绝不携带问答原文）；
- ``prune_older_than``：保留窗口清理（默认 90 天），返回删除行数。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, delete, select

from app.core.time_utils import utcnow_aware
from app.models.trajectory_model import LearningTrajectoryRecord, TrajectoryEventType

TRAJECTORY_RETENTION_DAYS = 90
MAX_CONTEXT_RECORDS = 8


def append_event(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    event_type: str,
    concept_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
    dedup_key: str | None = None,
) -> LearningTrajectoryRecord | None:
    """幂等追加一条轨迹记录；dedup_key 重复时返回 None（不新增）。"""
    if dedup_key:
        existing = session.exec(
            select(LearningTrajectoryRecord).where(
                LearningTrajectoryRecord.dedup_key == dedup_key,
            )
        ).first()
        if existing is not None:
            return None
    record = LearningTrajectoryRecord(
        student_id=student_id,
        course_id=course_id,
        event_type=event_type,
        concept_id=concept_id,
        dedup_key=dedup_key,
        payload=dict(payload or {}),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_recent(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    concept_id: str | None = None,
    limit: int = 20,
) -> list[LearningTrajectoryRecord]:
    stmt = (
        select(LearningTrajectoryRecord)
        .where(
            LearningTrajectoryRecord.student_id == student_id,
            LearningTrajectoryRecord.course_id == course_id,
        )
        .order_by(LearningTrajectoryRecord.created_at.desc())
        .limit(limit)
    )
    if concept_id:
        stmt = stmt.where(LearningTrajectoryRecord.concept_id == concept_id)
    return list(session.exec(stmt).all())


def compact_context(
    records: list[LearningTrajectoryRecord],
    *,
    max_records: int = MAX_CONTEXT_RECORDS,
) -> list[dict[str, Any]]:
    """紧凑上下文：只保留事件类型/知识点/数值快照/时间，供 LLM 注入。

    过滤规则：payload 中仅保留 int/float/str/bool/None 标量（丢弃嵌套结构与
    可能含原文的长文本），且每条记录压缩为单行描述。
    """
    rows: list[dict[str, Any]] = []
    for record in records[:max_records]:
        scalar_payload = {
            key: value
            for key, value in (record.payload or {}).items()
            if value is None or isinstance(value, (int, float, str, bool))
        }
        rows.append({
            "event_type": record.event_type,
            "concept_id": record.concept_id,
            "payload": scalar_payload,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        })
    return rows


def prune_older_than(
    session: Session,
    *,
    course_id: int | None = None,
    before: datetime | None = None,
    days: int = TRAJECTORY_RETENTION_DAYS,
) -> int:
    """删除早于保留窗口的记录（默认 90 天）；返回删除行数。"""
    cutoff = before or (utcnow_aware() - timedelta(days=days))
    stmt = delete(LearningTrajectoryRecord).where(
        LearningTrajectoryRecord.created_at < cutoff,
    )
    if course_id is not None:
        stmt = stmt.where(LearningTrajectoryRecord.course_id == course_id)
    result = session.exec(stmt)
    session.commit()
    return result.rowcount or 0


__all__ = [
    "MAX_CONTEXT_RECORDS",
    "TRAJECTORY_RETENTION_DAYS",
    "TrajectoryEventType",
    "append_event",
    "compact_context",
    "get_recent",
    "prune_older_than",
]
