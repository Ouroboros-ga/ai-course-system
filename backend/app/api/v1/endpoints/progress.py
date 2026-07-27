"""
进度续接API接口
提供学习进度管理、理解度分析、节点定位等接口
"""

from typing import Optional, List
from app.core.time_utils import utcnow_aware

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user, _get_user_id, _get_username, _get_user_identity
from app.models.database import get_session
from app.models.progress_model import LearningProgress, NodeProgress, LearningStatus, UnderstandingLevel
from app.models.course_model import Course, ScriptNode, CourseScript
from app.models.user_model import ChatMessage
from app.services.progress_service import progress_service
from app.common.llm_client import llm_client, Message
from app.common.prompts.progress import (
    PROGRESS_CONTINUATION_PROMPT,
    build_progress_continuation_prompt
)
from app.services.course_access_service import require_course_permission

router = APIRouter(tags=["进度续接"])


@router.post("/analyze", response_model=UnifiedResponse)
async def analyze_understanding(
    session: Session = Depends(get_session),
    user_id: int = Depends(_get_user_id),
    username: str = Depends(_get_username),
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
        access = require_course_permission(session, current_user, courseId, "course.learn")
        if not access.analytics_eligible:
            raise HTTPException(status_code=403, detail="Only learner participation can record progress")
        print(f"[进度分析] 用户 {username} (ID: {user_id}) 提交分析请求")

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
    user_id: int = Depends(_get_user_id),
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
        access = require_course_permission(session, current_user, course_id, "course.progress.read_self")
        if not access.analytics_eligible:
            raise HTTPException(status_code=403, detail="Only learner participation has personal progress")
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
    user_id: int = Depends(_get_user_id),
    current_user: dict = Depends(get_current_user),
    courseId: int = Body(..., description="课程ID"),
    nodeId: int = Body(..., description="当前节点ID"),
    timestamp: float = Body(0.0, description="当前播放时间点(秒)"),
    isCompleted: bool = Body(False, description="当前节点是否已完成"),
    timeSpent: int = Body(0, description="本次学习时长(秒)"),
    nodeIndex: Optional[int] = Body(None, description="节点索引"),
    understandingLevel: Optional[str] = Body(None, description="理解程度等级"),
    understandingScore: Optional[float] = Body(None, ge=0.0, le=1.0, description="理解分数(0-1)"),
    studyTime: Optional[int] = Body(None, description="学习时长(秒)"),
    totalNodes: Optional[int] = Body(None, description="总节点数"),
):
    """
    同步学习进度

    用于前端定期同步播放进度，支持断点续接
    """
    try:
        access = require_course_permission(session, current_user, courseId, "course.progress.read_self")
        if not access.analytics_eligible:
            raise HTTPException(status_code=403, detail="Only learner participation can record progress")
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
                started_at=utcnow_aware(),
                total_nodes=totalNodes or 0,
            )
            session.add(progress)
            session.commit()
            session.refresh(progress)

        progress.current_node_id = nodeId
        progress.current_timestamp = timestamp
        progress.last_accessed_at = utcnow_aware()
        if timeSpent > 0:
            progress.total_learning_time += timeSpent
        elif studyTime and studyTime > 0:
            progress.total_learning_time += studyTime

        if totalNodes and totalNodes > 0:
            progress.total_nodes = totalNodes

        if nodeIndex is not None:
            progress.current_node_index = nodeIndex

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
                node_index=nodeIndex if nodeIndex is not None else (script.node_index if script else 0),
                first_accessed_at=utcnow_aware(),
            )
            session.add(node_progress)
            session.commit()
            session.refresh(node_progress)

        node_progress.last_timestamp = timestamp
        if timeSpent > 0:
            node_progress.time_spent += timeSpent
        elif studyTime and studyTime > 0:
            node_progress.time_spent += studyTime
        node_progress.last_accessed_at = utcnow_aware()

        if understandingLevel:
            try:
                node_progress.understanding_level = UnderstandingLevel(understandingLevel)
            except ValueError:
                pass
        if understandingScore is not None:
            node_progress.understanding_score = understandingScore

        if isCompleted and not node_progress.is_completed:
            node_progress.is_completed = True
            node_progress.completed_at = utcnow_aware()
            node_progress.completion_count += 1

            progress.completed_nodes += 1
            if progress.total_nodes > 0:
                progress.completion_rate = progress.completed_nodes / progress.total_nodes

            if progress.completion_rate >= 1.0:
                progress.status = LearningStatus.COMPLETED
                progress.completed_at = utcnow_aware()

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
    user_id: int = Depends(_get_user_id),
    current_user: dict = Depends(get_current_user),
):
    """
    获取断点续接信息

    返回上次学习的位置，用于学生重新进入课程时恢复进度
    """
    try:
        access = require_course_permission(session, current_user, course_id, "course.progress.read_self")
        if not access.analytics_eligible:
            raise HTTPException(status_code=403, detail="Only learner participation has personal progress")
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


@router.get("/detail/{course_id}", response_model=UnifiedResponse)
async def get_progress_detail(
    course_id: int,
    session: Session = Depends(get_session),
    user_id: int = Depends(_get_user_id),
    current_user: dict = Depends(get_current_user),
):
    """
    获取学生学习进度详情

    返回完整的进度信息，包括：
    - 总体学习统计
    - 每个节点的完成状态、理解度、学习时长
    - 用于学生进入课程时加载历史进度
    """
    try:
        access = require_course_permission(session, current_user, course_id, "course.progress.read_self")
        if not access.analytics_eligible:
            raise HTTPException(status_code=403, detail="Only learner participation has personal progress")
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        if not progress:
            return unified_response(
                code=200,
                message="暂无学习记录",
                data={
                    "has_progress": False,
                    "overall": None,
                    "nodes_progress": [],
                }
            )

        nodes_progress = session.exec(
            select(NodeProgress).where(
                NodeProgress.progress_id == progress.id
            ).order_by(NodeProgress.node_index)
        ).all()

        nodes_data = []
        for np in nodes_progress:
            node_data = {
                "node_id": np.node_id,
                "node_index": np.node_index,
                "is_completed": np.is_completed,
                "understanding_score": round(np.understanding_score * 100, 1) if np.understanding_score else 0,
                "understanding_level": np.understanding_level.value if np.understanding_level else None,
                "question_count": np.question_count,
                "time_spent": np.time_spent,
                "completion_count": np.completion_count,
                "last_accessed_at": np.last_accessed_at.isoformat() if np.last_accessed_at else None,
            }
            nodes_data.append(node_data)

        overall_data = {
            "progress_id": progress.id,
            "completion_rate": round(progress.completion_rate * 100, 1),
            "status": progress.status.value,
            "total_nodes": progress.total_nodes,
            "completed_nodes": progress.completed_nodes,
            "current_node_index": progress.current_node_index,
            "total_learning_time": progress.total_learning_time,
            "session_count": progress.session_count,
            "last_accessed_at": progress.last_accessed_at.isoformat() if progress.last_accessed_at else None,
            "started_at": progress.started_at.isoformat() if progress.started_at else None,
        }

        return unified_response(
            code=200,
            message="获取进度详情成功",
            data={
                "has_progress": True,
                "overall": overall_data,
                "nodes_progress": nodes_data,
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500, message=f"获取进度详情失败: {str(e)}", data=None
        )


@router.post("/node/complete", response_model=UnifiedResponse)
async def mark_node_completed(
    session: Session = Depends(get_session),
    user_id: int = Depends(_get_user_id),
    current_user: dict = Depends(get_current_user),
    courseId: int = Body(..., description="课程ID"),
    nodeId: int = Body(..., description="节点ID"),
):
    """
    标记节点为已完成
    """
    try:
        access = require_course_permission(session, current_user, courseId, "course.progress.read_self")
        if not access.analytics_eligible:
            raise HTTPException(status_code=403, detail="Only learner participation can record progress")
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
                first_accessed_at=utcnow_aware(),
            )
            session.add(node_progress)
            session.commit()
            session.refresh(node_progress)

        if not node_progress.is_completed:
            node_progress.is_completed = True
            node_progress.completed_at = utcnow_aware()
            node_progress.completion_count += 1

            progress.completed_nodes += 1
            if progress.total_nodes > 0:
                progress.completion_rate = progress.completed_nodes / progress.total_nodes

            if progress.completion_rate >= 1.0:
                progress.status = LearningStatus.COMPLETED
                progress.completed_at = utcnow_aware()

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


@router.post("/continuation", response_model=UnifiedResponse)
async def get_progress_continuation(
    session: Session = Depends(get_session),
    user_id: int = Depends(_get_user_id),
    username: str = Depends(_get_username),
    current_user: dict = Depends(get_current_user),
    courseId: int = Body(..., description="课程ID"),
    chatId: Optional[int] = Body(None, description="会话ID，用于获取历史对话"),
):
    """
    进度续接分析

    核心功能：
    1. 获取用户历史答疑记录
    2. 调用LLM分析学习进度和理解度
    3. 生成结构化的续接脚本和建议

    返回：
    - 进度摘要（整体进度、状态、预计时间）
    - 理解度分析（等级、分数、强弱项）
    - 学习建议（下一步操作、推荐节点、复习建议）
    - 续接脚本（欢迎语、进度回顾、下一步介绍、鼓励语）
    """
    try:
        access = require_course_permission(session, current_user, courseId, "course.progress.read_self")
        if not access.analytics_eligible:
            raise HTTPException(status_code=403, detail="Only learner participation has personal progress")
        import json
        import re

        print(f"[进度续接] 用户 {username} (ID: {user_id}) 请求进度续接分析")

        # 获取课程信息
        course = session.get(Course, courseId)
        if not course:
            return unified_response(code=404, message="课程不存在", data=None)

        # 获取当前学习进度
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == courseId,
            )
        ).first()

        # 获取当前节点
        current_node_id = progress.current_node_id if progress else None
        current_node = None
        if current_node_id:
            current_node = session.get(ScriptNode, current_node_id)

        # 获取课程脚本结构
        course_script = session.exec(
            select(CourseScript).where(CourseScript.course_id == courseId)
        ).first()

        script_nodes = []
        if course_script and course_script.script_content:
            sections = course_script.script_content.get("sections", [])
            script_nodes = [
                {
                    "id": i,
                    "title": s.get("title", f"节点{i}"),
                    "type": s.get("type", "lecture")
                }
                for i, s in enumerate(sections)
            ]

        # 获取历史答疑记录
        chat_messages = []
        if chatId:
            messages = session.exec(
                select(ChatMessage)
                .where(ChatMessage.chat_id == chatId)
                .order_by(ChatMessage.created_at.asc())
            ).all()
            chat_messages = [
                {"role": "user" if m.role.value == "user" else "assistant", "content": m.content}
                for m in messages
            ]

        # 构建提示词
        current_node_info = {
            "id": current_node.id if current_node else None,
            "title": current_node.title if current_node else "未知节点",
            "content": current_node.content if current_node else ""
        }

        user_prompt = build_progress_continuation_prompt(
            chat_history=chat_messages,
            current_node=current_node_info,
            course_structure=script_nodes
        )

        # 调用LLM生成续接分析
        messages = [
            Message(role="system", content=PROGRESS_CONTINUATION_PROMPT),
            Message(role="user", content=user_prompt)
        ]

        print(f"[进度续接] 发送LLM请求，历史记录数: {len(chat_messages)}")
        response = await llm_client.chat(messages, temperature=0.3)
        print(f"[进度续接] 收到LLM响应，长度: {len(response.content)} 字符")

        # 解析JSON结果
        json_match = re.search(r'\{[\s\S]*\}', response.content)
        if json_match:
            continuation_result = json.loads(json_match.group())
        else:
            # 默认结果
            continuation_result = {
                "progress_summary": {
                    "overall_progress": progress.completion_rate if progress else 0.0,
                    "current_status": "学习中",
                    "estimated_completion_time": "继续学习"
                },
                "understanding_analysis": {
                    "overall_level": "medium",
                    "overall_score": 0.6,
                    "strength_areas": [],
                    "weak_areas": [],
                    "analysis_summary": "基于当前学习进度进行分析"
                },
                "learning_recommendations": {
                    "next_action": "continue",
                    "recommended_nodes": [current_node_id] if current_node_id else [],
                    "review_suggestions": [],
                    "pace_adjustment": "保持当前节奏"
                },
                "continuation_script": {
                    "welcome_back": f"欢迎回来，{username}！",
                    "progress_review": "继续你之前的学习进度。",
                    "next_step_intro": "让我们继续学习。",
                    "encouragement": "加油！"
                }
            }

        # 补充进度信息
        if progress:
            continuation_result["progress_summary"]["overall_progress"] = progress.completion_rate
            continuation_result["progress_summary"]["total_learning_time"] = progress.total_learning_time
            continuation_result["progress_summary"]["last_accessed_at"] = progress.last_accessed_at.isoformat() if progress.last_accessed_at else None

        return unified_response(
            code=200,
            message="进度续接分析完成",
            data=continuation_result
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500, message=f"进度续接分析失败: {str(e)}", data=None
        )
