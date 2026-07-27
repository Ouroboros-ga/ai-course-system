from enum import Enum


class TaskStatus(str, Enum):
    """Internal normalized status for long-running task steps."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    # 后端重启等非正常中断遗留的 running/pending 任务，启动扫尾时转为 interrupted。
    # 非终态成功，但不再是"处理中"：前端给出"重新解析"操作，retry() 可回到 pending。
    INTERRUPTED = "interrupted"
    PARTIAL_SUCCESS = "partial_success"
