"""OJ 学生 façade 路由（PR-10 后端半部）：题库 / 题目详情 / 我的提交。

挂既有前缀 `/api/v1/experiments`（ADR ⑥ 不引入 /oj）。全部只读，
权限统一 `experiment.view`；"我的"维度一律以 token 里的学生为准。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.services.course_access_service import require_course_permission
from app.services.experiment_student_service import ExperimentStudentService

student_router = APIRouter()

student_service = ExperimentStudentService()


@student_router.get("/course/{course_id}/problems")
async def list_student_problems(
    course_id: int,
    search: Optional[str] = Query(default=None, max_length=100),
    difficulty: Optional[str] = Query(default=None, max_length=16),
    tags: Optional[str] = Query(default=None, max_length=200, description="逗号分隔标签"),
    status: Optional[str] = Query(default=None, max_length=16),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生题库列表：已发布题目 + 全班通过率 + 我的作答状态。"""
    require_course_permission(session, current_user, course_id, "experiment.view")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    data = student_service.list_problem_bank(
        session,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
        search=search,
        difficulty=difficulty,
        tags=tag_list,
        status_filter=status,
        page=page,
        page_size=page_size,
    )
    return unified_response(code=200, message="获取题库成功", data=data)


@student_router.get("/course/{course_id}/problems/{experiment_id}")
async def get_student_problem(
    course_id: int,
    experiment_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生题目详情：公开面 + 限制 + 起始代码 + 我的作答摘要。不含任何 testcase。"""
    require_course_permission(session, current_user, course_id, "experiment.view")
    data = student_service.get_student_problem(
        session,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
        experiment_id=experiment_id,
    )
    return unified_response(code=200, message="获取题目详情成功", data=data)


@student_router.get("/course/{course_id}/submissions")
async def list_my_submissions(
    course_id: int,
    experiment_id: Optional[str] = Query(default=None, max_length=64),
    outcome: Optional[str] = Query(default=None, max_length=32),
    language: Optional[str] = Query(default=None, max_length=50),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """我的提交记录（按 token 学生过滤；筛选：题目 / 结果 / 语言）。"""
    require_course_permission(session, current_user, course_id, "experiment.view")
    items = student_service.list_my_submissions(
        session,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
        experiment_id=experiment_id,
        outcome=outcome,
        language=language,
        limit=limit,
    )
    return unified_response(
        code=200, message="获取提交记录成功",
        data={"items": items, "total": len(items)},
    )


@student_router.get("/course/{course_id}/submissions/{run_id}")
async def get_my_submission(
    course_id: int,
    run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """单条提交详情（只认本人；他人 run 一律 404）。"""
    require_course_permission(session, current_user, course_id, "experiment.view")
    data = student_service.get_my_submission(
        session,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
        run_id=run_id,
    )
    return unified_response(code=200, message="获取提交详情成功", data=data)
