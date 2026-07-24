"""G8 媒体时间轴与数字人 API

外部完整课程视频可按时间轴驱动 PPT。
讲稿可作为真实字幕/讲解内容展示。
"""
from __future__ import annotations

from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.media_timeline_model import (
    MediaAsset,
    MediaTimelineCue,
    CueType,
    StorageBackend,
    DigitalHumanPreset,
)
from app.services.course_access_service import require_course_permission
from app.services.media_timeline_service import (
    create_timeline_cues_from_node,
    get_node_timeline,
    get_course_timeline,
    serialize_cue,
    register_media_asset,
)

router = APIRouter(tags=["G8 媒体时间轴"])


class CreateCuesRequest(BaseModel):
    node_id: int
    script_content: str
    audio_duration: float
    ppt_pages: list[int] = []
    video_object_key: Optional[str] = None
    audio_object_key: Optional[str] = None


class RegisterAssetRequest(BaseModel):
    object_key: str
    asset_type: str  # video/audio/subtitle/thumbnail
    local_path: Optional[str] = None
    mime_type: str = ""
    size_bytes: int = 0
    duration_seconds: float = 0.0


@router.get("/course/{course_id}/timeline")
async def get_timeline(
    course_id: int,
    node_id: Optional[int] = Query(None, description="按节点筛选"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取课程时间轴

    外部完整课程视频可按时间轴驱动 PPT。
    """
    require_course_permission(session, current_user, course_id, "course.content.read")

    if node_id:
        cues = get_node_timeline(session, course_id, node_id)
        return unified_response(
            code=200, message="获取节点时间轴成功",
            data={"items": [serialize_cue(c, session) for c in cues], "total": len(cues)},
        )
    else:
        timeline = get_course_timeline(session, course_id)
        return unified_response(
            code=200, message="获取课程时间轴成功",
            data={"items": timeline, "total": len(timeline)},
        )


@router.post("/course/{course_id}/cues")
async def create_cues(
    course_id: int,
    payload: CreateCuesRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """为节点创建时间轴提示

    讲稿可作为真实字幕/讲解内容展示，不再只是 220 字节点摘要。
    """
    require_course_permission(session, current_user, course_id, "course.media.generate")

    cues = create_timeline_cues_from_node(
        session,
        course_id=course_id,
        script_id=0,  # 由调用方补充
        node_id=payload.node_id,
        script_content=payload.script_content,
        audio_duration=payload.audio_duration,
        ppt_pages=payload.ppt_pages,
        video_object_key=payload.video_object_key,
        audio_object_key=payload.audio_object_key,
    )

    return unified_response(
        code=200, message=f"创建 {len(cues)} 个时间轴提示",
        data={"items": [serialize_cue(c, session) for c in cues], "total": len(cues)},
    )


@router.post("/assets")
async def register_asset(
    payload: RegisterAssetRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """注册媒体资产（抽象存储）

    使用抽象 object_key，未来可平滑迁移 OSS。
    """
    asset = register_media_asset(
        session,
        object_key=payload.object_key,
        asset_type=payload.asset_type,
        local_path=payload.local_path,
        mime_type=payload.mime_type,
        size_bytes=payload.size_bytes,
        duration_seconds=payload.duration_seconds,
    )

    return unified_response(
        code=200, message="媒体资产已注册",
        data={
            "id": asset.id,
            "object_key": asset.object_key,
            "asset_type": asset.asset_type,
            "backend": asset.backend.value,
            "url": asset.resolve_url(),
        },
    )


@router.get("/assets/{object_key}")
async def get_asset(
    object_key: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取媒体资产信息"""
    asset = session.exec(
        select(MediaAsset).where(MediaAsset.object_key == object_key)
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="媒体资产不存在")

    return unified_response(
        code=200, message="获取媒体资产成功",
        data={
            "id": asset.id,
            "object_key": asset.object_key,
            "asset_type": asset.asset_type,
            "backend": asset.backend.value,
            "url": asset.resolve_url(),
            "mime_type": asset.mime_type,
            "size_bytes": asset.size_bytes,
            "duration_seconds": asset.duration_seconds,
            "content_hash": asset.content_hash,
        },
    )


@router.get("/digital-human/presets")
async def list_dh_presets(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出可用的数字人预设（CPU 路线）"""
    presets = [
        {
            "preset": DigitalHumanPreset.DH_LIVE_MINI.value,
            "name": "DH_live_mini / MiniMates",
            "description": "首选：开源、纯 CPU 实时推理数字人",
            "cpu_only": True,
            "status": "candidate",
        },
        {
            "preset": DigitalHumanPreset.LITE_AVATAR.value,
            "name": "LiteAvatar",
            "description": "对照：CPU 30fps、MIT 许可证",
            "cpu_only": True,
            "status": "candidate",
        },
        {
            "preset": DigitalHumanPreset.DUIL_AVATAR.value,
            "name": "Duix.Avatar (现有)",
            "description": "现有 GPU 路线，成本高压力大",
            "cpu_only": False,
            "status": "legacy",
        },
    ]
    return unified_response(
        code=200, message="获取数字人预设成功",
        data={"presets": presets},
    )
