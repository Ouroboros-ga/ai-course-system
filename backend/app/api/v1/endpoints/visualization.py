"""G4 算法可视化 API

使用统一权限解析器进行课程级权限校验。
- 创建/验证计划: course.mapping.edit (教师)
- 查看计划: course.content.read (学生+教师)
- 列出算法: course.view

JSAV 只负责动画；Judge0 只负责学生代码执行与判定。
LLM 不能输出任意 JS/HTML，只能输出受限 VisualizationPlan JSON。
"""
from __future__ import annotations

import uuid
from app.core.time_utils import utcnow_aware
from typing import Optional, Any, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.visualization_model import (
    VisualizationPlanRecord,
    VisualizationStatus,
)
from app.services.course_access_service import require_course_permission
from app.services.visualization.algorithm_registry import list_allowed_algorithms
from app.services.visualization.plan_validator import validate_visualization_plan

router = APIRouter(tags=["G4 算法可视化"])


class CreatePlanRequest(BaseModel):
    """创建可视化计划请求"""
    algorithm_id: str
    initial_params: dict
    steps: list[dict] = Field(max_length=200)
    highlights: list[dict] = Field(default_factory=list, max_length=200)
    playback_speed: float = Field(default=1.0, ge=0.1, le=5.0)
    return_anchor: Optional[dict] = None
    # 兼容旧版数值 ScriptNode ID 与新版 release outline_node_id（如 on_xxx）。
    # 数据库列仍为整数：outline ID 无法落库时按空处理，只拒绝真实非法值。
    node_id: Optional[Union[int, str]] = None


def _int_node_id(value) -> Optional[int]:
    """把数值或可解析为整数的 node_id 归一化；outline 字符串等返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    return int(text) if text.isdigit() else None


@router.get("/algorithms")
async def list_algorithms(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出所有允许的算法（白名单）"""
    return unified_response(
        code=200,
        message="获取算法列表成功",
        data={"algorithms": list_allowed_algorithms()},
    )


@router.post("/course/{course_id}/plan")
async def create_plan(
    course_id: int,
    payload: CreatePlanRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建并验证可视化计划

    需要 course.mapping.edit 权限(教师)。
    后端验证课程、知识点、参数范围和算法白名单。
    LLM 不能输出任意 JS/HTML。
    """
    context = require_course_permission(session, current_user, course_id, "course.mapping.edit")
    user_id = int(current_user["user_id"])

    # 构建完整计划
    plan = {
        "algorithm_id": payload.algorithm_id,
        "initial_params": payload.initial_params,
        "steps": payload.steps,
        "highlights": payload.highlights,
        "playback_speed": payload.playback_speed,
    }
    if payload.return_anchor:
        plan["return_anchor"] = payload.return_anchor

    # 验证计划
    result = validate_visualization_plan(plan)
    if not result.valid:
        return unified_response(
            code=400,
            message="可视化计划验证失败",
            data={"errors": result.errors},
        )

    # 持久化
    record = VisualizationPlanRecord(
        plan_id=str(uuid.uuid4()),
        course_id=course_id,
        node_id=_int_node_id(payload.node_id),
        algorithm_id=result.algorithm_spec.algorithm_id,
        algorithm_name=result.algorithm_spec.name,
        plan_data=result.sanitized_plan,
        return_anchor_node_id=(
            _int_node_id(payload.return_anchor.get("node_id"))
            if payload.return_anchor
            else None
        ),
        return_anchor_label=str(payload.return_anchor.get("label", "")) if payload.return_anchor else "",
        status=VisualizationStatus.VALIDATED,
        created_by=user_id,
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    return unified_response(
        code=200,
        message="可视化计划已创建并验证",
        data=_serialize_plan(record),
    )


@router.get("/course/{course_id}/plans")
async def list_plans(
    course_id: int,
    node_id: Optional[Union[int, str]] = Query(None, description="按知识点筛选（兼容 outline_node_id；整数列下 outline ID 不命中任何计划）"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程的可视化计划"""
    require_course_permission(session, current_user, course_id, "course.content.read")

    stmt = select(VisualizationPlanRecord).where(
        VisualizationPlanRecord.course_id == course_id,
    )
    if node_id:
        numeric_node_id = _int_node_id(node_id)
        if numeric_node_id is not None:
            stmt = stmt.where(VisualizationPlanRecord.node_id == numeric_node_id)
    if status:
        stmt = stmt.where(VisualizationPlanRecord.status == VisualizationStatus(status))

    # 学生只能看 published
    context = require_course_permission(session, current_user, course_id, "course.content.read")
    if context.role and context.role.value == "student":
        stmt = stmt.where(VisualizationPlanRecord.status == VisualizationStatus.PUBLISHED)

    records = session.exec(stmt.order_by(VisualizationPlanRecord.created_at.desc())).all()

    return unified_response(
        code=200,
        message="获取可视化计划列表成功",
        data={
            "items": [_serialize_plan(r) for r in records],
            "total": len(records),
        },
    )


@router.get("/{plan_id}")
async def get_plan(
    plan_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取可视化计划详情（用于回放）"""
    record = session.exec(
        select(VisualizationPlanRecord).where(
            VisualizationPlanRecord.plan_id == plan_id,
        )
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="可视化计划不存在")

    # 权限校验
    require_course_permission(session, current_user, record.course_id, "course.content.read")

    # 学生只能看 published
    context = require_course_permission(session, current_user, record.course_id, "course.content.read")
    if context.role and context.role.value == "student" and record.status != VisualizationStatus.PUBLISHED:
        raise HTTPException(status_code=403, detail="计划未发布")

    # 更新回放统计
    record.play_count += 1
    record.last_played_at = utcnow_aware()
    session.add(record)
    session.commit()

    return unified_response(
        code=200,
        message="获取可视化计划成功",
        data=_serialize_plan(record),
    )


@router.post("/course/{course_id}/{plan_id}/publish")
async def publish_plan(
    course_id: int,
    plan_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """发布可视化计划给学生使用"""
    require_course_permission(session, current_user, course_id, "course.mapping.edit")
    user_id = int(current_user["user_id"])

    record = session.exec(
        select(VisualizationPlanRecord).where(
            VisualizationPlanRecord.plan_id == plan_id,
            VisualizationPlanRecord.course_id == course_id,
        )
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="计划不存在")

    record.status = VisualizationStatus.PUBLISHED
    record.published_at = utcnow_aware()
    session.add(record)
    session.commit()

    return unified_response(
        code=200,
        message="可视化计划已发布",
        data={"plan_id": plan_id, "status": "published"},
    )


def _serialize_plan(record: VisualizationPlanRecord) -> dict[str, Any]:
    """序列化可视化计划"""
    return {
        "id": record.id,
        "plan_id": record.plan_id,
        "course_id": record.course_id,
        "node_id": record.node_id,
        "algorithm_id": record.algorithm_id,
        "algorithm_name": record.algorithm_name,
        "plan_data": record.plan_data,
        "plan_version": record.plan_version,
        "return_anchor": {
            "node_id": record.return_anchor_node_id,
            "label": record.return_anchor_label,
        } if record.return_anchor_node_id else None,
        "status": record.status.value,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "published_at": record.published_at.isoformat() if record.published_at else None,
        "play_count": record.play_count,
        "last_played_at": record.last_played_at.isoformat() if record.last_played_at else None,
    }
