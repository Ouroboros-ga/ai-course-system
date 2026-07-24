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
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.services.course_access_service import require_course_permission
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
    source_code: str
    language: str  # 必须在 ALLOWED_LANGUAGES 中
    stdin: str = ""
    expected_output: str = ""

    # 可选资源限制（不超过系统上限）
    cpu_time_limit: Optional[int] = None
    memory_limit: Optional[int] = None
    wall_time_limit: Optional[int] = None
    max_processes: Optional[int] = None
    max_file_size: Optional[int] = None


@router.get("/health")
async def sandbox_health():
    """检查沙箱是否可用"""
    available = sandbox_client.health_check()
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
    require_course_permission(session, current_user, course_id, "experiment.run")

    # 构建资源限制
    limits = SandboxResourceLimits(
        cpu_time_limit=payload.cpu_time_limit or 5,
        memory_limit=payload.memory_limit or 128000,
        wall_time_limit=payload.wall_time_limit or 10,
        max_processes=payload.max_processes or 30,
        max_file_size=payload.max_file_size or 1024,
    )

    result = sandbox_client.submit_code(
        source_code=payload.source_code,
        language=payload.language,
        stdin=payload.stdin,
        expected_output=payload.expected_output,
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
