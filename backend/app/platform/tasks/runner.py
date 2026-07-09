from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.platform.adapters.base import AdapterResult, classify_exception
from app.platform.adapters.errors import AdapterErrorCode
from app.platform.tasks.context import TaskContext
from app.platform.tasks.errors import TaskExecutionError
from app.platform.tasks.result import TaskResult
from app.platform.tasks.status import TaskStatus


class TaskRunner:
    """Lightweight wrapper that normalizes one task step without owning storage."""

    async def create_task(self, context: TaskContext) -> TaskResult:
        return TaskResult.ok(status=TaskStatus.PENDING, context=context)

    async def mark_running(self, context: TaskContext) -> TaskResult:
        return TaskResult.ok(status=TaskStatus.RUNNING, context=context)

    async def mark_progress(self, context: TaskContext, progress: dict[str, Any]) -> TaskResult:
        return TaskResult.ok(data=progress, status=TaskStatus.RUNNING, context=context)

    async def mark_succeeded(self, context: TaskContext, data: Any = None) -> TaskResult:
        return TaskResult.ok(data=data, status=TaskStatus.SUCCEEDED, context=context)

    async def mark_failed(
        self,
        context: TaskContext,
        error_code: AdapterErrorCode | str | None,
        error_message: str,
        *,
        status: TaskStatus | None = None,
    ) -> TaskResult:
        return TaskResult.fail(
            error_code,
            error_message,
            status=status,
            context=context,
        )

    async def query_status(self, context: TaskContext) -> TaskResult:
        current_status = context.metadata.get("status", TaskStatus.PENDING)
        return TaskResult.ok(
            data=context.metadata,
            status=TaskStatus(current_status),
            context=context,
        )

    async def run(
        self,
        context: TaskContext,
        operation: Callable[[], Any],
    ) -> TaskResult:
        started_at = datetime.now(timezone.utc)
        started_counter = time.perf_counter()
        try:
            raw_result = operation()
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
            finished_at = datetime.now(timezone.utc)
            duration_ms = (time.perf_counter() - started_counter) * 1000
            if isinstance(raw_result, TaskResult):
                raw_result.context = raw_result.context or context
                raw_result.started_at = raw_result.started_at or started_at
                raw_result.finished_at = raw_result.finished_at or finished_at
                raw_result.duration_ms = raw_result.duration_ms or duration_ms
                return raw_result
            if isinstance(raw_result, AdapterResult):
                return TaskResult.from_adapter_result(
                    raw_result,
                    context=context,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=raw_result.duration_ms or duration_ms,
                )
            return TaskResult.ok(
                raw_result,
                context=context,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
        except TaskExecutionError as exc:
            finished_at = datetime.now(timezone.utc)
            duration_ms = (time.perf_counter() - started_counter) * 1000
            return TaskResult.fail(
                exc.error_code or AdapterErrorCode.UNKNOWN_ERROR,
                str(exc),
                status=exc.status,
                provider=exc.provider,
                raw=exc.raw,
                context=context,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            duration_ms = (time.perf_counter() - started_counter) * 1000
            return TaskResult.fail(
                classify_exception(exc),
                str(exc),
                context=context,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
