"""
视频生成任务数据模型
记录每个脚本节点的视频生成状态和结果
"""

from __future__ import annotations

from sqlmodel import SQLModel, Field, JSON, Column
from typing import Optional
from datetime import datetime
from enum import Enum

from app.core.time_utils import utcnow_aware


class GenerationStatus(str, Enum):
    """视频生成状态"""
    PENDING = "pending"        # 等待生成
    TTS_SYNTHESIZING = "tts_synthesizing"  # TTS合成中
    TTS_COMPLETED = "tts_completed"        # TTS合成完成
    DH_GENERATING = "dh_generating"        # 数字人生成中
    COMPLETED = "completed"                # 全部完成
    FAILED = "failed"                      # 生成失败


class VideoGenerationTask(SQLModel, table=True):
    """
    视频生成任务表
    记录每个脚本节点的视频生成管线状态
    """

    __tablename__ = "video_generation_tasks"

    id: Optional[int] = Field(default=None, primary_key=True)

    course_id: int = Field(
        foreign_key="courses.id", index=True, description="所属课程ID"
    )
    script_id: int = Field(
        foreign_key="course_scripts.id", index=True, description="所属脚本ID"
    )
    node_id: int = Field(
        foreign_key="script_nodes.id", index=True, description="关联的脚本节点ID"
    )

    # 生成状态
    status: GenerationStatus = Field(
        default=GenerationStatus.PENDING, description="生成状态"
    )

    # TTS合成相关
    audio_path: Optional[str] = Field(
        default=None, description="TTS合成的音频文件路径"
    )
    audio_duration: float = Field(
        default=0.0, description="音频时长(秒)"
    )
    voice: Optional[str] = Field(
        default=None, description="使用的音色"
    )

    # 数字人视频相关
    face_video_asset_id: Optional[int] = Field(
        default=None, description="使用的人脸视频素材ID"
    )
    dh_video_path: Optional[str] = Field(
        default=None, description="数字人生成的视频文件路径"
    )
    dh_generation_time: Optional[str] = Field(
        default=None, description="数字人生成耗时"
    )

    # 最终视频（分屏合成后的路径，暂不实现）
    final_video_path: Optional[str] = Field(
        default=None, description="最终分屏合成视频路径"
    )

    # 错误信息
    error_message: Optional[str] = Field(
        default=None, description="生成失败时的错误信息"
    )

    # 重试次数
    retry_count: int = Field(
        default=0, description="重试次数"
    )

    created_at: datetime = Field(
        default_factory=utcnow_aware, description="创建时间"
    )
    updated_at: Optional[datetime] = Field(
        default=None, description="最后更新时间"
    )
