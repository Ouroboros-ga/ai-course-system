"""G5 对象存储运维端点

挂在 `/api/v1/admin/storage` 前缀下，全部要求 `PlatformPermission.ADMIN`：
- GET  /stats                 存储总览
- POST /reconcile              扫描 Provider 与 DB 引用，对齐 refs 表
- POST /gc                     回收超过保留期的软删除对象
- POST /verify-readback        抽样回读校验
- GET  /refs                   分页列出 refs
- POST /refs/{object_key}/soft-delete   手动标记软删除
- POST /refs/{object_key}/reactivate    撤销软删除

所有写操作返回结构化报告；GC 支持 dry_run，避免误删。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.access_control_model import PlatformPermission
from app.models.database import get_session
from app.services.course_access_service import require_platform_permission
from app.services.storage_admin_service import storage_admin_service


storage_admin_router = APIRouter(tags=["G5 对象存储运维"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class ReconcileRequest(BaseModel):
    prefix: str = Field(default="", max_length=500, description="只扫描此前缀下的对象")


class GarbageCollectRequest(BaseModel):
    retention_seconds: int = Field(default=86_400, ge=0, description="软删除保留期（秒）")
    dry_run: bool = Field(default=False, description="dry_run 只列候选不删除")
    max_deletions: int = Field(default=1_000, ge=1, le=10_000)


class VerifyReadbackRequest(BaseModel):
    sample_size: int = Field(default=10, ge=0, le=1_000, description="抽样数量；0 表示全量")
    prefix: str = Field(default="", max_length=500)


class SoftDeleteRequest(BaseModel):
    reason: str = Field(default="manual", max_length=200)


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@storage_admin_router.get("/stats")
async def get_storage_stats(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """存储总览：总数、总大小、按后端/校验状态分组"""
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)
    stats = storage_admin_service.get_stats(session)
    return unified_response(code=200, message="对象存储总览", data=stats)


@storage_admin_router.post("/reconcile")
async def reconcile_refs(
    payload: ReconcileRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """扫描 Provider 与 DB 引用，对齐 storage_object_refs 表"""
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)
    report = storage_admin_service.reconcile(session, prefix=payload.prefix)
    return unified_response(code=200, message="引用对齐完成", data=report.to_dict())


@storage_admin_router.post("/gc")
async def run_garbage_collection(
    payload: GarbageCollectRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """回收超过保留期的软删除对象

    - dry_run=True 只返回候选列表，不真正删除
    - 真正删除时若 Provider 中已无对象，只清理 ref 行
    - 删除失败保留 ref 行，错误记录在 report.errors
    """
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)
    report = storage_admin_service.run_gc(
        session,
        retention_seconds=payload.retention_seconds,
        dry_run=payload.dry_run,
        max_deletions=payload.max_deletions,
    )
    return unified_response(code=200, message="GC 完成", data=report.to_dict())


@storage_admin_router.post("/verify-readback")
async def verify_readback(
    payload: VerifyReadbackRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """抽样回读校验：真实读取 Provider 字节并重算 SHA256"""
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)
    report = storage_admin_service.verify_readback(
        session, sample_size=payload.sample_size, prefix=payload.prefix
    )
    return unified_response(code=200, message="回读校验完成", data=report.to_dict())


@storage_admin_router.get("/refs")
async def list_refs(
    soft_deleted_only: bool = Query(default=False),
    prefix: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """分页列出 refs"""
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)
    data = storage_admin_service.list_refs(
        session,
        soft_deleted_only=soft_deleted_only,
        prefix=prefix,
        limit=limit,
        offset=offset,
    )
    return unified_response(code=200, message="refs 列表", data=data)


@storage_admin_router.post("/refs/{object_key:path}/soft-delete")
async def mark_soft_deleted(
    object_key: str,
    payload: SoftDeleteRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """手动标记一个 object_key 为软删除"""
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)
    ok = storage_admin_service.mark_soft_deleted(
        session, object_key, reason=payload.reason
    )
    if not ok:
        return unified_response(code=404, message="ref 不存在", data={"object_key": object_key})
    return unified_response(code=200, message="已标记软删除", data={"object_key": object_key})


@storage_admin_router.post("/refs/{object_key:path}/reactivate")
async def reactivate_ref(
    object_key: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """撤销软删除标记（GC 真正删除前可恢复）"""
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)
    ok = storage_admin_service.reactivate(session, object_key)
    if not ok:
        return unified_response(code=404, message="ref 不存在或未标记软删除", data={"object_key": object_key})
    return unified_response(code=200, message="已恢复引用", data={"object_key": object_key})
