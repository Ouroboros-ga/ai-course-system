"""G8 媒体时间轴服务

将数字人视频、PPT、讲稿和字幕精确同步到同一全局时间轴。
首版优先按课程节点预生成，不把 CPU 推理塞入实时问答请求。
使用抽象 object_key 存储，未来可平滑迁移 OSS。
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Optional, Any

from sqlmodel import Session, select

from app.models.media_timeline_model import (
    MediaAsset,
    MediaTimelineCue,
    CueType,
    StorageBackend,
    DigitalHumanPreset,
)
from app.models.course_model import ScriptNode, CourseScript
from app.models.video_generation_model import VideoGenerationTask, GenerationStatus


def register_media_asset(
    session: Session,
    *,
    course_id: int,
    object_key: str,
    asset_type: str,
    local_path: Optional[str] = None,
    oss_url: Optional[str] = None,
    mime_type: str = "",
    size_bytes: int = 0,
    duration_seconds: float = 0.0,
    content: Optional[bytes] = None,
) -> MediaAsset:
    """注册媒体资产（抽象存储）

    使用抽象 object_key 替代直接文件路径。
    """
    content_hash = ""
    if content:
        content_hash = hashlib.sha256(content).hexdigest()

    asset = MediaAsset(
        course_id=course_id,
        object_key=object_key,
        asset_type=asset_type,
        backend=StorageBackend.LOCAL,
        local_path=local_path,
        oss_url=oss_url,
        mime_type=mime_type,
        size_bytes=size_bytes,
        duration_seconds=duration_seconds,
        content_hash=content_hash,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def create_timeline_cues_from_node(
    session: Session,
    *,
    course_id: int,
    script_id: int,
    node_id: int,
    script_content: str,
    audio_duration: float,
    ppt_pages: list[int],
    outline_node_id: Optional[str] = None,
    material_version_id: Optional[str] = None,
    video_object_key: Optional[str] = None,
    audio_object_key: Optional[str] = None,
) -> list[MediaTimelineCue]:
    """从节点讲稿创建时间轴提示

    将讲稿分段映射到时间轴，每段对应一个 PPT 页、字幕片段和视频段。
    讲稿可作为真实字幕/讲解内容展示，不再只是 220 字节点摘要。
    """
    script = session.get(CourseScript, script_id)
    node = session.get(ScriptNode, node_id)
    if script is None or script.course_id != course_id:
        raise ValueError("讲稿不属于当前课程")
    if node is None or node.script_id != script_id:
        raise ValueError("节点不属于指定课程讲稿")
    if audio_duration <= 0 or audio_duration > 86_400:
        raise ValueError("音频时长超出允许范围")
    for object_key in (video_object_key, audio_object_key):
        if not object_key:
            continue
        asset = session.exec(
            select(MediaAsset).where(
                MediaAsset.course_id == course_id,
                MediaAsset.object_key == object_key,
            )
        ).first()
        if asset is None:
            raise ValueError(f"课程媒体资产不存在: {object_key}")

    previous_cues = list(session.exec(
        select(MediaTimelineCue).where(
            MediaTimelineCue.course_id == course_id,
            MediaTimelineCue.node_id == node_id,
            MediaTimelineCue.is_active == True,
        )
    ).all())
    version_numbers = []
    for previous in previous_cues:
        previous.is_active = False
        session.add(previous)
        if previous.resource_version.startswith("v"):
            try:
                version_numbers.append(int(previous.resource_version[1:]))
            except ValueError:
                pass
    resource_version = f"v{max(version_numbers, default=0) + 1}"

    # 将讲稿按自然段分割
    segments = _split_script_into_segments(script_content, ppt_pages)

    cues: list[MediaTimelineCue] = []
    current_time = 0.0
    total_segments = len(segments)

    if total_segments == 0:
        # 无讲稿时创建单个提示
        segments = [(script_content[:200] if script_content else "", ppt_pages[0] if ppt_pages else None)]

    segment_duration = audio_duration / len(segments) if segments else 0.0

    for i, (text, ppt_page) in enumerate(segments):
        start_time = current_time
        end_time = current_time + segment_duration

        content_hash = hashlib.sha256(text.encode()).hexdigest()[:32]

        cue = MediaTimelineCue(
            course_id=course_id,
            script_id=script_id,
            node_id=node_id,
            cue_index=i,
            start_time=start_time,
            end_time=end_time,
            cue_type=CueType.NARRATION,
            ppt_page=ppt_page,
            subtitle_text=text,
            script_reference=f"node_{node_id}_segment_{i}",
            video_object_key=video_object_key,
            audio_object_key=audio_object_key,
            resource_version=resource_version,
            content_hash=content_hash,
            is_active=True,
            cue_metadata={
                "total_segments": len(segments),
                "segment_index": i,
                "outline_node_id": outline_node_id,
                "material_version_id": material_version_id,
            },
        )
        session.add(cue)
        cues.append(cue)
        current_time = end_time

    session.commit()
    for cue in cues:
        session.refresh(cue)

    return cues


def _split_script_into_segments(script_content: str, ppt_pages: list[int]) -> list[tuple[str, Optional[int]]]:
    """将讲稿分割为时间轴段落

    按 PPT 页标记分割（如"第N页"标记），每段关联对应的 PPT 页码。
    """
    if not script_content:
        return []

    import re
    # 按"第N页"标记分割
    pattern = r'第\s*(\d+)\s*页'
    parts = re.split(pattern, script_content)

    segments: list[tuple[str, Optional[int]]] = []

    if len(parts) <= 1:
        # 无页码标记，整体作为一个段落
        segments.append((script_content.strip(), ppt_pages[0] if ppt_pages else None))
    else:
        # 按页码标记分割
        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                page_num = int(parts[i])
                text = parts[i + 1].strip()
                if text:
                    # 检查页码是否在有效范围内
                    actual_page = page_num if page_num in ppt_pages else (ppt_pages[0] if ppt_pages else None)
                    segments.append((text, actual_page))

        # 处理页码标记前的内容
        if parts[0].strip():
            segments.insert(0, (parts[0].strip(), ppt_pages[0] if ppt_pages else None))

    return segments if segments else [(script_content[:200], ppt_pages[0] if ppt_pages else None)]


def get_node_timeline(
    session: Session,
    course_id: int,
    node_id: int,
) -> list[MediaTimelineCue]:
    """获取节点的时间轴提示列表"""
    return list(session.exec(
        select(MediaTimelineCue).where(
            MediaTimelineCue.course_id == course_id,
            MediaTimelineCue.node_id == node_id,
            MediaTimelineCue.is_active == True,
        ).order_by(MediaTimelineCue.cue_index)
    ).all())


def get_course_timeline(
    session: Session,
    course_id: int,
) -> list[dict[str, Any]]:
    """获取课程完整时间轴

    外部完整课程视频可按时间轴驱动 PPT。
    """
    cues = session.exec(
        select(MediaTimelineCue).where(
            MediaTimelineCue.course_id == course_id,
            MediaTimelineCue.is_active == True,
        ).order_by(MediaTimelineCue.node_id, MediaTimelineCue.cue_index)
    ).all()

    # 解析资产 URL
    result: list[dict[str, Any]] = []
    for cue in cues:
        video_url = None
        audio_url = None
        if cue.video_object_key:
            asset = session.exec(
                select(MediaAsset).where(
                    MediaAsset.course_id == course_id,
                    MediaAsset.object_key == cue.video_object_key,
                )
            ).first()
            if asset:
                video_url = asset.resolve_url()
        if cue.audio_object_key:
            asset = session.exec(
                select(MediaAsset).where(
                    MediaAsset.course_id == course_id,
                    MediaAsset.object_key == cue.audio_object_key,
                )
            ).first()
            if asset:
                audio_url = asset.resolve_url()

        result.append({
            "id": cue.id,
            "course_id": cue.course_id,
            "node_id": cue.node_id,
            "cue_index": cue.cue_index,
            "start_time": cue.start_time,
            "end_time": cue.end_time,
            "cue_type": cue.cue_type.value,
            "ppt_page": cue.ppt_page,
            "material_version_id": (cue.cue_metadata or {}).get("material_version_id"),
            "outline_node_id": (cue.cue_metadata or {}).get("outline_node_id"),
            "subtitle_text": cue.subtitle_text,
            "script_reference": cue.script_reference,
            "video_url": video_url,
            "audio_url": audio_url,
            "resource_version": cue.resource_version,
            "content_hash": cue.content_hash,
        })

    return result


def serialize_cue(cue: MediaTimelineCue, session: Session) -> dict[str, Any]:
    """序列化时间轴提示"""
    video_url = None
    audio_url = None
    if cue.video_object_key:
        asset = session.exec(
            select(MediaAsset).where(
                MediaAsset.course_id == cue.course_id,
                MediaAsset.object_key == cue.video_object_key,
            )
        ).first()
        if asset:
            video_url = asset.resolve_url()
    if cue.audio_object_key:
        asset = session.exec(
            select(MediaAsset).where(
                MediaAsset.course_id == cue.course_id,
                MediaAsset.object_key == cue.audio_object_key,
            )
        ).first()
        if asset:
            audio_url = asset.resolve_url()

    return {
        "id": cue.id,
        "course_id": cue.course_id,
        "node_id": cue.node_id,
        "cue_index": cue.cue_index,
        "start_time": cue.start_time,
        "end_time": cue.end_time,
        "cue_type": cue.cue_type.value,
        "ppt_page": cue.ppt_page,
        "material_version_id": (cue.cue_metadata or {}).get("material_version_id"),
        "outline_node_id": (cue.cue_metadata or {}).get("outline_node_id"),
        "subtitle_text": cue.subtitle_text,
        "script_reference": cue.script_reference,
        "video_url": video_url,
        "audio_url": audio_url,
        "resource_version": cue.resource_version,
        "content_hash": cue.content_hash,
    }
