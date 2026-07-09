from enum import Enum


class TaskStatus(str, Enum):
    """Internal normalized status for long-running task steps."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    PARTIAL_SUCCESS = "partial_success"
