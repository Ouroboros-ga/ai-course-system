from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from sqlmodel import Session, select

from app.models.agent_run_model import AgentLLMDiagnosticRecord, AgentRunEventRecord, AgentRunRecord
from ...runtime.events import AgentRunEventPort, AgentRunStorePort, RunEventType, RunStatus


class SqlAgentRunStorePort(AgentRunStorePort):
    """Idempotent SQLModel implementation of the run store port."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def create_run(self, *, run_id: str, trace_id: str, agent_type: str,
                         actor_id: str, actor_type: str, course_id: str | None,
                         config_version: str, idempotency_key: str | None = None) -> None:
        with self._session_factory() as session:
            existing = session.exec(select(AgentRunRecord).where(AgentRunRecord.run_id == run_id)).first()
            if existing is None:
                session.add(AgentRunRecord(
                    run_id=run_id, trace_id=trace_id, agent_type=agent_type,
                    actor_id=actor_id, actor_type=actor_type,
                    course_id=int(course_id) if course_id and str(course_id).isdigit() else None,
                    config_version=config_version, idempotency_key=idempotency_key,
                    status=RunStatus.RUNNING.value,
                ))
                session.commit()

    async def update_status(self, *, run_id: str, status: RunStatus,
                            errors: list[Mapping[str, Any]] | None = None,
                            result: Mapping[str, Any] | None = None) -> None:
        with self._session_factory() as session:
            record = session.exec(select(AgentRunRecord).where(AgentRunRecord.run_id == run_id)).first()
            if record is None:
                return
            record.status = status.value if isinstance(status, RunStatus) else str(status)
            errors_list = [dict(item) for item in (errors or []) if isinstance(item, Mapping)]
            record.error_details = errors_list
            record.error_code = str(errors_list[-1].get("code") or "") if errors_list else ""
            record.result_summary = dict(result or {})
            record.stage = str((result or {}).get("stage") or record.stage or "")
            if record.status in {RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value, RunStatus.TIMEOUT.value}:
                from app.core.time_utils import utcnow_aware
                record.completed_at = utcnow_aware()
            from app.core.time_utils import utcnow_aware
            record.updated_at = utcnow_aware()
            session.add(record)
            session.commit()

    async def get_run(self, *, run_id: str) -> Mapping[str, Any] | None:
        with self._session_factory() as session:
            record = session.exec(select(AgentRunRecord).where(AgentRunRecord.run_id == run_id)).first()
            if record is None:
                return None
            return _run_dict(record)

    async def list_runs(self, *, agent_type: str | None = None, actor_id: str | None = None,
                        course_id: str | None = None, status: RunStatus | None = None,
                        limit: int = 50, offset: int = 0) -> list[Mapping[str, Any]]:
        with self._session_factory() as session:
            statement = select(AgentRunRecord)
            if agent_type:
                statement = statement.where(AgentRunRecord.agent_type == agent_type)
            if actor_id:
                statement = statement.where(AgentRunRecord.actor_id == actor_id)
            if course_id:
                statement = statement.where(AgentRunRecord.course_id == int(course_id))
            if status:
                statement = statement.where(AgentRunRecord.status == status.value)
            rows = session.exec(statement.order_by(AgentRunRecord.started_at.desc()).offset(offset).limit(min(limit, 200))).all()
            return [_run_dict(row) for row in rows]


class SqlAgentRunEventPort(AgentRunEventPort):
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def emit(self, *, run_id: str, trace_id: str, event_type: RunEventType,
                   payload: Mapping[str, Any]) -> None:
        with self._session_factory() as session:
            duplicate = session.exec(select(AgentRunEventRecord).where(
                AgentRunEventRecord.run_id == run_id,
                AgentRunEventRecord.event_type == (event_type.value if isinstance(event_type, RunEventType) else str(event_type)),
                AgentRunEventRecord.payload == _sanitize_payload(payload),
            )).first()
            if duplicate is not None:
                return
            session.add(AgentRunEventRecord(
                run_id=run_id, trace_id=trace_id,
                event_type=event_type.value if isinstance(event_type, RunEventType) else str(event_type),
                payload=_sanitize_payload(payload),
            ))
            session.commit()


class SqlAgentLLMDiagnosticStore:
    """Bounded diagnostic sink; never stores prompt or response bodies."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def record(self, **data: Any) -> None:
        with self._session_factory() as session:
            session.add(AgentLLMDiagnosticRecord(**_diagnostic_values(data)))
            session.commit()


def _run_dict(record: AgentRunRecord) -> dict[str, Any]:
    return {
        "run_id": record.run_id, "trace_id": record.trace_id,
        "agent_type": record.agent_type, "actor_id": record.actor_id,
        "actor_type": record.actor_type, "course_id": record.course_id,
        "config_version": record.config_version, "status": record.status,
        "stage": record.stage, "error_code": record.error_code,
        "errors": record.error_details or [], "result": record.result_summary or {},
        "started_at": record.started_at.isoformat(),
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "updated_at": record.updated_at.isoformat(),
    }


def _sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"agent_type", "status", "node", "stage", "error_code", "attempt", "duration_ms"}
    result = {key: value for key, value in payload.items() if key in allowed}
    return json.loads(json.dumps(result, ensure_ascii=False, default=str))


def _diagnostic_values(data: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "run_id", "trace_id", "course_id", "agent_type", "stage", "node", "purpose",
        "prompt_version", "schema_name", "model", "attempt", "repaired", "finish_reason",
        "input_tokens", "output_tokens", "input_chars", "output_chars", "response_hash",
        "truncated", "response_format_requested", "response_format_fallback",
        "validation_errors", "usage_metadata", "latency_ms",
    }
    values = {key: value for key, value in data.items() if key in allowed}
    if values.get("course_id") not in (None, ""):
        try:
            values["course_id"] = int(values["course_id"])
        except (TypeError, ValueError):
            values["course_id"] = None
    return values


__all__ = ["SqlAgentRunStorePort", "SqlAgentRunEventPort", "SqlAgentLLMDiagnosticStore"]
