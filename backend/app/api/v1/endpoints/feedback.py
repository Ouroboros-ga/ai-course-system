"""
学生向教师反馈通道API接口
提供反馈的创建、查询、详情、状态更新功能
"""

from typing import Optional
from app.core.time_utils import utcnow_aware

from fastapi import APIRouter, Depends, Query, Body
from sqlmodel import Session, select

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.feedback_model import Feedback, FeedbackType, FeedbackStatus
from app.models.course_model import Course, StudentEnrollment, ScriptNode, CourseScript
from app.models.user_model import User
from app.models.access_control_model import CourseMembership, CourseRole, MembershipStatus
from app.services.course_access_service import require_course_permission

router = APIRouter(tags=["学生反馈通道"])


# ==================== 反馈管理接口 ====================

@router.post("", response_model=UnifiedResponse)
async def create_feedback(
    course_id: int = Body(..., description="课程ID"),
    node_id: Optional[int] = Body(None, description="节点ID(可选)"),
    feedback_type: FeedbackType = Body(FeedbackType.OTHER, description="反馈类型"),
    content: str = Body(..., description="反馈内容"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    学生创建反馈

    自动设置 from_user_id 为当前登录用户,
    自动查询课程 teacher_id 设置 to_user_id
    """
    try:
        user_id = int(current_user["user_id"])

        if not content or not content.strip():
            return unified_response(
                code=400,
                message="反馈内容不能为空",
                data=None
            )

        course = session.get(Course, course_id)
        if not course:
            return unified_response(
                code=404,
                message="课程不存在",
                data=None
            )

        require_course_permission(session, current_user, course_id, "course.feedback.create")

        # 校验 node_id 属于该课程
        if node_id is not None:
            node = session.get(ScriptNode, node_id)
            if not node:
                return unified_response(
                    code=400,
                    message="指定的节点不存在",
                    data=None
                )
            script = session.exec(
                select(CourseScript).where(
                    CourseScript.id == node.script_id,
                    CourseScript.course_id == course_id,
                )
            ).first()
            if not script:
                return unified_response(
                    code=400,
                    message="指定的节点不属于该课程",
                    data=None
                )

        owner = session.exec(
            select(CourseMembership).where(
                CourseMembership.course_id == course_id,
                CourseMembership.role == CourseRole.OWNER,
                CourseMembership.status == MembershipStatus.ACTIVE,
            )
        ).first()
        if owner is None:
            return unified_response(code=409, message="Course owner membership is not available", data=None)

        feedback = Feedback(
            from_user_id=user_id,
            to_user_id=owner.user_id,
            course_id=course_id,
            node_id=node_id,
            feedback_type=feedback_type,
            content=content,
            status=FeedbackStatus.OPEN,
        )
        session.add(feedback)
        session.commit()
        session.refresh(feedback)

        return unified_response(
            code=200,
            message="反馈创建成功",
            data={
                "id": feedback.id,
                "from_user_id": feedback.from_user_id,
                "to_user_id": feedback.to_user_id,
                "course_id": feedback.course_id,
                "node_id": feedback.node_id,
                "feedback_type": feedback.feedback_type.value,
                "content": feedback.content,
                "status": feedback.status.value,
                "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"创建反馈失败: {str(e)}",
            data=None
        )


@router.get("", response_model=UnifiedResponse)
async def list_feedbacks(
    course_id: int = Query(..., description="课程ID"),
    status: Optional[FeedbackStatus] = Query(None, description="反馈状态过滤"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    教师查看课程反馈列表

    按 course_id 筛选, 可选 status 过滤,
    返回反馈列表并包含 from_user 的 username
    """
    try:
        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, message="课程不存在", data=None)
        require_course_permission(session, current_user, course_id, "course.feedback.manage")

        stmt = select(Feedback).where(Feedback.course_id == course_id)
        if status is not None:
            stmt = stmt.where(Feedback.status == status)
        stmt = stmt.order_by(Feedback.created_at.desc())
        feedbacks = session.exec(stmt).all()

        # 批量查询反馈发起人的用户名, 避免 N+1 查询
        from_user_ids = {fb.from_user_id for fb in feedbacks if fb.from_user_id is not None}
        username_map = {}
        if from_user_ids:
            users = session.exec(
                select(User).where(User.id.in_(from_user_ids))
            ).all()
            username_map = {u.id: u.username for u in users}

        result = []
        for fb in feedbacks:
            result.append({
                "id": fb.id,
                "from_user_id": fb.from_user_id,
                "from_username": username_map.get(fb.from_user_id, ""),
                "to_user_id": fb.to_user_id,
                "course_id": fb.course_id,
                "node_id": fb.node_id,
                "feedback_type": fb.feedback_type.value if fb.feedback_type else None,
                "content": fb.content,
                "status": fb.status.value if fb.status else None,
                "teacher_reply": fb.teacher_reply,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
                "updated_at": fb.updated_at.isoformat() if fb.updated_at else None,
            })

        return unified_response(
            code=200,
            message="获取成功",
            data={
                "list": result,
                "total": len(result),
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取反馈列表失败: {str(e)}",
            data=None
        )


@router.get("/{feedback_id}", response_model=UnifiedResponse)
async def get_feedback(
    feedback_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    反馈详情

    仅允许反馈创建者或课程教师查看
    """
    try:
        user_id = int(current_user["user_id"])

        feedback = session.get(Feedback, feedback_id)
        if not feedback:
            return unified_response(
                code=404,
                message="反馈不存在",
                data=None
            )

        context = require_course_permission(session, current_user, feedback.course_id, "course.feedback.create")
        is_creator = feedback.from_user_id == user_id
        if not is_creator and not context.allows("course.feedback.manage"):
            return unified_response(code=403, message="无权查看该反馈", data=None)

        # 查发起人用户名
        from_username = ""
        if feedback.from_user_id is not None:
            user = session.get(User, feedback.from_user_id)
            if user:
                from_username = user.username

        return unified_response(
            code=200,
            message="获取成功",
            data={
                "id": feedback.id,
                "from_user_id": feedback.from_user_id,
                "from_username": from_username,
                "to_user_id": feedback.to_user_id,
                "course_id": feedback.course_id,
                "node_id": feedback.node_id,
                "feedback_type": feedback.feedback_type.value if feedback.feedback_type else None,
                "content": feedback.content,
                "status": feedback.status.value if feedback.status else None,
                "teacher_reply": feedback.teacher_reply,
                "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
                "updated_at": feedback.updated_at.isoformat() if feedback.updated_at else None,
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取反馈详情失败: {str(e)}",
            data=None
        )


@router.put("/{feedback_id}/status", response_model=UnifiedResponse)
async def update_feedback_status(
    feedback_id: int,
    status: FeedbackStatus = Body(..., description="反馈状态: addressed/closed"),
    teacher_reply: Optional[str] = Body(None, description="教师回复(可选)"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    教师更新反馈状态/回复

    参数:
    - status: 反馈状态 (addressed/closed)
    - teacher_reply: 教师回复内容(可选)
    """
    try:
        feedback = session.get(Feedback, feedback_id)
        if not feedback:
            return unified_response(
                code=404,
                message="反馈不存在",
                data=None
            )

        course = session.get(Course, feedback.course_id)
        if not course:
            return unified_response(code=404, message="课程不存在", data=None)
        require_course_permission(session, current_user, feedback.course_id, "course.feedback.manage")

        # 仅允许更新为 addressed 或 closed
        if status not in (FeedbackStatus.ADDRESSED, FeedbackStatus.CLOSED):
            return unified_response(
                code=400,
                message="状态仅支持 addressed 或 closed",
                data=None
            )

        feedback.status = status
        if teacher_reply is not None:
            feedback.teacher_reply = teacher_reply
        feedback.updated_at = utcnow_aware()

        session.add(feedback)
        session.commit()
        session.refresh(feedback)

        return unified_response(
            code=200,
            message="更新成功",
            data={
                "id": feedback.id,
                "status": feedback.status.value,
                "teacher_reply": feedback.teacher_reply,
                "updated_at": feedback.updated_at.isoformat() if feedback.updated_at else None,
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"更新反馈状态失败: {str(e)}",
            data=None
        )
