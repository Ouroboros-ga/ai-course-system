"""统一任务中心服务（阶段0）。

不依赖 Redis/Celery；使用 SQLModel 持久化 + 可替换的本地 worker 适配接口。
后续可替换为 RQ/Celery/Dramatiq，只要保留相同的 TaskService 接口。

设计要点：
- create_task：支持 idempotency_key 幂等，未提供时生成 UUID；
- 任何课程范围任务必须传 course_id，并要求调用方先做 CourseAccess 校验
  （TaskService 不直接耦合 CourseAccess，保持单一职责）；
- 跨课程查询拒绝：list_tasks 必须按 owner_user_id 或 course_id 过滤；
- 状态机严格：pending→running→succeeded/failed/cancelled，禁止跨态跳跃；
- cancel/retry/acknowledge 均追加事件，保持事件流完整；
- 失败时记录 error_code 与 retryable，前端据此决定是否可重试。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlmodel import Session, select

from app.core.exceptions import (
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.models.task_model import (
    IdempotencyKeyRecord,
    TaskEventRecord,
    TaskRecord,
    TaskResourceLinkRecord,
)


# ---------------------------------------------------------------------------
# 协议：TaskService 与 worker 之间的契约
# ---------------------------------------------------------------------------


@dataclass
class TaskCreateRequest:
    """创建任务的输入参数。"""

    task_type: str
    owner_user_id: int
    course_id: Optional[int] = None
    node_id: Optional[int] = None
    input_summary: str = ""
    input_payload: dict[str, Any] = field(default_factory=dict)
    resource_links: list[dict[str, str]] = field(default_factory=list)
    idempotency_key: Optional[str] = None
    idempotency_ttl_seconds: int = 24 * 3600
    parent_task_id: Optional[str] = None


@dataclass
class TaskViewModel:
    """对外的任务视图，不暴露自增主键与原始 payload 大对象。"""

    task_id: str
    task_type: str
    status: str
    stage: str
    progress: int
    owner_user_id: int
    course_id: Optional[int]
    node_id: Optional[int]
    input_summary: str
    result_ref: str
    result_data: dict[str, Any]
    error_code: str
    error_message: str
    retryable: bool
    acknowledged: bool
    acknowledged_at: Optional[str]
    parent_task_id: Optional[str]
    idempotency_key: Optional[str]
    created_at: str
    updated_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    affected_resources: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_record(
        cls,
        record: TaskRecord,
        *,
        links: Iterable[TaskResourceLinkRecord] = (),
    ) -> "TaskViewModel":
        def _iso(value: Optional[datetime]) -> Optional[str]:
            return value.isoformat() if value else None

        try:
            result_data = json.loads(record.result_data) if record.result_data else {}
        except (TypeError, ValueError):
            result_data = {}

        return cls(
            task_id=record.task_id,
            task_type=record.task_type,
            status=record.status,
            stage=record.stage,
            progress=record.progress,
            owner_user_id=record.owner_user_id,
            course_id=record.course_id,
            node_id=record.node_id,
            input_summary=record.input_summary,
            result_ref=record.result_ref,
            result_data=result_data,
            error_code=record.error_code,
            error_message=record.error_message,
            retryable=record.retryable,
            acknowledged=record.acknowledged,
            acknowledged_at=_iso(record.acknowledged_at),
            parent_task_id=record.parent_task_id,
            idempotency_key=record.idempotency_key,
            created_at=record.created_at.isoformat() if record.created_at else "",
            updated_at=record.updated_at.isoformat() if record.updated_at else "",
            started_at=_iso(record.started_at),
            finished_at=_iso(record.finished_at),
            affected_resources=[
                {
                    "resource_kind": link.resource_kind,
                    "resource_id": link.resource_id,
                    "relation": link.relation,
                }
                for link in links
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["affected_resources"] = list(self.affected_resources)
        return data


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "cancelled", "failed"},
    "running": {"succeeded", "failed", "cancelled", "partial_success"},
    "partial_success": {"failed", "cancelled"},
    "failed": {"running"},  # retry
    "cancelled": {"running"},  # retry
    "succeeded": set(),  # terminal
}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "partial_success"}


def _assert_transition(current: str, target: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        reject_state_conflict(
            f"任务状态不允许从 {current} 转移到 {target}",
            details={"current_status": current, "target_status": target},
        )


# ---------------------------------------------------------------------------
# TaskService
# ---------------------------------------------------------------------------


class TaskService:
    """任务中心核心服务。

    所有写操作都接受外部 Session，由路由层管理事务边界；
    服务自身不创建独立 session，避免与请求级事务脱节。
    """

    IDEMPOTENCY_DEFAULT_TTL = timedelta(days=1)

    # --- 创建 ---------------------------------------------------------------

    def create_task(self, session: Session, request: TaskCreateRequest) -> TaskViewModel:
        if not request.task_type:
            reject_validation_failed("task_type 不能为空")
        if not request.owner_user_id:
            reject_validation_failed("owner_user_id 不能为空")

        # 幂等检查
        if request.idempotency_key:
            existing = self._lookup_idempotent(
                session,
                request.owner_user_id,
                request.idempotency_key,
            )
            if existing is not None:
                # 命中窗口期内已存在的任务，直接返回（不重复创建）
                return self.get_task(session, existing, owner_user_id=request.owner_user_id)

        task_id = uuid.uuid4().hex
        now = datetime.utcnow()
        payload_str = json.dumps(request.input_payload, ensure_ascii=False, sort_keys=True)
        record = TaskRecord(
            task_id=task_id,
            task_type=request.task_type,
            status="pending",
            stage="",
            progress=0,
            owner_user_id=request.owner_user_id,
            course_id=request.course_id,
            node_id=request.node_id,
            input_summary=request.input_summary[:500],
            input_payload=payload_str,
            parent_task_id=request.parent_task_id,
            idempotency_key=request.idempotency_key,
            created_at=now,
            updated_at=now,
        )
        session.add(record)

        # 幂等键记录
        if request.idempotency_key:
            payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
            session.add(IdempotencyKeyRecord(
                user_id=request.owner_user_id,
                idempotency_key=request.idempotency_key,
                task_id=task_id,
                request_payload_hash=payload_hash,
                expires_at=now + timedelta(seconds=request.idempotency_ttl_seconds),
                created_at=now,
            ))

        # 资源链接
        link_records: list[TaskResourceLinkRecord] = []
        for link in request.resource_links:
            if not link.get("resource_kind") or not link.get("resource_id"):
                continue
            link_record = TaskResourceLinkRecord(
                task_id=task_id,
                resource_kind=link["resource_kind"],
                resource_id=str(link["resource_id"]),
                relation=link.get("relation", "input"),
                created_at=now,
            )
            session.add(link_record)
            link_records.append(link_record)

        # 事件
        session.add(TaskEventRecord(
            task_id=task_id,
            event_type="created",
            stage="",
            progress=0,
            message=request.input_summary[:200],
            event_data=payload_str,
            created_at=now,
        ))

        session.commit()
        session.refresh(record)
        return TaskViewModel.from_record(record, links=link_records)

    # --- 查询 ---------------------------------------------------------------

    def get_task(
        self,
        session: Session,
        task_id: str,
        *,
        owner_user_id: Optional[int] = None,
    ) -> TaskViewModel:
        record = self._require_task(session, task_id)
        if owner_user_id is not None and record.owner_user_id != owner_user_id:
            # 跨用户访问拒绝，但统一返回 404 避免泄露任务存在性
            reject_resource_not_found("任务不存在或无权访问")
        links = session.exec(
            select(TaskResourceLinkRecord).where(TaskResourceLinkRecord.task_id == task_id)
        ).all()
        return TaskViewModel.from_record(record, links=links)

    def list_tasks(
        self,
        session: Session,
        *,
        owner_user_id: Optional[int] = None,
        course_id: Optional[int] = None,
        view: str = "created",
        cursor: Optional[str] = None,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """列表查询。view=todo|created|system|completed 控制过滤范围。"""
        if page_size < 1 or page_size > 100:
            reject_validation_failed("page_size 必须在 1..100 之间")

        stmt = select(TaskRecord)
        if owner_user_id is not None:
            stmt = stmt.where(TaskRecord.owner_user_id == owner_user_id)
        if course_id is not None:
            stmt = stmt.where(TaskRecord.course_id == course_id)

        if view == "todo":
            # 待处理：未完成且未确认
            stmt = stmt.where(TaskRecord.status.in_(["pending", "running", "failed", "partial_success"]))
            stmt = stmt.where(TaskRecord.acknowledged == False)
        elif view == "created":
            pass  # 由 owner_user_id 过滤即可
        elif view == "system":
            # 系统视角：所有未完成任务（需调用方具备平台权限）
            stmt = stmt.where(TaskRecord.status.in_(["pending", "running"]))
        elif view == "completed":
            stmt = stmt.where(TaskRecord.status.in_(TERMINAL_STATUSES))
        else:
            reject_validation_failed(f"未知的 view: {view}")

        # 游标分页：按 created_at 倒序，cursor 为上一页最后一条的 created_at+task_id
        if cursor:
            try:
                cursor_ts, cursor_id = cursor.split("|", 1)
                stmt = stmt.where(
                    (TaskRecord.created_at < datetime.fromisoformat(cursor_ts))
                    | (
                        (TaskRecord.created_at == datetime.fromisoformat(cursor_ts))
                        & (TaskRecord.task_id < cursor_id)
                    )
                )
            except (ValueError, IndexError):
                reject_validation_failed("cursor 格式非法")

        stmt = stmt.order_by(TaskRecord.created_at.desc(), TaskRecord.task_id.desc()).limit(page_size + 1)
        records = session.exec(stmt).all()
        has_next = len(records) > page_size
        records = records[:page_size]

        items: list[dict[str, Any]] = []
        for record in records:
            links = session.exec(
                select(TaskResourceLinkRecord).where(TaskResourceLinkRecord.task_id == record.task_id)
            ).all()
            items.append(TaskViewModel.from_record(record, links=links).to_dict())

        next_cursor = None
        if has_next and records:
            last = records[-1]
            next_cursor = f"{last.created_at.isoformat()}|{last.task_id}"

        return {
            "items": items,
            "next_cursor": next_cursor,
            "total": len(items),
            "has_next": has_next,
            "view": view,
        }

    # --- 状态流转 -----------------------------------------------------------

    def mark_running(
        self,
        session: Session,
        task_id: str,
        *,
        stage: Optional[str] = None,
    ) -> TaskViewModel:
        record = self._require_task(session, task_id)
        _assert_transition(record.status, "running")
        now = datetime.utcnow()
        record.status = "running"
        record.started_at = record.started_at or now
        record.updated_at = now
        if stage:
            record.stage = stage
        session.add(record)
        session.add(TaskEventRecord(
            task_id=task_id,
            event_type="started",
            stage=stage or record.stage,
            progress=record.progress,
            message="任务开始执行",
            created_at=now,
        ))
        session.commit()
        session.refresh(record)
        return TaskViewModel.from_record(record)

    def mark_progress(
        self,
        session: Session,
        task_id: str,
        *,
        progress: int,
        stage: Optional[str] = None,
        message: str = "",
    ) -> TaskViewModel:
        record = self._require_task(session, task_id)
        if record.status not in {"pending", "running", "partial_success"}:
            reject_state_conflict(f"任务处于 {record.status} 状态，不能更新进度")
        if not 0 <= progress <= 100:
            reject_validation_failed("progress 必须在 0..100 之间")
        now = datetime.utcnow()
        record.progress = progress
        record.updated_at = now
        if stage:
            record.stage = stage
        session.add(record)
        session.add(TaskEventRecord(
            task_id=task_id,
            event_type="progress",
            stage=record.stage,
            progress=progress,
            message=message,
            created_at=now,
        ))
        session.commit()
        session.refresh(record)
        return TaskViewModel.from_record(record)

    def mark_succeeded(
        self,
        session: Session,
        task_id: str,
        *,
        result_ref: str = "",
        result_data: Optional[dict[str, Any]] = None,
    ) -> TaskViewModel:
        record = self._require_task(session, task_id)
        _assert_transition(record.status, "succeeded")
        now = datetime.utcnow()
        record.status = "succeeded"
        record.progress = 100
        record.finished_at = now
        record.updated_at = now
        record.result_ref = result_ref
        if result_data is not None:
            record.result_data = json.dumps(result_data, ensure_ascii=False)
        session.add(record)
        session.add(TaskEventRecord(
            task_id=task_id,
            event_type="succeeded",
            stage=record.stage,
            progress=100,
            message="任务执行成功",
            event_data=record.result_data,
            created_at=now,
        ))
        session.commit()
        session.refresh(record)
        return TaskViewModel.from_record(record)

    def mark_failed(
        self,
        session: Session,
        task_id: str,
        *,
        error_code: str,
        error_message: str,
        retryable: bool = True,
    ) -> TaskViewModel:
        record = self._require_task(session, task_id)
        _assert_transition(record.status, "failed")
        now = datetime.utcnow()
        record.status = "failed"
        record.finished_at = now
        record.updated_at = now
        record.error_code = error_code
        record.error_message = error_message[:500]
        record.retryable = retryable
        session.add(record)
        session.add(TaskEventRecord(
            task_id=task_id,
            event_type="failed",
            stage=record.stage,
            progress=record.progress,
            message=error_message[:200],
            error_code=error_code,
            created_at=now,
        ))
        session.commit()
        session.refresh(record)
        return TaskViewModel.from_record(record)

    def cancel(
        self,
        session: Session,
        task_id: str,
        *,
        reason: str = "",
        operator_user_id: Optional[int] = None,
    ) -> TaskViewModel:
        record = self._require_task(session, task_id)
        if operator_user_id is not None and record.owner_user_id != operator_user_id:
            reject_resource_not_found("任务不存在或无权访问")
        _assert_transition(record.status, "cancelled")
        now = datetime.utcnow()
        record.status = "cancelled"
        record.finished_at = now
        record.updated_at = now
        session.add(record)
        session.add(TaskEventRecord(
            task_id=task_id,
            event_type="cancelled",
            stage=record.stage,
            message=reason or "用户取消",
            created_at=now,
        ))
        session.commit()
        session.refresh(record)
        return TaskViewModel.from_record(record)

    def retry(
        self,
        session: Session,
        task_id: str,
        *,
        operator_user_id: Optional[int] = None,
    ) -> TaskViewModel:
        record = self._require_task(session, task_id)
        if operator_user_id is not None and record.owner_user_id != operator_user_id:
            reject_resource_not_found("任务不存在或无权访问")
        if not record.retryable:
            reject_state_conflict("任务不可重试")
        _assert_transition(record.status, "running")
        now = datetime.utcnow()
        record.status = "running"
        record.error_code = ""
        record.error_message = ""
        record.progress = 0
        record.started_at = now
        record.finished_at = None
        record.updated_at = now
        session.add(record)
        session.add(TaskEventRecord(
            task_id=task_id,
            event_type="retried",
            message="任务重试",
            created_at=now,
        ))
        session.commit()
        session.refresh(record)
        return TaskViewModel.from_record(record)

    def acknowledge(
        self,
        session: Session,
        task_id: str,
        *,
        operator_user_id: Optional[int] = None,
    ) -> TaskViewModel:
        record = self._require_task(session, task_id)
        if operator_user_id is not None and record.owner_user_id != operator_user_id:
            reject_resource_not_found("任务不存在或无权访问")
        if record.acknowledged:
            return TaskViewModel.from_record(record)
        now = datetime.utcnow()
        record.acknowledged = True
        record.acknowledged_at = now
        record.updated_at = now
        session.add(record)
        session.add(TaskEventRecord(
            task_id=task_id,
            event_type="acknowledged",
            message="用户已确认",
            created_at=now,
        ))
        session.commit()
        session.refresh(record)
        return TaskViewModel.from_record(record)

    # --- 事件流 -------------------------------------------------------------

    def list_events(
        self,
        session: Session,
        task_id: str,
        *,
        owner_user_id: Optional[int] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        record = self._require_task(session, task_id)
        if owner_user_id is not None and record.owner_user_id != owner_user_id:
            reject_resource_not_found("任务不存在或无权访问")
        if limit < 1 or limit > 500:
            reject_validation_failed("limit 必须在 1..500 之间")
        events = session.exec(
            select(TaskEventRecord)
            .where(TaskEventRecord.task_id == task_id)
            .order_by(TaskEventRecord.created_at.asc(), TaskEventRecord.id.asc())
            .limit(limit)
        ).all()
        return [
            {
                "event_type": e.event_type,
                "stage": e.stage,
                "progress": e.progress,
                "message": e.message,
                "error_code": e.error_code,
                "event_data": json.loads(e.event_data) if e.event_data else {},
                "created_at": e.created_at.isoformat() if e.created_at else "",
            }
            for e in events
        ]

    # --- 内部辅助 ------------------------------------------------------------

    def _require_task(self, session: Session, task_id: str) -> TaskRecord:
        record = session.exec(
            select(TaskRecord).where(TaskRecord.task_id == task_id)
        ).first()
        if record is None:
            reject_resource_not_found("任务不存在或无权访问")
        return record

    def _lookup_idempotent(
        self,
        session: Session,
        user_id: int,
        idempotency_key: str,
    ) -> Optional[str]:
        now = datetime.utcnow()
        record = session.exec(
            select(IdempotencyKeyRecord).where(
                IdempotencyKeyRecord.user_id == user_id,
                IdempotencyKeyRecord.idempotency_key == idempotency_key,
                IdempotencyKeyRecord.expires_at > now,
            )
        ).first()
        return record.task_id if record else None


# 模块级单例，供路由注入；后续可替换为依赖注入容器
task_service = TaskService()
