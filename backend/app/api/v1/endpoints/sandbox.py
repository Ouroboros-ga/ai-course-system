"""G3 代码沙箱 API

使用统一权限解析器进行课程级权限校验。
- 执行代码: experiment.run (学生) / experiment.configure (教师)
- 查看沙箱状态: course.view

不允许前端直接调用 Judge0。
不允许题目携带任意 shell、Docker、网络权限。
后端停用沙箱时，学习主流程可正常降级。
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from sqlmodel import select
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.core.config import settings
from app.models.database import get_session
from app.services.course_access_service import require_course_permission
from app.services.experiment_service import FreeSandboxQuotaService
from app.models.safety_policy_model import (
    CourseSandboxPolicy,
    SafetyAuditLog,
    AuditEventType,
)
from app.services.safety_guard_service import check_forbidden_operations
from app.services.sandbox_client import (
    sandbox_client,
    SandboxClient,
    SandboxResourceLimits,
    SandboxResult,
    SubmissionStatus,
    ALLOWED_LANGUAGES,
)

router = APIRouter(tags=["G3 代码沙箱"])


class CodeExecutionRequest(BaseModel):
    """代码执行请求"""
    source_code: str = Field(min_length=1, max_length=100_000)
    language: str  # 必须在 ALLOWED_LANGUAGES 中
    stdin: str = Field(default="", max_length=100_000)


@router.get("/health")
async def sandbox_health(
    current_user: dict = Depends(get_current_user),
):
    """检查沙箱是否可用"""
    available = await run_in_threadpool(sandbox_client.health_check)
    return unified_response(
        code=200,
        message="沙箱可用" if available else "沙箱不可用",
        data={
            "enabled": sandbox_client.enabled,
            "available": available,
            "allowed_languages": list(ALLOWED_LANGUAGES.keys()),
        },
    )


@router.post("/course/{course_id}/execute")
async def execute_code(
    course_id: int,
    payload: CodeExecutionRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """在沙箱中执行学生代码

    需要 experiment.run 权限。
    不在主应用进程执行学生代码。
    默认关闭网络，禁止在线安装依赖。
    """
    context = require_course_permission(
        session, current_user, course_id, "experiment.run"
    )
    if not context.capabilities.get("coding_sandbox", False):
        raise HTTPException(status_code=403, detail="课程代码沙箱能力未启用")
    if payload.language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail="不支持的编程语言")

    course_policy = session.exec(
        select(CourseSandboxPolicy).where(
            CourseSandboxPolicy.course_id == course_id
        )
    ).first()
    if course_policy and payload.language not in (course_policy.allowed_languages or []):
        raise HTTPException(status_code=400, detail="课程未允许该编程语言")

    # 2026-08-17：平台硬边界命令黑名单接入真实执行路径（此前仅 Agent 工具层生效）。
    # 对源代码与标准输入同时扫描，命中禁止操作直接拒绝并写审计。
    scanned = f"{payload.source_code}\n{payload.stdin}"
    forbidden_operation = check_forbidden_operations(scanned)
    if forbidden_operation is not None:
        session.add(SafetyAuditLog(
            course_id=course_id,
            user_id=int(current_user["user_id"]),
            event_type=AuditEventType.SANDBOX_BLOCK,
            action=f"沙箱执行含平台禁止操作 '{forbidden_operation}'",
            reason="platform_hard_limit_violation",
            details={"language": payload.language, "forbidden_operation": forbidden_operation},
        ))
        session.commit()
        raise HTTPException(
            status_code=400,
            detail=f"代码包含平台禁止操作 '{forbidden_operation}'，无法执行",
        )

    retry_after = FreeSandboxQuotaService().consume(
        session,
        student_id=int(current_user["user_id"]),
        course_id=course_id,
    )
    if retry_after:
        session.rollback()
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "FREE_SANDBOX_QUOTA_EXCEEDED",
                "message": "自由运行次数已达上限，请稍后再试",
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    session.commit()

    cpu_limit = min(
        settings.JUDGE0_DEFAULT_CPU_TIME_LIMIT,
        course_policy.cpu_limit if course_policy else settings.JUDGE0_DEFAULT_CPU_TIME_LIMIT,
        settings.JUDGE0_DEFAULT_CPU_TIME_LIMIT,
    )
    memory_limit = min(
        settings.JUDGE0_DEFAULT_MEMORY_LIMIT,
        course_policy.memory_limit if course_policy else settings.JUDGE0_DEFAULT_MEMORY_LIMIT,
        settings.JUDGE0_DEFAULT_MEMORY_LIMIT,
    )
    wall_limit = min(
        settings.JUDGE0_DEFAULT_WALL_TIME_LIMIT,
        course_policy.wall_time_limit if course_policy else settings.JUDGE0_DEFAULT_WALL_TIME_LIMIT,
        settings.JUDGE0_DEFAULT_WALL_TIME_LIMIT,
    )

    # 构建资源限制
    limits = SandboxResourceLimits(
        cpu_time_limit=cpu_limit,
        memory_limit=memory_limit,
        wall_time_limit=wall_limit,
        max_processes=min(
            settings.JUDGE0_DEFAULT_MAX_PROCESSES,
            settings.JUDGE0_DEFAULT_MAX_PROCESSES,
        ),
        max_file_size=min(
            settings.JUDGE0_DEFAULT_MAX_FILE_SIZE,
            settings.JUDGE0_DEFAULT_MAX_FILE_SIZE,
        ),
    )

    result = await run_in_threadpool(
        sandbox_client.submit_code,
        source_code=payload.source_code,
        language=payload.language,
        stdin=payload.stdin,
        expected_output="",
        limits=limits,
    )

    return unified_response(
        code=200,
        message="代码执行完成" if result.is_accepted else "代码执行结果",
        data=result.to_dict(),
    )


@router.get("/languages")
async def list_allowed_languages(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出允许的编程语言"""
    return unified_response(
        code=200,
        message="获取允许语言列表成功",
        data={"languages": list(ALLOWED_LANGUAGES.keys())},
    )
