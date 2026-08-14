from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, func

from app.core.config import settings
from app.core.security import get_password_hash
from app.core.time_utils import utcnow_aware
from app.models.access_control_model import (
    CourseCapability,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course
from app.models.platform_admin_model import PlatformAdminAuditEvent, PlatformIntegrationConfig
from app.models.user_model import User, UserRole, normalize_username
from app.services.course_access_service import CAPABILITY_NAMES
from app.services.platform_provider_manager import provider_manager


def _key_material() -> bytes:
    raw = getattr(settings, "PLATFORM_CONFIG_ENCRYPTION_KEY", "") or getattr(settings, "JWT_SECRET_KEY", "")
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return Fernet(_key_material()).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return Fernet(_key_material()).decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(status_code=503, detail="平台密钥材料无效，无法读取 Provider 配置") from exc


def audit(session: Session, actor_id: int, action: str, target_type: str, target_id: str, metadata: dict[str, Any] | None = None) -> None:
    session.add(PlatformAdminAuditEvent(actor_user_id=actor_id, action=action, target_type=target_type, target_id=target_id, audit_metadata=metadata or {}))


def serialize_integration(config: PlatformIntegrationConfig) -> dict[str, Any]:
    return {
        "integration_key": config.integration_key,
        "provider": config.provider,
        "base_url": config.base_url,
        "model_name": config.model_name,
        "key_configured": bool(config.encrypted_api_key),
        "key_last4": config.api_key_last4 or None,
        "extra_config": {k: v for k, v in (config.extra_config or {}).items() if not str(k).lower().endswith(("key", "secret", "token"))},
        "enabled": config.enabled,
        "version": config.version,
        "health_status": config.health_status,
        "health_message": config.health_message,
        "last_checked_at": config.last_checked_at.isoformat() if config.last_checked_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


_INTEGRATION_KEYS: tuple = ("llm", "tts", "ppt", "asr")
#: 支持管理员一键开关（真实接入 true/false）的集成；ppt 仅保留配置管理兼容。
_TOGGLE_KEYS: tuple = ("llm", "tts", "asr")


def list_integrations(session: Session) -> list[dict[str, Any]]:
    values = {item.integration_key: item for item in session.exec(select(PlatformIntegrationConfig)).all()}
    return [serialize_integration(values[key]) if key in values else {"integration_key": key, "provider": "", "base_url": "", "model_name": "", "key_configured": False, "key_last4": None, "extra_config": {}, "enabled": False, "version": 0, "health_status": "not_configured", "health_message": "尚未配置"} for key in _INTEGRATION_KEYS]


async def update_integration(session: Session, actor_id: int, key: str, payload: dict[str, Any]) -> dict[str, Any]:
    if key not in _INTEGRATION_KEYS:
        raise HTTPException(status_code=404, detail="不支持的集成类型")
    item = session.exec(select(PlatformIntegrationConfig).where(PlatformIntegrationConfig.integration_key == key)).first()
    expected = payload.get("expected_version")
    if item is None:
        item = PlatformIntegrationConfig(integration_key=key)
    elif expected is not None and int(expected) != item.version:
        raise HTTPException(status_code=409, detail="配置版本冲突，请刷新后重试")
    enabled_now = bool(payload.get("enabled", item.enabled))
    for field in ("provider", "base_url", "model_name", "enabled"):
        if field in payload and payload[field] is not None:
            setattr(item, field, payload[field])
    if payload.get("api_key"):
        secret = str(payload["api_key"])
        item.encrypted_api_key = encrypt_secret(secret)
        item.api_key_last4 = secret[-4:]
    if payload.get("extra_config") is not None:
        item.extra_config = payload["extra_config"]
    item.version = max(1, item.version + (0 if item.id is None else 1))
    item.updated_by = actor_id
    item.updated_at = utcnow_aware()

    secret = decrypt_secret(item.encrypted_api_key)
    # 管理员开关语义：enabled=false 直接保存并应用禁用态，不要求 Provider 可达；
    # enabled=true 必须先通过配置校验（probe）再热刷新真实接入。
    if not enabled_now:
        item.health_status = "disabled"
        item.health_message = "真实接入已关闭；未调用外部服务"
        item.last_checked_at = utcnow_aware()
        session.add(item)
        audit(session, actor_id, "integration.disable", "integration", key, {"version": item.version})
        session.commit()
        session.refresh(item)
        provider_manager.apply_disabled(key)
        return serialize_integration(item)

    item.health_status = "pending"
    item.health_message = "配置已保存，等待 Provider 健康检查"
    probe = await provider_manager.probe(key, provider=item.provider, base_url=item.base_url, model_name=item.model_name, api_key=secret, extra_config=item.extra_config)
    if probe.status not in {"reachable", "configured"}:
        session.rollback()
        raise HTTPException(status_code=503, detail={"code": "PROVIDER_UNAVAILABLE", "message": probe.message})
    try:
        provider_manager.refresh(key, provider=item.provider, base_url=item.base_url, model_name=item.model_name, api_key=secret, extra_config=item.extra_config)
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail={"code": "PROVIDER_UNAVAILABLE", "message": type(exc).__name__}) from exc
    item.health_status = "healthy"
    item.health_message = probe.message
    item.last_checked_at = utcnow_aware()
    session.add(item)
    audit(session, actor_id, "integration.enable", "integration", key, {"version": item.version})
    session.commit()
    session.refresh(item)
    return serialize_integration(item)


def list_users(session: Session, *, user_id: int | None = None, query: str = "", role: str | None = None, is_active: bool | None = None, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    statement = select(User)
    if user_id is not None:
        statement = statement.where(User.id == user_id)
    if query:
        statement = statement.where(User.username.contains(query))
    if role:
        normalized = "admin" if role == "admin" else "user"
        statement = statement.where(User.role == UserRole.ADMIN if normalized == "admin" else User.role != UserRole.ADMIN)
    if is_active is not None:
        statement = statement.where(User.is_active == is_active)
    total = session.exec(select(func.count()).select_from(statement.subquery())).one()
    users = session.exec(statement.order_by(User.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": u.id, "username": u.username, "role": "admin" if str(u.role) == "UserRole.ADMIN" or getattr(u.role, "value", u.role) == "admin" else "user", "is_active": u.is_active, "created_at": u.created_at.isoformat() if u.created_at else None} for u in users], "total": int(total), "page": page, "page_size": page_size}


def _sync_admin_assignment(session: Session, user_id: int, is_admin: bool) -> None:
    """Keep ``platform.admin`` in sync with the global ``admin`` role.

    The platform role is ``user/admin``; course and platform enforcement read
    ``PlatformPermissionAssignment`` (see ``require_platform_permission``), so
    promoting/demoting must add/revoke the explicit grant instead of only
    touching ``users.role``.
    """
    assignment = session.exec(
        select(PlatformPermissionAssignment).where(
            PlatformPermissionAssignment.user_id == user_id,
            PlatformPermissionAssignment.permission == PlatformPermission.ADMIN,
        )
    ).first()
    if is_admin:
        if assignment is None:
            session.add(PlatformPermissionAssignment(
                user_id=user_id,
                permission=PlatformPermission.ADMIN,
                granted_by_user_id=user_id,
            ))
        elif assignment.revoked_at is not None:
            assignment.revoked_at = None
            assignment.granted_by_user_id = user_id
            session.add(assignment)
    elif assignment is not None and assignment.revoked_at is None:
        assignment.revoked_at = utcnow_aware()
        session.add(assignment)


def update_user(session: Session, actor_id: int, target_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    user = session.get(User, target_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target_id == actor_id and (payload.get("is_active") is False or payload.get("role") not in (None, "admin")):
        raise HTTPException(status_code=403, detail="不能停用或降级当前管理员账号")
    if "username" in payload:
        try:
            username = normalize_username(payload["username"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        existing = session.exec(
            select(User.id).where(User.username == username, User.id != target_id)
        ).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail="用户名已存在")
        user.username = username
    if "is_active" in payload:
        user.is_active = bool(payload["is_active"])
    if payload.get("role") is not None:
        is_admin = payload["role"] == "admin"
        user.role = UserRole.ADMIN if is_admin else UserRole.USER
        _sync_admin_assignment(session, target_id, is_admin)
    user.updated_at = utcnow_aware()
    session.add(user)
    audit(session, actor_id, "user.update", "user", str(target_id), {"fields": sorted(payload.keys())})
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在") from exc
    session.refresh(user)
    return {"id": user.id, "username": user.username, "role": "admin" if getattr(user.role, "value", user.role) == "admin" else "user", "is_active": user.is_active}


def reset_password(session: Session, actor_id: int, target_id: int, password: str) -> None:
    user = session.get(User, target_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="密码至少 8 位")
    user.hashed_password = get_password_hash(password)
    user.auth_version += 1
    user.updated_at = utcnow_aware()
    session.add(user); audit(session, actor_id, "user.reset_password", "user", str(target_id)); session.commit()


def _capability_dict(capability: CourseCapability | None) -> dict[str, bool]:
    if capability is None:
        return {name: False for name in CAPABILITY_NAMES}
    return {name: bool(getattr(capability, name)) for name in CAPABILITY_NAMES}


def list_course_capabilities(session: Session) -> list[dict[str, Any]]:
    """Return every course paired with its capability switches for admin oversight.

    Platform admins need a cross-course view to unlock demo capabilities without
    navigating into each course's owner-only settings.  A missing
    ``CourseCapability`` row (e.g. legacy courses predating the baseline) is
    reported as all-False so the operator can see exactly what is locked.
    """
    rows = session.exec(
        select(Course, CourseCapability)
        .outerjoin(CourseCapability, CourseCapability.course_id == Course.id)
        .order_by(Course.id)
    ).all()
    return [
        {
            "course_id": course.id,
            "title": course.title,
            "status": course.status.value if course.status else None,
            "teacher_id": course.teacher_id,
            "capabilities": _capability_dict(capability),
        }
        for course, capability in rows
    ]


def update_course_capabilities(
    session: Session,
    course_id: int,
    values: dict[str, bool],
    actor_id: int,
) -> dict[str, Any]:
    """Create or overwrite a course's capability switches with admin authority.

    Unlike the course-scoped ``PUT /course-access/.../capabilities`` endpoint
    (which requires ``permission.manage`` and therefore course ownership), this
    path is authorized by the platform admin permission and can repair legacy
    courses whose capabilities were never initialised.
    """
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    cleaned = {name: bool(values.get(name, False)) for name in CAPABILITY_NAMES}
    # Preserve the invariant shared with the teacher-facing endpoint: the only
    # current experiment runtime is the code sandbox, so experiment cannot stay
    # on when coding_sandbox is off.
    if not cleaned["coding_sandbox"]:
        cleaned["experiment"] = False
    if capability is None:
        capability = CourseCapability(course_id=course_id, **cleaned)
    else:
        for name, value in cleaned.items():
            setattr(capability, name, value)
        capability.updated_at = utcnow_aware()
    session.add(capability)
    audit(session, actor_id, "course.capability.update", "course", str(course_id), {"capabilities": cleaned})
    session.commit()
    session.refresh(capability)
    return {"course_id": course_id, "capabilities": _capability_dict(capability)}
