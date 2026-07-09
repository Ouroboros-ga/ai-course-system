from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.platform.adapters.base import AdapterResult
from app.platform.adapters.errors import AdapterErrorCode
from app.platform.tasks.context import TaskContext
from app.platform.tasks.status import TaskStatus


@dataclass
class TaskResult:
    success: bool
    status: TaskStatus
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None
    provider: str | None = None
    raw: Any = None
    duration_ms: float = 0.0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    context: TaskContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, TaskStatus):
            self.status = TaskStatus(self.status)

    @classmethod
    def ok(
        cls,
        data: Any = None,
        *,
        status: TaskStatus = TaskStatus.SUCCEEDED,
        provider: str | None = None,
        raw: Any = None,
        duration_ms: float = 0.0,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        context: TaskContext | None = None,
    ) -> "TaskResult":
        return cls(
            success=True,
            status=status,
            data=data,
            provider=provider or (context.provider if context else None),
            raw=raw if raw is not None else data,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=finished_at,
            context=context,
        )

    @classmethod
    def fail(
        cls,
        error_code: AdapterErrorCode | str | None,
        error_message: str,
        *,
        status: TaskStatus | None = None,
        provider: str | None = None,
        raw: Any = None,
        duration_ms: float = 0.0,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        context: TaskContext | None = None,
    ) -> "TaskResult":
        code = error_code.value if isinstance(error_code, AdapterErrorCode) else error_code
        normalized_status = status or (
            TaskStatus.TIMEOUT if code == AdapterErrorCode.TIMEOUT.value else TaskStatus.FAILED
        )
        return cls(
            success=False,
            status=normalized_status,
            error_code=code,
            error_message=error_message,
            provider=provider or (context.provider if context else None),
            raw=raw,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=finished_at,
            context=context,
        )

    @classmethod
    def from_adapter_result(
        cls,
        adapter_result: AdapterResult,
        *,
        context: TaskContext | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        duration_ms: float | None = None,
    ) -> "TaskResult":
        resolved_duration = adapter_result.duration_ms if duration_ms is None else duration_ms
        if adapter_result.success:
            return cls.ok(
                adapter_result.data,
                provider=adapter_result.provider,
                raw=adapter_result.raw,
                duration_ms=resolved_duration,
                started_at=started_at,
                finished_at=finished_at,
                context=context,
            )
        return cls.fail(
            adapter_result.error_code,
            adapter_result.error_message or adapter_result.error_code or "task failed",
            provider=adapter_result.provider,
            raw=adapter_result.raw,
            duration_ms=resolved_duration,
            started_at=started_at,
            finished_at=finished_at,
            context=context,
        )
