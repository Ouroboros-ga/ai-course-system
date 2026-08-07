"""G8 MediaTimelineCue 与抽象存储模型

MediaTimelineCue 保存视频起止、PPT 页、字幕片段、讲稿引用、资源版本和哈希。
本地存储使用抽象 object_key，未来可平滑迁移 OSS。
讲稿可作为真实字幕/讲解内容展示，不再只是 220 字节点摘要。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class CueType(str, Enum):
    """时间轴提示类型"""
    NARRATION = "narration"        # 讲解（视频+字幕+PPT页）
    TRANSITION = "transition"      # 过渡（仅PPT页切换）
    QUIZ = "quiz"                   # 提问
    BREAKPOINT = "breakpoint"      # 暂停点


class StorageBackend(str, Enum):
    """存储后端"""
    LOCAL = "local"    # 本地文件系统
    OSS = "oss"        # 对象存储（未来）


class MediaAsset(SQLModel, table=True):
    """媒体资产表（抽象存储）

    使用抽象 object_key 替代直接文件路径，未来可平滑迁移 OSS。
    """

    __tablename__ = "media_assets"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    object_key: str = Field(unique=True, index=True, description="抽象存储键(如 videos/course_1/node_5/segment_3.mp4)")
    asset_type: str = Field(index=True, description="类型: video/audio/subtitle/thumbnail")
    backend: StorageBackend = Field(default=StorageBackend.LOCAL, description="存储后端")
    local_path: Optional[str] = Field(default=None, description="本地路径(LOCAL后端时使用)")
    oss_url: Optional[str] = Field(default=None, description="OSS URL(OSS后端时使用)")
    mime_type: str = Field(default="", description="MIME类型")
    size_bytes: int = Field(default=0, description="文件大小(字节)")
    duration_seconds: float = Field(default=0.0, description="时长(秒)")
    content_hash: str = Field(default="", index=True, description="内容SHA256哈希")
    resource_version: str = Field(default="v1", description="资源版本")
    created_at: datetime = Field(default_factory=utcnow_aware)

    def resolve_url(self) -> str:
        """Return a short-lived signed URL for the immutable object key."""
        from app.services.object_storage import get_object_storage

        if self.backend == StorageBackend.OSS and self.oss_url:
            return self.oss_url
        return get_object_storage().sign_read_url(
            self.object_key,
            scope={"course_id": self.course_id, "purpose": "media_asset"},
        )


class MediaTimelineCue(SQLModel, table=True):
    """媒体时间轴提示

    保存视频起止、PPT 页、字幕片段、讲稿引用、资源版本和哈希。
    PPT 页、字幕、讲稿、视频同一全局时间轴。
    """

    __tablename__ = "media_timeline_cues"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    script_id: int = Field(foreign_key="course_scripts.id", index=True)
    node_id: int = Field(foreign_key="script_nodes.id", index=True)

    # 全局时间轴位置
    cue_index: int = Field(description="在节点内的序号(从0开始)")
    start_time: float = Field(description="起始时间(秒，相对节点视频)")
    end_time: float = Field(description="结束时间(秒)")

    # 类型
    cue_type: CueType = Field(default=CueType.NARRATION, index=True)

    # PPT 页关联
    ppt_page: Optional[int] = Field(default=None, description="关联的PPT页码")

    # 字幕/讲稿内容（不再是220字摘要，而是完整讲稿）
    subtitle_text: str = Field(default="", description="字幕文本(完整讲稿片段)")
    script_reference: Optional[str] = Field(default=None, description="讲稿引用标识")

    # 媒体资产关联（抽象存储）
    video_object_key: Optional[str] = Field(default=None, description="视频资产object_key")
    audio_object_key: Optional[str] = Field(default=None, description="音频资产object_key")

    # 资源版本与哈希
    resource_version: str = Field(default="v1", description="资源版本")
    content_hash: str = Field(default="", description="内容哈希")
    is_active: bool = Field(default=True, index=True, description="是否为节点当前生效时间轴")

    # 额外数据
    cue_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON), description="扩展元数据")

    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class DigitalHumanPreset(str, Enum):
    """数字人预设（CPU 路线）"""
    DH_LIVE_MINI = "dh_live_mini"      # 首选：DH_live_mini / MiniMates
    LITE_AVATAR = "lite_avatar"        # 对照：LiteAvatar
    DUIL_AVATAR = "duix_avatar"        # 现有：Duix.Avatar (GPU)
    NONE = "none"                      # 不使用数字人
