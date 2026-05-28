"""
分屏视频播放器API接口
提供学生端分屏播放所需的数据接口，包括：
- 播放器初始化数据（课程信息、节点列表、视频URL等）
- 知识点导航数据
- 学习进度保存与恢复
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlmodel import Session, select, func
from pydantic import BaseModel, Field
from pathlib import Path

from app.core.exceptions import unified_response
from app.core.security import get_current_user, teacher_student_allowed
from app.models.database import get_session
from app.models.course_model import Course, CourseScript, ScriptNode, ScriptNodeType
from app.models.video_generation_model import VideoGenerationTask, GenerationStatus
from app.models.progress_model import LearningProgress, LearningStatus
from app.models.mapping_model import KnowledgePageMap
from app.core.config import settings

router = APIRouter(tags=["分屏播放器"])

logger = logging.getLogger(__name__)


class PlayerInitData(BaseModel):
    """播放器初始化数据响应模型"""
    course_id: int
    course_title: str
    script_id: int
    total_duration: float = Field(description="总时长(秒)")
    total_nodes: int = Field(description="总节点数")
    nodes: List[dict] = Field(description="脚本节点列表")
    video_base_url: str = Field(description="视频基础URL")
    ppt_pages: Optional[List[dict]] = Field(default=None, description="PPT逐页内容（用于右侧显示）")
    slide_images: Optional[List[dict]] = Field(default=None, description="PPT逐页图片URL列表")
    saved_progress: Optional[dict] = Field(default=None, description="已保存的学习进度")


class KnowledgePoint(BaseModel):
    """知识点导航项"""
    node_id: int
    chapter_id: Optional[str] = None
    title: str
    timestamp_start: float
    timestamp_end: float
    node_index: int
    is_completed: bool = False


class ProgressSaveRequest(BaseModel):
    """进度保存请求体"""
    course_id: int = Field(..., description="课程ID")
    current_node_id: Optional[int] = Field(None, description="当前节点ID")
    current_timestamp: float = Field(..., description="当前播放时间(秒)")
    current_page: int = Field(1, description="当前PPT页码")
    completed_nodes: List[int] = Field(default=[], description="已完成节点ID列表")


@router.get("/init/{course_id}", response_model=PlayerInitData)
async def get_player_init_data(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_student_allowed),
):
    """
    获取分屏播放器初始化数据

    返回播放器所需的全部数据：
    - 课程基本信息
    - 脚本节点列表（包含时间戳、页码、知识点ID）
    - 各节点的数字人视频URL
    - 已保存的学习进度（用于断点续播）

    前端收到此数据后即可渲染完整的分屏播放界面
    """
    try:
        user_id = int(current_user["user_id"])

        # 1. 查询课程信息
        course = session.get(Course, course_id)
        if not course:
            raise HTTPException(status_code=404, detail="课程不存在")

        # 2. 查询当前激活的脚本版本
        active_script = session.exec(
            select(CourseScript)
            .where(
                CourseScript.course_id == course_id,
                CourseScript.is_active == True,
            )
            .order_by(CourseScript.version.desc())
        ).first()

        if not active_script:
            raise HTTPException(status_code=404, detail="课程暂无可用脚本")

        # 3. 查询所有脚本节点（按node_index排序）
        nodes = session.exec(
            select(ScriptNode)
            .where(ScriptNode.script_id == active_script.id)
            .order_by(ScriptNode.node_index.asc())
        ).all()

        if not nodes:
            raise HTTPException(status_code=404, detail="脚本暂无节点数据")

        # 4. 批量查询各节点的视频生成任务
        node_ids = [node.id for node in nodes]
        video_tasks = {}
        if node_ids:
            tasks = session.exec(
                select(VideoGenerationTask)
                .where(
                    VideoGenerationTask.node_id.in_(node_ids),
                    VideoGenerationTask.status == GenerationStatus.COMPLETED,
                )
            ).all()
            video_tasks = {task.node_id: task for task in tasks}

        # 5. 查询页码映射表（优先使用F5映射引擎的精确数据）
        page_maps = session.exec(
            select(KnowledgePageMap)
            .where(KnowledgePageMap.course_id == course_id)
        ).all()
        page_map_dict = {m.node_id: m for m in page_maps}

        # 6. 构建节点数据列表
        nodes_data = []
        for node in nodes:
            task = video_tasks.get(node.id)
            video_url = None
            if task and task.dh_video_path:
                import os
                filename = os.path.basename(task.dh_video_path)
                video_url = f"/api/v1/video/stream/{filename}"

            # 优先使用KnowledgePageMap的页码（F5映射引擎数据）
            mapping = page_map_dict.get(node.id)
            if mapping:
                page_start = mapping.page_start
                page_end = mapping.page_end
            else:
                page_start = node.page_start
                page_end = node.page_end

            node_dict = {
                "id": node.id,
                "node_index": node.node_index,
                "node_type": node.node_type.value,
                "title": node.title or f"知识点 {node.node_index}",
                "content": node.content[:200] + "..." if len(node.content) > 200 else node.content,
                "chapter_id": node.chapter_id,
                "timestamp_start": node.timestamp_start,
                "timestamp_end": node.timestamp_end,
                "duration": node.duration,
                "page_start": page_start,
                "page_end": page_end,
                "is_key_point": node.is_key_point,
                "video_url": video_url,
                "status": "completed" if task else "pending",
            }
            nodes_data.append(node_dict)

        # 7. 查询已保存的学习进度
        saved_progress = None
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        if progress:
            saved_progress = {
                "current_node_id": progress.current_node_id,
                "current_node_index": progress.current_node_index,
                "current_timestamp": progress.current_timestamp,
                "current_page": progress.current_page,
                "completion_rate": progress.completion_rate,
                "total_learning_time": progress.total_learning_time,
                "last_accessed_at": progress.last_accessed_at.isoformat() if progress.last_accessed_at else None,
            }

        # 7. 获取PPT逐页内容（用于右侧PPT显示）
        ppt_pages = []
        try:
            from app.services.mapping_service import MappingService
            ppt_pages = MappingService.get_page_texts(session, course_id)
        except Exception as e:
            logger.warning(f"[Player] 获取PPT页面内容失败: {e}")

        # 8. 构建PPT逐页图片URL列表
        slide_images = None
        if course.pdf_file_path or course.source_file_path:
            from app.common.slide_converter import is_pdf_file, get_or_create_pdf
            source_path = course.source_file_path
            pdf_path = course.pdf_file_path

            if pdf_path and Path(pdf_path).exists():
                effective_pdf = pdf_path
            elif source_path and Path(source_path).exists():
                if is_pdf_file(source_path):
                    effective_pdf = source_path
                else:
                    effective_pdf = get_or_create_pdf(source_path)
                    if effective_pdf:
                        course.pdf_file_path = effective_pdf
                        session.add(course)
                        session.commit()
            else:
                effective_pdf = None

            if effective_pdf:
                try:
                    import fitz
                    doc = fitz.open(str(effective_pdf))
                    total_slide_pages = len(doc)
                    doc.close()

                    slide_images = []
                    for i in range(total_slide_pages):
                        slide_images.append({
                            "page": i + 1,
                            "url": f"/api/v1/document/course/{course_id}/slide/{i + 1}",
                        })
                    logger.info(f"[Player] 课程 {course_id} 共 {total_slide_pages} 页PPT图片")
                except Exception as e:
                    logger.warning(f"[Player] 获取PDF页数失败: {e}")

        # 9. 返回完整数据
        return PlayerInitData(
            course_id=course_id,
            course_title=course.title,
            script_id=active_script.id,
            total_duration=active_script.audio_duration or sum(n.duration for n in nodes),
            total_nodes=len(nodes),
            nodes=nodes_data,
            video_base_url="/api/v1/video/stream/",
            ppt_pages=ppt_pages if ppt_pages else None,
            slide_images=slide_images,
            saved_progress=saved_progress,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取播放器数据失败: {str(e)}")


@router.get("/knowledge-points/{course_id}")
async def get_knowledge_points(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_student_allowed),
):
    """
    获取知识点导航条数据

    返回所有知识点的简要信息用于底部导航条显示：
    - 知识点标题
    - 时间范围
    - 完成状态
    """
    try:
        # 查询激活脚本
        active_script = session.exec(
            select(CourseScript)
            .where(
                CourseScript.course_id == course_id,
                CourseScript.is_active == True,
            )
        ).first()

        if not active_script:
            return unified_response(404, "课程暂无脚本", None)

        # 查询所有节点
        nodes = session.exec(
            select(ScriptNode)
            .where(ScriptNode.script_id == active_script.id)
            .order_by(ScriptNode.node_index.asc())
        ).all()

        # 查询学习进度（获取已完成节点）
        user_id = int(current_user["user_id"])
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        completed_nodes = []
        if progress:
            # 可以从NodeProgress表查询更详细的完成状态
            from app.models.progress_model import NodeProgress
            node_progress_list = session.exec(
                select(NodeProgress)
                .where(
                    NodeProgress.progress_id == progress.id,
                    NodeProgress.is_completed == True,
                )
            ).all()
            completed_nodes = [np.node_id for np in node_progress_list]

        # 构建知识点列表
        knowledge_points = []
        for node in nodes:
            kp = KnowledgePoint(
                node_id=node.id,
                chapter_id=node.chapter_id,
                title=node.title or f"知识点{node.node_index}",
                timestamp_start=node.timestamp_start,
                timestamp_end=node.timestamp_end,
                node_index=node.node_index,
                is_completed=node.id in completed_nodes,
            )
            knowledge_points.append(kp.dict())

        return unified_response(200, "获取成功", {
            "knowledge_points": knowledge_points,
            "total_count": len(knowledge_points),
            "completed_count": len(completed_nodes),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(500, f"获取失败: {str(e)}", None)


@router.post("/progress/save")
async def save_player_progress(
    request: ProgressSaveRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    保存播放器学习进度

    用于断点续播功能：
    - 定期自动保存（建议每5秒或暂停时）
    - 记录当前播放位置、当前节点、已完成节点列表
    """
    try:
        user_id = int(current_user["user_id"])

        # 查询或创建学习进度记录
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == request.course_id,
            )
        ).first()

        if not progress:
            # 创建新记录
            course = session.get(Course, request.course_id)
            if not course:
                return unified_response(404, "课程不存在", None)

            progress = LearningProgress(
                user_id=user_id,
                course_id=request.course_id,
                status=LearningStatus.IN_PROGRESS,
                started_at=datetime.utcnow(),
            )
            session.add(progress)

        # 更新进度数据
        progress.current_node_id = request.current_node_id
        progress.current_timestamp = request.current_timestamp
        progress.current_page = request.current_page

        # 计算完成率
        if request.completed_nodes:
            progress.completed_nodes = len(request.completed_nodes)

            # 获取总节点数
            active_script = session.exec(
                select(CourseScript)
                .where(
                    CourseScript.course_id == request.course_id,
                    CourseScript.is_active == True,
                )
            ).first()
            if active_script:
                total_nodes = session.exec(
                    select(func.count(ScriptNode.id))
                    .where(ScriptNode.script_id == active_script.id)
                ).one()
                progress.total_nodes = total_nodes
                progress.completion_rate = len(request.completed_nodes) / max(total_nodes, 1)

        progress.status = LearningStatus.IN_PROGRESS
        progress.last_accessed_at = datetime.utcnow()
        progress.updated_at = datetime.utcnow()

        session.commit()
        session.refresh(progress)

        return unified_response(200, "进度保存成功", {
            "progress_id": progress.id,
            "saved_timestamp": request.current_timestamp,
            "completion_rate": progress.completion_rate,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(500, f"保存失败: {str(e)}", None)


@router.get("/progress/{course_id}")
async def get_player_progress(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取播放器学习进度

    用于断点续播：进入播放器页面时调用此接口恢复上次的播放位置
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
            return unified_response(200, "暂无学习记录", {
                "has_progress": False,
                "current_timestamp": 0.0,
                "current_page": 1,
                "current_node_index": 0,
            })

        return unified_response(200, "获取成功", {
            "has_progress": True,
            "progress_id": progress.id,
            "current_node_id": progress.current_node_id,
            "current_node_index": progress.current_node_index,
            "current_timestamp": progress.current_timestamp,
            "current_page": progress.current_page,
            "completion_rate": progress.completion_rate,
            "total_learning_time": progress.total_learning_time,
            "status": progress.value if hasattr(progress, 'value') else progress.status,
            "last_accessed_at": progress.last_accessed_at.isoformat() if progress.last_accessed_at else None,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(500, f"获取失败: {str(e)}", None)
