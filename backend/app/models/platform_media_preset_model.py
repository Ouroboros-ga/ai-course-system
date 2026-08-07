"""Platform-owned media preset registry models.

The registry deliberately stores only opaque/internal voice references.  A
browser can select a stable preset identity, but it can never receive the
provider speaker/resource identifier that is used by the server at synthesis
time.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class PlatformPresetStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRED = "retired"


class PlatformVoicePreset(SQLModel, table=True):
    """A server-resolved platform voice option.

    ``resource_ref_hash`` is an audit/cache reference only.  It must not be
    serialized to the construction UI, logs, or playback contract.
    """

    __tablename__ = "platform_voice_presets"
    __table_args__ = (
        UniqueConstraint("preset_id", "version", name="uq_platform_voice_preset_version"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    preset_id: str = Field(sa_column=Column(String(100), nullable=False, index=True))
    version: str = Field(default="1.0.0", max_length=40)
    display_name: str = Field(default="平台讲解音色", max_length=160)
    provider_key: str = Field(default="", max_length=100, index=True)
    resource_ref_hash: str = Field(default="", max_length=128)
    status: PlatformPresetStatus = Field(default=PlatformPresetStatus.ACTIVE, index=True)
    content_hash: str = Field(default="", max_length=128, index=True)
    created_at: datetime = Field(
        default_factory=utcnow_aware,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utcnow_aware,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PlatformAvatarPreset(SQLModel, table=True):
    """A versioned, platform-owned browser Sprite2D character preset."""

    __tablename__ = "platform_avatar_presets"
    __table_args__ = (
        UniqueConstraint("preset_id", "version", name="uq_platform_avatar_preset_version"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    preset_id: str = Field(sa_column=Column(String(100), nullable=False, index=True))
    version: str = Field(default="1.0.0", max_length=40)
    display_name: str = Field(default="平台 2D 讲师", max_length=160)
    provider_key: str = Field(default="platform_sprite2d", max_length=100, index=True)
    manifest_object_key: str = Field(default="", max_length=500)
    status: PlatformPresetStatus = Field(default=PlatformPresetStatus.ACTIVE, index=True)
    content_hash: str = Field(default="", max_length=128, index=True)
    created_at: datetime = Field(
        default_factory=utcnow_aware,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utcnow_aware,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
