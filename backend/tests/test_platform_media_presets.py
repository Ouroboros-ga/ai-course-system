"""P5.1 platform voice/avatar registry contracts.

These tests use the local fake provider and object storage only.  They verify
that preset identity is frozen per media version without exposing provider
credentials or allowing a later registry change to rewrite an old release.
"""
from __future__ import annotations

from sqlmodel import select

from app.models.course_outline_model import TeachingScriptNode
from app.models.media_release_model import MediaRelease
from app.models.platform_media_preset_model import PlatformAvatarPreset, PlatformVoicePreset
from app.services.media_batch_service import build_media_plan, confirm_media_batch
from app.services.object_storage import reset_object_storage_for_tests
from app.services.platform_media_preset_service import (
    ensure_platform_presets,
    list_public_presets,
    sign_avatar_package_for_release,
    sign_avatar_manifest_for_release,
)
from app.services.media_release_service import media_release_service
from test_media_release import _course


def test_public_registry_is_safe_and_seeded(session, teacher_user):
    ensure_platform_presets(session)
    payload = list_public_presets(session, active_tts_provider_key="fake_tts")

    assert len(payload["voices"]) == 1
    assert len(payload["avatars"]) == 4
    avatar_ids = {item["preset_id"] for item in payload["avatars"]}
    assert "platform-female-instructor-v1" in avatar_ids
    assert "platform-instructor-real-v1" not in avatar_ids
    for voice in payload["voices"]:
        assert {"preset_id", "version", "display_name", "provider_key", "status", "content_hash"} <= voice.keys()
        assert "resource_ref_hash" not in voice
        assert "speaker" not in voice
        assert "resource_id" not in voice
    for avatar in payload["avatars"]:
        assert avatar["manifest_available"] is True


def test_batch_confirmation_freezes_selected_presets(session, teacher_user):
    course = _course(session, teacher_user.id)
    node = TeachingScriptNode(
        course_id=course.id,
        script_version_id="p51-script",
        outline_node_id="p51-outline",
        content="P5.1 preset freeze",
    )
    session.add(node)
    session.commit()

    plan = build_media_plan(
        session,
        course_id=course.id,
        node_ids=[node.id],
        voice_preset_id="platform-demo-narrator-v1",
        voice_preset_version="1.0.0",
        avatar_preset_id="platform-mentor-v1",
        avatar_preset_version="1.0.0",
    )
    batch, release, _jobs = confirm_media_batch(
        session,
        course_id=course.id,
        created_by=teacher_user.id,
        plan=plan,
        idempotency_key="p51-freeze-1",
    )

    assert batch.voice_preset_id == "platform-demo-narrator-v1"
    assert batch.voice_preset_version == "1.0.0"
    assert batch.avatar_preset_id == "platform-mentor-v1"
    assert batch.avatar_preset_version == "1.0.0"
    assert release.voice_preset_id == batch.voice_preset_id
    assert release.avatar_preset_id == batch.avatar_preset_id
    assert release.avatar_preset_version == batch.avatar_preset_version


def test_release_versions_sign_different_immutable_manifests(session, teacher_user):
    reset_object_storage_for_tests()
    course = _course(session, teacher_user.id)
    ensure_platform_presets(session)
    # v2 has been bumped to 1.1.0 (rewritten SVG content); a release frozen on
    # the superseded 1.0.0 must still resolve through the retired row when the
    # migration path kept it, while a new release uses the active 1.1.0.
    first = MediaRelease(
        course_id=course.id,
        version_number=1,
        created_by=teacher_user.id,
        avatar_preset_id="platform-instructor-v2",
        avatar_preset_version="1.1.0",
    )
    second = MediaRelease(
        course_id=course.id,
        version_number=2,
        created_by=teacher_user.id,
        avatar_preset_id="platform-analyst-v1",
        avatar_preset_version="1.0.0",
    )
    session.add(first)
    session.add(second)
    session.commit()

    _preset_a, url_a = sign_avatar_manifest_for_release(
        session,
        course_id=course.id,
        release_id=first.release_id,
        preset_id=first.avatar_preset_id,
        preset_version=first.avatar_preset_version,
    )
    _preset_b, url_b = sign_avatar_manifest_for_release(
        session,
        course_id=course.id,
        release_id=second.release_id,
        preset_id=second.avatar_preset_id,
        preset_version=second.avatar_preset_version,
    )

    assert url_a and url_b and url_a != url_b
    assert "platform-instructor-v2" in url_a
    assert "platform-analyst-v1" in url_b
    # Registry rows remain distinct; no update to one release is implied by
    # adding another preset version.
    rows = session.exec(select(PlatformAvatarPreset)).all()
    assert {row.preset_id for row in rows} >= {"platform-instructor-v2", "platform-analyst-v1"}


def test_female_instructor_signs_all_object_backed_layers(session, teacher_user):
    """The realistic preset has one 480p portrait and compact signed patches.

    The browser must not use an unprotected local/static image route for these
    assets: every object-backed manifest entry gets a release-scoped URL.
    """
    reset_object_storage_for_tests()
    course = _course(session, teacher_user.id)
    release = MediaRelease(
        course_id=course.id,
        version_number=1,
        created_by=teacher_user.id,
        avatar_preset_id="platform-female-instructor-v1",
        avatar_preset_version="1.0.0",
    )
    session.add(release)
    session.commit()

    preset, manifest_url, asset_urls = sign_avatar_package_for_release(
        session,
        course_id=course.id,
        release_id=release.release_id,
        preset_id=release.avatar_preset_id,
        preset_version=release.avatar_preset_version,
    )

    assert preset is not None
    assert preset.preset_id == "platform-female-instructor-v1"
    assert manifest_url and "platform-female-instructor-v1" in manifest_url
    assert len(asset_urls) == 11
    assert all("platform_avatar_texture" in url for url in asset_urls.values())
    assert all(key.startswith("platform/avatar-presets/platform-female-instructor-v1/1.0.0/assets/") for key in asset_urls)


def test_superseded_preset_version_is_retired_and_still_resolvable(session, teacher_user):
    """P1: when a preset's manifest content changes, the version must move.
    ensure_platform_presets must retire the old ACTIVE version (keeping the
    row/object for frozen releases) and resolve the preset without an explicit
    version to the new active version."""
    from app.models.platform_media_preset_model import PlatformPresetStatus
    from app.services.object_storage import get_object_storage
    from app.services.platform_media_preset_service import resolve_avatar_preset

    reset_object_storage_for_tests()
    # Simulate a legacy database row + object frozen on the old manifest
    # version, exactly as a pre-migration deployment would have.
    legacy_object_key = "platform/avatar-presets/platform-instructor-v2/1.0.0/manifest.json"
    get_object_storage().put(
        legacy_object_key,
        b'{"schema":"sprite2d-manifest/v1","preset_id":"platform-instructor-v2","version":"1.0.0"}',
        mime_type="application/json",
    )
    legacy = PlatformAvatarPreset(
        preset_id="platform-instructor-v2",
        version="1.0.0",
        display_name="知性讲师",
        provider_key="platform_sprite2d",
        manifest_object_key=legacy_object_key,
        content_hash="legacy",
        status=PlatformPresetStatus.ACTIVE,
    )
    session.add(legacy)
    session.commit()

    ensure_platform_presets(session)
    session.refresh(legacy)
    assert legacy.status == PlatformPresetStatus.RETIRED

    active = session.exec(select(PlatformAvatarPreset).where(
        PlatformAvatarPreset.preset_id == "platform-instructor-v2",
        PlatformAvatarPreset.version == "1.1.0",
        PlatformAvatarPreset.status == PlatformPresetStatus.ACTIVE,
    )).first()
    assert active is not None

    # Preset resolution without a version picks the active latest (1.1.0).
    resolved = resolve_avatar_preset(session, preset_id="platform-instructor-v2")
    assert resolved.version == "1.1.0"
    assert resolved.status == PlatformPresetStatus.ACTIVE

    # A frozen release on the retired version still resolves with allow_inactive.
    frozen = resolve_avatar_preset(
        session,
        preset_id="platform-instructor-v2",
        version="1.0.0",
        allow_inactive=True,
    )
    assert frozen.version == "1.0.0"
    assert frozen.status == PlatformPresetStatus.RETIRED

    # Default resolution without ids targets the new, realistic female preset.
    default = resolve_avatar_preset(session)
    assert default.preset_id == "platform-female-instructor-v1"
