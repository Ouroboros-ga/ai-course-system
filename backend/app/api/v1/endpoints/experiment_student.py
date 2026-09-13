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
from app.services.experiment_activity_service import ExperimentActivityService
from app.services.experiment_student_service import ExperimentStudentService

student_router = APIRouter()

student_service = ExperimentStudentService()
activity_service = ExperimentActivityService()


@student_router.get("/course/{course_id}/problems")
async def list_student_problems(
    course_id: int,
    search: Optional[str] = Query(default=None, max_length=100),
    search_in: Optional[str] = Query(
        default=None, max_length=16,
        description="关键词范围：title（默认）/ statement（题面正文）/ both",
    ),
    difficulty: Optional[str] = Query(default=None, max_length=16),
    difficulty_min: Optional[str] = Query(
        default=None, max_length=16, description="难度区间下界（含）",
    ),
    difficulty_max: Optional[str] = Query(
        default=None, max_length=16, description="难度区间上界（含）",
    ),
    tags: Optional[str] = Query(default=None, max_length=200, description="逗号分隔标签"),
    tag_mode: Optional[str] = Query(default=None, max_length=8, description="and（默认）/ or"),
    source: Optional[str] = Query(default=None, max_length=64, description="题目来源，大小写不敏感"),
    year: Optional[int] = Query(default=None, description="题目年份"),
    status: Optional[str] = Query(default=None, max_length=16),
    sort_by: Optional[str] = Query(
        default=None, max_length=16,
        description="default / no / title / difficulty / pass_rate / attempt_total",
    ),
    sort_order: Optional[str] = Query(default=None, max_length=8, description="asc（默认）/ desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生题库列表：已发布题目 + 全班通过率 + 我的作答状态。

    B1（2026-09-13）新增：`search_in` / `difficulty_min|max` / `tag_mode` /
    `source` / `year` / `sort_by|order`。**排序在服务端的全量命中集上做，
    再分页** —— 先分页再排序只能排到当前页，跨页排序会给出错误的第一名。

    取值合法性一律由域层（`domain/oj/problems/catalog.py`）判定并转 422；
    本路由不做重复校验，避免值域在路由与服务层分裂成两份。
    """
    require_course_permission(session, current_user, course_id, "experiment.view")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    data = student_service.list_problem_bank(
        session,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
        search=search,
        search_in=search_in,
        difficulty=difficulty,
        difficulty_min=difficulty_min,
        difficulty_max=difficulty_max,
        tags=tag_list,
        tag_mode=tag_mode,
        source=source,
        year=year,
        status_filter=status,
        sort_by=sort_by,
        sort_order=sort_order,
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
    """学生题目详情：公开面 + 限制 + 起始代码 + 我的作答摘要。不含任何 testcase。

    B2（2026-09-13）新增返回：`problem_no` / `source` / `year` /
    `statement_locales` / `statement_default_locale`，以及 `samples[].sample_id`。
    """
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
    date_from: Optional[str] = Query(default=None, max_length=10),
    date_to: Optional[str] = Query(default=None, max_length=10),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """我的提交记录（按 token 学生过滤；筛选：题目 / 结果 / 语言 / 日期；分页）。"""
    require_course_permission(session, current_user, course_id, "experiment.view")
    total, items = student_service.list_my_submissions(
        session,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
        experiment_id=experiment_id,
        outcome=outcome,
        language=language,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return unified_response(
        code=200, message="获取提交记录成功",
        data={"items": items, "total": total},
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


# ⚠️ 路径必须是 /student/activities：activity_router 的
# GET /activities/{activity_id} 会把 /activities/student 当成
# activity_id="student" 遮蔽掉（先注册者优先）。
@student_router.get("/course/{course_id}/student/activities")
async def list_student_activities(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生侧活动列表（PR-12）：已发布 + 对我可见 + 作答窗口状态 + 题目摘要。

    与教师管理列表（activities，experiment.configure）分端点：学生只看
    published 且 scope 命中的，且窗口状态由服务端算好。
    """
    require_course_permission(session, current_user, course_id, "experiment.view")
    items = activity_service.list_student_activities(
        session,
        course_id=course_id,
        student_id=int(current_user["user_id"]),
    )
    return unified_response(
        code=200, message="获取活动列表成功",
        data={"items": items, "total": len(items)},
    )
