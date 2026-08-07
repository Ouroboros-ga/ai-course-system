"""Registry and immutable asset seed for platform media presets.

The seed is intentionally request-driven and idempotent: Alembic owns schema
creation, while this service only registers the small set of platform-owned
choices and immutable object-store manifests needed by a local Demo.  Neither
the public DTO nor the playback response exposes a provider speaker/resource
identifier.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import quote

from sqlmodel import Session, select

from app.core.exceptions import reject_resource_not_found, reject_validation_failed
from app.core.time_utils import utcnow_aware
from app.models.platform_media_preset_model import (
    PlatformAvatarPreset,
    PlatformPresetStatus,
    PlatformVoicePreset,
)
from app.services.object_storage import get_object_storage


DEFAULT_AVATAR_PRESET_ID = "platform-instructor-v2"
DEFAULT_AVATAR_PRESET_VERSION = "1.0.0"


def _sha256(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _svg_data_url(content: str, *, view_box: str = "0 0 480 480") -> str:
    raw = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}">{content}</svg>'
    return f"data:image/svg+xml;charset=utf-8,{quote(raw, safe='')}"


def _avatar_manifest(*, preset_id: str, version: str, label: str, palette: dict[str, str]) -> dict[str, Any]:
    """Build a self-contained Sprite2D manifest safe for object storage.

    The renderer already loads data URLs through Pixi.  Keeping the artwork
    inside versioned JSON means the browser never needs a teacher asset or an
    additional unprotected image route for the platform preset.
    """

    def mouth(path: str) -> str:
        return _svg_data_url(f'<path d="{path}" fill="{palette["mouth"]}"/>', view_box="0 0 100 56")

    return {
        "schema": "sprite2d-manifest/v1",
        "provider": "platform_sprite2d",
        "version": f"{preset_id}@{version}",
        "label": label,
        "stage": {"width": 480, "height": 480},
        "expressions": ["neutral", "warm", "attentive"],
        "gestures": ["rest", "emphasis"],
        "sprites": {
            "body": _svg_data_url(
                f'<path d="M90 480c16-136 69-190 150-190s134 54 150 190H90Z" fill="{palette["jacket"]}"/>'
                f'<path d="M156 480c13-109 45-160 84-160s71 51 84 160H156Z" fill="{palette["shirt"]}"/>'
                f'<path d="M214 311h52v73h-52z" fill="{palette["skin"]}"/>'
                '<path d="M178 480h124l-62-73-62 73Z" fill="#F7F8FA"/>',
            ),
            "head": _svg_data_url(
                f'<path d="M148 164c0-73 40-119 92-119s92 46 92 119v80c0 60-38 104-92 104s-92-44-92-104v-80Z" fill="{palette["skin"]}"/>'
                f'<path d="M145 174c-2-67 31-133 95-133 54 0 98 38 96 120-25-29-51-43-97-44-18 31-49 49-94 57Z" fill="{palette["hair"]}"/>'
                f'<path d="M151 164c5 38 18 54 32 66v-49c-14-3-25-9-32-17Zm178 0c-7 8-18 14-32 17v49c14-12 27-28 32-66Z" fill="{palette["hair"]}"/>'
                f'<circle cx="156" cy="239" r="14" fill="{palette["skin"]}"/><circle cx="324" cy="239" r="14" fill="{palette["skin"]}"/>',
            ),
            "eyes": _svg_data_url(
                '<path d="M184 217c14-13 38-13 52 0-14 16-38 16-52 0Zm60 0c14-13 38-13 52 0-14 16-38 16-52 0Z" fill="#FFFFFF"/>'
                f'<circle cx="210" cy="217" r="7" fill="{palette["eye"]}"/><circle cx="270" cy="217" r="7" fill="{palette["eye"]}"/>'
                f'<path d="M183 196c15-8 34-8 50 0M247 196c15-8 34-8 50 0" fill="none" stroke="{palette["hair"]}" stroke-width="7" stroke-linecap="round"/>',
            ),
            "mouths": {
                "sil": mouth("M30 28c12 5 28 5 40 0 12 5 28 5 40 0-20 12-60 12-80 0Z"),
                "a": mouth("M27 26c5-18 41-23 46-2 5-21 41-16 46 2-13 25-80 25-92 0Z"),
                "e": mouth("M21 24c14-14 64-14 78 0-18 15-61 15-78 0Z"),
                "i": mouth("M37 19c10-8 16-8 26 0 10-8 16-8 26 0-12 19-40 19-52 0Z"),
                "o": mouth("M31 13c13-14 35-14 48 0v23c-13 14-35 14-48 0V13Z"),
                "u": mouth("M40 14c7-9 14-9 20 0v25c-7 9-14 9-20 0V14Z"),
                "fv": mouth("M20 18h80v11H20zM29 30c12 9 30 9 42 0-9 17-33 17-42 0Z"),
                "mbp": mouth("M24 26c17-5 35-5 52 0-17 10-35 10-52 0Z"),
            },
        },
    }


_AVATAR_DEFINITIONS = (
    {
        "preset_id": "platform-instructor-v2",
        "version": "1.0.0",
        "display_name": "知性讲师",
        "palette": {"jacket": "#203A5F", "shirt": "#355C7D", "skin": "#E8BA96", "hair": "#14213D", "eye": "#172033", "mouth": "#8B3A3A"},
    },
    {
        "preset_id": "platform-mentor-v1",
        "version": "1.0.0",
        "display_name": "温和导师",
        "palette": {"jacket": "#3F6B52", "shirt": "#5E8C61", "skin": "#D99F7D", "hair": "#4A302A", "eye": "#172033", "mouth": "#8B3A3A"},
    },
    {
        "preset_id": "platform-analyst-v1",
        "version": "1.0.0",
        "display_name": "理工讲师",
        "palette": {"jacket": "#4E5969", "shirt": "#8EA7BE", "skin": "#C98F6E", "hair": "#27313F", "eye": "#172033", "mouth": "#71353B"},
    },
)


_VOICE_DEFINITIONS = (
    {
        "preset_id": "platform-demo-narrator-v1",
        "version": "1.0.0",
        "display_name": "平台演示讲解音色",
        "provider_key": "fake_tts",
    },
    {
        "preset_id": "platform-doubao-narrator-v1",
        "version": "1.0.0",
        "display_name": "平台讲解音色",
        "provider_key": "volcengine_doubao_tts",
    },
)


def _manifest_key(preset_id: str, version: str) -> str:
    return f"platform/avatar-presets/{preset_id}/{version}/manifest.json"


def _voice_public(preset: PlatformVoicePreset) -> dict[str, Any]:
    return {
        "preset_id": preset.preset_id,
        "version": preset.version,
        "display_name": preset.display_name,
        "provider_key": preset.provider_key,
        "status": preset.status.value if hasattr(preset.status, "value") else str(preset.status),
        "content_hash": preset.content_hash,
    }


def _avatar_public(preset: PlatformAvatarPreset, *, manifest_available: bool) -> dict[str, Any]:
    return {
        "preset_id": preset.preset_id,
        "version": preset.version,
        "display_name": preset.display_name,
        "provider_key": preset.provider_key,
        "status": preset.status.value if hasattr(preset.status, "value") else str(preset.status),
        "content_hash": preset.content_hash,
        "manifest_available": manifest_available,
    }


def ensure_platform_presets(session: Session) -> None:
    """Register immutable platform presets without updating prior versions."""
    storage = get_object_storage()
    now = utcnow_aware()

    for definition in _VOICE_DEFINITIONS:
        existing = session.exec(select(PlatformVoicePreset).where(
            PlatformVoicePreset.preset_id == definition["preset_id"],
            PlatformVoicePreset.version == definition["version"],
        )).first()
        if existing is None:
            resource_hash = _sha256(
                f"server-managed-voice:{definition['provider_key']}:{definition['preset_id']}:{definition['version']}"
            )
            session.add(PlatformVoicePreset(
                **definition,
                resource_ref_hash=resource_hash,
                content_hash=_sha256(f"voice-preset:{definition['preset_id']}:{definition['version']}:{resource_hash}"),
                created_at=now,
                updated_at=now,
            ))

    for definition in _AVATAR_DEFINITIONS:
        manifest = _avatar_manifest(
            preset_id=definition["preset_id"],
            version=definition["version"],
            label=definition["display_name"],
            palette=definition["palette"],
        )
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        content_hash = _sha256(manifest_bytes)
        object_key = _manifest_key(definition["preset_id"], definition["version"])
        if storage.exists(object_key):
            stored_hash = _sha256(storage.get(object_key))
            if stored_hash != content_hash:
                raise RuntimeError(
                    f"平台角色 manifest 已存在但内容不匹配: {definition['preset_id']}@{definition['version']}"
                )
        else:
            storage.put(object_key, manifest_bytes, mime_type="application/json")
        existing = session.exec(select(PlatformAvatarPreset).where(
            PlatformAvatarPreset.preset_id == definition["preset_id"],
            PlatformAvatarPreset.version == definition["version"],
        )).first()
        if existing is None:
            session.add(PlatformAvatarPreset(
                preset_id=definition["preset_id"],
                version=definition["version"],
                display_name=definition["display_name"],
                provider_key="platform_sprite2d",
                manifest_object_key=object_key,
                content_hash=content_hash,
                created_at=now,
                updated_at=now,
            ))
    session.flush()


def list_public_presets(session: Session, *, active_tts_provider_key: str) -> dict[str, list[dict[str, Any]]]:
    ensure_platform_presets(session)
    voices = list(session.exec(select(PlatformVoicePreset).where(
        PlatformVoicePreset.status == PlatformPresetStatus.ACTIVE,
        PlatformVoicePreset.provider_key == active_tts_provider_key,
    ).order_by(PlatformVoicePreset.display_name)).all())
    storage = get_object_storage()
    avatars = list(session.exec(select(PlatformAvatarPreset).where(
        PlatformAvatarPreset.status == PlatformPresetStatus.ACTIVE,
    ).order_by(PlatformAvatarPreset.display_name)).all())
    return {
        "voices": [_voice_public(item) for item in voices],
        "avatars": [_avatar_public(item, manifest_available=bool(item.manifest_object_key and storage.exists(item.manifest_object_key))) for item in avatars],
    }


def resolve_voice_preset(
    session: Session,
    *,
    preset_id: str = "",
    version: str = "",
    active_tts_provider_key: str,
) -> PlatformVoicePreset:
    ensure_platform_presets(session)
    stmt = select(PlatformVoicePreset).where(
        PlatformVoicePreset.status == PlatformPresetStatus.ACTIVE,
        PlatformVoicePreset.provider_key == active_tts_provider_key,
    )
    if preset_id:
        stmt = stmt.where(PlatformVoicePreset.preset_id == preset_id)
    if version:
        stmt = stmt.where(PlatformVoicePreset.version == version)
    preset = session.exec(stmt.order_by(PlatformVoicePreset.display_name)).first()
    if preset is None:
        reject_validation_failed("所选平台音色不可用，或与当前服务器 TTS Provider 不匹配")
    return preset


def resolve_avatar_preset(
    session: Session,
    *,
    preset_id: str = "",
    version: str = "",
    allow_inactive: bool = False,
) -> PlatformAvatarPreset:
    ensure_platform_presets(session)
    stmt = select(PlatformAvatarPreset)
    if preset_id:
        stmt = stmt.where(PlatformAvatarPreset.preset_id == preset_id)
    else:
        stmt = stmt.where(PlatformAvatarPreset.preset_id == DEFAULT_AVATAR_PRESET_ID)
    if version:
        stmt = stmt.where(PlatformAvatarPreset.version == version)
    else:
        stmt = stmt.where(PlatformAvatarPreset.version == DEFAULT_AVATAR_PRESET_VERSION)
    if not allow_inactive:
        stmt = stmt.where(PlatformAvatarPreset.status == PlatformPresetStatus.ACTIVE)
    preset = session.exec(stmt).first()
    if preset is None:
        reject_resource_not_found("所选平台数字人角色不存在或已停用")
    storage = get_object_storage()
    if not preset.manifest_object_key or not storage.exists(preset.manifest_object_key):
        reject_validation_failed("所选平台数字人角色的 manifest 不可用")
    return preset


def sign_avatar_manifest_for_release(
    session: Session,
    *,
    course_id: int,
    release_id: str,
    preset_id: str | None,
    preset_version: str | None,
) -> tuple[PlatformAvatarPreset | None, str | None]:
    """Resolve the release's frozen version, including a retired preset.

    A later registry change must never switch an earlier course release to a
    different visual asset.  If the historic record/object is unavailable, the
    player receives ``None`` and selects its local static fallback instead.
    """
    if not preset_id or not preset_version:
        return None, None
    try:
        preset = resolve_avatar_preset(
            session,
            preset_id=preset_id,
            version=preset_version,
            allow_inactive=True,
        )
        url = get_object_storage().sign_read_url(
            preset.manifest_object_key,
            scope={
                "course_id": course_id,
                "release_id": release_id,
                "purpose": "platform_avatar_manifest",
                "preset_id": preset.preset_id,
                "preset_version": preset.version,
            },
        )
        return preset, url
    except Exception:
        return None, None
