"""统一任务中心 API（阶段0）。

契约来源：PageDesign前端API契约规划.md §3.10
- GET /tasks?view=todo|created|system|completed&cursor=
- GET /tasks/{task_id}
- POST /tasks/{task_id}/cancel
- POST /tasks/{task_id}/retry
- GET /tasks/{task_id}/events
- POST /tasks/{task_id}/acknowledge

权限模型：
- 列表与详情均按 owner_user_id 隔离；course_id 过滤由调用方在请求参数中提供，
  且调用方必须先通过 CourseAccess 校验（后续阶段补强 course_id 过滤时的权限校验）；
- system view 需要平台权限（platform.admin / platform.audit），否则 403；
- 任何写操作（cancel/retry/acknowledge）只能由 owner 执行。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import (
    reject_capability_disabled,
    reject_course_access_denied,
    reject_validation_failed,
    unified_response,
)
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.access_control_model import PlatformPermission
from app.models.task_model import SchemaMigrationRecord
from app.services.course_access_service import require_platform_permission
from app.services.task_service import TaskCreateRequest, TaskViewModel, task_service


router = APIRouter(tags=["任务中心"])


# ---------------------------------------------------------------------------
# 请求体 schema
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    """创建任务请求体。

    路由层不直接暴露此接口；各业务域（document_parse/graph_ingest/...）有自己的
    创建端点，内部调用 TaskService.create_task。这里仅供自检端点使用。
    """

    task_type: str = Field(..., description="任务类型，如 document_parse|graph_ingest|media_gen")
    course_id: Optional[int] = Field(default=None, description="课程隔离键")
    node_id: Optional[int] = Field(default=None, description="关联知识点节点")
    input_summary: str = Field(default="", max_length=500)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    resource_links: list[dict[str, str]] = Field(default_factory=list)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class CancelRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------


@router.get("")
async def list_tasks(
    view: str = Query("created", description="todo|created|system|completed"),
    course_id: Optional[int] = Query(None),
    cursor: Optional[str] = Query(None),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])

    # system view 需要平台权限
    if view == "system":
        try:
            require_platform_permission(session, current_user, PlatformPermission.ADMIN)
        except Exception:
            # 退而求其次：只要 platform.course_audit 也可看 system view
            try:
                require_platform_permission(session, current_user, PlatformPermission.COURSE_AUDIT)
            except Exception:
                reject_course_access_denied("需要平台管理员或审计权限才能查看系统任务视图")

    result = task_service.list_tasks(
        session,
        owner_user_id=user_id,
        course_id=course_id,
        view=view,
        cursor=cursor,
        page_size=page_size,
    )
    return unified_response(200, "获取任务列表成功", result)


# ---------------------------------------------------------------------------
# 自检端点：必须先于 /{task_id} 注册，避免路径被吞为 task_id
# ---------------------------------------------------------------------------


@router.post("/self-check/{kind}")
async def self_check(
    kind: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """阶段0自检：创建一个 no-op 或 always-fail 任务并同步执行。

    kind=noop: 创建并立即成功；
    kind=fail: 创建并立即失败（DEPENDENCY_UNAVAILABLE）。
    不接入真实业务，仅用于验证任务中心端到端契约。
    """
    user_id = int(current_user["user_id"])
    if kind == "noop":
        task_type = "self_check_noop"
        summary = "self-check noop"
    elif kind == "fail":
        task_type = "self_check_fail"
        summary = "self-check always-fail"
    else:
        reject_validation_failed(f"未知的自检类型: {kind}")

    request = TaskCreateRequest(
        task_type=task_type,
        owner_user_id=user_id,
        input_summary=summary,
        input_payload={"kind": kind},
    )
    view = task_service.create_task(session, request)

    # 同步执行（测试 / 自检场景）。生产应使用 submit 异步触发。
    from app.platform.tasks.worker import local_task_worker, register_builtin_handlers
    register_builtin_handlers()
    from app.models.database import engine
    from sqlmodel import Session as _Session
    session_factory = lambda: _Session(engine)
    await local_task_worker.run_inline(session_factory, view.task_id, request.input_payload)

    final = task_service.get_task(session, view.task_id, owner_user_id=user_id)
    return unified_response(201, "自检任务已执行", final.to_dict())


# ---------------------------------------------------------------------------
# 迁移记录查询：必须先于 /{task_id} 注册
# ---------------------------------------------------------------------------


@router.get("/admin/migrations")
async def list_migrations(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出 schema_migration_records（需平台管理员权限）。"""
    try:
        require_platform_permission(session, current_user, PlatformPermission.ADMIN)
    except Exception:
        reject_course_access_denied("需要平台管理员权限才能查看迁移记录")
    from sqlmodel import select
    records = session.exec(
        select(SchemaMigrationRecord).order_by(SchemaMigrationRecord.applied_at.desc())
    ).all()
    items = [
        {
            "batch_id": r.batch_id,
            "name": r.name,
            "applied_at": r.applied_at.isoformat() if r.applied_at else "",
            "status": r.status,
            "rollback_notes": r.rollback_notes,
            "preflight_ok": r.preflight_ok,
            "applied_rows": r.applied_rows,
        }
        for r in records
    ]
    return unified_response(200, "获取迁移记录成功", {"items": items, "total": len(items)})


# ---------------------------------------------------------------------------
# 详情与状态流转
# ---------------------------------------------------------------------------


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])
    view = task_service.get_task(session, task_id, owner_user_id=user_id)
    return unified_response(200, "获取任务详情成功", view.to_dict())


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    body: CancelRequest = CancelRequest(),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])
    view = task_service.cancel(
        session,
        task_id,
        reason=body.reason,
        operator_user_id=user_id,
    )
    return unified_response(200, "任务已取消", view.to_dict())


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])
    view = task_service.retry(session, task_id, operator_user_id=user_id)
    return unified_response(202, "任务已重新入队", view.to_dict())


@router.post("/{task_id}/acknowledge")
async def acknowledge_task(
    task_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])
    view = task_service.acknowledge(session, task_id, operator_user_id=user_id)
    return unified_response(200, "任务已确认", view.to_dict())


@router.get("/{task_id}/events")
async def list_task_events(
    task_id: str,
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])
    events = task_service.list_events(
        session,
        task_id,
        owner_user_id=user_id,
        limit=limit,
    )
    return unified_response(200, "获取任务事件流成功", {"items": events, "total": len(events)})
