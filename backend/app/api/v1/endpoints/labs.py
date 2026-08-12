"""Course-experiment laboratory projection API.

The former independent laboratory lifecycle is deliberately retired.  This
router is read-only: it discovers published course experiments, directs the
student into a course experiment, and shows records materialised exclusively
by the formal execution worker.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.services.course_access_service import (
    require_course_permission as _base_require_course_permission,
    resolve_course_access,
)
from app.services.resource_service import lab_projection_service


lab_router = APIRouter()


def _require_projection_access(session: Session, current_user: dict, course_id: int):
    context = _base_require_course_permission(session, current_user, course_id, "experiment.view")
    if not context.capabilities.get("experiment", False) or not context.capabilities.get("coding_sandbox", False):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail={"error_code": "EXPERIMENT_PLATFORM_DISABLED", "message": "课程实验平台未启用"})
    return context


@lab_router.get("/catalog")
@lab_router.get("/course-tasks")
async def list_course_tasks(
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Read-only list of published experiments projected into the laboratory."""
    _require_projection_access(session, current_user, course_id)
    user_id = int(current_user["user_id"])
    items = lab_projection_service.list_course_tasks(
        session, course_id=course_id, student_id=user_id,
    )
    session.commit()  # persists only missing projection mappings, never grades
    return unified_response(
        code=200,
        message="获取课程实验投影成功",
        data={"course_id": course_id, "items": items, "total": len(items)},
    )


@lab_router.get("/my-experiments")
async def list_my_experiments(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Show teacher-approved recommendations; students still start themselves."""
    items = lab_projection_service.list_my_experiments(
        session, student_id=int(current_user["user_id"]),
    )
    items = [
        item for item in items
        if (access := resolve_course_access(session, current_user, int(item["course_id"]))).capabilities.get("experiment", False)
        and access.capabilities.get("coding_sandbox", False)
    ]
    session.commit()
    return unified_response(
        code=200,
        message="获取我的实验推荐成功",
        data={"items": items, "total": len(items)},
    )


@lab_router.get("/records")
async def list_records(
    course_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Show only records with an experiment-finalisation provenance marker."""
    if course_id is not None:
        _require_projection_access(session, current_user, course_id)
    records = lab_projection_service.list_records(
        session,
        student_id=int(current_user["user_id"]),
        course_id=course_id,
    )
    return unified_response(
        code=200,
        message="获取可信实验记录成功",
        data={"items": records, "total": len(records)},
    )
