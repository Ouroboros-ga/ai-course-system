from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.access_control_model import PlatformPermission
from app.services.course_access_service import require_platform_permission
from app.services.platform_admin_service import (
    list_course_capabilities,
    list_integrations,
    update_course_capabilities,
    update_integration,
    list_users,
    update_user,
    reset_password,
)
from app.services.platform_task_concurrency_service import get_config, update_config

router = APIRouter(tags=["平台管理员"])


async def require_admin_management(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> dict:
    try:
        require_platform_permission(session, current_user, PlatformPermission.USER_MANAGE)
    except HTTPException:
        require_platform_permission(session, current_user, PlatformPermission.ADMIN)
    return current_user


class IntegrationUpdate(BaseModel):
    provider: Optional[str] = Field(default=None, max_length=64)
    base_url: Optional[str] = Field(default=None, max_length=500)
    model_name: Optional[str] = Field(default=None, max_length=200)
    api_key: Optional[str] = Field(default=None, max_length=1000)
    extra_config: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    expected_version: Optional[int] = Field(default=None, ge=0)


class UserUpdate(BaseModel):
    username: Optional[str] = Field(default=None, max_length=50)
    role: Optional[str] = Field(default=None, pattern="^(user|admin)$")
    is_active: Optional[bool] = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class TaskConcurrencyUpdate(BaseModel):
    developer_mode: bool = False
    max_total: int = Field(default=1, ge=1, le=32)
    document_parse: int = Field(default=1, ge=1, le=32)
    course_draft_build: int = Field(default=1, ge=1, le=32)
    graphrag: int = Field(default=1, ge=1, le=32)
    vector_index: int = Field(default=1, ge=1, le=32)
    sandbox_execution: int = Field(default=1, ge=1, le=32)
    # GraphRAG 单次构建的最大输入 token 预算（0 = 使用环境默认值）。
    graphrag_max_input_tokens: int = Field(default=0, ge=0, le=2000000)


class AdminCapabilityUpdate(BaseModel):
    learning: bool
    course_building: bool
    knowledge_graph: bool
    evidence: bool
    experiment: bool
    coding_sandbox: bool
    cognitive_analysis: bool
    safety_policy: bool


@router.get("/integrations")
async def get_integrations(session: Session = Depends(get_session), current_user: dict = Depends(require_admin_management)):
    return unified_response(200, "获取平台集成配置成功", {"items": list_integrations(session)})


@router.get("/task-concurrency")
async def get_task_concurrency(session: Session = Depends(get_session), current_user: dict = Depends(require_admin_management)):
    return unified_response(200, "获取任务并发配置成功", get_config(session))


@router.put("/task-concurrency")
async def put_task_concurrency(payload: TaskConcurrencyUpdate, session: Session = Depends(get_session), current_user: dict = Depends(require_admin_management)):
    data = update_config(session, int(current_user["user_id"]), payload.model_dump())
    return unified_response(200, "任务并发配置已保存", data)


@router.put("/integrations/{integration_key}")
async def put_integration(integration_key: str, payload: IntegrationUpdate, session: Session = Depends(get_session), current_user: dict = Depends(require_admin_management)):
    data = await update_integration(session, int(current_user["user_id"]), integration_key, payload.model_dump(exclude_none=True))
    return unified_response(200, "平台集成配置已保存", data)


@router.post("/integrations/{integration_key}/test")
async def test_integration(integration_key: str, session: Session = Depends(get_session), current_user: dict = Depends(require_admin_management)):
    from sqlmodel import select
    from app.models.platform_admin_model import PlatformIntegrationConfig
    from app.services.platform_admin_service import decrypt_secret
    from app.services.platform_provider_manager import provider_manager
    if integration_key in {"llm", "tts", "ppt", "asr"}:
        item = session.exec(select(PlatformIntegrationConfig).where(PlatformIntegrationConfig.integration_key == integration_key)).first()
        if item is None:
            return unified_response(503, "PROVIDER_NOT_CONFIGURED", {"integration_key": integration_key, "status": "not_configured"})
        probe = await provider_manager.probe(integration_key, provider=item.provider, base_url=item.base_url, model_name=item.model_name, api_key=decrypt_secret(item.encrypted_api_key), extra_config=item.extra_config)
        return unified_response(200 if probe.status in {"reachable", "configured"} else 503, probe.message, {"integration_key": integration_key, "status": probe.status})
    if integration_key not in {"llm", "tts", "ppt", "asr"}:
        return unified_response(404, "不支持的集成类型", None)
    # The actual Provider Manager can replace this probe without changing the API.
    return unified_response(200, "配置格式校验通过；运行时健康检查将在 Provider 刷新时执行", {"integration_key": integration_key, "status": "accepted"})


@router.get("/users")
async def get_users(
    user_id: Optional[int] = Query(default=None, ge=1),
    query: str = Query(default="", max_length=100),
    role: Optional[str] = Query(default=None, pattern="^(user|admin)$"),
    is_active: Optional[bool] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(require_admin_management),
):
    return unified_response(200, "获取用户列表成功", list_users(session, user_id=user_id, query=query, role=role, is_active=is_active, page=page, page_size=page_size))


@router.patch("/users/{user_id}")
async def patch_user(user_id: int, payload: UserUpdate, session: Session = Depends(get_session), current_user: dict = Depends(require_admin_management)):
    data = update_user(session, int(current_user["user_id"]), user_id, payload.model_dump(exclude_none=True))
    return unified_response(200, "用户信息已更新", data)


@router.post("/users/{user_id}/reset-password")
async def post_reset_password(user_id: int, payload: PasswordReset, session: Session = Depends(get_session), current_user: dict = Depends(require_admin_management)):
    reset_password(session, int(current_user["user_id"]), user_id, payload.password)
    return unified_response(200, "密码已重置", {"user_id": user_id})


@router.get("/courses/capabilities")
async def get_course_capabilities(session: Session = Depends(get_session), current_user: dict = Depends(require_admin_management)):
    return unified_response(200, "获取课程能力开关成功", {"items": list_course_capabilities(session)})


@router.put("/courses/{course_id}/capabilities")
async def put_course_capabilities(course_id: int, payload: AdminCapabilityUpdate, session: Session = Depends(get_session), current_user: dict = Depends(require_admin_management)):
    data = update_course_capabilities(session, course_id, payload.model_dump(), int(current_user["user_id"]))
    return unified_response(200, "课程能力开关已保存", data)
