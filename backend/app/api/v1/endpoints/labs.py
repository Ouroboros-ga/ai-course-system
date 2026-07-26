"""阶段7 平台实验室目录 API 路由

契约来源：PageDesign前端API契约规划.md §3.7

路由前缀：/api/v1/lab

提供四个列表页与教师/学生操作：
- GET    /lab/catalog                  平台实验室大厅（按 visibility 过滤）
- GET    /lab/course-tasks             课程任务页（课程实验+学生参与情况）
- GET    /lab/my-experiments           我的实验页（学生参与的所有平台/课程实验室）
- GET    /lab/records                  实验记录页（学生最终记录汇总）
- POST   /lab                          教师创建实验室条目
- GET    /lab/{lab_id}                 实验室详情
- POST   /lab/{lab_id}/publish         教师发布实验室
- POST   /lab/{lab_id}/enroll          学生加入实验室
- POST   /lab/{lab_id}/records         记录学生尝试结果（由实验 finalize 写入）

权限模型：
- 平台实验与课程实验共享沙箱能力，但课程实验可回写课程证据和 return anchor
- 按 visibility 控制发现范围：public | course_only | private
- 学生只能看自己参与情况；教师只能管理所属课程实验室
- 跨用户/课程严格隔离
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.resource_model import LabCatalogVisibility
from app.services.course_access_service import require_course_permission
from app.services.resource_service import lab_catalog_service


lab_router = APIRouter()


# ---------------------------------------------------------------------------
# 请求 schema
# ---------------------------------------------------------------------------


class LabCreateRequest(BaseModel):
    """教师创建实验室条目"""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    course_id: Optional[int] = Field(
        default=None, description="课程级实验室；为空表示平台级"
    )
    experiment_id: Optional[str] = Field(
        default=None, description="关联课程实验（课程级）"
    )
    language_whitelist: list[str] = Field(default_factory=list)
    visibility: LabCatalogVisibility = LabCatalogVisibility.COURSE_ONLY
    cpu_time_limit: int = Field(default=5, ge=1, le=30)
    memory_limit: int = Field(default=128_000, ge=16_000, le=512_000)
    wall_time_limit: int = Field(default=10, ge=1, le=60)
    knowledge_node_ids: list[int] = Field(default_factory=list)
    statement_object_key: str = Field(default="", max_length=500)


class LabRecordCreateRequest(BaseModel):
    """记录学生在实验室的最终尝试结果

    由实验 finalize 流程或教师批量导入时调用，不应被学生直接调用。
    """

    attempt_id: str = Field(min_length=1, max_length=64)
    final_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    passed: Optional[bool] = None
    evidence_id: Optional[str] = None
    return_anchor: dict = Field(default_factory=dict)
    student_id: Optional[int] = Field(
        default=None,
        description="若调用方为教师/系统，需指定 student_id；学生调用则使用自身",
    )


# ---------------------------------------------------------------------------
# 序列化（与 service 内 _serialize_lab 保持一致；这里复用 service 的序列化）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@lab_router.get("/catalog")
async def list_catalog(
    course_id: Optional[int] = Query(default=None),
    visibility: Optional[LabCatalogVisibility] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """平台实验室大厅：catalog 列表。

    - 学生视角：仅看 public 或自己课程（course_id）的实验室
    - 教师视角：可按 visibility 过滤；course_id 指定时返回该课程实验室
    """
    user_id = int(current_user["user_id"])
    result = lab_catalog_service.list_catalog(
        session,
        student_id=user_id,
        course_id=course_id,
        visibility=visibility,
        published_only=True,
        cursor=cursor,
        page_size=page_size,
    )
    return unified_response(
        code=200,
        message="获取实验室目录成功",
        data=result,
    )


@lab_router.get("/course-tasks")
async def list_course_tasks(
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课程任务页：列出课程实验与学生的参与情况。

    需 experiment.view 权限；学生只能看自己的参与情况。
    """
    context = require_course_permission(session, current_user, course_id, "experiment.view")
    user_id = int(current_user["user_id"])
    # 学生视角使用自身 student_id；教师视角传 0 表示不返回个人参与情况
    student_id_for_query = user_id if (context.role is None or context.role.value == "student") else 0
    items = lab_catalog_service.list_course_tasks(
        session, course_id=course_id, student_id=student_id_for_query,
    )
    return unified_response(
        code=200,
        message="获取课程任务成功",
        data={
            "course_id": course_id,
            "items": items,
            "total": len(items),
        },
    )


@lab_router.get("/my-experiments")
async def list_my_experiments(
    active_only: bool = Query(default=True),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """我的实验页：列出当前学生参与的所有平台/课程实验室。"""
    user_id = int(current_user["user_id"])
    items = lab_catalog_service.list_my_experiments(
        session, student_id=user_id, active_only=active_only,
    )
    return unified_response(
        code=200,
        message="获取我的实验成功",
        data={
            "items": items,
            "total": len(items),
        },
    )


@lab_router.get("/records")
async def list_records(
    course_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """实验记录页：汇总学生在平台/课程实验室的最终记录。

    学生只能看自己的记录；course_id 指定时按课程过滤。
    """
    user_id = int(current_user["user_id"])
    records = lab_catalog_service.list_records(
        session, student_id=user_id, course_id=course_id,
    )
    return unified_response(
        code=200,
        message="获取实验记录成功",
        data={
            "items": records,
            "total": len(records),
        },
    )


@lab_router.post("")
async def create_lab(
    payload: LabCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师创建实验室条目。

    课程级实验室需 experiment.configure 权限；平台级实验室仅需登录教师。
    """
    user_id = int(current_user["user_id"])
    if payload.course_id is not None:
        require_course_permission(
            session, current_user, payload.course_id, "experiment.configure",
        )
    lab = lab_catalog_service.create_lab(
        session,
        owner_user_id=user_id,
        title=payload.title,
        description=payload.description,
        course_id=payload.course_id,
        experiment_id=payload.experiment_id,
        language_whitelist=payload.language_whitelist,
        visibility=payload.visibility,
        cpu_time_limit=payload.cpu_time_limit,
        memory_limit=payload.memory_limit,
        wall_time_limit=payload.wall_time_limit,
        knowledge_node_ids=payload.knowledge_node_ids,
        statement_object_key=payload.statement_object_key,
        created_by=user_id,
    )
    session.commit()
    session.refresh(lab)
    return unified_response(
        code=201,
        message="实验室已创建",
        data=lab_catalog_service._serialize_lab(lab),
    )


@lab_router.get("/{lab_id}")
async def get_lab(
    lab_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取实验室详情。"""
    lab = lab_catalog_service.get_lab(session, lab_id=lab_id)
    # 课程级实验室需课程权限校验
    if lab.course_id is not None:
        require_course_permission(
            session, current_user, lab.course_id, "experiment.view",
        )
    return unified_response(
        code=200,
        message="获取实验室详情成功",
        data=lab_catalog_service._serialize_lab(lab),
    )


@lab_router.post("/{lab_id}/publish")
async def publish_lab(
    lab_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师发布实验室。课程级实验室需 experiment.configure 权限。"""
    lab = lab_catalog_service.get_lab(session, lab_id=lab_id)
    if lab.course_id is not None:
        require_course_permission(
            session, current_user, lab.course_id, "experiment.configure",
        )
    else:
        # 平台级实验室仅 owner 可发布
        user_id = int(current_user["user_id"])
        if lab.owner_user_id != user_id:
            from app.core.exceptions import reject_course_access_denied
            reject_course_access_denied("无权发布该实验室")
    lab = lab_catalog_service.publish_lab(session, lab_id=lab_id)
    session.commit()
    session.refresh(lab)
    return unified_response(
        code=200,
        message="实验室已发布",
        data=lab_catalog_service._serialize_lab(lab),
    )


@lab_router.post("/{lab_id}/enroll")
async def enroll_lab(
    lab_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生加入实验室。"""
    user_id = int(current_user["user_id"])
    lab = lab_catalog_service.get_lab(session, lab_id=lab_id)
    # 课程级实验室需课程权限校验
    if lab.course_id is not None:
        require_course_permission(
            session, current_user, lab.course_id, "experiment.view",
        )
    enrollment = lab_catalog_service.enroll_student(
        session, lab_id=lab_id, student_id=user_id,
    )
    session.commit()
    session.refresh(enrollment)
    return unified_response(
        code=201,
        message="已加入实验室",
        data={
            "lab_id": enrollment.lab_id,
            "student_id": enrollment.student_id,
            "course_id": enrollment.course_id,
            "enrolled_at": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else None,
            "is_active": enrollment.is_active,
            "last_attempt_id": enrollment.last_attempt_id,
        },
    )


@lab_router.post("/{lab_id}/records")
async def record_lab_result(
    lab_id: str,
    payload: LabRecordCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """记录学生在实验室的最终尝试结果。

    - 学生调用：student_id 默认为自身
    - 教师/系统调用：需指定 student_id 且具备 experiment.configure 权限
    """
    user_id = int(current_user["user_id"])
    lab = lab_catalog_service.get_lab(session, lab_id=lab_id)
    target_student_id = payload.student_id or user_id

    # 若指定的 student_id 不是自身，需教师权限
    if target_student_id != user_id:
        if lab.course_id is not None:
            require_course_permission(
                session, current_user, lab.course_id, "experiment.configure",
            )
        else:
            from app.core.exceptions import reject_course_access_denied
            if lab.owner_user_id != user_id:
                reject_course_access_denied("无权为其他学生记录结果")
    else:
        # 学生自身调用：课程级实验室需 view 权限
        if lab.course_id is not None:
            require_course_permission(
                session, current_user, lab.course_id, "experiment.run",
            )

    record = lab_catalog_service.record_attempt_result(
        session,
        lab_id=lab_id,
        student_id=target_student_id,
        attempt_id=payload.attempt_id,
        final_score=payload.final_score,
        passed=payload.passed,
        evidence_id=payload.evidence_id,
        return_anchor=payload.return_anchor,
    )
    session.commit()
    session.refresh(record)
    return unified_response(
        code=201,
        message="实验记录已写入",
        data={
            "record_id": record.record_id,
            "lab_id": record.lab_id,
            "student_id": record.student_id,
            "course_id": record.course_id,
            "attempt_id": record.attempt_id,
            "final_score": record.final_score,
            "passed": record.passed,
            "evidence_id": record.evidence_id,
            "return_anchor": record.return_anchor,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        },
    )
