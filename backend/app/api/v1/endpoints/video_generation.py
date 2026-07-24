"""
视频生成API接口
F5视频生成管线：脚本节点 → TTS合成 → 数字人视频
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.course_model import Course, CourseScript, ScriptNode
from app.models.video_generation_model import VideoGenerationTask, GenerationStatus
from app.services.video_generation_service import video_generation_service
from app.common.digital_human_client import digital_human_client, DigitalHumanError
from app.platform.adapters.registry import get_digital_human_adapter
from app.services.course_access_service import CourseAccessContext, course_permission, require_course_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["视频生成"])


class GenerateRequest(BaseModel):
    """视频生成请求"""
    node_ids: Optional[List[int]] = None  # 指定节点ID列表，为空则生成全部
    force: bool = False  # 是否强制重新生成


@router.post("/course/{course_id}/generate")
async def generate_course_videos(
    course_id: int,
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("course.media.generate")),
):
    """
    批量生成课程视频（异步后台任务）

    流程：遍历脚本节点 → TTS合成语音 → 数字人视频生成
    """
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    # 检查数字人服务可用性
    health_result = await get_digital_human_adapter(digital_human_client).check_health()
    if not health_result.success:
        raise HTTPException(
            status_code=503,
            detail="数字人服务不可用，请确认服务已启动"
        )

    # 查询节点数量
    script = session.exec(
        select(CourseScript).where(
            CourseScript.course_id == course_id,
            CourseScript.is_active == True,
        )
    ).first()
    if not script:
        raise HTTPException(status_code=404, detail="课程没有激活的脚本")

    node_query = select(ScriptNode).where(ScriptNode.script_id == script.id)
    if request.node_ids:
        node_query = node_query.where(ScriptNode.id.in_(request.node_ids))
    nodes = session.exec(node_query).all()

    if not nodes:
        raise HTTPException(status_code=400, detail="没有可生成的脚本节点")

    # 后台异步执行生成
    async def _generate():
        from app.models.database import engine
        from sqlmodel import Session as SQLModelSession
        bg_session = SQLModelSession(engine)
        try:
            await video_generation_service.generate_course_videos(
                course_id=course_id,
                session=bg_session,
                node_ids=request.node_ids,
                force=request.force,
            )
        except Exception as e:
            logger.error(f"[视频生成] 后台任务异常: {e}")
        finally:
            bg_session.close()

    background_tasks.add_task(_generate)

    return unified_response(
        code=200,
        message=f"已提交视频生成任务，共{len(nodes)}个节点",
        data={
            "course_id": course_id,
            "total_nodes": len(nodes),
            "status": "processing",
        },
    )


@router.post("/node/{node_id}/generate")
async def generate_node_video(
    node_id: int,
    force: bool = Query(False, description="是否强制重新生成"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    为单个脚本节点生成数字人视频（同步）

    流程：TTS合成语音 → 数字人视频生成
    """
    # 查询节点
    node = session.get(ScriptNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="脚本节点不存在")

    script = session.get(CourseScript, node.script_id)
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")

    require_course_permission(session, current_user, script.course_id, "course.media.generate")

    # 检查数字人服务
    health_result = await get_digital_human_adapter(digital_human_client).check_health()
    if not health_result.success:
        raise HTTPException(
            status_code=503,
            detail="数字人服务不可用，请确认服务已启动"
        )

    try:
        task = await video_generation_service.generate_node_video(
            node_id=node_id,
            session=session,
            force=force,
        )
        return unified_response(
            code=200,
            message="视频生成完成" if task.status == GenerationStatus.COMPLETED else "视频生成失败",
            data=_task_to_dict(task),
        )
    except (TTSError, DigitalHumanError, ValueError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[视频生成] 节点{node_id}生成异常: {e}")
        raise HTTPException(status_code=500, detail=f"视频生成异常: {str(e)}")


@router.get("/task/{task_id}")
async def get_task_status(
    task_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """查询视频生成任务状态"""
    task = session.get(VideoGenerationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    require_course_permission(session, current_user, task.course_id, "course.content.read")

    return unified_response(
        code=200,
        message="查询成功",
        data=_task_to_dict(task),
    )


@router.get("/course/{course_id}/tasks")
async def get_course_tasks(
    course_id: int,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("course.content.read")),
):
    """查询课程所有视频生成任务"""
    tasks = video_generation_service.get_course_tasks(course_id, session)

    return unified_response(
        code=200,
        message="查询成功",
        data={
            "course_id": course_id,
            "tasks": [_task_to_dict(t) for t in tasks],
            "total": len(tasks),
            "completed": sum(1 for t in tasks if t.status == GenerationStatus.COMPLETED),
            "failed": sum(1 for t in tasks if t.status == GenerationStatus.FAILED),
            "pending": sum(1 for t in tasks if t.status in (
                GenerationStatus.PENDING,
                GenerationStatus.TTS_SYNTHESIZING,
                GenerationStatus.TTS_COMPLETED,
                GenerationStatus.DH_GENERATING,
            )),
        },
    )


@router.get("/health")
async def check_digital_human_health():
    """检查数字人服务健康状态"""
    adapter = get_digital_human_adapter(digital_human_client)
    health_result = await adapter.check_health()
    available = health_result.success
    api_url = getattr(adapter.client, "api_url", None) or getattr(adapter.client, "base_url", "")
    return unified_response(
        code=200 if available else 503,
        message="数字人服务可用" if available else "数字人服务不可用",
        data={"available": available, "api_url": api_url},
    )


def _task_to_dict(task: VideoGenerationTask) -> dict:
    """将任务对象转为字典"""
    return {
        "id": task.id,
        "course_id": task.course_id,
        "node_id": task.node_id,
        "status": task.status.value,
        "audio_path": task.audio_path,
        "audio_duration": task.audio_duration,
        "voice": task.voice,
        "face_video_asset_id": task.face_video_asset_id,
        "dh_video_path": task.dh_video_path,
        "dh_generation_time": task.dh_generation_time,
        "final_video_path": task.final_video_path,
        "error_message": task.error_message,
        "retry_count": task.retry_count,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


# 导入TTSError用于异常处理
from app.common.tts_client import TTSError
