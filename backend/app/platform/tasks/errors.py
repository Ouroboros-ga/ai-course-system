from __future__ import annotations

from typing import Any

from app.platform.adapters.errors import AdapterErrorCode
from app.platform.tasks.status import TaskStatus


class TaskExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: AdapterErrorCode | str | None = None,
        status: TaskStatus = TaskStatus.FAILED,
        provider: str | None = None,
        raw: Any = None,
    ):
        self.error_code = error_code.value if isinstance(error_code, AdapterErrorCode) else error_code
        self.status = status
        self.provider = provider
        self.raw = raw
        super().__init__(message)
