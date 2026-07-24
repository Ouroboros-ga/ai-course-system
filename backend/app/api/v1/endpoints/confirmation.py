"""
教师确认管理API
提供课程结构、映射、引用等关键环节的教师确认与状态追踪
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import teacher_only
from app.models.database import get_session
from app.models.confirmation_model import (
    CourseConfirmation,
    ConfirmationType,
    ConfirmationStatus,
)
from app.models.course_model import Course
from app.models.user_model import User

router = APIRouter(tags=["教师确认"])


# ---------- 请求模型 ----------

class ConfirmationCreate(BaseModel):
    """创建确认记录请求"""
    course_id: int
    confirmation_type: str = "mapping"
    target_id: Optional[int] = None
    notes: str = ""


class ConfirmationUpdate(BaseModel):
    """更新确认状态请求"""
    status: str
    notes: str = ""


# ---------- API接口 ----------

@router.get("")
async def list_confirmations(
    course_id: Optional[int] = Query(None, description="按课程筛选"),
    type: Optional[str] = Query(None, description="按确认类型筛选(structure/mapping/citation)"),
    status: Optional[str] = Query(None, description="按状态筛选(pending/confirmed/rejected/deferred)"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    列出确认记录，支持按课程、类型、状态筛选
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "teacher")

        # 如果指定了 course_id，校验课程归属（管理员跳过）
        if course_id is not None:
            course = session.get(Course, course_id)
            if not course:
                return unified_response(code=404, message="课程不存在", data=None)
            if user_role != "admin" and str(course.teacher_id) != str(user_id):
                return unified_response(code=403, message="无权查看此课程确认记录", data=None)

        # 查询范围：管理员查全部，教师限定自己的课程
        if user_role == "admin":
            statement = select(CourseConfirmation)
        else:
            owned_courses = session.exec(
                select(Course.id).where(Course.teacher_id == user_id)
            ).all()
            owned_course_ids = list(owned_courses)
            statement = select(CourseConfirmation).where(
                CourseConfirmation.course_id.in_(owned_course_ids)
            )

        if course_id is not None:
            statement = statement.where(CourseConfirmation.course_id == course_id)
        if type is not None:
            statement = statement.where(CourseConfirmation.confirmation_type == type)
        if status is not None:
            statement = statement.where(CourseConfirmation.status == status)
        statement = statement.order_by(CourseConfirmation.id.desc())

        confirmations = session.exec(statement).all()
        data = [
            {
                "id": c.id,
                "course_id": c.course_id,
                "confirmation_type": c.confirmation_type.value if isinstance(c.confirmation_type, ConfirmationType) else c.confirmation_type,
                "target_id": c.target_id,
                "status": c.status.value if isinstance(c.status, ConfirmationStatus) else c.status,
                "confirmed_by": c.confirmed_by,
                "confirmed_at": c.confirmed_at.isoformat() if c.confirmed_at else None,
                "notes": c.notes,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in confirmations
        ]
        return unified_response(code=200, message="获取确认列表成功", data=data)
    except Exception as e:
        return unified_response(code=500, message=f"获取确认列表失败: {str(e)}", data=None)


@router.post("")
async def create_confirmation(
    body: ConfirmationCreate,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    创建确认记录
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "teacher")

        # 校验课程归属（管理员跳过）
        course = session.get(Course, body.course_id)
        if not course:
            return unified_response(code=404, message="课程不存在", data=None)
        if user_role != "admin" and str(course.teacher_id) != str(user_id):
            return unified_response(code=403, message="无权操作此课程", data=None)

        try:
            conf_type = ConfirmationType(body.confirmation_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的确认类型: {body.confirmation_type}")

        confirmation = CourseConfirmation(
            course_id=body.course_id,
            confirmation_type=conf_type,
            target_id=body.target_id,
            status=ConfirmationStatus.PENDING,
            notes=body.notes,
        )
        session.add(confirmation)
        session.commit()
        session.refresh(confirmation)

        return unified_response(
            code=200,
            message="创建确认记录成功",
            data={
                "id": confirmation.id,
                "course_id": confirmation.course_id,
                "confirmation_type": confirmation.confirmation_type.value,
                "target_id": confirmation.target_id,
                "status": confirmation.status.value,
                "notes": confirmation.notes,
                "created_at": confirmation.created_at.isoformat() if confirmation.created_at else None,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        return unified_response(code=500, message=f"创建确认记录失败: {str(e)}", data=None)


@router.put("/{confirmation_id}")
async def update_confirmation(
    confirmation_id: int,
    body: ConfirmationUpdate,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    更新确认状态
    自动记录确认人与确认时间
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "teacher")

        confirmation = session.get(CourseConfirmation, confirmation_id)
        if not confirmation:
            raise HTTPException(status_code=404, detail="确认记录不存在")

        # 校验课程归属（管理员跳过）
        course = session.get(Course, confirmation.course_id)
        if not course:
            raise HTTPException(status_code=404, detail="课程不存在")
        if user_role != "admin" and str(course.teacher_id) != str(user_id):
            raise HTTPException(status_code=403, detail="无权操作此课程的确认记录")

        try:
            new_status = ConfirmationStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的确认状态: {body.status}")

        confirmation.status = new_status
        confirmation.confirmed_by = int(current_user["user_id"])
        confirmation.confirmed_at = datetime.utcnow()
        confirmation.notes = body.notes
        confirmation.updated_at = datetime.utcnow()
        session.add(confirmation)
        session.commit()
        session.refresh(confirmation)

        return unified_response(
            code=200,
            message="更新确认状态成功",
            data={
                "id": confirmation.id,
                "course_id": confirmation.course_id,
                "confirmation_type": confirmation.confirmation_type.value,
                "target_id": confirmation.target_id,
                "status": confirmation.status.value,
                "confirmed_by": confirmation.confirmed_by,
                "confirmed_at": confirmation.confirmed_at.isoformat() if confirmation.confirmed_at else None,
                "notes": confirmation.notes,
                "updated_at": confirmation.updated_at.isoformat() if confirmation.updated_at else None,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        return unified_response(code=500, message=f"更新确认状态失败: {str(e)}", data=None)


@router.get("/course/{course_id}/status")
async def get_course_confirmation_status(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    获取课程全部确认状态汇总
    返回各确认类型(structure/mapping/citation)的最新状态
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "teacher")

        # 校验课程归属（管理员跳过）
        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, message="课程不存在", data=None)
        if user_role != "admin" and str(course.teacher_id) != str(user_id):
            return unified_response(code=403, message="无权查看此课程确认状态", data=None)

        statement = (
            select(CourseConfirmation)
            .where(CourseConfirmation.course_id == course_id)
            .order_by(CourseConfirmation.id.desc())
        )
        confirmations = session.exec(statement).all()

        # 初始化各类型为 pending
        summary = {
            ConfirmationType.STRUCTURE.value: {"status": ConfirmationStatus.PENDING.value},
            ConfirmationType.MAPPING.value: {"status": ConfirmationStatus.PENDING.value},
            ConfirmationType.CITATION.value: {"status": ConfirmationStatus.PENDING.value},
        }

        # 收集需要查询的用户ID，用于显示确认人名称
        user_ids = {
            c.confirmed_by for c in confirmations if c.confirmed_by is not None
        }
        user_map = {}
        if user_ids:
            users = session.exec(select(User).where(User.id.in_(list(user_ids)))).all()
            user_map = {u.id: u.real_name or u.username for u in users}

        # 每种类型取最新一条（按id降序，首次出现即最新）
        seen = set()
        for c in confirmations:
            type_key = (
                c.confirmation_type.value
                if isinstance(c.confirmation_type, ConfirmationType)
                else c.confirmation_type
            )
            if type_key in summary and type_key not in seen:
                seen.add(type_key)
                status_value = (
                    c.status.value
                    if isinstance(c.status, ConfirmationStatus)
                    else c.status
                )
                entry = {"status": status_value}
                if c.confirmed_by is not None:
                    entry["confirmed_by"] = user_map.get(c.confirmed_by, str(c.confirmed_by))
                if c.confirmed_at is not None:
                    entry["confirmed_at"] = c.confirmed_at.isoformat()
                summary[type_key] = entry

        return unified_response(code=200, message="获取课程确认状态汇总成功", data=summary)
    except Exception as e:
        return unified_response(code=500, message=f"获取确认状态汇总失败: {str(e)}", data=None)
