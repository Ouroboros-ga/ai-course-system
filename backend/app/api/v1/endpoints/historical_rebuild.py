"""阶段10 历史课程补建清单编排 API 路由。

.. deprecated:: 2026-07-27 (统一课程建设九步实施计划 Step 0)
   旧课程自动迁移/自动补建已**关闭**。本模块端点保留为**只读遗留参考**，
   仅展示历史补建清单与状态，不再触发任何自动迁移动作。旧课程保持只读；
   想使用新解析链与新建设功能，请通过 ``POST /document/course-imports``
   重新上传创建新草稿课程。见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md。

路由前缀：
- /api/v1/historical-rebuild/checklist              全局补建清单（按阶段聚合，只读）
- /api/v1/historical-rebuild/summary                全局进度汇总（只读）
- /api/v1/historical-rebuild/course/{course_id}     课程级补建状态详情（只读）

权限模型：
- platform.course.audit：平台审计员可查看全部课程
- course.edit：课程教师可查看本课程补建状态
- 跨课程严格隔离：所有查询按 course_id 过滤
- 编排端点不直接修改业务数据：触发动作调用对应服务的现有 API
- 失败保留原始 error_code，禁止伪装成功
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.access_control_model import PlatformPermission
from app.models.database import get_session
from app.models.course_model import CourseStatus
from app.services.course_access_service import (
    require_course_permission,
    require_platform_permission,
)
from app.services.historical_rebuild_service import (
    REBUILD_STAGES,
    STAGE_DISPLAY_NAMES,
    historical_rebuild_service,
)


historical_rebuild_router = APIRouter()


# ---------------------------------------------------------------------------
# 全局清单
# ---------------------------------------------------------------------------


@historical_rebuild_router.get("/checklist")
async def list_global_checklist(
    status: Optional[CourseStatus] = Query(default=None, description="按课程状态过滤"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """平台审计员查看全局补建清单；按阶段聚合每个课程最前的待办阶段。

    返回 [{course_id, course_title, stage, pending_count, last_activity_at}]。
    """
    require_platform_permission(session, current_user, PlatformPermission.COURSE_AUDIT)
    items = historical_rebuild_service.list_global_checklist(
        session, status_filter=status,
    )
    return unified_response(
        200,
        "获取补建清单成功",
        {
            "items": items,
            "total": len(items),
            "stages": [{"name": s, "display": STAGE_DISPLAY_NAMES[s]} for s in REBUILD_STAGES],
        },
    )


@historical_rebuild_router.get("/summary")
async def get_global_summary(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """平台审计员查看全局补建进度汇总。"""
    require_platform_permission(session, current_user, PlatformPermission.COURSE_AUDIT)
    summary = historical_rebuild_service.get_global_summary(session)
    return unified_response(200, "获取补建汇总成功", summary)


# ---------------------------------------------------------------------------
# 课程级详情
# ---------------------------------------------------------------------------


@historical_rebuild_router.get("/course/{course_id}")
async def get_course_detail(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """查看课程级补建状态详情：列出全部 6 阶段计数。

    - 课程教师（course.edit）或平台审计员可访问
    - 跨课程严格隔离
    """
    # 优先按 course.edit 校验；教师无权时回退到 platform permission
    try:
        require_course_permission(session, current_user, course_id, "course.edit")
    except Exception:
        require_platform_permission(session, current_user, PlatformPermission.COURSE_AUDIT)
    detail = historical_rebuild_service.list_course_detail(session, course_id=course_id)
    return unified_response(200, "获取课程补建详情成功", detail)
