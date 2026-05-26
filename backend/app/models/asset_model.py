"""
老师素材数据模型
存储老师上传的人脸视频、参考音频等数字人素材
"""

from __future__ import annotations

from sqlmodel import SQLModel, Field, JSON, Column
from typing import Optional
from datetime import datetime
from enum import Enum


class AssetType(str, Enum):
    """素材类型枚举"""

    FACE_VIDEO = "face_video"      # 人脸视频素材
    REF_AUDIO = "ref_audio"        # 参考音频素材
    OTHER = "other"                # 其他素材


class CloneStatus(str, Enum):
    """声音复刻状态"""
    NONE = "none"            # 未复刻
    PENDING = "pending"      # 复刻中
    SUCCESS = "success"      # 复刻成功
    FAILED = "failed"        # 复刻失败


class TeacherAsset(SQLModel, table=True):
    """
    老师素材表
    存储老师上传的人脸视频、参考音频等，用于数字人视频生成
    """

    __tablename__ = "teacher_assets"

    id: Optional[int] = Field(default=None, primary_key=True)

    teacher_id: int = Field(
        foreign_key="users.id", index=True, description="所属老师ID"
    )

    asset_type: AssetType = Field(description="素材类型：face_video/ref_audio/other")

    file_name: str = Field(description="原始文件名")
    file_path: str = Field(description="文件存储路径")
    file_size: int = Field(default=0, description="文件大小(字节)")
    mime_type: str = Field(default="", description="文件MIME类型")

    duration: float = Field(default=0.0, description="音视频时长(秒)")

    thumbnail_url: Optional[str] = Field(
        default=None, description="缩略图路径(视频封面)"
    )

    is_default: bool = Field(
        default=False, description="是否为该类型的默认素材(同类型只能有一个默认)"
    )

    # 声音复刻相关字段（仅ref_audio类型使用）
    clone_voice_id: Optional[str] = Field(
        default=None, description="声音复刻后的speaker_id（如S_xxxxxxxxx）"
    )
    clone_status: CloneStatus = Field(
        default=CloneStatus.NONE, description="声音复刻状态"
    )

    metadata_: Optional[dict] = Field(
        default=None,
        sa_column=Column("metadata", JSON, nullable=True),
        description="扩展元数据(JSON)，如人脸特征提取结果、音频采样率等",
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="创建时间"
    )
    updated_at: Optional[datetime] = Field(
        default=None, description="最后更新时间"
    )
