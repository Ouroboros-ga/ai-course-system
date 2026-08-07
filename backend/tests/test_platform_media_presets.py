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
    sign_avatar_manifest_for_release,
)
from app.services.media_release_service import media_release_service
from test_media_release import _course


def test_public_registry_is_safe_and_seeded(session, teacher_user):
    ensure_platform_presets(session)
    payload = list_public_presets(session, active_tts_provider_key="fake_tts")

    assert len(payload["voices"]) == 1
    assert len(payload["avatars"]) == 3
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
    first = MediaRelease(
        course_id=course.id,
        version_number=1,
        created_by=teacher_user.id,
        avatar_preset_id="platform-instructor-v2",
        avatar_preset_version="1.0.0",
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
