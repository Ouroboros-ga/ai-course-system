"""
老师素材管理API
提供人脸视频、参考音频等数字人素材的上传、查询、删除、设为默认等操作
"""

import os
import uuid
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session, select
from PIL import Image

from app.core.config import settings
from app.core.exceptions import unified_response
from app.core.security import get_current_user, teacher_only
from app.models.database import get_session
from app.models.asset_model import TeacherAsset, AssetType

router = APIRouter(tags=["素材管理"])

# 素材存储根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
ASSET_ROOT = BASE_DIR / settings.ASSET_STORAGE_PATH

# 允许的文件类型
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"}
ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/mp3", "audio/x-wav", "audio/ogg"}
ALLOWED_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".avi"}
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac"}


def _ensure_asset_dir():
    """确保素材存储目录存在"""
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)


def _get_safe_path(filename: str) -> str:
    """生成安全的存储文件名，避免路径遍历和重名"""
    ext = Path(filename).suffix.lower()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    return safe_name


def _extract_duration(file_path: Path) -> float:
    """使用 ffprobe 提取音视频时长（秒），失败返回 0.0"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def _extract_video_thumbnail(video_path: Path, output_path: Path) -> Optional[str]:
    """使用 ffmpeg 提取视频第1秒帧作为缩略图，返回缩略图相对路径或 None"""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i", str(video_path),
                "-ss", "00:00:01",
                "-vframes", "1",
                "-q:v", "2",
                str(output_path),
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and output_path.exists():
            return str(output_path)
    except Exception:
        pass
    return None


def _validate_file(file: UploadFile, asset_type: AssetType):
    """校验上传文件类型和大小"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = Path(file.filename).suffix.lower()
    content_type = file.content_type or ""

    if asset_type == AssetType.FACE_VIDEO:
        if ext not in ALLOWED_VIDEO_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"人脸视频仅支持 {', '.join(ALLOWED_VIDEO_EXTS)} 格式",
            )
        if content_type and content_type not in ALLOWED_VIDEO_TYPES:
            # 部分浏览器上传mp4时content_type可能为空，以扩展名为准
            if ext not in ALLOWED_VIDEO_EXTS:
                raise HTTPException(status_code=400, detail="不支持的视频格式")

    elif asset_type == AssetType.REF_AUDIO:
        if ext not in ALLOWED_AUDIO_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"参考音频仅支持 {', '.join(ALLOWED_AUDIO_EXTS)} 格式",
            )

    return True


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(..., description="素材文件"),
    asset_type: AssetType = Form(..., description="素材类型：face_video/ref_audio/other"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    上传老师素材（人脸视频/参考音频）

    - 人脸视频：mp4/webm/mov，最大200MB
    - 参考音频：mp3/wav/ogg，最大50MB
    """
    _ensure_asset_dir()

    # 校验文件类型
    _validate_file(file, asset_type)

    user_id = int(current_user["user_id"])

    max_size = (
        settings.MAX_VIDEO_ASSET_SIZE_MB * 1024 * 1024
        if asset_type == AssetType.FACE_VIDEO
        else settings.MAX_AUDIO_ASSET_SIZE_MB * 1024 * 1024
    )
    max_mb = settings.MAX_VIDEO_ASSET_SIZE_MB if asset_type == AssetType.FACE_VIDEO else settings.MAX_AUDIO_ASSET_SIZE_MB

    # 流式写入文件，边读边写，避免全量读入内存
    safe_name = _get_safe_path(file.filename)
    teacher_dir = ASSET_ROOT / str(user_id)
    teacher_dir.mkdir(parents=True, exist_ok=True)
    file_path = teacher_dir / safe_name

    file_size = 0
    with open(file_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)  # 每次读1MB
            if not chunk:
                break
            file_size += len(chunk)
            if file_size > max_size:
                f.close()
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=400,
                    detail=f"文件大小超过限制，{asset_type.value}类型最大允许 {max_mb}MB",
                )
            f.write(chunk)

    # 提取音视频时长
    duration = _extract_duration(file_path)

    # 视频素材生成缩略图
    thumbnail_url = None
    if asset_type == AssetType.FACE_VIDEO:
        thumb_name = f"{safe_name.rsplit('.', 1)[0]}_thumb.jpg"
        thumb_path = teacher_dir / thumb_name
        thumb_result = _extract_video_thumbnail(file_path, thumb_path)
        if thumb_result:
            thumbnail_url = str(thumb_path)

    # 检查该老师同类型是否已有素材，如果没有则自动设为默认
    existing_count = session.exec(
        select(TeacherAsset).where(
            TeacherAsset.teacher_id == user_id,
            TeacherAsset.asset_type == asset_type,
        )
    ).all()
    is_default = len(existing_count) == 0

    # 创建数据库记录
    asset = TeacherAsset(
        teacher_id=user_id,
        asset_type=asset_type,
        file_name=file.filename,
        file_path=str(file_path),
        file_size=file_size,
        mime_type=file.content_type or "",
        duration=duration,
        thumbnail_url=thumbnail_url,
        is_default=is_default,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    return unified_response(
        code=200,
        message="素材上传成功",
        data={
            "id": asset.id,
            "asset_type": asset.asset_type.value,
            "file_name": asset.file_name,
            "file_size": asset.file_size,
            "is_default": asset.is_default,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
        },
    )


@router.get("/")
async def list_assets(
    asset_type: Optional[AssetType] = Query(None, description="按素材类型筛选"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取当前老师的素材列表，支持按类型筛选
    """
    user_id = int(current_user["user_id"])

    query = select(TeacherAsset).where(TeacherAsset.teacher_id == user_id)
    if asset_type:
        query = query.where(TeacherAsset.asset_type == asset_type)
    query = query.order_by(TeacherAsset.created_at.desc())

    assets = session.exec(query).all()

    assets_data = []
    for a in assets:
        assets_data.append({
            "id": a.id,
            "asset_type": a.asset_type.value,
            "file_name": a.file_name,
            "file_size": a.file_size,
            "mime_type": a.mime_type,
            "duration": a.duration,
            "thumbnail_url": a.thumbnail_url,
            "is_default": a.is_default,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })

    return unified_response(
        code=200,
        message="获取素材列表成功",
        data={"assets": assets_data, "total": len(assets_data)},
    )


@router.get("/{asset_id}/preview")
async def preview_asset(
    asset_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    预览/下载素材文件，支持流式播放和Range请求
    """
    asset = session.get(TeacherAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")

    # 权限校验：只能预览自己的素材
    user_id = int(current_user["user_id"])
    if asset.teacher_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该素材")

    file_path = Path(asset.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="素材文件不存在")

    file_size = file_path.stat().st_size

    # 判断媒体类型
    media_type = asset.mime_type or "application/octet-stream"
    if asset.asset_type == AssetType.FACE_VIDEO:
        media_type = "video/mp4"
    elif asset.asset_type == AssetType.REF_AUDIO:
        media_type = "audio/mpeg"

    async def iterfile():
        with open(file_path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                yield chunk

    return StreamingResponse(
        iterfile(),
        media_type=media_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{asset.file_name}"',
        },
    )


@router.put("/{asset_id}/default")
async def set_default_asset(
    asset_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    将指定素材设为该类型的默认素材（同类型只能有一个默认）
    """
    user_id = int(current_user["user_id"])

    asset = session.get(TeacherAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")

    if asset.teacher_id != user_id:
        raise HTTPException(status_code=403, detail="无权操作该素材")

    # 取消同类型旧的默认
    old_defaults = session.exec(
        select(TeacherAsset).where(
            TeacherAsset.teacher_id == user_id,
            TeacherAsset.asset_type == asset.asset_type,
            TeacherAsset.is_default == True,
        )
    ).all()
    for old in old_defaults:
        old.is_default = False
        session.add(old)

    # 设置新默认
    asset.is_default = True
    asset.updated_at = datetime.utcnow()
    session.add(asset)
    session.commit()

    return unified_response(code=200, message="已设为默认素材", data={"id": asset.id})


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    删除素材（同时删除物理文件）
    """
    user_id = int(current_user["user_id"])

    asset = session.get(TeacherAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")

    if asset.teacher_id != user_id:
        raise HTTPException(status_code=403, detail="无权操作该素材")

    # 检查素材是否被课程脚本节点引用（通过 extra_data 中的 asset_id 关联）
    from app.models.course_model import ScriptNode
    referenced_nodes = session.exec(
        select(ScriptNode).where(
            ScriptNode.extra_data.isnot(None),
        )
    ).all()
    for node in referenced_nodes:
        if node.extra_data and node.extra_data.get("asset_id") == asset_id:
            raise HTTPException(
                status_code=409,
                detail=f"该素材已被课程脚本节点引用（节点ID: {node.id}），请先解除引用后再删除",
            )

    # 删除物理文件
    file_path = Path(asset.file_path)
    if file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            pass  # 文件删除失败不影响数据库记录删除

    # 如果删除的是默认素材，自动将同类型第一个设为默认
    was_default = asset.is_default
    session.delete(asset)
    session.commit()

    if was_default:
        new_default = session.exec(
            select(TeacherAsset).where(
                TeacherAsset.teacher_id == user_id,
                TeacherAsset.asset_type == asset.asset_type,
            ).order_by(TeacherAsset.created_at.desc())
        ).first()
        if new_default:
            new_default.is_default = True
            session.add(new_default)
            session.commit()

    return unified_response(code=200, message="素材已删除", data=None)
