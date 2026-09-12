"""OJ Activity 管理 API（PR-08）：教师对活动 / 题目 / 可见范围的管理端点。

**为什么独立成文件而不加进 `experiments.py`**：那已是 1200+ 行的兼容接口大文件；
Activity 是新 bounded context，路由也按 context 分文件（与 PR-03/04 的服务拆分
同构）。**前缀不变**（ADR ⑥ 决定 6）：本 router 同样挂在 `/api/v1/experiments` 下，
不引入 `/oj`。

权限：全部走 `experiment.configure`（教师侧管理语义）。学生侧可见性接口属 PR-12
学生 Activity 页，本文件不提供 —— 别在这里提前开学生口子。

A DR ⑪：router 只做「鉴权 + 参数形状 + 透传 + 序列化」，业务规则全在
`ExperimentActivityService` / `domain/oj/activity/`。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentRun,
)

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.experiment_activity_model import ExperimentActivityProblem
from app.services.course_access_service import require_course_permission
from app.services.experiment_activity_service import ExperimentActivityService
from app.services.experiment_analytics_service import ExperimentAnalyticsService
from app.services.experiment_scoreboard_service import ExperimentScoreboardService

activity_router = APIRouter()

activity_service = ExperimentActivityService()
scoreboard_service = ExperimentScoreboardService()
analytics_service = ExperimentAnalyticsService()


# ---------------------------------------------------------------------------
# 请求 schema（只做形状约束；取值合法性在 service → 域层）
# ---------------------------------------------------------------------------


class ActivityCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: Optional[str] = Field(default=None, max_length=32)
    description_md: str = Field(default="", max_length=20_000)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    allow_late_submit: bool = False
    max_submissions: int = Field(default=0, ge=0)
    scoring_mode: Optional[str] = Field(default=None, max_length=32)
    ranking_mode: Optional[str] = Field(default=None, max_length=32)


class ActivityUpdateRequest(BaseModel):
    """PATCH 语义：`None` = 不动；`clear_window=True` = 清空时间窗（不限时）。"""

    title: Optional[str] = Field(default=None, max_length=200)
    description_md: Optional[str] = Field(default=None, max_length=20_000)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    allow_late_submit: Optional[bool] = None
    max_submissions: Optional[int] = Field(default=None, ge=0)
    clear_window: bool = False


class ActivityProblemAddRequest(BaseModel):
    problem_definition_id: str = Field(min_length=1, max_length=64)
    ordinal: Optional[int] = Field(default=None, ge=1)
    label: str = Field(default="", max_length=32)
    max_score: float = Field(default=1.0, ge=0.0)


class ActivityScopeSetRequest(BaseModel):
    scopes: list[dict] = Field(default_factory=list, max_length=100)


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def _serialize_activity(a) -> dict[str, Any]:
    return {
        "activity_id": a.activity_id,
        "type": a.type,
        "title": a.title,
        "description_md": a.description_md,
        "course_id": a.course_id,
        "owner_id": a.owner_id,
        "status": a.status,
        "start_at": a.start_at.isoformat() if a.start_at else None,
        "end_at": a.end_at.isoformat() if a.end_at else None,
        "allow_late_submit": a.allow_late_submit,
        "freeze_at": a.freeze_at.isoformat() if a.freeze_at else None,
        "scoring_mode": a.scoring_mode,
        "ranking_mode": a.ranking_mode,
        "max_submissions": a.max_submissions,
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _serialize_problem(p: ExperimentActivityProblem) -> dict[str, Any]:
    return {
        "ordinal": p.ordinal,
        "problem_definition_id": p.problem_definition_id,
        "problem_version_id": p.problem_version_id,
        "label": p.label,
        "max_score": p.max_score,
    }


# ---------------------------------------------------------------------------
# 端点（鉴权 + 形状 + 透传；规则在 service/域层）
# ---------------------------------------------------------------------------


@activity_router.post("/course/{course_id}/activities")
async def create_activity(
    course_id: int,
    payload: ActivityCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师创建活动（draft 态）。contest/exam 等未实现类型在 service 显式拒绝。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    activity = activity_service.create_activity(
        session,
        course_id=course_id,
        owner_id=int(current_user["user_id"]),
        title=payload.title,
        type=payload.type,
        description_md=payload.description_md,
        start_at=payload.start_at,
        end_at=payload.end_at,
        allow_late_submit=payload.allow_late_submit,
        max_submissions=payload.max_submissions,
        scoring_mode=payload.scoring_mode,
        ranking_mode=payload.ranking_mode,
    )
    session.commit()
    session.refresh(activity)
    return unified_response(
        code=201, message="活动已创建", data=_serialize_activity(activity)
    )


@activity_router.get("/course/{course_id}/activities")
async def list_activities(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师列出本课程全部活动（管理视图：含 draft / archived）。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    activities = activity_service.list_activities(session, course_id=course_id)
    return unified_response(
        code=200,
        message="获取活动列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_activity(a) for a in activities],
            "total": len(activities),
        },
    )


@activity_router.get("/course/{course_id}/activities/{activity_id}")
async def get_activity(
    course_id: int,
    activity_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """活动详情（含题目与可见范围）。跨课程访问由 service 统一 404。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    activity = activity_service.get_activity(
        session, course_id=course_id, activity_id=activity_id
    )
    return unified_response(
        code=200,
        message="获取活动详情成功",
        data={
            **_serialize_activity(activity),
            "problems": [
                _serialize_problem(p)
                for p in activity_service.list_problems(
                    session, activity_id=activity.activity_id
                )
            ],
            "scopes": [
                {"scope_type": s.scope_type, "scope_id": s.scope_id}
                for s in activity_service.list_scopes(
                    session, activity_id=activity.activity_id
                )
            ],
        },
    )


@activity_router.put("/course/{course_id}/activities/{activity_id}")
async def update_activity(
    course_id: int,
    activity_id: str,
    payload: ActivityUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """PATCH 更新。时间窗收紧 / 放宽 / 清空均可（教师刚需），题目集合不可在此动。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    activity = activity_service.update_activity(
        session,
        course_id=course_id,
        activity_id=activity_id,
        title=payload.title,
        description_md=payload.description_md,
        start_at=payload.start_at,
        end_at=payload.end_at,
        allow_late_submit=payload.allow_late_submit,
        max_submissions=payload.max_submissions,
        clear_window=payload.clear_window,
    )
    session.commit()
    session.refresh(activity)
    return unified_response(
        code=200, message="活动已更新", data=_serialize_activity(activity)
    )


@activity_router.post("/course/{course_id}/activities/{activity_id}/publish")
async def publish_activity(
    course_id: int,
    activity_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """发布：至少一题 + 版本固化 + 版本真实存在，全部在 service 强制。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    activity = activity_service.publish_activity(
        session, course_id=course_id, activity_id=activity_id
    )
    session.commit()
    session.refresh(activity)
    return unified_response(
        code=200, message="活动已发布", data=_serialize_activity(activity)
    )


@activity_router.post("/course/{course_id}/activities/{activity_id}/archive")
async def archive_activity(
    course_id: int,
    activity_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "experiment.configure")
    activity = activity_service.archive_activity(
        session, course_id=course_id, activity_id=activity_id
    )
    session.commit()
    session.refresh(activity)
    return unified_response(
        code=200, message="活动已归档", data=_serialize_activity(activity)
    )


@activity_router.post("/course/{course_id}/activities/{activity_id}/problems")
async def add_activity_problem(
    course_id: int,
    activity_id: str,
    payload: ActivityProblemAddRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """挂题。版本在写入时逐题固化；发布后不可变更。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    problem = activity_service.add_problem(
        session,
        course_id=course_id,
        activity_id=activity_id,
        problem_definition_id=payload.problem_definition_id,
        ordinal=payload.ordinal,
        label=payload.label,
        max_score=payload.max_score,
    )
    session.commit()
    session.refresh(problem)
    return unified_response(
        code=201, message="题目已挂入活动", data=_serialize_problem(problem)
    )


@activity_router.delete("/course/{course_id}/activities/{activity_id}/problems/{ordinal}")
async def remove_activity_problem(
    course_id: int,
    activity_id: str,
    ordinal: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "experiment.configure")
    activity_service.remove_problem(
        session, course_id=course_id, activity_id=activity_id, ordinal=ordinal
    )
    session.commit()
    return unified_response(code=200, message="题目已移出活动", data={"ordinal": ordinal})


@activity_router.put("/course/{course_id}/activities/{activity_id}/scopes")
async def set_activity_scopes(
    course_id: int,
    activity_id: str,
    payload: ActivityScopeSetRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """整体替换可见范围。class / user 可写入但解析行为未实现（PR-12 前不影响学生端）。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    activity_service.get_activity(session, course_id=course_id, activity_id=activity_id)
    scopes = activity_service.set_scopes(session, activity_id=activity_id, scopes=payload.scopes)
    session.commit()
    return unified_response(
        code=200,
        message="可见范围已更新",
        data={"items": [{"scope_type": s.scope_type, "scope_id": s.scope_id} for s in scopes]},
    )


@activity_router.get("/course/{course_id}/activities/{activity_id}/scoreboard")
async def get_activity_scoreboard(
    course_id: int,
    activity_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """作业榜（教师侧）。口径 = finalized attempts；与单生算分同源可重算。

    学生侧看榜属 PR-12/PR-15 的教学策略口径，本端点不开放。
    """
    require_course_permission(session, current_user, course_id, "experiment.configure")
    board = scoreboard_service.get_homework_board(
        session, course_id=course_id, activity_id=activity_id
    )
    return unified_response(code=200, message="获取作业榜成功", data=board)


@activity_router.get("/course/{course_id}/analytics/oj")
async def get_oj_analytics(
    course_id: int,
    trend_days: int = 30,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """OJ 数据看板聚合（教师侧，PR-14 缩范围版）。

    只含现有数据源可确定计算的指标；雷达/质量反馈等无数据源的
    **明确不提供**，前端不得伪造。
    """
    require_course_permission(session, current_user, course_id, "experiment.configure")
    summary = analytics_service.get_course_summary(
        session, course_id=course_id, trend_days=max(7, min(trend_days, 90))
    )
    activity_ids = [
        a.activity_id
        for a in activity_service.list_activities(session, course_id=course_id)
    ]
    summary["activity_problem_counts"] = analytics_service.get_activity_problem_counts(
        session, activity_ids=activity_ids
    )
    return unified_response(code=200, message="获取 OJ 学情聚合成功", data=summary)


@activity_router.get("/course/{course_id}/teacher/submissions")
async def list_course_submissions(
    course_id: int,
    experiment_id: Optional[str] = Query(default=None, max_length=64),
    outcome: Optional[str] = Query(default=None, max_length=32),
    student_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师评测记录：课程内全部提交流水（含学生归属）。

    与学生 façade 的 /submissions 分端点：教师视图带学生身份，
    且走 experiment.configure（全班评测明细是教师资产）。
    total 是全部命中数（分页前），items 是本页切片。
    """
    require_course_permission(session, current_user, course_id, "experiment.configure")
    from app.models.user_model import User

    stmt = select(ExperimentRun).where(ExperimentRun.course_id == course_id)
    if student_id is not None:
        stmt = stmt.where(ExperimentRun.student_id == student_id)
    if experiment_id is not None:
        # run 不直接挂 experiment —— 经 attempt 关联解析
        stmt = stmt.join(  # type: ignore[arg-type]
            ExperimentAttempt,
            ExperimentAttempt.attempt_id == ExperimentRun.attempt_id,
        ).where(ExperimentAttempt.experiment_id == experiment_id)
    rows = list(session.exec(stmt.order_by(  # type: ignore[arg-type]
        ExperimentRun.submitted_at.desc()  # type: ignore[attr-defined]
    )).all())

    wanted = outcome.strip().lower() if outcome else None
    user_ids = {r.student_id for r in rows}
    usernames: dict[int, str] = {}
    if user_ids:
        for u in session.exec(
            select(User).where(User.id.in_(user_ids))  # type: ignore[attr-defined]
        ).all():
            usernames[u.id] = u.username or f"user-{u.id}"
    attempt_ids = {r.attempt_id for r in rows}
    exp_by_attempt: dict[str, str] = {}
    if attempt_ids:
        for a in session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.attempt_id.in_(attempt_ids)  # type: ignore[attr-defined]
            )
        ).all():
            exp_by_attempt[a.attempt_id] = a.experiment_id

    items = []
    for r in rows:
        outcome_value = str(getattr(r.outcome, "value", r.outcome) or "").lower()
        if wanted and outcome_value != wanted:
            continue
        items.append({
            "run_id": r.run_id,
            "student_id": r.student_id,
            "username": usernames.get(r.student_id, "—"),
            "experiment_id": exp_by_attempt.get(r.attempt_id),
            "activity_id": r.activity_id,
            "language": r.language,
            "outcome": outcome_value,
            "run_state": r.run_state,
            "score": r.score,
            "passed_count": r.passed_count,
            "total_count": r.total_count,
            "cpu_time_ms": r.cpu_time_ms,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        })
    total = len(items)
    start = max(0, offset)
    return unified_response(
        code=200, message="获取评测记录成功",
        data={"items": items[start:start + limit], "total": total},
    )
