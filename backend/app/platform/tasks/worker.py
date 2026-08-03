"""本地进程任务 worker（阶段0）。

不依赖 Redis/Celery；提供可替换的 handler 注册表与同步/异步执行接口。
后续可替换为 RQ/Celery/Dramatiq，只要保留相同的 handler 注册协议。

设计要点：
- handler 注册：task_type → async callable；
- 提交任务时若该 task_type 无 handler，标记任务 failed + DEPENDENCY_UNAVAILABLE，
  前端可显示「该任务类型暂未实现」而非无限 pending；
- handler 接收 TaskHandlerContext，包含 task_id、input_payload、session_factory、service；
- handler 自行调用 service.mark_running/mark_progress/mark_succeeded/mark_failed；
- run_inline 用于测试同步执行；submit 用于生产异步触发（asyncio.create_task）；
- 任何异常都会被捕获并分类为 error_code，绝不抛回调用方。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol

from sqlmodel import Session

from app.services.task_service import TaskService, task_service


logger = logging.getLogger(__name__)


class SessionFactory(Protocol):
    """与 app.models.database.get_session 兼容的会话工厂。"""

    def __call__(self) -> Any: ...


@dataclass
class TaskHandlerContext:
    """传给 task handler 的执行上下文。"""

    task_id: str
    input_payload: dict[str, Any]
    session_factory: SessionFactory
    service: TaskService
    # Optional platform reference lets durable handlers invoke a registered
    # runtime without importing the FastAPI app or creating a second graph.
    agent_platform: Any | None = None


TaskHandler = Callable[[TaskHandlerContext], Awaitable[None]]


# ---------------------------------------------------------------------------
# 错误码分类
# ---------------------------------------------------------------------------


class TaskExecutionError(Exception):
    """handler 抛出的结构化错误，携带 error_code 与 retryable。"""

    def __init__(self, error_code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retryable = retryable


def _classify_exception(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, TaskExecutionError):
        return exc.error_code, exc.message, exc.retryable
    if isinstance(exc, TimeoutError) or isinstance(exc, asyncio.TimeoutError):
        return "TIMEOUT", str(exc) or "任务执行超时", True
    if isinstance(exc, ValueError):
        return "VALIDATION_FAILED", str(exc) or "输入参数非法", False
    return "UNKNOWN_ERROR", f"{type(exc).__name__}: {exc}", True


# ---------------------------------------------------------------------------
# LocalTaskWorker
# ---------------------------------------------------------------------------


class LocalTaskWorker:
    """本地进程任务执行器。

    handler 注册表 + 同步/异步执行。任何未注册的 task_type 会被立即标记为
    failed + DEPENDENCY_UNAVAILABLE，避免任务无限 pending。
    """

    def __init__(self, service: TaskService = task_service, agent_platform: Any | None = None) -> None:
        self._service = service
        self._handlers: dict[str, TaskHandler] = {}
        self._agent_platform = agent_platform

    def set_agent_platform(self, platform: Any | None) -> None:
        """Inject the process-level AgentPlatform after application bootstrap."""
        self._agent_platform = platform

    def register(self, task_type: str, handler: TaskHandler) -> None:
        if not task_type:
            raise ValueError("task_type 不能为空")
        self._handlers[task_type] = handler

    def has_handler(self, task_type: str) -> bool:
        return task_type in self._handlers

    def submit(
        self,
        session_factory: SessionFactory,
        task_id: str,
        input_payload: dict[str, Any],
    ) -> asyncio.Task[None]:
        """异步触发任务执行（fire-and-forget）。返回 asyncio.Task 便于测试 await。"""
        return asyncio.create_task(self._execute(session_factory, task_id, input_payload))

    async def run_inline(
        self,
        session_factory: SessionFactory,
        task_id: str,
        input_payload: dict[str, Any],
    ) -> None:
        """同步执行（测试用）。"""
        await self._execute(session_factory, task_id, input_payload)

    async def _execute(
        self,
        session_factory: SessionFactory,
        task_id: str,
        input_payload: dict[str, Any],
    ) -> None:
        # 在独立 session 中执行，避免与请求级事务耦合
        with session_factory() as session:
            try:
                # 取任务记录以确定 task_type
                from app.models.task_model import TaskRecord
                from sqlmodel import select as _select
                record = session.exec(
                    _select(TaskRecord).where(TaskRecord.task_id == task_id)
                ).first()
                if record is None:
                    logger.error("Task %s not found; cannot execute", task_id)
                    return
                task_type = record.task_type
            except Exception:
                logger.exception("Failed to load task %s for execution", task_id)
                return

            handler = self._handlers.get(task_type)
            if handler is None:
                # 未注册的 task_type：诚实降级为 failed + DEPENDENCY_UNAVAILABLE
                try:
                    self._service.mark_failed(
                        session,
                        task_id,
                        error_code="DEPENDENCY_UNAVAILABLE",
                        error_message=f"任务类型 {task_type} 暂未注册 handler",
                        retryable=False,
                    )
                except Exception:
                    logger.exception("Failed to mark task %s as DEPENDENCY_UNAVAILABLE", task_id)
                return

            ctx = TaskHandlerContext(
                task_id=task_id,
                input_payload=input_payload,
                session_factory=session_factory,
                service=self._service,
                agent_platform=self._agent_platform,
            )
            try:
                await handler(ctx)
            except Exception as exc:
                error_code, message, retryable = _classify_exception(exc)
                try:
                    self._service.mark_failed(
                        session,
                        task_id,
                        error_code=error_code,
                        error_message=message,
                        retryable=retryable,
                    )
                except Exception:
                    logger.exception(
                        "Failed to record failure for task %s (original: %s)",
                        task_id,
                        message,
                    )


# 模块级单例
local_task_worker = LocalTaskWorker()


# ---------------------------------------------------------------------------
# 内置 handler：用于阶段0自检与测试
# ---------------------------------------------------------------------------


async def _noop_handler(ctx: TaskHandlerContext) -> None:
    """无副作用 handler，用于自检与契约测试。

    真实业务 handler 在后续阶段注册（document_parse、graph_ingest、media_gen 等）。
    每次 state 转移都使用独立 session，避免跨状态共享未提交事务。
    """
    with ctx.session_factory() as session:
        ctx.service.mark_running(session, ctx.task_id, stage="noop")
    with ctx.session_factory() as session:
        ctx.service.mark_progress(
            session,
            ctx.task_id,
            progress=50,
            stage="noop",
            message="no-op handler reached 50%",
        )
    with ctx.session_factory() as session:
        ctx.service.mark_succeeded(
            session,
            ctx.task_id,
            result_ref="noop://self-check",
            result_data={"handler": "noop", "completed_at": datetime.now(timezone.utc).isoformat()},
        )


async def _always_fail_handler(ctx: TaskHandlerContext) -> None:
    """总是失败的 handler，用于测试错误分类与重试流程。"""
    with ctx.session_factory() as session:
        ctx.service.mark_running(session, ctx.task_id, stage="failing")
    raise TaskExecutionError(
        "DEPENDENCY_UNAVAILABLE",
        "外部依赖不可用（测试用 handler）",
        retryable=True,
    )


def register_builtin_handlers(worker: LocalTaskWorker = local_task_worker) -> None:
    """注册阶段0自检 handler。"""
    worker.register("self_check_noop", _noop_handler)
    worker.register("self_check_fail", _always_fail_handler)
