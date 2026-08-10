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
import logging
from pathlib import Path
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

logger = logging.getLogger(__name__)


DEFAULT_AVATAR_PRESET_ID = "platform-female-instructor-v1"
DEFAULT_AVATAR_PRESET_VERSION = "1.0.0"


def _sha256(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _svg_data_url(content: str, *, view_box: str = "0 0 480 480") -> str:
    raw = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}">{content}</svg>'
    return f"data:image/svg+xml;charset=utf-8,{quote(raw, safe='')}"


def _avatar_manifest(*, preset_id: str, version: str, label: str, palette: dict[str, str], realistic: bool = False) -> dict[str, Any]:
    """Build a self-contained Sprite2D manifest safe for object storage.

    The renderer already loads data URLs through Pixi.  Keeping the artwork
    inside versioned JSON means the browser never needs a teacher asset or an
    additional unprotected image route for the platform preset.
    """

    def mouth(path: str) -> str:
        return _svg_data_url(f'<path d="{path}" fill="{palette["mouth"]}"/>', view_box="0 0 100 56")

    if realistic:
        body_svg = (
            f'<defs><linearGradient id="j" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{palette["jacket_light"]}"/><stop offset="1" stop-color="{palette["jacket"]}"/></linearGradient>'
            f'<linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop stop-color="{palette["shirt"]}"/><stop offset="1" stop-color="#D9E0E8"/></linearGradient></defs>'
            '<path d="M70 480c11-127 70-196 170-196s159 69 170 196H70Z" fill="url(#j)"/>'
            '<path d="M161 480c11-91 38-151 79-171 41 20 68 80 79 171H161Z" fill="url(#s)"/>'
            f'<path d="M240 308 205 480h70Z" fill="{palette["tie"]}" opacity=".92"/>'
            '<path d="M164 316 214 480h-46l-43-112c10-25 22-40 39-52Zm152 0-50 164h46l43-112c-10-25-22-40-39-52Z" fill="#172941" opacity=".55"/>'
            '<path d="M104 390c25-19 46-29 62-34M376 390c-25-19-46-29-62-34" fill="none" stroke="#9FB0C2" stroke-width="5" opacity=".55"/>'
        )
        head_svg = (
            f'<defs><linearGradient id="skin" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{palette["skin_light"]}"/><stop offset="1" stop-color="{palette["skin"]}"/></linearGradient>'
            f'<linearGradient id="hair" x1="0" y1="0" x2="0" y2="1"><stop stop-color="{palette["hair_light"]}"/><stop offset="1" stop-color="{palette["hair"]}"/></linearGradient></defs>'
            '<path d="M151 170c0-73 39-119 89-119s89 46 89 119v76c0 62-37 108-89 108s-89-46-89-108v-76Z" fill="url(#skin)"/>'
            '<path d="M151 174c-6-65 29-137 92-137 64 0 101 47 87 139-29-31-59-47-105-48-18 29-40 43-74 46Z" fill="url(#hair)"/>'
            '<path d="M164 255c8 20 22 34 40 42M316 255c-8 20-22 34-40 42" fill="none" stroke="#A76F58" stroke-width="5" stroke-linecap="round" opacity=".35"/>'
            '<path d="M224 245c7 5 15 5 22 0l-6 30c-5 4-11 4-16 0Z" fill="#B67D67" opacity=".56"/>'
            '<path d="M208 302c21 13 43 13 64 0" fill="none" stroke="#7E3F45" stroke-width="6" stroke-linecap="round" opacity=".75"/>'
            '<circle cx="153" cy="237" r="15" fill="url(#skin)"/><circle cx="327" cy="237" r="15" fill="url(#skin)"/>'
        )
        eyes_svg = (
            '<path d="M177 217c15-15 40-15 55 0-15 17-40 17-55 0Zm71 0c15-15 40-15 55 0-15 17-40 17-55 0Z" fill="#FFF"/>'
            f'<circle cx="212" cy="218" r="8" fill="{palette["eye"]}"/><circle cx="268" cy="218" r="8" fill="{palette["eye"]}"/>'
            f'<path d="M174 197c17-10 39-10 57 0M249 197c18-10 40-10 57 0" fill="none" stroke="{palette["hair"]}" stroke-width="7" stroke-linecap="round"/>'
            '<path d="M174 214h57M249 214h57M231 216h18" fill="none" stroke="#4A5666" stroke-width="3" opacity=".85"/>'
            '<path d="M176 213c0-14 14-22 29-22h8c12 0 19 8 19 22s-8 23-22 23h-13c-13 0-21-9-21-23Zm73 0c0-14 8-22 20-22h8c15 0 29 8 29 22s-8 23-21 23h-13c-14 0-23-9-23-23Z" fill="none" stroke="#25384F" stroke-width="4"/>'
        )
    else:
        body_svg = (
            f'<path d="M90 480c16-136 69-190 150-190s134 54 150 190H90Z" fill="{palette["jacket"]}"/>'
            f'<path d="M156 480c13-109 45-160 84-160s71 51 84 160H156Z" fill="{palette["shirt"]}"/>'
            f'<path d="M214 311h52v73h-52z" fill="{palette["skin"]}"/><path d="M178 480h124l-62-73-62 73Z" fill="#F7F8FA"/>'
        )
        head_svg = (
            f'<path d="M148 164c0-73 40-119 92-119s92 46 92 119v80c0 60-38 104-92 104s-92-44-92-104v-80Z" fill="{palette["skin"]}"/>'
            f'<path d="M145 174c-2-67 31-133 95-133 54 0 98 38 96 120-25-29-51-43-97-44-18 31-49 49-94 57Z" fill="{palette["hair"]}"/>'
            f'<circle cx="156" cy="239" r="14" fill="{palette["skin"]}"/><circle cx="324" cy="239" r="14" fill="{palette["skin"]}"/>'
        )
        eyes_svg = (
            '<path d="M184 217c14-13 38-13 52 0-14 16-38 16-52 0Zm60 0c14-13 38-13 52 0-14 16-38 16-52 0Z" fill="#FFFFFF"/>'
            f'<circle cx="210" cy="217" r="7" fill="{palette["eye"]}"/><circle cx="270" cy="217" r="7" fill="{palette["eye"]}"/>'
            f'<path d="M183 196c15-8 34-8 50 0M247 196c15-8 34-8 50 0" fill="none" stroke="{palette["hair"]}" stroke-width="7" stroke-linecap="round"/>'
        )

    return {
        "schema": "sprite2d-manifest/v1",
        "provider": "platform_sprite2d",
        "version": f"{preset_id}@{version}",
        "label": label,
        "stage": {"width": 480, "height": 480},
        "expressions": ["neutral", "warm", "attentive"],
        "gestures": ["rest", "emphasis"],
        "sprites": {
            "body": _svg_data_url(body_svg),
            "head": _svg_data_url(head_svg),
            "eyes": _svg_data_url(eyes_svg),
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
        "preset_id": "platform-female-instructor-v1",
        "version": "1.0.0",
        "display_name": "平台女性讲师",
        "asset_bundle": "platform_female_instructor_v1",
    },
    {
        "preset_id": "platform-instructor-real-v1",
        "version": "1.0.0",
        "display_name": "半写实汽车教师",
        "realistic": True,
        # Kept only for releases which already froze this version.  New
        # construction work must use the female instructor or another active
        # preset, never silently rewrite historic releases.
        "status": PlatformPresetStatus.RETIRED,
        "palette": {"jacket": "#203A5F", "jacket_light": "#486B92", "shirt": "#F7F8FA", "tie": "#B34B4B", "skin": "#D59B78", "skin_light": "#F0C5A5", "hair": "#1A2230", "hair_light": "#46556A", "eye": "#182235", "mouth": "#8B3A3A"},
    },
    {
        "preset_id": "platform-instructor-v2",
        # v2.1.0 carries a rewritten SVG body/head/eyes.  The manifest content
        # changed, so the version must move (1.0.0 stays archived for older
        # releases that froze it); the same preset_id@version pair is treated
        # as immutable by ``ensure_platform_presets``.
        "version": "1.1.0",
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


_FEMALE_INSTRUCTOR_ASSET_ROOT = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "platform_avatar_presets"
    / "platform-female-instructor-v1"
    / "1.0.0"
)
_FEMALE_INSTRUCTOR_ASSETS = {
    "body": "body.png",
    "head": "transparent.png",
    "eyes": "eyes-closed.png",
    "mouth:sil": "mouth-sil.png",
    "mouth:a": "mouth-a.png",
    "mouth:e": "mouth-e.png",
    "mouth:i": "mouth-i.png",
    "mouth:o": "mouth-o.png",
    "mouth:u": "mouth-u.png",
    "mouth:fv": "mouth-fv.png",
    "mouth:mbp": "mouth-mbp.png",
}
_MOUTH_KEYS = ("sil", "a", "e", "i", "o", "u", "fv", "mbp")


def _asset_key(preset_id: str, version: str, filename: str, content_hash: str) -> str:
    """Use a content-addressed key so a corrected bitmap cannot overwrite it."""
    stem, suffix = filename.rsplit(".", 1)
    return (
        f"platform/avatar-presets/{preset_id}/{version}/assets/"
        f"{stem}-{content_hash[:16]}.{suffix}"
    )


def _seed_female_instructor_manifest(definition: dict[str, Any], storage: Any) -> dict[str, Any]:
    """Store compact real-portrait layers once and return their manifest.

    The source images are repository-owned, fictional reference art.  The
    browser receives signed texture URLs only; the manifest remains an
    immutable object-key contract just like audio and PPT assets.
    """
    object_keys: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for asset_id, filename in _FEMALE_INSTRUCTOR_ASSETS.items():
        source = _FEMALE_INSTRUCTOR_ASSET_ROOT / filename
        if not source.is_file():
            raise RuntimeError(f"platform female instructor seed asset missing: {filename}")
        content = source.read_bytes()
        content_hash = _sha256(content)
        object_key = _asset_key(definition["preset_id"], definition["version"], filename, content_hash)
        if storage.exists(object_key):
            if _sha256(storage.get(object_key)) != content_hash:
                # The path embeds the expected hash.  A mismatch means storage
                # corruption, not a mutable preset upgrade; do not serve it.
                raise RuntimeError(f"platform female instructor immutable asset corrupt: {object_key}")
        else:
            storage.put(object_key, content, mime_type="image/png")
        object_keys[asset_id] = object_key
        hashes[asset_id] = content_hash

    def asset(asset_id: str) -> dict[str, str]:
        return {"object_key": object_keys[asset_id], "sha256": hashes[asset_id]}

    return {
        "schema": "sprite2d-manifest/v1",
        "provider": "platform_sprite2d",
        "version": f"{definition['preset_id']}@{definition['version']}",
        "label": definition["display_name"],
        "render_mode": "portrait_patch_v1",
        "stage": {"width": 480, "height": 480},
        "expressions": ["neutral", "warm", "attentive"],
        "gestures": ["rest"],
        "asset_provenance": "platform-owned-fictional/1",
        "sprites": {
            "body": asset("body"),
            # Kept for the v1 schema. portrait_patch_v1 does not render it.
            "head": asset("head"),
            "eyes": asset("eyes"),
            "mouths": {key: asset(f"mouth:{key}") for key in _MOUTH_KEYS},
        },
        "layout": {
            "body": {"x": 240, "y": 240, "width": 480, "height": 480},
            "eyes": {"x": 240, "y": 151, "width": 151, "height": 41},
            "mouth": {"x": 240, "y": 218, "width": 96, "height": 45},
        },
    }


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
        # Retire superseded versions of the same preset.  The manifest object
        # and DB row are kept (a release that froze the old version still
        # resolves it through ``allow_inactive``), but the old version stops
        # appearing in the public/active registry.
        for superseded in session.exec(select(PlatformAvatarPreset).where(
            PlatformAvatarPreset.preset_id == definition["preset_id"],
            PlatformAvatarPreset.version != definition["version"],
            PlatformAvatarPreset.status == PlatformPresetStatus.ACTIVE,
        )).all():
            superseded.status = PlatformPresetStatus.RETIRED
            session.add(superseded)
        if definition.get("asset_bundle") == "platform_female_instructor_v1":
            manifest = _seed_female_instructor_manifest(definition, storage)
        else:
            manifest = _avatar_manifest(
                preset_id=definition["preset_id"],
                version=definition["version"],
                label=definition["display_name"],
                palette=definition["palette"],
                realistic=bool(definition.get("realistic", False)),
            )
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        content_hash = _sha256(manifest_bytes)
        object_key = _manifest_key(definition["preset_id"], definition["version"])
        existing = session.exec(select(PlatformAvatarPreset).where(
            PlatformAvatarPreset.preset_id == definition["preset_id"],
            PlatformAvatarPreset.version == definition["version"],
        )).first()
        desired_status = definition.get("status", PlatformPresetStatus.ACTIVE)
        if existing is not None and existing.status != desired_status:
            existing.status = desired_status
            existing.updated_at = now
            session.add(existing)
        if storage.exists(object_key):
            stored_bytes = storage.get(object_key)
            stored_hash = _sha256(stored_bytes)
            if stored_hash != content_hash:
                if existing is not None:
                    logger.warning(
                        "保留存量平台角色 manifest %s@%s；代码生成内容已变化，请升版本",
                        definition["preset_id"], definition["version"],
                    )
                    continue
                # An object without a registry row is an untracked historical
                # asset. Preserve that immutable object and register its
                # actual hash instead of failing every preset lookup with 500.
                manifest_bytes = stored_bytes
                content_hash = stored_hash
        else:
            storage.put(object_key, manifest_bytes, mime_type="application/json")
        if existing is None:
            session.add(PlatformAvatarPreset(
                preset_id=definition["preset_id"],
                version=definition["version"],
                display_name=definition["display_name"],
                provider_key="platform_sprite2d",
                manifest_object_key=object_key,
                content_hash=content_hash,
                status=desired_status,
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
        # Only the default preset defaults its version; an explicit preset_id
        # without a version must resolve to that preset's active latest version
        # instead of being forced onto the default version.
        if not version:
            version = DEFAULT_AVATAR_PRESET_VERSION
    if version:
        stmt = stmt.where(PlatformAvatarPreset.version == version)
    if not allow_inactive:
        stmt = stmt.where(PlatformAvatarPreset.status == PlatformPresetStatus.ACTIVE)
    preset = session.exec(stmt.order_by(PlatformAvatarPreset.version.desc())).first()
    if preset is None:
        reject_resource_not_found("所选平台数字人角色不存在或已停用")
    storage = get_object_storage()
    if not preset.manifest_object_key or not storage.exists(preset.manifest_object_key):
        reject_validation_failed("所选平台数字人角色的 manifest 不可用")
    return preset


def _manifest_asset_keys(manifest: dict[str, Any], *, preset: PlatformAvatarPreset) -> list[str]:
    """Return only this preset's object-backed texture keys.

    Legacy SVG/data-URL manifests naturally return an empty list.  Keeping the
    prefix check here prevents a malformed platform manifest from becoming a
    generic signed-object URL oracle.
    """
    prefix = f"platform/avatar-presets/{preset.preset_id}/{preset.version}/assets/"
    result: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            candidate = value.get("object_key")
            if isinstance(candidate, str) and candidate.startswith(prefix):
                result.append(candidate)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit((manifest or {}).get("sprites"))
    return list(dict.fromkeys(result))


def sign_avatar_package_for_release(
    session: Session,
    *,
    course_id: int,
    release_id: str,
    preset_id: str | None,
    preset_version: str | None,
 ) -> tuple[PlatformAvatarPreset | None, str | None, dict[str, str]]:
    """Sign an immutable preset manifest and its object-backed textures.

    A later registry change must never switch an earlier course release to a
    different visual asset.  The returned map is keyed by the object's own
    immutable key; browsers receive short-lived URLs, never filesystem paths.
    """
    if not preset_id or not preset_version:
        return None, None, {}
    try:
        preset = resolve_avatar_preset(
            session,
            preset_id=preset_id,
            version=preset_version,
            allow_inactive=True,
        )
        storage = get_object_storage()
        url = storage.sign_read_url(
            preset.manifest_object_key,
            scope={
                "course_id": course_id,
                "release_id": release_id,
                "purpose": "platform_avatar_manifest",
                "preset_id": preset.preset_id,
                "preset_version": preset.version,
            },
        )
        manifest = json.loads(storage.get(preset.manifest_object_key).decode("utf-8"))
        asset_urls = {
            object_key: storage.sign_read_url(
                object_key,
                scope={
                    "course_id": course_id,
                    "release_id": release_id,
                    "purpose": "platform_avatar_texture",
                    "preset_id": preset.preset_id,
                    "preset_version": preset.version,
                },
            )
            for object_key in _manifest_asset_keys(manifest, preset=preset)
        }
        return preset, url, asset_urls
    except Exception:
        return None, None, {}


def sign_avatar_manifest_for_release(
    session: Session,
    *,
    course_id: int,
    release_id: str,
    preset_id: str | None,
    preset_version: str | None,
) -> tuple[PlatformAvatarPreset | None, str | None]:
    """Backward-compatible manifest-only wrapper for legacy callers."""
    preset, url, _asset_urls = sign_avatar_package_for_release(
        session,
        course_id=course_id,
        release_id=release_id,
        preset_id=preset_id,
        preset_version=preset_version,
    )
    return preset, url
