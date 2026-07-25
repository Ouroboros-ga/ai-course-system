"""
前置知识智能跳转API端点
提供知识缺陷检测、跳转管理、学习路径可视化等接口
"""

import logging
import traceback
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Body, Query, HTTPException
from sqlmodel import Session, select

from app.models.database import get_session
from app.core.security import get_current_user
from app.core.exceptions import unified_response
from app.models.progress_model import LearningJumpHistory
from app.models.course_model import CourseScript, ScriptNode
from app.services.prerequisite_service import (
    prerequisite_analyzer,
    jump_history_manager,
)
from app.services.course_access_service import require_course_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/prerequisite", tags=["前置知识智能跳转"])


def _require_course_node(session: Session, course_id: int, node_id: int) -> ScriptNode:
    """Reject node IDs that belong to another course before using them."""
    node = session.get(ScriptNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Course node does not exist")
    script = session.get(CourseScript, node.script_id)
    if script is None or script.course_id != course_id:
        raise HTTPException(status_code=404, detail="Course node does not exist")
    return node


@router.post("/analyze-gap")
async def analyze_prerequisite_gap(
    courseId: int = Body(..., description="课程ID"),
    currentNodeId: int = Body(..., description="当前节点ID"),
    question: str = Body(..., description="学生提问内容"),
    conversationHistory: list = Body(default=[], description="历史对话记录"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    分析学生提问是否涉及前置知识缺陷
    
    使用AI分析学生的提问内容，结合当前知识点的前置依赖关系，
    判断是否存在前置知识盲区，并给出是否需要跳转复习的建议。
    
    **使用场景**：
    - 学生在学习"洛必达法则"时提问："这个公式怎么推导的？"
    - 系统检测到学生对"函数极限"理解不足
    - 返回建议：跳转到"函数极限"知识点复习
    
    **请求示例**:
    ```json
    {
        "courseId": 1,
        "currentNodeId": 15,
        "question": "洛必达法则的0/0型不定式怎么处理？",
        "conversationHistory": [
            {"role": "user", "content": "..."},
            {"role": "ai", "content": "..."}
        ]
    }
    ```
    
    **响应示例**:
    ```json
    {
        "code": 200,
        "data": {
            "hasGaps": true,
            "overallConfidence": 0.85,
            "weakPrerequisites": [
                {
                    "prerequisiteId": 5,
                    "title": "函数极限",
                    "reason": "洛必达法则需要用到极限计算基础",
                    "confidence": 0.9,
                    "targetNodeIndex": 2,
                    "urgencyLevel": "high"
                }
            ],
            "suggestedAction": "jump_to_review",
            "analysisSummary": "检测到学生对'函数极限'概念理解存在明显缺陷..."
        }
    }
    ```
    """
    try:
        user_id = int(current_user["user_id"])
        access = require_course_permission(session, current_user, courseId, "course.learn")
        if not access.analytics_eligible:
            return unified_response(code=403, message="Only learner participation can create prerequisite signals", data=None)
        
        current_node = _require_course_node(session, courseId, currentNodeId)
        
        result = await prerequisite_analyzer.analyze_prerequisite_gaps(
            question=question,
            current_node=current_node,
            course_id=courseId,
            user_id=user_id,
            session=session,
            conversation_history=conversationHistory,
        )
        
        return unified_response(
            code=200,
            message="分析完成",
            data={
                "hasGaps": result.get("has_gaps", False),
                "overallConfidence": result.get("overall_confidence", 0.0),
                "weakPrerequisites": result.get("weak_prerequisites", []),
                "suggestedAction": result.get("suggested_action", "continue"),
                "analysisSummary": result.get("analysis_summary", ""),
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[前置知识缺陷检测失败] {str(e)}\n{traceback.format_exc()}")
        return unified_response(
            code=500,
            message=f"分析失败: {str(e)}",
            data=None
        )


@router.post("/jump")
async def execute_jump_to_prerequisite(
    courseId: int = Body(..., description="课程ID"),
    fromNodeId: int = Body(..., description="源节点ID（当前学习的节点）"),
    fromNodeTitle: str = Body("", description="源节点标题"),
    fromNodeIndex: int = Body(0, description="源节点索引位置"),
    toPrerequisiteId: int = Body(..., description="目标前置知识点ID"),
    toNodeTitle: str = Body("", description="目标节点标题"),
    toNodeIndex: int = Body(0, description="目标节点索引位置"),
    triggerQuestion: str = Body("", description="触发跳转的问题"),
    analysisResult: Optional[str] = Body(default=None, description="AI分析结果JSON字符串"),
    gapDescription: str = Body("", description="知识缺陷描述"),
    confidenceScore: float = Body(0.8, ge=0.0, le=1.0, description="置信度"),
    urgencyLevel: str = Body("medium", description="紧急程度: high/medium/low"),
    parentJumpId: Optional[int] = Body(None, description="父级跳转ID（多层嵌套时）"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    执行前置知识跳转并记录历史
    
    当学生确认要跳转复习前置知识时，调用此接口记录跳转事件，
    并返回完整的跳转栈信息用于前端管理状态。
    
    **功能**：
    - 创建跳转记录到数据库
    - 支持多层嵌套跳转（从A→B，再从B→C）
    - 记录触发原因和AI分析结果
    - 维护跳转历史栈
    
    **请求示例**:
    ```json
    {
        "courseId": 1,
        "fromNodeId": 15,
        "fromNodeTitle": "洛必达法则",
        "fromNodeIndex": 14,
        "toPrerequisiteId": 5,
        "toNodeTitle": "函数极限",
        "toNodeIndex": 2,
        "triggerQuestion": "这个公式怎么推导的？",
        "gapDescription": "需要掌握极限定义才能理解洛必达法则",
        "confidenceScore": 0.9,
        "urgencyLevel": "high"
    }
    ```
    
    **响应示例**:
    ```json
    {
        "code": 200,
        "data": {
            "jumpId": 123,
            "success": true,
            "message": "已创建跳转记录",
            "jumpStack": [...],
            "canGoBack": true
        }
    }
    ```
    """
    try:
        user_id = int(current_user["user_id"])
        access = require_course_permission(session, current_user, courseId, "course.learn")
        if not access.analytics_eligible:
            return unified_response(code=403, message="Only learner participation can create prerequisite jumps", data=None)
        _require_course_node(session, courseId, fromNodeId)
        _require_course_node(session, courseId, toPrerequisiteId)
        if parentJumpId is not None:
            parent = session.get(LearningJumpHistory, parentJumpId)
            if parent is None or parent.user_id != user_id or parent.course_id != courseId:
                raise HTTPException(status_code=404, detail="Parent jump record does not exist")
        
        jump_record = jump_history_manager.create_jump_record(
            session=session,
            user_id=user_id,
            course_id=courseId,
            from_node_id=fromNodeId,
            from_node_title=fromNodeTitle,
            from_node_index=fromNodeIndex,
            to_node_id=toPrerequisiteId,
            to_node_title=toNodeTitle,
            to_node_index=toNodeIndex,
            trigger_type="prerequisite_gap",
            trigger_question=triggerQuestion,
            analysis_result=analysisResult,
            prerequisite_ids=[toPrerequisiteId],
            prerequisite_titles=[toNodeTitle] if toNodeTitle else [],
            gap_description=gapDescription,
            confidence_score=confidenceScore,
            urgency_level=urgencyLevel,
            parent_jump_id=parentJumpId,
        )
        
        # 获取更新后的跳转栈
        jump_stack = jump_history_manager.get_jump_stack(
            session=session,
            user_id=user_id,
            course_id=courseId,
            include_returned=False
        )
        
        return unified_response(
            code=200,
            message="跳转记录已创建",
            data={
                "jumpId": jump_record.id,
                "success": True,
                "sessionId": jump_record.session_id,
                "jumpDepth": jump_record.jump_depth,
                "jumpStack": [
                    {
                        "id": j.id,
                        "fromNode": j.from_node_title,
                        "toNode": j.to_node_title,
                        "depth": j.jump_depth,
                        "urgencyLevel": j.urgency_level,
                        "createdAt": j.created_at.isoformat(),
                    }
                    for j in jump_stack
                ],
                "canGoBack": len(jump_stack) > 0,
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[执行跳转失败] {str(e)}\n{traceback.format_exc()}")
        return unified_response(
            code=500,
            message=f"跳转失败: {str(e)}",
            data=None
        )


@router.post("/return")
async def return_to_original_position(
    jumpId: int = Body(..., description="跳转记录ID"),
    reviewDurationSeconds: int = Body(0, description="复习耗时（秒）"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    返回原位置（完成复习后）
    
    学生复习完前置知识后，调用此接口返回到原来的学习位置。
    系统会标记跳转记录为已返回，并返回原节点的信息。
    
    **功能**：
    - 标记跳转记录为已完成
    - 记录复习时长
    - 返回原节点信息供前端跳转
    - 更新学习路径数据
    
    **请求示例**:
    ```json
    {
        "jumpId": 123,
        "reviewDurationSeconds": 300
    }
    ```
    
    **响应示例**:
    ```json
    {
        "code": 200,
        "data": {
            "success": true,
            "originalNode": {
                "nodeId": 15,
                "nodeTitle": "洛必达法则",
                "nodeIndex": 14
            },
            "reviewSummary": {
                "duration": "5分钟",
                "completedAt": "2024-01-15T10:30:00"
            }
        }
    }
    ```
    """
    try:
        user_id = int(current_user["user_id"])
        jump = session.get(LearningJumpHistory, jumpId)
        if jump is None or jump.user_id != user_id:
            return unified_response(code=404, message="Jump record does not exist", data=None)
        require_course_permission(session, current_user, jump.course_id, "course.progress.read_self")
        success = jump_history_manager.mark_as_returned(
            session=session,
            jump_id=jumpId,
            review_duration_seconds=reviewDurationSeconds,
        )
        
        if not success:
            return unified_response(
                code=404,
                message="跳转记录不存在",
                data=None
            )

        # 获取原节点信息
        jump_record = session.get(LearningJumpHistory, jumpId)
        
        original_node = None
        if jump_record:
            original_node = {
                "nodeId": jump_record.from_node_id,
                "nodeTitle": jump_record.from_node_title,
                "nodeIndex": jump_record.from_node_index,
            }
            
            # 自动标记复习完成
            jump_history_manager.mark_review_completed(session, jumpId)
        
        return unified_response(
            code=200,
            message="已返回原位置",
            data={
                "success": True,
                "originalNode": original_node,
                "reviewSummary": {
                    "duration": f"{reviewDurationSeconds // 60}分钟{reviewDurationSeconds % 60}秒",
                    "completedAt": datetime.utcnow().isoformat(),
                } if reviewDurationSeconds > 0 else None,
            }
        )
        
    except Exception as e:
        logger.error(f"[返回原位置失败] {str(e)}\n{traceback.format_exc()}")
        return unified_response(
            code=500,
            message=f"返回失败: {str(e)}",
            data=None
        )


@router.get("/jump-stack")
async def get_current_jump_stack(
    courseId: int = Query(..., description="课程ID"),
    includeReturned: bool = Query(False, description="是否包含已返回的记录"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取当前会话的跳转历史栈
    
    用于前端显示当前的跳转层级，支持"逐级返回"功能。
    
    **响应示例** (多层嵌套场景):
    ```json
    {
        "code": 200,
        "data": {
            "stack": [
                {
                    "id": 120,
                    "from": "洛必达法则",
                    "to": "函数极限",
                    "depth": 1,
                    "isReturned": false,
                    "createdAt": "2024-01-15T10:20:00"
                },
                {
                    "id": 121,
                    "from": "函数极限",
                    "to": "数列极限",
                    "depth": 2,
                    "isReturned": false,
                    "createdAt": "2024-01-15T10:25:00"
                }
            ],
            "currentDepth": 2,
            "canGoBack": true,
            "totalJumpsInSession": 2
        }
    }
    ```
    """
    try:
        user_id = int(current_user["user_id"])
        require_course_permission(session, current_user, courseId, "course.progress.read_self")
        
        jump_stack = jump_history_manager.get_jump_stack(
            session=session,
            user_id=user_id,
            course_id=courseId,
            include_returned=includeReturned
        )
        
        unresolved_count = sum(1 for j in jump_stack if not j.is_returned)
        max_depth = max((j.jump_depth for j in jump_stack), default=0)
        
        return unified_response(
            code=200,
            message="获取成功",
            data={
                "stack": [
                    {
                        "id": j.id,
                        "fromNode": j.from_node_title,
                        "fromNodeIndex": j.from_node_index,
                        "toNode": j.to_node_title,
                        "toNodeIndex": j.to_node_index,
                        "depth": j.jump_depth,
                        "triggerType": j.trigger_type,
                        "urgencyLevel": j.urgency_level,
                        "gapDescription": j.gap_description,
                        "isReturned": j.is_returned,
                        "returnedAt": j.returned_at.isoformat() if j.returned_at else None,
                        "reviewCompleted": j.review_completed,
                        "createdAt": j.created_at.isoformat(),
                    }
                    for j in jump_stack
                ],
                "currentDepth": max_depth,
                "canGoBack": unresolved_count > 0,
                "unresolvedCount": unresolved_count,
                "totalCount": len(jump_stack),
            }
        )
        
    except Exception as e:
        logger.error(f"[获取跳转栈失败] {str(e)}")
        return unified_response(
            code=500,
            message=f"获取失败: {str(e)}",
            data=None
        )


@router.post("/mark-reviewed")
async def mark_prerequisite_reviewed(
    jumpId: int = Body(..., description="跳转记录ID"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    标记前置知识复习完成
    
    当学生在目标知识点完成了复习（如通过测试、达到一定理解度等），
    调用此接口标记复习完成，系统可以据此调整后续的学习推荐策略。
    
    **响应示例**:
    ```json
    {
        "code": 200,
        "data": {
            "success": true,
            "message": "已标记复习完成",
            "nextRecommendation": "建议返回原位置继续学习'洛必达法则'"
        }
    }
    ```
    """
    try:
        user_id = int(current_user["user_id"])
        jump = session.get(LearningJumpHistory, jumpId)
        if jump is None or jump.user_id != user_id:
            return unified_response(code=404, message="Jump record does not exist", data=None)
        require_course_permission(session, current_user, jump.course_id, "course.progress.read_self")
        success = jump_history_manager.mark_review_completed(
            session=session,
            jump_id=jumpId,
        )
        
        if not success:
            return unified_response(
                code=404,
                message="跳转记录不存在",
                data=None
            )
        
        jump_record = session.get(LearningJumpHistory, jumpId)
        
        next_recommendation = ""
        if jump_record and not jump_record.is_returned:
            next_recommendation = f"建议返回原位置继续学习'{jump_record.from_node_title}'"
        
        return unified_response(
            code=200,
            message="已标记复习完成",
            data={
                "success": True,
                "nextRecommendation": next_recommendation,
            }
        )
        
    except Exception as e:
        logger.error(f"[标记复习完成失败] {str(e)}")
        return unified_response(
            code=500,
            message=f"操作失败: {str(e)}",
            data=None
        )


@router.get("/learning-path")
async def get_learning_path_visualization(
    courseId: int = Query(..., description="课程ID"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取学习路径可视化数据
    
    返回完整的学习路径图数据，包括：
    - 所有知识点的学习状态（已完成/当前/待学/前置复习中）
    - 前置知识跳转的历史轨迹
    - 当前学习路径链（支持多层嵌套）
    
    **用途**：前端渲染交互式学习路径图，帮助学生了解自己的学习轨迹
    
    **响应示例**:
    ```json
    {
        "code": 200,
        "data": {
            "nodes": [
                {
                    "id": 1,
                    "index": 0,
                    "title": "课程导论",
                    "status": "completed",
                    "understandingScore": 0.92
                },
                {
                    "id": 5,
                    "index": 2,
                    "title": "函数极限",
                    "status": "current",
                    "understandingScore": 0.65
                },
                {
                    "id": 15,
                    "index": 14,
                    "title": "洛必达法则",
                    "status": "pending",
                    "understandingScore": null
                }
            ],
            "edges": [
                {
                    "from": 15,
                    "to": 5,
                    "type": "prerequisite_jump",
                    "label": "跳转复习: 需要掌握极限定义",
                    "timestamp": "2024-01-15T10:20:00",
                    "isReturned": false
                }
            ],
            "currentPath": [
                {"fromNode": "洛必达法则", "toNode": "函数极限", "depth": 1}
            ],
            "statistics": {
                "totalJumps": 3,
                "completedJumps": 2,
                "avgReviewTime": "4.5分钟"
            }
        }
    }
    """
    try:
        user_id = int(current_user["user_id"])
        require_course_permission(session, current_user, courseId, "course.progress.read_self")
        
        path_data = jump_history_manager.get_learning_path_data(
            session=session,
            user_id=user_id,
            course_id=courseId,
        )
        
        # 补充统计信息
        all_jumps = path_data.get("edges", [])
        completed_jumps = [e for e in all_jumps if e.get("isReturned")]
        
        total_review_time = 0
        jumps_records = session.exec(
            select(LearningJumpHistory).where(
                LearningJumpHistory.user_id == user_id,
                LearningJumpHistory.course_id == courseId,
                LearningJumpHistory.is_returned == True
            )
        ).all()
        
        for jr in jumps_records:
            total_review_time += jr.review_duration_seconds
        
        avg_review_time = (
            f"{total_review_time // len(jumps_records)}分{total_review_time % len(jumps_records) % 60}秒"
            if jumps_records else "0分钟"
        )
        
        return unified_response(
            code=200,
            message="获取成功",
            data={
                "nodes": path_data.get("nodes", []),
                "edges": path_data.get("edges", []),
                "currentPath": path_data.get("currentPath", []),
                "statistics": {
                    "totalJumps": len(all_jumps),
                    "completedJumps": len(completed_jumps),
                    "pendingJumps": len(all_jumps) - len(completed_jumps),
                    "avgReviewTime": avg_review_time,
                }
            }
        )
        
    except Exception as e:
        logger.error(f"[获取学习路径失败] {str(e)}\n{traceback.format_exc()}")
        return unified_response(
            code=500,
            message=f"获取失败: {str(e)}",
            data=None
        )
