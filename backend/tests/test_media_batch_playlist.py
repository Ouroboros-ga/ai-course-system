"""P4 batch-media and immutable playlist regression tests.

All synthesis work here uses the in-process Fake provider and local object
storage.  No test can reach a billable Provider.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.models.course_outline_model import CoursePptMapping, TeachingScriptNode
from app.models.media_release_model import (
    MediaGenerationJob,
    MediaGenerationJobType,
    MediaRelease,
    MediaReleaseItem,
    MediaReleaseStatus,
)
from app.services.media_batch_service import (
    build_media_plan,
    confirm_media_batch,
    freeze_playlist,
)
from app.services.media_release_service import (
    ensure_release_tts_assets_registered,
    media_generation_job_service,
    media_playback_service,
    media_release_service,
    tts_execution_service,
)
from app.services.object_storage import get_object_storage, reset_object_storage_for_tests
from app.services.tts_provider import reset_tts_registry_for_tests
from test_media_release import _course


@pytest.fixture(autouse=True)
def _reset_media_dependencies():
    reset_object_storage_for_tests()
    reset_tts_registry_for_tests()
    yield
    reset_object_storage_for_tests()
    reset_tts_registry_for_tests()


def _script(session, course_id: int, *, suffix: str, content: str) -> TeachingScriptNode:
    node = TeachingScriptNode(
        course_id=course_id,
        script_version_id=f"tsv_p4_{suffix}",
        outline_node_id=f"outline_p4_{suffix}",
        content=content,
    )
    session.add(node)
    session.flush()
    return node


def _mapped(session, course_id: int, node: TeachingScriptNode, created_by: int) -> None:
    session.add(CoursePptMapping(
        course_id=course_id,
        outline_node_id=node.outline_node_id,
        material_version_id=f"smv_p4_{node.id}",
        page_start=1,
        page_end=1,
        page_refs=[1],
        teacher_locked=True,
        status="published",
        created_by=created_by,
    ))
    session.flush()


def _complete_item(session, *, course_id: int, release_id: str, node: TeachingScriptNode, created_by: int, order: int) -> MediaReleaseItem:
    """Use the Fake provider and direct Cue result projection to make one ready item."""
    job, _ = media_generation_job_service.create_job(
        session,
        course_id=course_id,
        job_type=MediaGenerationJobType.TTS,
        created_by=created_by,
        node_id=node.id,
        provider_key="fake",
        provider_version="v1",
        idempotency_key=f"p4-ready-{release_id}-{node.id}",
        media_release_id=release_id,
    )
    job = tts_execution_service.execute_tts_job(
        session,
        course_id=course_id,
        job_id=job.job_id,
        script_text=node.content,
        voice_id="default",
        provider_key="fake",
        max_retries=1,
    )
    item = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.course_id == course_id,
        MediaReleaseItem.release_id == release_id,
        MediaReleaseItem.node_id == node.id,
    )).one()
    metadata = job.output_metadata
    item.status = "ready"
    item.audio_object_key = job.output_object_key
    item.audio_sha256 = metadata["audio_sha256"]
    item.duration_ms = metadata["duration_ms"]
    item.subtitle_manifest_object_key = f"subtitle-manifest/p4/{release_id}/{node.id}.json"
    item.avatar_cues_object_key = f"avatar-cues/p4/{release_id}/{node.id}.json"
    storage = get_object_storage()
    storage.put(item.subtitle_manifest_object_key, json.dumps({
        "schema": "subtitle-manifest/v1",
        "segments": metadata["subtitle_segments"],
    }).encode(), mime_type="application/json")
    storage.put(item.avatar_cues_object_key, b'{"schema":"avatar-cues/v1"}', mime_type="application/json")
    session.add(item)
    session.flush()
    return item


def test_legacy_draft_audio_is_registered_without_resynthesis(session, teacher_user):
    """A historical draft can regain guarded preview access without new TTS."""
    course = _course(session, teacher_user.id)
    release = media_release_service.create_release(
        session, course_id=course.id, created_by=teacher_user.id,
    )
    node = _script(session, course.id, suffix="legacy-ledger", content="旧草稿试听。")
    object_key = f"tts/course_{course.id}/legacy-preview.mp3"
    raw = b"legacy fake audio bytes"
    storage = get_object_storage()
    audio_sha = storage.put(object_key, raw, mime_type="audio/mpeg")
    session.add(MediaReleaseItem(
        release_id=release.release_id,
        course_id=course.id,
        node_id=node.id,
        outline_node_id=node.outline_node_id,
        order_index=0,
        script_hash="legacy",
        status="ready",
        audio_object_key=object_key,
        audio_sha256=audio_sha,
        duration_ms=1_000,
    ))
    session.commit()

    assert ensure_release_tts_assets_registered(
        session, course_id=course.id, release_id=release.release_id,
    ) == 1
    from app.models.media_timeline_model import MediaAsset
    asset = session.exec(select(MediaAsset).where(MediaAsset.object_key == object_key)).one()
    assert asset.course_id == course.id
    assert asset.content_hash == audio_sha
    assert storage.get(object_key) == raw
    assert ensure_release_tts_assets_registered(
        session, course_id=course.id, release_id=release.release_id,
    ) == 0


def test_batch_plan_is_read_only_and_rejects_client_provider_or_voice(session, teacher_user):
    course = _course(session, teacher_user.id)
    node = _script(session, course.id, suffix="plan", content="P4 计划只能核算，不能触发语音合成。")
    session.commit()

    plan = build_media_plan(session, course_id=course.id, node_ids=[node.id])
    assert plan["node_count"] == 1
    assert plan["billable_chars"] == len(node.content)
    assert session.exec(select(MediaGenerationJob).where(MediaGenerationJob.course_id == course.id)).all() == []

    with pytest.raises(HTTPException) as provider_error:
        build_media_plan(session, course_id=course.id, node_ids=[node.id], provider_key="mock_xfyun")
    assert provider_error.value.status_code == 422
    with pytest.raises(HTTPException) as voice_error:
        build_media_plan(session, course_id=course.id, node_ids=[node.id], voice_id="browser-forged-voice")
    assert voice_error.value.status_code == 422


def test_batch_plan_rejects_single_node_over_script_byte_cap(session, teacher_user):
    """核算阶段就拦截超长讲稿，而不是让核算通过后由 media.tts Worker 必然失败。"""
    course = _course(session, teacher_user.id)
    oversized = _script(session, course.id, suffix="too-long", content="超" * 4000)  # 12000 字节 > 8000
    session.commit()
    with pytest.raises(HTTPException) as too_long:
        build_media_plan(session, course_id=course.id, node_ids=[oversized.id])
    assert too_long.value.status_code == 422
    assert "8000" in str(too_long.value.detail)


def test_batch_plan_exposes_server_owned_caps(session, teacher_user):
    """计划回传服务端权威上限，供 UI 展示，避免前端硬编码与后端不一致。"""
    from app.core.config import settings
    course = _course(session, teacher_user.id)
    node = _script(session, course.id, suffix="caps", content="核算上限展示。")
    session.commit()
    plan = build_media_plan(session, course_id=course.id, node_ids=[node.id])
    assert plan["max_chars"] == settings.MEDIA_BATCH_MAX_BILLABLE_CHARS
    assert plan["max_script_bytes"] == settings.TTS_MAX_SCRIPT_BYTES
    assert plan["billable_chars"] == len(node.content)


def test_batch_confirmation_reuses_cached_audio_without_new_synthesis(session, teacher_user):
    course = _course(session, teacher_user.id)
    node = _script(session, course.id, suffix="cache", content="缓存命中不再次调用 TTS。")
    session.commit()
    source, _ = media_generation_job_service.create_job(
        session,
        course_id=course.id,
        job_type=MediaGenerationJobType.TTS,
        created_by=teacher_user.id,
        node_id=node.id,
        provider_key="fake",
        provider_version="fake-v1",
        idempotency_key="p4-cache-source",
    )
    tts_execution_service.execute_tts_job(
        session, course_id=course.id, job_id=source.job_id, script_text=node.content,
        voice_id="default", provider_key="fake", max_retries=1,
    )
    session.commit()

    plan = build_media_plan(session, course_id=course.id, node_ids=[node.id])
    assert plan["cache_hit_count"] == 1
    batch, release, jobs = confirm_media_batch(
        session, course_id=course.id, created_by=teacher_user.id, plan=plan,
        idempotency_key="p4-cache-batch",
    )
    assert batch.estimate["billable_chars"] == 0
    assert len(jobs) == 1
    copied = media_generation_job_service.get_job(session, course_id=course.id, job_id=jobs[0].job_id)
    assert copied.output_metadata["cache_hit"] is True
    assert copied.output_metadata["cache_source_job_id"] == source.job_id
    assert copied.output_object_key == source.output_object_key
    item = session.exec(select(MediaReleaseItem).where(MediaReleaseItem.release_id == release.release_id)).one()
    assert item.status == "tts_succeeded"
    assert item.audio_object_key == source.output_object_key


def test_batch_plan_uses_course_teaching_order_not_outline_identifier_order(session, teacher_user):
    course = _course(session, teacher_user.id)
    first = _script(session, course.id, suffix="tree-first", content="先讲。")
    second = _script(session, course.id, suffix="tree-second", content="后讲。")
    from app.models.course_outline_model import CourseOutlineNode, CourseOutlineVersion, OutlineLifecycleStatus
    outline = CourseOutlineVersion(
        course_id=course.id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
    )
    session.add(outline)
    session.flush()
    # Deliberately choose opaque IDs whose lexical order disagrees with the
    # teacher's teaching order; playlist offsets must follow the latter.
    session.add_all([
        CourseOutlineNode(
            course_id=course.id, outline_version_id=outline.outline_version_id,
            outline_node_id=second.outline_node_id, title="后讲", order_index=20,
        ),
        CourseOutlineNode(
            course_id=course.id, outline_version_id=outline.outline_version_id,
            outline_node_id=first.outline_node_id, title="先讲", order_index=10,
        ),
    ])
    session.commit()

    plan = build_media_plan(session, course_id=course.id, node_ids=[second.id, first.id])
    assert [item["node_id"] for item in plan["items"]] == [first.id, second.id]
    assert [item["order_index"] for item in plan["items"]] == [0, 1]


def test_batch_plan_uses_preorder_across_multiple_chapters(session, teacher_user):
    course = _course(session, teacher_user.id)
    from app.models.course_outline_model import (
        CourseOutlineNode,
        CourseOutlineVersion,
        OutlineLifecycleStatus,
        TeachingScriptVersion,
        OutlineNodeType,
    )

    outline = CourseOutlineVersion(
        course_id=course.id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
    )
    script_version = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
    )
    session.add_all([outline, script_version])
    session.flush()
    chapter_a = CourseOutlineNode(
        course_id=course.id, outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.CHAPTER, title="A", order_index=0,
    )
    chapter_b = CourseOutlineNode(
        course_id=course.id, outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.CHAPTER, title="B", order_index=1,
    )
    session.add_all([chapter_a, chapter_b])
    session.flush()
    ordered_ids = []
    scripts = []
    for parent, suffix in ((chapter_a, "a1"), (chapter_a, "a2"), (chapter_b, "b1"), (chapter_b, "b2")):
        node = CourseOutlineNode(
            course_id=course.id, outline_version_id=outline.outline_version_id,
            parent_node_id=parent.outline_node_id,
            node_type=OutlineNodeType.KNOWLEDGE_POINT,
            title=suffix, order_index=0 if suffix.endswith("1") else 1,
        )
        session.add(node)
        session.flush()
        ordered_ids.append(node.outline_node_id)
        script = TeachingScriptNode(
            course_id=course.id,
            script_version_id=script_version.script_version_id,
            outline_node_id=node.outline_node_id,
            content=suffix,
        )
        scripts.append(script)
        session.add(script)
    session.commit()

    plan = build_media_plan(
        session,
        course_id=course.id,
        node_ids=[script.id for script in reversed(scripts)],
    )
    assert [item["outline_node_id"] for item in plan["items"]] == ordered_ids


def test_freeze_playlist_uses_preorder_across_multiple_chapters(session, teacher_user):
    """Freezing must not reintroduce the old flat sibling order bug."""
    course = _course(session, teacher_user.id)
    from app.models.course_outline_model import (
        CourseOutlineNode,
        CourseOutlineVersion,
        OutlineLifecycleStatus,
        TeachingScriptVersion,
        OutlineNodeType,
    )

    outline = CourseOutlineVersion(course_id=course.id, version=1, lifecycle_status=OutlineLifecycleStatus.DRAFT)
    script_version = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
    )
    session.add_all([outline, script_version])
    session.flush()
    chapter_a = CourseOutlineNode(
        course_id=course.id, outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.CHAPTER, title="A", order_index=0,
    )
    chapter_b = CourseOutlineNode(
        course_id=course.id, outline_version_id=outline.outline_version_id,
        node_type=OutlineNodeType.CHAPTER, title="B", order_index=1,
    )
    session.add_all([chapter_a, chapter_b])
    session.flush()
    scripts = []
    for parent, suffix in ((chapter_a, "a1"), (chapter_a, "a2"), (chapter_b, "b1"), (chapter_b, "b2")):
        outline_node = CourseOutlineNode(
            course_id=course.id, outline_version_id=outline.outline_version_id,
            parent_node_id=parent.outline_node_id,
            node_type=OutlineNodeType.KNOWLEDGE_POINT, title=suffix,
            order_index=0 if suffix.endswith("1") else 1,
        )
        session.add(outline_node)
        session.flush()
        script = TeachingScriptNode(
            course_id=course.id, script_version_id=script_version.script_version_id,
            outline_node_id=outline_node.outline_node_id, content=suffix,
        )
        session.add(script)
        scripts.append(script)
    session.flush()
    release = MediaRelease(course_id=course.id, created_by=teacher_user.id, status=MediaReleaseStatus.DRAFT)
    release.ppt_manifest_object_key = "ppt-manifest/p4/preorder.json"
    session.add(release)
    session.flush()
    # This is the historically wrong cross-chapter flat SQL sequence.
    flat_order = [scripts[0], scripts[2], scripts[1], scripts[3]]
    storage = get_object_storage()
    for flat_rank, script in enumerate(flat_order):
        item = MediaReleaseItem(
            release_id=release.release_id, course_id=course.id, node_id=script.id,
            outline_node_id=script.outline_node_id, order_index=flat_rank,
            script_hash="preorder", status="ready", duration_ms=1_000,
            audio_object_key=f"tts/p4/{release.release_id}/{script.id}.mp3",
            audio_sha256="test", subtitle_manifest_object_key=f"subtitle/p4/{script.id}.json",
            avatar_cues_object_key=f"avatar/p4/{script.id}.json",
            ppt_mapping_snapshot={"mappings": [{
                "material_version_id": f"smv-{script.id}", "page_refs": [1],
            }]},
        )
        session.add(item)
    storage.put(release.ppt_manifest_object_key, json.dumps({
        "schema": "ppt-manifest/v1", "pages": [], "decks": [
            {"material_version_id": f"smv-{script.id}", "pages": [{"page": 1}]}
            for script in scripts
        ],
    }).encode(), mime_type="application/json")
    session.flush()

    frozen = freeze_playlist(session, course_id=course.id, release_id=release.release_id)
    assert [item["outline_node_id"] for item in frozen["items"]] == [script.outline_node_id for script in scripts]
    assert [item["offset_ms"] for item in frozen["items"]] == [0, 1_000, 2_000, 3_000]


def test_playlist_requires_every_ready_item_and_frozen_ppt_manifest(session, teacher_user):
    course = _course(session, teacher_user.id)
    first = _script(session, course.id, suffix="first", content="第一个知识点。")
    second = _script(session, course.id, suffix="second", content="第二个知识点。")
    _mapped(session, course.id, first, teacher_user.id)
    _mapped(session, course.id, second, teacher_user.id)
    session.commit()
    plan = build_media_plan(session, course_id=course.id, node_ids=[first.id, second.id])
    batch, release, _ = confirm_media_batch(
        session, course_id=course.id, created_by=teacher_user.id, plan=plan,
        idempotency_key="p4-freeze-gate",
    )
    release.ppt_manifest_object_key = "ppt-manifest/p4/frozen.json"
    ppt_manifest = {
        "schema": "ppt-manifest/v1",
        "pages": [],
        "decks": [
            {"material_version_id": f"smv_p4_{first.id}", "pages": [{"page": 1}]},
            {"material_version_id": f"smv_p4_{second.id}", "pages": [{"page": 1}]},
        ],
    }
    get_object_storage().put(
        release.ppt_manifest_object_key,
        json.dumps(ppt_manifest).encode(),
        mime_type="application/json",
    )
    session.add(release)
    _complete_item(session, course_id=course.id, release_id=release.release_id, node=first, created_by=teacher_user.id, order=0)
    session.flush()

    with pytest.raises(HTTPException) as incomplete:
        freeze_playlist(session, course_id=course.id, release_id=release.release_id)
    assert incomplete.value.status_code == 409
    remaining = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.release_id == release.release_id,
        MediaReleaseItem.node_id == second.id,
    )).one()
    assert remaining.status in {"pending", "tts_succeeded", "cached"}

    _complete_item(session, course_id=course.id, release_id=release.release_id, node=second, created_by=teacher_user.id, order=1)
    result = freeze_playlist(session, course_id=course.id, release_id=release.release_id)
    assert result["schema"] == "audio-playlist/v1"
    assert [item["node_id"] for item in result["items"]] == [first.id, second.id]
    assert result["items"][1]["offset_ms"] == result["items"][0]["duration_ms"]
    assert release.audio_playlist_sha256 == result["sha256"]
    assert release.audio_playlist_object_key

    release.status = MediaReleaseStatus.ACTIVE
    session.add(release)
    session.flush()
    with pytest.raises(HTTPException) as immutable:
        freeze_playlist(session, course_id=course.id, release_id=release.release_id)
    assert immutable.value.status_code == 409


def test_playlist_playback_projects_global_time_without_second_offset(session, teacher_user):
    course = _course(session, teacher_user.id)
    release = media_release_service.create_release(session, course_id=course.id, created_by=teacher_user.id)
    release.release_metadata = {"audio_playlist_mode": True}
    first = _script(session, course.id, suffix="playback-first", content="第一段。")
    second = _script(session, course.id, suffix="playback-second", content="第二段。")
    release.ppt_manifest_object_key = "ppt-manifest/p4/playback.json"
    storage = get_object_storage()
    storage.put(release.ppt_manifest_object_key, json.dumps({
        "schema": "ppt-manifest/v1",
        "pages": [],
        "decks": [
            {"material_version_id": "smv_first", "pages": [{"page": 1}]},
            {"material_version_id": "smv_second", "pages": [{"page": 2}, {"page": 3}]},
        ],
    }).encode(), mime_type="application/json")
    _mapped(session, course.id, first, teacher_user.id)
    _mapped(session, course.id, second, teacher_user.id)
    session.add_all([
        MediaReleaseItem(
            release_id=release.release_id, course_id=course.id, node_id=first.id,
            outline_node_id=first.outline_node_id, order_index=0, script_hash="first", status="ready",
            audio_object_key="tts/p4/first.mp3", audio_sha256="first", duration_ms=1_000,
            subtitle_manifest_object_key="subtitle/p4/first.json", avatar_cues_object_key="avatar/p4/first.json",
            ppt_mapping_snapshot={"mappings": [{"material_version_id": "smv_first", "page_refs": [1]}]},
        ),
        MediaReleaseItem(
            release_id=release.release_id, course_id=course.id, node_id=second.id,
            outline_node_id=second.outline_node_id, order_index=1, script_hash="second", status="ready",
            audio_object_key="tts/p4/second.mp3", audio_sha256="second", duration_ms=2_000,
            subtitle_manifest_object_key="subtitle/p4/second.json", avatar_cues_object_key="avatar/p4/second.json",
            ppt_mapping_snapshot={"mappings": [{"material_version_id": "smv_second", "page_refs": [2, 3]}]},
        ),
    ])
    for key in ["tts/p4/first.mp3", "tts/p4/second.mp3"]:
        storage.put(key, b"audio", mime_type="audio/mpeg")
    storage.put("subtitle/p4/first.json", json.dumps({
        "segments": [{"start_ms": 0, "end_ms": 900, "text": "第一段"}],
    }, ensure_ascii=False).encode(), mime_type="application/json")
    storage.put("subtitle/p4/second.json", json.dumps({
        "segments": [{"start_ms": 100, "end_ms": 1200, "text": "第二段"}],
    }, ensure_ascii=False).encode(), mime_type="application/json")
    for key in ["avatar/p4/first.json", "avatar/p4/second.json"]:
        storage.put(key, b'{"schema":"avatar-cues/v1"}', mime_type="application/json")
    session.flush()
    result = freeze_playlist(session, course_id=course.id, release_id=release.release_id)
    release.status = MediaReleaseStatus.ACTIVE
    session.add(release)
    session.commit()

    playback = media_playback_service.get_current_playback(session, course_id=course.id)
    frozen_items = list(session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.release_id == release.release_id,
    ).order_by(MediaReleaseItem.order_index)).all())
    # Item identity is part of the public frozen playback coordinate.  A
    # learner must never have to guess an item from a bare global timestamp.
    assert [item["item_id"] for item in result["items"]] == [item.item_id for item in frozen_items]
    assert [item["item_id"] for item in playback["playlist"]["items"]] == [item.item_id for item in frozen_items]
    assert playback["playlist"]["items"][1]["ppt_timeline"][0]["start_ms"] == 1_000
    assert playback["playlist"]["items"][1]["ppt_timeline"][1]["start_ms"] == 2_000
    assert playback["playlist"]["items"][1]["subtitle_segments"][0]["start_ms"] == 100
    assert result["duration_ms"] == 3_000
