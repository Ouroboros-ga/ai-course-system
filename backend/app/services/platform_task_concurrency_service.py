"""Persisted developer-mode limits for the local durable task worker."""
from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.platform_admin_model import PlatformTaskConcurrencyConfig

DEFAULTS = {
    "developer_mode": False,
    "max_total": 1,
    "document_parse": 1,
    "course_draft_build": 1,
    "graphrag": 1,
    "vector_index": 1,
}

TASK_GROUPS = {
    "document_parse": "document_parse",
    "course_draft_build": "course_draft_build",
    "knowledge.graphrag_build": "graphrag",
    "knowledge.vector_index": "vector_index",
}


def get_config(session: Session) -> dict[str, Any]:
    row = session.exec(select(PlatformTaskConcurrencyConfig).where(
        PlatformTaskConcurrencyConfig.config_key == "default",
    )).first()
    if row is None:
        return dict(DEFAULTS)
    return {key: getattr(row, key) for key in DEFAULTS}


def get_group_limit(session: Session, task_type: str) -> tuple[int, int]:
    config = get_config(session)
    # Developer mode is an explicit opt-in for values above the safe default;
    # when off, all long-running resource-heavy work is serialized.
    if not config["developer_mode"]:
        return 1, 1
    group = TASK_GROUPS.get(task_type)
    return max(1, int(config["max_total"])), max(1, int(config.get(group, 1))) if group else max(1, int(config["max_total"]))


def update_config(session: Session, actor_user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    row = session.exec(select(PlatformTaskConcurrencyConfig).where(
        PlatformTaskConcurrencyConfig.config_key == "default",
    )).first()
    if row is None:
        row = PlatformTaskConcurrencyConfig(config_key="default")
    for key in DEFAULTS:
        if key in payload:
            value = payload[key] if key == "developer_mode" else max(1, min(32, int(payload[key])))
            setattr(row, key, value)
    row.updated_by = actor_user_id
    row.updated_at = utcnow_aware()
    session.add(row)
    session.commit()
    session.refresh(row)
    return get_config(session)
