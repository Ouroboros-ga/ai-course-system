"""
仪表盘聚合API接口
提供首页聚合数据和课程概览聚合数据
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.progress_model import (
    LearningProgress,
    NodeProgress,
    UnderstandingAnalysis,
    LearningJumpHistory,
)
from app.models.course_model import Course, CourseScript, ScriptNode
from app.models.user_model import User

router = APIRouter(tags=["仪表盘"])


@router.get("", response_model=UnifiedResponse)
async def get_dashboard(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    首页聚合数据

    返回：
    - continue_learning: 最近访问的课程列表
    - pending_items: 待处理的跳转记录
    - system_responses: 最近的理解度分析反馈
    """
    try:
        user_id = int(current_user["user_id"])

        # --- continue_learning: 最近访问的课程 ---
        progresses = session.exec(
            select(LearningProgress)
            .where(LearningProgress.user_id == user_id)
            .order_by(LearningProgress.last_accessed_at.desc())
        ).all()

        # 关联 User 获取 role（同一用户，查一次）
        user = session.get(User, user_id)
        role = user.role.value if user and user.role else None

        continue_learning = []
        for p in progresses:
            course = session.get(Course, p.course_id)
            continue_learning.append(
                {
                    "course_id": p.course_id,
                    "title": course.title if course else "",
                    "role": role,
                    "current_node": p.current_node_id,
                    "progress": p.completion_rate,
                    "last_accessed": p.last_accessed_at.isoformat()
                    if p.last_accessed_at
                    else None,
                }
            )

        # --- pending_items: 未返回的跳转记录 ---
        jumps = session.exec(
            select(LearningJumpHistory)
            .where(
                LearningJumpHistory.user_id == user_id,
                LearningJumpHistory.is_returned.is_(False),
            )
            .order_by(LearningJumpHistory.created_at.desc())
        ).all()

        pending_items = []
        for j in jumps:
            pending_items.append(
                {
                    "type": "prerequisite_jump",
                    "title": j.to_node_title or j.gap_description or "",
                    "course_id": j.course_id,
                    "deadline": None,
                    "action_url": None,
                }
            )

        # --- system_responses: 最近的理解度分析 ---
        system_responses = []
        progress_ids = [p.id for p in progresses]
        if progress_ids:
            analyses = session.exec(
                select(UnderstandingAnalysis)
                .where(UnderstandingAnalysis.progress_id.in_(progress_ids))
                .order_by(UnderstandingAnalysis.created_at.desc())
                .limit(3)
            ).all()
            for a in analyses:
                system_responses.append(
                    {
                        "observation": a.analysis_reason,
                        "evidence": f"理解等级: {a.understanding_level.value if a.understanding_level else '未知'}, 理解分数: {a.understanding_score}",
                        "suggestion": a.suggestions,
                        "action_label": None,
                        "action_url": None,
                    }
                )

        return unified_response(
            code=200,
            message="获取首页数据成功",
            data={
                "continue_learning": continue_learning,
                "pending_items": pending_items,
                "system_responses": system_responses,
            },
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return unified_response(
            code=500, message=f"获取首页数据失败: {str(e)}", data=None
        )


@router.get("/course/{course_id}", response_model=UnifiedResponse)
async def get_course_dashboard(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    课程概览聚合数据

    返回：
    - continue: 当前学习位置
    - progress: 学习进度统计
    - pending: 待处理跳转记录
    - recent_responses: 最近理解度分析
    - structure_summary: 章节结构摘要
    """
    try:
        user_id = int(current_user["user_id"])

        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        # --- continue: 当前学习位置 ---
        continue_data = None
        if progress:
            current_node = None
            if progress.current_node_id:
                current_node = session.get(ScriptNode, progress.current_node_id)
            continue_data = {
                "node_id": progress.current_node_id,
                "node_title": current_node.title if current_node else "",
                "node_index": progress.current_node_index,
                "page": progress.current_page,
                "timestamp": progress.current_timestamp,
                "progress": progress.completion_rate,
            }

        # --- progress: 进度统计 ---
        progress_data = None
        if progress:
            node_progresses = session.exec(
                select(NodeProgress).where(NodeProgress.progress_id == progress.id)
            ).all()
            completed_nodes = sum(1 for np in node_progresses if np.is_completed)

            current_chapter = None
            if progress.current_node_id:
                current_node = session.get(ScriptNode, progress.current_node_id)
                if current_node:
                    current_chapter = current_node.title

            progress_data = {
                "completed_nodes": completed_nodes,
                "total_nodes": progress.total_nodes,
                "completion_rate": progress.completion_rate,
                "current_chapter": current_chapter,
            }

        # --- pending: 待处理跳转 ---
        jumps = session.exec(
            select(LearningJumpHistory)
            .where(
                LearningJumpHistory.user_id == user_id,
                LearningJumpHistory.course_id == course_id,
                LearningJumpHistory.is_returned.is_(False),
            )
            .order_by(LearningJumpHistory.created_at.desc())
        ).all()

        pending = []
        for j in jumps:
            pending.append(
                {
                    "type": "prerequisite_jump",
                    "title": j.to_node_title or j.gap_description or "",
                    "deadline": None,
                }
            )

        # --- recent_responses: 最近理解度分析 ---
        recent_responses = []
        if progress:
            analyses = session.exec(
                select(UnderstandingAnalysis)
                .where(UnderstandingAnalysis.progress_id == progress.id)
                .order_by(UnderstandingAnalysis.created_at.desc())
                .limit(3)
            ).all()
            for a in analyses:
                recent_responses.append(
                    {
                        "observation": a.analysis_reason,
                        "evidence": f"理解等级: {a.understanding_level.value if a.understanding_level else '未知'}, 理解分数: {a.understanding_score}",
                        "suggestion": a.suggestions,
                        "action_label": None,
                    }
                )

        # --- structure_summary: 章节结构 ---
        structure_summary = {
            "current_chapter": None,
            "prev_chapter": None,
            "next_chapter": None,
        }
        course_script = session.exec(
            select(CourseScript).where(CourseScript.course_id == course_id)
        ).first()
        if course_script:
            script_nodes = session.exec(
                select(ScriptNode)
                .where(ScriptNode.script_id == course_script.id)
                .order_by(ScriptNode.node_index)
            ).all()
            current_node_id = progress.current_node_id if progress else None
            if script_nodes and current_node_id:
                current_idx = None
                for i, node in enumerate(script_nodes):
                    if node.id == current_node_id:
                        current_idx = i
                        break
                if current_idx is not None:
                    structure_summary["current_chapter"] = script_nodes[
                        current_idx
                    ].title
                    if current_idx > 0:
                        structure_summary["prev_chapter"] = script_nodes[
                            current_idx - 1
                        ].title
                    if current_idx < len(script_nodes) - 1:
                        structure_summary["next_chapter"] = script_nodes[
                            current_idx + 1
                        ].title

        return unified_response(
            code=200,
            message="获取课程概览成功",
            data={
                "continue": continue_data,
                "progress": progress_data,
                "pending": pending,
                "recent_responses": recent_responses,
                "structure_summary": structure_summary,
            },
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return unified_response(
            code=500, message=f"获取课程概览失败: {str(e)}", data=None
        )
