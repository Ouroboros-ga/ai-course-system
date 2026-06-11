"""
课程 CRUD API
课程列表、详情、创建/更新、发布/取消发布、删除
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query, Body
from sqlmodel import Session, select, text, func

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user, teacher_only, _get_user_id
from app.models.database import get_session
from app.models.course_model import (
    Course, CourseScript, ScriptNode, StudentEnrollment,
    CourseStatus, ParseStatus, ScriptNodeType,
)
from .document_utils import verify_course_owner, document_cache

router = APIRouter(prefix="/document", tags=["课程管理"])


@router.get("/courses")
async def get_courses_list(
    status: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取课程列表"""
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")

        statement = select(Course)
        if user_role == "student":
            statement = statement.where(Course.status == CourseStatus.PUBLISHED)
        else:
            from sqlmodel import or_
            statement = statement.where(
                or_(Course.teacher_id == user_id, Course.status == CourseStatus.PUBLISHED)
            )
        if status:
            try:
                statement = statement.where(Course.status == CourseStatus(status))
            except ValueError:
                pass
        statement = statement.order_by(Course.created_at.desc())
        courses = session.exec(statement).all()

        courses_data = []
        for course in courses:
            teacher_name = "未知教师"
            tr = session.execute(text("SELECT username FROM users WHERE id = :uid"), {"uid": course.teacher_id}).fetchone()
            if tr: teacher_name = tr[0]
            student_count = session.exec(
                select(func.count()).select_from(StudentEnrollment).where(
                    StudentEnrollment.course_id == course.id, StudentEnrollment.is_active == True
                )
            ).one()
            courses_data.append({
                "id": course.id, "title": course.title, "description": course.description,
                "status": course.status.value, "teacher_id": course.teacher_id,
                "teacher_name": teacher_name, "total_nodes": course.total_nodes,
                "total_duration": course.total_duration, "source_file_name": course.source_file_name,
                "is_ai_generated": course.is_ai_generated, "student_count": student_count,
                "created_at": course.created_at.isoformat() if course.created_at else None,
            })
        return unified_response(code=200, message="获取课程列表成功", data={"courses": courses_data, "total": len(courses_data)})
    except Exception as e:
        return unified_response(code=500, message=f"获取课程列表失败: {str(e)}", data=None)


# 以下端点从 document.py 原位迁移，保持原有逻辑不变：
# - GET /{document_id}          (line ~556)
# - POST /course/{course_id}/save   (line ~611)
# - GET /course/{course_id}     (line ~673)  [教师视角]
# - GET /courses               (line ~751)  [教师视角]
# - POST /course/{course_id}/save   (line ~836) [学生视角]
# - POST /course/{course_id}/publish  (line ~1311)
# - POST /course/{course_id}/unpublish (line ~1353)
# - DELETE /course/{course_id}  (line ~1393)

# 迁移说明：将上述 endpoint 的函数体从 document.py 移至此文件，
# 将 @router 替换为上方定义的 router 实例即可。
