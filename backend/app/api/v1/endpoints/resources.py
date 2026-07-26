"""阶段7 资源库 API 路由

契约来源：PageDesign前端API契约规划.md §3.9

路由前缀：/api/v1/resources

权限模型：
- 资源按 owner_user_id 严格隔离；course scope 资源额外按 course_id 隔离
- 仅 owner（或被 ACL 授权的用户）可读/写资源
- 软删除进入回收站，恢复时返回下游影响，purge 需更高权限
- 跨用户/课程绝不暴露

接口：
- GET    /resources/files                  列表（scope=mine|course|recent|trash）
- POST   /resources/files                  创建资源（含首版本）
- GET    /resources/files/{resource_id}    资源详情
- PATCH  /resources/files/{resource_id}    更新名称/描述/标签
- POST   /resources/files/{resource_id}/references   新增引用
- GET    /resources/files/{resource_id}/references   引用列表
- DELETE /resources/files/{resource_id}    软删除（返回下游影响）
- POST   /resources/files/{resource_id}/restore      从回收站恢复
- DELETE /resources/files/{resource_id}/purge        彻底删除
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.resource_model import ResourceItemType
from app.services.resource_service import resource_service


resource_router = APIRouter()


# ---------------------------------------------------------------------------
# 请求 schema
# ---------------------------------------------------------------------------


class ResourceCreateRequest(BaseModel):
    """创建资源请求体

    实际文件上传通过 object_key 关联到本地/OSS 对象；本接口只创建资源记录与首版本。
    """

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    resource_type: ResourceItemType = ResourceItemType.OTHER
    mime_type: str = Field(default="", max_length=200)
    file_size: int = Field(default=0, ge=0)
    object_key: str = Field(default="", max_length=500)
    content_hash: str = Field(default="", max_length=128)
    tags: list[str] = Field(default_factory=list)
    course_id: Optional[int] = Field(
        default=None,
        description="课程级资源时填写；为空表示个人资源",
    )


class ResourceUpdateRequest(BaseModel):
    """更新资源元数据"""

    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    tags: Optional[list[str]] = None


class ReferenceCreateRequest(BaseModel):
    """新增资源引用"""

    target_type: str = Field(..., description="course|node|experiment|lab")
    target_course_id: Optional[int] = None
    target_node_id: Optional[int] = None
    target_experiment_id: Optional[str] = None
    target_lab_id: Optional[str] = None
    version_id: Optional[str] = None
    reference_note: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def _serialize_resource(r) -> dict[str, Any]:
    return {
        "resource_id": r.resource_id,
        "owner_user_id": r.owner_user_id,
        "course_id": r.course_id,
        "scope": r.scope.value,
        "name": r.name,
        "description": r.description,
        "resource_type": r.resource_type.value,
        "mime_type": r.mime_type,
        "file_size": r.file_size,
        "current_version_id": r.current_version_id,
        "is_deleted": r.is_deleted,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
    }


def _serialize_reference(ref) -> dict[str, Any]:
    return {
        "reference_id": ref.reference_id,
        "resource_id": ref.resource_id,
        "version_id": ref.version_id,
        "owner_user_id": ref.owner_user_id,
        "target_type": ref.target_type,
        "target_course_id": ref.target_course_id,
        "target_node_id": ref.target_node_id,
        "target_experiment_id": ref.target_experiment_id,
        "target_lab_id": ref.target_lab_id,
        "reference_note": ref.reference_note,
        "created_at": ref.created_at.isoformat() if ref.created_at else None,
    }


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@resource_router.get("/files")
async def list_files(
    scope: str = Query(default="mine", description="mine|course|recent|trash"),
    course_id: Optional[int] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出资源文件，按 scope 过滤；只能看到自己的资源。"""
    user_id = int(current_user["user_id"])
    result = resource_service.list_resources(
        session,
        owner_user_id=user_id,
        course_id=course_id,
        scope=scope,
        include_deleted=(scope == "trash"),
        cursor=cursor,
        page_size=page_size,
    )
    return unified_response(
        code=200,
        message="获取资源列表成功",
        data=result,
    )


@resource_router.post("/files")
async def create_file(
    payload: ResourceCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建资源（含首版本）。课程级资源需调用方拥有 course 权限；本端仅做归属登记。"""
    user_id = int(current_user["user_id"])
    resource = resource_service.create_resource(
        session,
        owner_user_id=user_id,
        course_id=payload.course_id,
        name=payload.name,
        description=payload.description,
        resource_type=payload.resource_type,
        mime_type=payload.mime_type,
        file_size=payload.file_size,
        object_key=payload.object_key,
        content_hash=payload.content_hash,
        tags=payload.tags,
    )
    session.commit()
    session.refresh(resource)
    return unified_response(
        code=201,
        message="资源已创建",
        data=_serialize_resource(resource),
    )


@resource_router.get("/files/{resource_id}")
async def get_file(
    resource_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取资源详情（仅 owner 或 ACL 授权用户）。"""
    user_id = int(current_user["user_id"])
    resource = resource_service.get_resource(
        session, resource_id=resource_id, owner_user_id=user_id,
    )
    return unified_response(
        code=200,
        message="获取资源详情成功",
        data=_serialize_resource(resource),
    )


@resource_router.patch("/files/{resource_id}")
async def update_file(
    resource_id: str,
    payload: ResourceUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新资源名称/描述/标签（仅 owner）。"""
    user_id = int(current_user["user_id"])
    resource = resource_service.update_resource(
        session,
        resource_id=resource_id,
        owner_user_id=user_id,
        name=payload.name,
        description=payload.description,
        tags=payload.tags,
    )
    session.commit()
    session.refresh(resource)
    return unified_response(
        code=200,
        message="资源已更新",
        data=_serialize_resource(resource),
    )


@resource_router.post("/files/{resource_id}/references")
async def add_reference(
    resource_id: str,
    payload: ReferenceCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """新增资源引用（用于删除时返回下游影响）。"""
    user_id = int(current_user["user_id"])
    reference = resource_service.add_reference(
        session,
        resource_id=resource_id,
        owner_user_id=user_id,
        target_type=payload.target_type,
        target_course_id=payload.target_course_id,
        target_node_id=payload.target_node_id,
        target_experiment_id=payload.target_experiment_id,
        target_lab_id=payload.target_lab_id,
        version_id=payload.version_id,
        reference_note=payload.reference_note,
    )
    session.commit()
    session.refresh(reference)
    return unified_response(
        code=201,
        message="引用已登记",
        data=_serialize_reference(reference),
    )


@resource_router.get("/files/{resource_id}/references")
async def list_references(
    resource_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出资源的所有引用（仅 owner）。"""
    user_id = int(current_user["user_id"])
    references = resource_service.list_references(
        session, resource_id=resource_id, owner_user_id=user_id,
    )
    return unified_response(
        code=200,
        message="获取引用列表成功",
        data={
            "resource_id": resource_id,
            "items": [_serialize_reference(r) for r in references],
            "total": len(references),
        },
    )


@resource_router.delete("/files/{resource_id}")
async def soft_delete_file(
    resource_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """软删除资源，返回下游影响（不静默删除）。"""
    user_id = int(current_user["user_id"])
    result = resource_service.soft_delete(
        session, resource_id=resource_id, deleted_by=user_id,
    )
    session.commit()
    return unified_response(
        code=200,
        message="资源已移入回收站",
        data=result,
    )


@resource_router.post("/files/{resource_id}/restore")
async def restore_file(
    resource_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """从回收站恢复资源。"""
    user_id = int(current_user["user_id"])
    resource = resource_service.restore(
        session, resource_id=resource_id, restored_by=user_id,
    )
    session.commit()
    session.refresh(resource)
    return unified_response(
        code=200,
        message="资源已恢复",
        data=_serialize_resource(resource),
    )


@resource_router.delete("/files/{resource_id}/purge")
async def purge_file(
    resource_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """彻底删除资源（需 owner；仅对回收站中的资源生效）。"""
    user_id = int(current_user["user_id"])
    result = resource_service.purge(
        session, resource_id=resource_id, purged_by=user_id,
    )
    session.commit()
    return unified_response(
        code=200,
        message="资源已彻底删除",
        data=result,
    )
