"""G8 媒体时间轴与数字人 API

外部完整课程视频可按时间轴驱动 PPT。
讲稿可作为真实字幕/讲解内容展示。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.media_timeline_model import (
    MediaAsset,
    MediaTimelineCue,
    CueType,
    DigitalHumanPreset,
)
from app.services.course_access_service import require_course_permission
from app.services.object_storage import LocalStorageProvider, get_object_storage
from app.services.media_timeline_service import (
    create_timeline_cues_from_node,
    get_node_timeline,
    get_course_timeline,
    serialize_cue,
    register_media_asset,
)

router = APIRouter(tags=["G8 媒体时间轴"])


class CreateCuesRequest(BaseModel):
    script_id: int = Field(ge=1)
    node_id: int
    script_content: str = Field(min_length=1, max_length=200_000)
    audio_duration: float = Field(gt=0, le=86_400)
    ppt_pages: list[int] = Field(default_factory=list, max_length=500)
    outline_node_id: Optional[str] = Field(None, max_length=100)
    material_version_id: Optional[str] = Field(None, max_length=100)
    video_object_key: Optional[str] = None
    audio_object_key: Optional[str] = None


class RegisterAssetRequest(BaseModel):
    course_id: int = Field(ge=1)
    object_key: str = Field(min_length=3, max_length=500)
    asset_type: str = Field(pattern="^(video|audio|subtitle|thumbnail)$")
    local_path: Optional[str] = Field(None, max_length=500)
    mime_type: str = Field(default="", max_length=200)
    size_bytes: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=0.0, ge=0, le=86_400)


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

    try:
        cues = create_timeline_cues_from_node(
            session,
            course_id=course_id,
            script_id=payload.script_id,
            node_id=payload.node_id,
            script_content=payload.script_content,
            audio_duration=payload.audio_duration,
            ppt_pages=payload.ppt_pages,
            outline_node_id=payload.outline_node_id,
            material_version_id=payload.material_version_id,
            video_object_key=payload.video_object_key,
            audio_object_key=payload.audio_object_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
    require_course_permission(
        session, current_user, payload.course_id, "course.media.generate"
    )
    for value, label in (
        (payload.object_key, "object_key"),
        (payload.local_path, "local_path"),
    ):
        if value and (
            ".." in Path(value).parts
            or Path(value).is_absolute()
            or ":" in value
            or value.startswith(("/", "\\"))
        ):
            raise HTTPException(status_code=422, detail=f"{label} 必须是安全相对路径")

    existing = session.exec(
        select(MediaAsset).where(MediaAsset.object_key == payload.object_key)
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="object_key 已存在")

    asset = register_media_asset(
        session,
        course_id=payload.course_id,
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


@router.get("/assets/{object_key:path}/content")
async def get_asset_content(
    object_key: str,
    exp: int = Query(..., ge=1),
    sig: str = Query(..., min_length=8, max_length=128),
    scope: str = Query(..., min_length=3, max_length=1000),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """按课程权限读取媒体内容。

    本地 Provider 由应用安全地流式返回；远程 Provider 在完成课程权限校验后
    返回短期预签名 URL。数据库中的 object_key 在迁移前后保持不变。
    """
    storage = get_object_storage()
    # Verify the signed URL before looking up or returning the object.  The
    # canonical scope is included in local signed URLs and is part of the
    # signature; an omitted/modified purpose or course scope therefore fails
    # closed instead of being treated as an unsigned asset request.
    if not isinstance(storage, LocalStorageProvider):
        raise HTTPException(status_code=400, detail="远程对象存储应直接使用 presigned URL")
    signed_scope = _parse_scope(scope)
    if not signed_scope.get("course_id") or not signed_scope.get("purpose"):
        raise HTTPException(status_code=403, detail="媒体签名 scope 缺少课程或用途")
    if not storage.verify_read_signature(
        object_key,
        exp,
        sig,
        signed_scope,
    ):
        raise HTTPException(status_code=403, detail="媒体签名无效或已过期")
    try:
        storage._safe_full_path(object_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="object_key 不安全") from exc

    asset = session.exec(
        select(MediaAsset).where(MediaAsset.object_key == object_key)
    ).first()
    if asset is None or asset.course_id is None:
        raise HTTPException(status_code=404, detail="媒体资产不存在")
    if signed_scope.get("course_id") not in {None, "", str(asset.course_id)}:
        raise HTTPException(status_code=403, detail="媒体签名课程范围不匹配")
    require_course_permission(
        session, current_user, asset.course_id, "course.content.read"
    )
    try:
        file_path = storage._safe_full_path(object_key)
        if not Path(file_path).is_file():
            raise FileNotFoundError(object_key)
        return FileResponse(path=file_path, media_type=asset.mime_type or None, filename=None)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="媒体文件不存在") from exc


def _parse_scope(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    result: dict[str, str] = {}
    for pair in raw.split(";"):
        if "=" not in pair:
            raise HTTPException(status_code=403, detail="媒体签名 scope 无效")
        key, value = pair.split("=", 1)
        if not key or key in result:
            raise HTTPException(status_code=403, detail="媒体签名 scope 无效")
        result[key] = value
    return result


@router.get("/assets/{object_key:path}")
async def get_asset(
    object_key: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取媒体资产信息"""
    asset = session.exec(
        select(MediaAsset).where(MediaAsset.object_key == object_key)
    ).first()
    if not asset or asset.course_id is None:
        raise HTTPException(status_code=404, detail="媒体资产不存在")
    require_course_permission(
        session, current_user, asset.course_id, "course.content.read"
    )

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
