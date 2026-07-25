"""G6 课程安全围栏与沙箱治理 API

教师可配置安全策略和沙箱权限，平台硬边界不可关闭。
所有策略修改、命中、放行、阻断和教师确认均可审计。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.safety_policy_model import (
    CourseSafetyPolicy,
    CourseSandboxPolicy,
    SafetyAuditLog,
    CourseType,
    SandboxPreset,
    NetworkMode,
    FileAccessMode,
    SafetyPolicyStatus,
    AuditEventType,
    PLATFORM_HARD_LIMITS,
    KEYWORD_ASSIST_LIST,
)
from app.services.course_access_service import require_course_permission
from app.services.safety_guard_service import (
    evaluate_content_safety,
    get_or_create_safety_policy,
    get_or_create_sandbox_policy,
)

router = APIRouter(tags=["G6 安全围栏与沙箱治理"])


# ==================== 请求模型 ====================

class SafetyPolicyUpdate(BaseModel):
    course_type: Optional[CourseType] = None
    forbidden_topics: Optional[list[str]] = Field(None, max_length=100)
    required_citation_topics: Optional[list[str]] = Field(None, max_length=100)
    course_whitelist: Optional[list[str]] = Field(None, max_length=100)
    high_risk_confirmation_required: Optional[bool] = None
    keyword_assist_enabled: Optional[bool] = None
    status: Optional[SafetyPolicyStatus] = None


class SandboxPolicyUpdate(BaseModel):
    sandbox_preset: Optional[SandboxPreset] = None
    allowed_languages: Optional[list[str]] = Field(None, max_length=20)
    allowed_packages: Optional[list[str]] = Field(None, max_length=100)
    network_mode: Optional[NetworkMode] = None
    network_whitelist: Optional[list[str]] = Field(None, max_length=100)
    file_access_mode: Optional[FileAccessMode] = None
    cpu_limit: Optional[int] = Field(None, ge=1)
    memory_limit: Optional[int] = Field(None, ge=16384)
    wall_time_limit: Optional[int] = Field(None, ge=1)
    environment_destroy_on_exit: Optional[bool] = None
    log_retention_days: Optional[int] = Field(None, ge=1, le=365)


class EvaluateRequest(BaseModel):
    content: str
    tool_target: Optional[str] = None


# ==================== 安全策略接口 ====================

@router.get("/course/{course_id}/safety-policy")
async def get_safety_policy(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取课程安全围栏配置"""
    require_course_permission(session, current_user, course_id, "course.view")
    policy = get_or_create_safety_policy(session, course_id)
    return unified_response(code=200, message="获取安全策略成功", data=_serialize_safety_policy(policy))


@router.put("/course/{course_id}/safety-policy")
async def update_safety_policy(
    course_id: int,
    payload: SafetyPolicyUpdate,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新课程安全围栏配置

    需要 agent.policy.configure 权限。
    平台硬边界不可关闭。
    """
    context = require_course_permission(session, current_user, course_id, "agent.policy.configure")
    user_id = int(current_user["user_id"])
    policy = get_or_create_safety_policy(session, course_id)

    old_values = {}
    if payload.course_type is not None:
        old_values["course_type"] = policy.course_type.value
        policy.course_type = payload.course_type
    if payload.forbidden_topics is not None:
        old_values["forbidden_topics"] = policy.forbidden_topics
        policy.forbidden_topics = payload.forbidden_topics
    if payload.required_citation_topics is not None:
        old_values["required_citation_topics"] = policy.required_citation_topics
        policy.required_citation_topics = payload.required_citation_topics
    if payload.course_whitelist is not None:
        old_values["course_whitelist"] = policy.course_whitelist
        policy.course_whitelist = payload.course_whitelist
    if payload.high_risk_confirmation_required is not None:
        old_values["high_risk_confirmation_required"] = policy.high_risk_confirmation_required
        policy.high_risk_confirmation_required = payload.high_risk_confirmation_required
    if payload.keyword_assist_enabled is not None:
        old_values["keyword_assist_enabled"] = policy.keyword_assist_enabled
        policy.keyword_assist_enabled = payload.keyword_assist_enabled
    if payload.status is not None:
        old_values["status"] = policy.status.value
        policy.status = payload.status

    policy.updated_at = datetime.utcnow()
    session.add(policy)

    # 审计日志
    log = SafetyAuditLog(
        course_id=course_id, user_id=user_id,
        event_type=AuditEventType.POLICY_CHANGE,
        action="更新安全策略",
        reason=f"修改字段: {list(old_values.keys())}",
        details={"old_values": old_values},
        course_type=policy.course_type.value,
    )
    session.add(log)
    session.commit()
    session.refresh(policy)

    return unified_response(code=200, message="安全策略已更新", data=_serialize_safety_policy(policy))


# ==================== 沙箱策略接口 ====================

@router.get("/course/{course_id}/sandbox-policy")
async def get_sandbox_policy(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取课程沙箱权限配置"""
    require_course_permission(session, current_user, course_id, "course.view")
    policy = get_or_create_sandbox_policy(session, course_id)
    return unified_response(code=200, message="获取沙箱策略成功", data=_serialize_sandbox_policy(policy))


@router.put("/course/{course_id}/sandbox-policy")
async def update_sandbox_policy(
    course_id: int,
    payload: SandboxPolicyUpdate,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新课程沙箱权限配置

    需要 sandbox.policy.configure 权限。
    教师不能关闭平台级隔离、审计、资源上限和高风险系统调用限制。
    """
    context = require_course_permission(session, current_user, course_id, "sandbox.policy.configure")
    user_id = int(current_user["user_id"])
    policy = get_or_create_sandbox_policy(session, course_id)

    if payload.environment_destroy_on_exit is False:
        raise HTTPException(
            status_code=422,
            detail="平台硬边界要求每次执行后销毁沙箱环境",
        )

    old_values = {}
    if payload.sandbox_preset is not None:
        old_values["sandbox_preset"] = policy.sandbox_preset.value
        policy.sandbox_preset = payload.sandbox_preset
    if payload.allowed_languages is not None:
        old_values["allowed_languages"] = policy.allowed_languages
        policy.allowed_languages = payload.allowed_languages
    if payload.allowed_packages is not None:
        old_values["allowed_packages"] = policy.allowed_packages
        policy.allowed_packages = payload.allowed_packages
    if payload.network_mode is not None:
        safety_policy = get_or_create_safety_policy(session, course_id)
        if (
            safety_policy.course_type in (CourseType.BASIC, CourseType.PROFESSIONAL)
            and payload.network_mode != NetworkMode.DISABLED
        ):
            raise HTTPException(
                status_code=422,
                detail="基础或专业课程的沙箱网络必须保持关闭",
            )
        old_values["network_mode"] = policy.network_mode.value
        policy.network_mode = payload.network_mode
    if payload.network_whitelist is not None:
        old_values["network_whitelist"] = policy.network_whitelist
        policy.network_whitelist = payload.network_whitelist
    if payload.file_access_mode is not None:
        old_values["file_access_mode"] = policy.file_access_mode.value
        policy.file_access_mode = payload.file_access_mode
    if payload.cpu_limit is not None:
        old_values["cpu_limit"] = policy.cpu_limit
        policy.cpu_limit = min(payload.cpu_limit, 15)  # 平台上限
    if payload.memory_limit is not None:
        old_values["memory_limit"] = policy.memory_limit
        policy.memory_limit = min(payload.memory_limit, 512000)  # 平台上限
    if payload.wall_time_limit is not None:
        old_values["wall_time_limit"] = policy.wall_time_limit
        policy.wall_time_limit = min(payload.wall_time_limit, 30)  # 平台上限
    if payload.environment_destroy_on_exit is not None:
        old_values["environment_destroy_on_exit"] = policy.environment_destroy_on_exit
        policy.environment_destroy_on_exit = True
    if payload.log_retention_days is not None:
        old_values["log_retention_days"] = policy.log_retention_days
        policy.log_retention_days = payload.log_retention_days

    policy.updated_at = datetime.utcnow()
    session.add(policy)

    log = SafetyAuditLog(
        course_id=course_id, user_id=user_id,
        event_type=AuditEventType.POLICY_CHANGE,
        action="更新沙箱策略",
        reason=f"修改字段: {list(old_values.keys())}",
        details={"old_values": old_values},
        sandbox_preset=policy.sandbox_preset.value,
    )
    session.add(log)
    session.commit()
    session.refresh(policy)

    return unified_response(code=200, message="沙箱策略已更新", data=_serialize_sandbox_policy(policy))


# ==================== 安全评估接口 ====================

@router.post("/course/{course_id}/evaluate")
async def evaluate_content(
    course_id: int,
    payload: EvaluateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """评估内容安全性（内部接口，供问答路径调用）

    关键词不能作为唯一允许或阻断依据。
    """
    require_course_permission(session, current_user, course_id, "course.question.ask")
    user_id = int(current_user["user_id"])

    decision = evaluate_content_safety(
        session, course_id, payload.content,
        user_id=user_id, tool_target=payload.tool_target,
    )

    return unified_response(
        code=200,
        message="安全评估完成",
        data={
            "allowed": decision.allowed,
            "action": decision.action.value if hasattr(decision, 'action') else ("allow" if decision.allowed else "reject"),
            "requires_confirmation": decision.requires_confirmation,
            "reason": decision.reason,
            "decision_factors": decision.decision_factors,
            "keyword_matched": decision.keyword_matched,
            "policy_version": decision.policy_version,
        },
    )


class EvaluateToolRequest(BaseModel):
    """工具调用评估请求"""
    tool_name: str
    tool_target: Optional[str] = None
    tool_params: Optional[dict] = None


class EvaluateAIContentRequest(BaseModel):
    """AI产出安全门控请求"""
    content: str
    source_materials: Optional[list[str]] = None


@router.post("/course/{course_id}/evaluate-tool")
async def evaluate_tool(
    course_id: int,
    payload: EvaluateToolRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """工具权限校验链

    Agent请求工具 -> 校验课程权限 -> 校验安全策略 -> 校验目标白名单 -> 校验沙箱能力 -> 执行/确认/拒绝
    安全不依赖模型"自觉"，而依赖执行层真正卡住危险动作。
    """
    from app.services.safety_guard_service import evaluate_tool_call

    require_course_permission(session, current_user, course_id, "course.question.ask")
    user_id = int(current_user["user_id"])

    decision = evaluate_tool_call(
        session, course_id,
        tool_name=payload.tool_name,
        tool_target=payload.tool_target,
        tool_params=payload.tool_params,
        user_id=user_id,
    )

    return unified_response(
        code=200,
        message="工具安全校验完成",
        data={
            "allowed": decision.allowed,
            "action": decision.action.value if hasattr(decision, 'action') else ("allow" if decision.allowed else "reject"),
            "requires_confirmation": decision.requires_confirmation,
            "reason": decision.reason,
            "decision_factors": decision.decision_factors,
            "policy_version": decision.policy_version,
        },
    )


@router.post("/course/{course_id}/evaluate-ai-content")
async def evaluate_ai(
    course_id: int,
    payload: EvaluateAIContentRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """AI产出安全门控

    AI生成 -> 安全策略检查 -> 原文与课程范围检查 -> 教师确认 -> 正式发布
    AI产出先作为候选，不直接进入正式课程。
    """
    from app.services.safety_guard_service import evaluate_ai_content

    require_course_permission(session, current_user, course_id, "course.question.ask")
    user_id = int(current_user["user_id"])

    decision = evaluate_ai_content(
        session, course_id, payload.content,
        source_materials=payload.source_materials,
        user_id=user_id,
    )

    return unified_response(
        code=200,
        message="AI产出安全门控完成",
        data={
            "allowed": decision.allowed,
            "action": decision.action.value if hasattr(decision, 'action') else ("allow" if decision.allowed else "reject"),
            "requires_confirmation": decision.requires_confirmation,
            "reason": decision.reason,
            "decision_factors": decision.decision_factors,
            "policy_version": decision.policy_version,
        },
    )


# ==================== 审计日志接口 ====================

@router.get("/course/{course_id}/audit")
async def list_audit_logs(
    course_id: int,
    event_type: Optional[str] = Query(None, description="按事件类型筛选"),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取安全审计日志

    所有策略修改、命中、放行、阻断和教师确认均可审计。
    """
    require_course_permission(session, current_user, course_id, "agent.policy.view")

    stmt = select(SafetyAuditLog).where(SafetyAuditLog.course_id == course_id)
    if event_type:
        stmt = stmt.where(SafetyAuditLog.event_type == AuditEventType(event_type))

    stmt = stmt.order_by(SafetyAuditLog.created_at.desc()).limit(limit)
    logs = session.exec(stmt).all()

    return unified_response(
        code=200,
        message="获取审计日志成功",
        data={
            "items": [_serialize_audit(log) for log in logs],
            "total": len(logs),
        },
    )


# ==================== 辅助函数 ====================

def _serialize_safety_policy(policy: CourseSafetyPolicy) -> dict[str, Any]:
    return {
        "course_id": policy.course_id,
        "course_type": policy.course_type.value,
        "forbidden_topics": policy.forbidden_topics,
        "required_citation_topics": policy.required_citation_topics,
        "course_whitelist": policy.course_whitelist,
        "high_risk_confirmation_required": policy.high_risk_confirmation_required,
        "keyword_assist_enabled": policy.keyword_assist_enabled,
        "keyword_assist_list": KEYWORD_ASSIST_LIST,
        "status": policy.status.value,
        "platform_hard_limits": policy.platform_hard_limits,
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }


def _serialize_sandbox_policy(policy: CourseSandboxPolicy) -> dict[str, Any]:
    return {
        "course_id": policy.course_id,
        "sandbox_preset": policy.sandbox_preset.value,
        "allowed_languages": policy.allowed_languages,
        "allowed_packages": policy.allowed_packages,
        "network_mode": policy.network_mode.value,
        "network_whitelist": policy.network_whitelist,
        "file_access_mode": policy.file_access_mode.value,
        "cpu_limit": policy.cpu_limit,
        "memory_limit": policy.memory_limit,
        "wall_time_limit": policy.wall_time_limit,
        "environment_destroy_on_exit": policy.environment_destroy_on_exit,
        "log_retention_days": policy.log_retention_days,
        "platform_hard_limits": {
            "no_host_path": policy.platform_no_host_path,
            "no_privileged_container": policy.platform_no_privileged,
            "no_public_internet": policy.platform_no_public_internet,
        },
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }


def _serialize_audit(log: SafetyAuditLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "course_id": log.course_id,
        "user_id": log.user_id,
        "event_type": log.event_type.value,
        "action": log.action,
        "reason": log.reason,
        "details": log.details,
        "course_type": log.course_type,
        "sandbox_preset": log.sandbox_preset,
        "keyword_matched": log.keyword_matched,
        "decision_factors": log.decision_factors,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
