"""
进度续接API接口
提供学习进度管理、理解度分析、节点定位等接口
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.progress_model import LearningProgress, NodeProgress, LearningStatus
from app.models.course_model import Course, ScriptNode
from app.models.user_model import ChatMessage
from app.services.progress_service import progress_service

router = APIRouter(prefix="/progress", tags=["进度续接"])


@router.post("/analyze", response_model=UnifiedResponse)
async def analyze_understanding(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
    courseId: int = Body(..., description="课程ID"),
    nodeId: int = Body(..., description="当前节点ID"),
    question: str = Body(..., description="学生提问内容"),
    chatId: Optional[int] = Body(None, description="会话ID，用于获取历史对话"),
):
    """
    分析学生理解度

    核心功能：
    1. 使用NLP分析学生提问内容
    2. 判断学生对当前知识点的理解程度
    3. 定位相关的学习节点
    4. 提供节奏调整建议

    返回：
    - 理解度等级和分数
    - 掌握/薄弱的关键词
    - 相关节点推荐
    - 节奏调整建议
    """
    try:
        user_id = int(current_user["user_id"])
        username = current_user.get("username", "user")
        print(f"[进度分析] 用户 {username} (ID: {user_id}) 提问分析请求")

        course = session.get(Course, courseId)
        if not course:
            return unified_response(code=404, message="课程不存在", data=None)

        chat_messages = []
        if chatId:
            messages = session.exec(
                select(ChatMessage)
                .where(ChatMessage.chat_id == chatId)
                .order_by(ChatMessage.created_at.asc())
            ).all()
            chat_messages = messages

        result = await progress_service.handle_student_question(
            session=session,
            user_id=user_id,
            course_id=courseId,
            question=question,
            current_node_id=nodeId,
            chat_messages=chat_messages,
        )

        return unified_response(
            code=200, message="理解度分析完成", data=result
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return unified_response(
            code=500, message=f"分析失败: {str(e)}", data={"error": str(e)}
        )


@router.get("/visualization/{course_id}", response_model=UnifiedResponse)
async def get_progress_visualization(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取学习进度可视化数据

    返回：
    - 总体进度（完成率、学习时长、会话次数）
    - 各节点进度（完成状态、理解度、提问次数）
    - 最近的理解度分析记录
    """
    try:
        user_id = int(current_user["user_id"])

        result = await progress_service.get_progress_visualization(
            session=session, user_id=user_id, course_id=course_id
        )

        if "error" in result:
            return unified_response(code=404, message=result["error"], data=None)

        return unified_response(code=200, message="获取进度成功", data=result)

    except Exception as e:
        import traceback

        traceback.print_exc()
        return unified_response(
            code=500, message=f"获取进度失败: {str(e)}", data=None
        )


@router.post("/sync", response_model=UnifiedResponse)
async def sync_learning_progress(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
    courseId: int = Body(..., description="课程ID"),
    nodeId: int = Body(..., description="当前节点ID"),
    timestamp: float = Body(..., description="当前播放时间点(秒)"),
    isCompleted: bool = Body(False, description="当前节点是否已完成"),
    timeSpent: int = Body(0, description="本次学习时长(秒)"),
):
    """
    同步学习进度

    用于前端定期同步播放进度，支持断点续接
    """
    try:
        user_id = int(current_user["user_id"])

        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == courseId,
            )
        ).first()

        if not progress:
            progress = LearningProgress(
                user_id=user_id,
                course_id=courseId,
                status=LearningStatus.IN_PROGRESS,
                started_at=datetime.utcnow(),
            )
            session.add(progress)
            session.commit()
            session.refresh(progress)

        progress.current_node_id = nodeId
        progress.current_timestamp = timestamp
        progress.last_accessed_at = datetime.utcnow()
        progress.total_learning_time += timeSpent

        node_progress = session.exec(
            select(NodeProgress).where(
                NodeProgress.progress_id == progress.id, NodeProgress.node_id == nodeId
            )
        ).first()

        if not node_progress:
            script = session.get(ScriptNode, nodeId)
            node_progress = NodeProgress(
                progress_id=progress.id,
                node_id=nodeId,
                node_index=script.node_index if script else 0,
                first_accessed_at=datetime.utcnow(),
            )
            session.add(node_progress)
            session.commit()
            session.refresh(node_progress)

        node_progress.last_timestamp = timestamp
        node_progress.time_spent += timeSpent
        node_progress.last_accessed_at = datetime.utcnow()

        if isCompleted and not node_progress.is_completed:
            node_progress.is_completed = True
            node_progress.completed_at = datetime.utcnow()
            node_progress.completion_count += 1

            progress.completed_nodes += 1
            if progress.total_nodes > 0:
                progress.completion_rate = progress.completed_nodes / progress.total_nodes

            if progress.completion_rate >= 1.0:
                progress.status = LearningStatus.COMPLETED
                progress.completed_at = datetime.utcnow()

        session.commit()

        return unified_response(
            code=200,
            message="进度同步成功",
            data={
                "progressId": progress.id,
                "completionRate": progress.completion_rate,
                "status": progress.status.value,
                "currentNodeIndex": node_progress.node_index,
                "isCompleted": node_progress.is_completed,
            },
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return unified_response(
            code=500, message=f"同步失败: {str(e)}", data=None
        )


@router.get("/resume/{course_id}", response_model=UnifiedResponse)
async def get_resume_point(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取断点续接信息

    返回上次学习的位置，用于学生重新进入课程时恢复进度
    """
    try:
        user_id = int(current_user["user_id"])

        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        if not progress:
            return unified_response(
                code=200,
                message="无历史学习记录",
                data={"hasProgress": False, "resumeNode": None},
            )

        current_node = None
        if progress.current_node_id:
            current_node = session.get(ScriptNode, progress.current_node_id)

        return unified_response(
            code=200,
            message="获取断点成功",
            data={
                "hasProgress": True,
                "resumeNode": {
                    "nodeId": progress.current_node_id,
                    "nodeIndex": current_node.node_index if current_node else 0,
                    "nodeTitle": current_node.title if current_node else "",
                    "timestamp": progress.current_timestamp,
                    "page": progress.current_page,
                }
                if current_node
                else None,
                "progress": {
                    "completionRate": progress.completion_rate,
                    "status": progress.status.value,
                    "totalLearningTime": progress.total_learning_time,
                    "lastAccessedAt": progress.last_accessed_at.isoformat(),
                },
            },
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return unified_response(
            code=500, message=f"获取断点失败: {str(e)}", data=None
        )


@router.post("/node/complete", response_model=UnifiedResponse)
async def mark_node_completed(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
    courseId: int = Body(..., description="课程ID"),
    nodeId: int = Body(..., description="节点ID"),
):
    """
    标记节点为已完成
    """
    try:
        user_id = int(current_user["user_id"])

        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == courseId,
            )
        ).first()

        if not progress:
            return unified_response(code=404, message="学习进度不存在", data=None)

        node_progress = session.exec(
            select(NodeProgress).where(
                NodeProgress.progress_id == progress.id, NodeProgress.node_id == nodeId
            )
        ).first()

        if not node_progress:
            script = session.get(ScriptNode, nodeId)
            node_progress = NodeProgress(
                progress_id=progress.id,
                node_id=nodeId,
                node_index=script.node_index if script else 0,
                first_accessed_at=datetime.utcnow(),
            )
            session.add(node_progress)
            session.commit()
            session.refresh(node_progress)

        if not node_progress.is_completed:
            node_progress.is_completed = True
            node_progress.completed_at = datetime.utcnow()
            node_progress.completion_count += 1

            progress.completed_nodes += 1
            if progress.total_nodes > 0:
                progress.completion_rate = progress.completed_nodes / progress.total_nodes

            if progress.completion_rate >= 1.0:
                progress.status = LearningStatus.COMPLETED
                progress.completed_at = datetime.utcnow()

            session.commit()

        return unified_response(
            code=200,
            message="节点已完成",
            data={
                "nodeId": nodeId,
                "isCompleted": node_progress.is_completed,
                "completionRate": progress.completion_rate,
            },
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return unified_response(
            code=500, message=f"标记失败: {str(e)}", data=None
        )


@router.post("/sync", response_model=UnifiedResponse)
async def sync_learning_progress(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
    data: dict = Body(..., description="学习进度数据"),
):
    """
    同步学习进度（学生端调用）

    接收前端发送的学习进度数据并保存到数据库，包括：
    - 当前节点位置
    - 节点完成状态
    - 理解度评分
    - 学习时长

    请求体格式：
    {
        "courseId": 1,
        "nodeId": 5,
        "nodeIndex": 2,
        "understandingLevel": "high",
        "understandingScore": 0.85,
        "studyTime": 120
    }
    """
    try:
        user_id = int(current_user["user_id"])
        username = current_user.get("username", "user")

        course_id = data.get("courseId")
        node_id = data.get("nodeId")
        node_index = data.get("nodeIndex", 0)
        understanding_level = data.get("understandingLevel", "unknown")
        understanding_score = data.get("understandingScore", 0.0)
        study_time = data.get("studyTime", 0)

        if not course_id:
            return unified_response(code=400, message="缺少课程ID", data=None)

        print(f"[进度同步] 用户 {username} 课程{course_id} 节点{node_index} 理解度:{understanding_level}")

        # 查找或创建学习进度记录
        learning_progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.student_id == user_id,
                LearningProgress.course_id == course_id
            )
        ).first()

        if not learning_progress:
            # 如果没有进度记录（理论上不应该发生，因为选课时会初始化），则创建
            learning_progress = LearningProgress(
                student_id=user_id,
                course_id=course_id,
                current_node_index=node_index,
                overall_progress=0.0 if node_index == 0 else (node_index / max(1, data.get("totalNodes", 10))) * 100,
                total_study_time=study_time,
                last_access_time=datetime.utcnow(),
            )
            session.add(learning_progress)
            session.commit()
            session.refresh(learning_progress)
            print(f"[进度同步] 创建新的LearningProgress ID={learning_progress.id}")
        else:
            # 更新总体进度
            learning_progress.current_node_index = node_index
            learning_progress.total_study_time += study_time
            learning_progress.last_access_time = datetime.utcnow()

            # 计算总体进度（基于节点完成情况）
            total_nodes = data.get("totalNodes", 10)
            if total_nodes > 0:
                # 假设当前节点及之前的都已完成
                completed_count = node_index + 1
                learning_progress.overall_progress = (completed_count / total_nodes) * 100

            session.add(learning_progress)
            session.commit()

        # 更新或创建节点级别的进度记录
        if node_id:
            node_progress = session.exec(
                select(NodeProgress).where(
                    NodeProgress.learning_progress_id == learning_progress.id,
                    NodeProgress.node_id == node_id
                )
            ).first()

            if not node_progress:
                # 创建新的节点进度记录
                node_progress = NodeProgress(
                    learning_progress_id=learning_progress.id,
                    node_id=node_id,
                    node_index=node_index,
                    is_completed=True,
                    completion_rate=100.0 if understanding_score >= 0.7 else (understanding_score * 100),
                    understanding_score=understanding_score,
                    understanding_level=understanding_level,
                    study_time=study_time,
                    question_count=1,  # 默认至少有1次交互
                )
                session.add(node_progress)
                print(f"[进度同步] 创建NodeProgress 节点{node_id}")
            else:
                # 更新已有记录
                node_progress.is_completed = True
                node_progress.completion_rate = 100.0 if understanding_score >= 0.7 else (understanding_score * 100)
                node_progress.understanding_score = max(node_progress.understanding_score, understanding_score)
                node_progress.understanding_level = understanding_level
                node_progress.study_time += study_time
                node_progress.question_count += 1
                session.add(node_progress)

            session.commit()

        # 同步更新StudentEnrollment表中的统计数据
        from app.models.course_model import StudentEnrollment
        enrollment = session.exec(
            select(StudentEnrollment).where(
                StudentEnrollment.student_id == user_id,
                StudentEnrollment.course_id == course_id,
                StudentEnrollment.is_active == True
            )
        ).first()

        if enrollment:
            enrollment.overall_progress = learning_progress.overall_progress
            enrollment.avg_understanding_score = understanding_score
            enrollment.avg_understanding_level = understanding_level
            enrollment.total_study_minutes += (study_time // 60) if study_time else 0
            enrollment.last_study_time = datetime.utcnow()

            # 计算完成的节点数
            completed_nodes = session.exec(
                select(NodeProgress).where(
                    NodeProgress.learning_progress_id == learning_progress.id,
                    NodeProgress.is_completed == True
                )
            ).count_all() or 0

            enrollment.total_nodes_completed = completed_nodes
            session.add(enrollment)
            session.commit()

        return unified_response(
            code=200,
            message="学习进度保存成功",
            data={
                "progress_id": learning_progress.id,
                "overall_progress": round(learning_progress.overall_progress, 1),
                "current_node": node_index,
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"进度同步失败: {str(e)}",
            data={"error": str(e)}
        )
