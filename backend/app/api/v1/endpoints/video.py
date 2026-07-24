"""
视频文件服务API
提供本地视频文件的访问和播放
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
import httpx

from app.core.security import get_current_user
from app.core.exceptions import unified_response
from app.core.config import settings
from sqlmodel import Session, select
from app.models.database import get_session
from app.models.video_generation_model import VideoGenerationTask
from app.services.course_access_service import require_course_permission

router = APIRouter(tags=["视频服务"])

# 视频文件根目录 - 使用相对路径，支持跨平台
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
VIDEO_ROOT = BASE_DIR / settings.VIDEO_STORAGE_PATH
TEMP_VIDEO_ROOT = BASE_DIR / settings.TEMP_VIDEO_STORAGE_PATH

# 确保目录存在
try:
    VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
except OSError as e:
    import logging
    logging.warning(f"无法创建视频目录: {e}")


def get_video_path(filename: str) -> Optional[Path]:
    """获取视频文件的完整路径"""
    # 防止路径遍历攻击
    safe_filename = os.path.basename(filename)
    if safe_filename != filename:
        raise HTTPException(status_code=400, detail="无效的文件名")

    # 优先从正式目录查找
    video_path = VIDEO_ROOT / safe_filename
    if video_path.exists():
        return video_path

    # 从临时目录查找
    temp_path = TEMP_VIDEO_ROOT / safe_filename
    if temp_path.exists():
        return temp_path

    return None


def _require_video_course_access(session: Session, current_user: dict, filename: str) -> None:
    task = session.exec(select(VideoGenerationTask).where(
        VideoGenerationTask.dh_video_path.is_not(None)
    )).all()
    matching = next((item for item in task if item.dh_video_path and os.path.basename(item.dh_video_path) == filename), None)
    if matching is None:
        raise HTTPException(status_code=404, detail="Video is not bound to a course task")
    require_course_permission(session, current_user, matching.course_id, "course.content.read")


@router.get("/stream/{filename}")
async def stream_video(
    filename: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    流式播放视频文件

    Args:
        filename: 视频文件名（支持.mp4等格式）

    Returns:
        视频文件流
    """
    _require_video_course_access(session, current_user, filename)
    video_path = get_video_path(filename)

    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    # 获取文件大小
    file_size = video_path.stat().st_size

    async def iterfile():
        with open(video_path, "rb") as f:
            while chunk := f.read(1024 * 1024):  # 1MB chunks
                yield chunk

    return StreamingResponse(
        iterfile(),
        media_type="video/mp4",
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{filename}"',
        }
    )


@router.get("/file/{filename}")
async def get_video_file(
    filename: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取视频文件（完整下载）

    Args:
        filename: 视频文件名

    Returns:
        视频文件
    """
    _require_video_course_access(session, current_user, filename)
    video_path = get_video_path(filename)

    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    return FileResponse(
        path=video_path,
        filename=filename,
        media_type="video/mp4",
    )


@router.get("/list")
async def list_videos(
    current_user: dict = Depends(get_current_user),
):
    """
    列出所有可用的本地视频文件

    Returns:
        视频文件列表
    """
    videos = []

    for root_dir in [VIDEO_ROOT, TEMP_VIDEO_ROOT]:
        if root_dir.exists():
            for file in root_dir.iterdir():
                if file.suffix.lower() in ['.mp4', '.avi', '.mov', '.mkv']:
                    videos.append({
                        "filename": file.name,
                        "size": file.stat().st_size,
                        "url": f"/api/v1/video/stream/{file.name}",
                    })

    return unified_response(200, "success", {"videos": videos})


@router.get("/remote")
async def play_remote_video(
    url: str = Query(..., description="远程视频URL"),
    current_user: dict = Depends(get_current_user),
):
    """
    播放远程视频（代理转发）

    Args:
        url: 远程视频的URL地址

    Returns:
        视频流
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, follow_redirects=True)

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"远程视频获取失败: {response.status_code}"
                )

            # 获取内容类型
            content_type = response.headers.get("content-type", "video/mp4")

            return StreamingResponse(
                response.aiter_bytes(),
                media_type=content_type,
                headers={
                    "Content-Length": response.headers.get("content-length", ""),
                    "Accept-Ranges": "bytes",
                }
            )

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="远程视频加载超时")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"远程视频访问失败: {str(e)}")


@router.post("/upload")
async def upload_video(
    file_url: str = Query(..., description="视频文件的URL或路径"),
    current_user: dict = Depends(get_current_user),
):
    """
    添加视频到本地目录（通过URL或路径）

    Args:
        file_url: 视频文件的URL或绝对路径

    Returns:
        视频信息
    """
    import shutil

    # 如果是本地路径
    source_path = Path(file_url)

    # 处理URL下载
    if str(file_url).startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(file_url, follow_redirects=True)

                if response.status_code != 200:
                    return unified_response(400, "远程视频下载失败", None)

                # 生成文件名
                filename = source_path.name or f"video_{int(__import__('time').time())}.mp4"
                save_path = TEMP_VIDEO_ROOT / filename

                # 保存文件
                with open(save_path, "wb") as f:
                    f.write(response.content)

                return unified_response(200, "视频上传成功", {
                    "filename": filename,
                    "size": save_path.stat().st_size,
                    "url": f"/api/v1/video/stream/{filename}",
                })

        except Exception as e:
            return unified_response(500, f"视频上传失败: {str(e)}", None)

    # 如果是本地文件
    elif source_path.exists() and source_path.is_file():
        if source_path.suffix.lower() not in ['.mp4', '.avi', '.mov', '.mkv']:
            return unified_response(400, "不支持的视频格式", None)

        # 复制到临时目录
        filename = source_path.name
        save_path = TEMP_VIDEO_ROOT / filename
        shutil.copy2(source_path, save_path)

        return unified_response(200, "视频添加成功", {
            "filename": filename,
            "size": save_path.stat().st_size,
            "url": f"/api/v1/video/stream/{filename}",
        })

    else:
        return unified_response(404, "文件不存在", None)


@router.get("/info/{filename}")
async def get_video_info(
    filename: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取视频文件信息

    Args:
        filename: 视频文件名

    Returns:
        视频信息
    """
    _require_video_course_access(session, current_user, filename)
    video_path = get_video_path(filename)

    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    stat = video_path.stat()

    return unified_response(200, "success", {
        "filename": filename,
        "size": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "url": f"/api/v1/video/stream/{filename}",
    })
