"""P2 tests: Provider timing becomes immutable release-scoped Cue assets.

All audio bytes and timing fixtures are local.  No test calls a TTS Provider.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import CoursePptMapping
from app.models.media_release_model import (
    MediaGenerationJobType,
    MediaGenerationStatus,
    MediaRelease,
)
from app.platform.tasks.handlers import media_timeline_publish_handler
from app.platform.tasks.worker import TaskHandlerContext
from app.services.avatar_cue_service import AVATAR_CUES_SCHEMA, load_avatar_cue_manifest
from app.services.course_access_service import establish_course_access_baseline
from app.services.media_release_service import (
    media_generation_job_service,
    media_playback_service,
    media_release_service,
)
from app.services.object_storage import get_object_storage, reset_object_storage_for_tests
from app.services.task_service import task_service


@pytest.fixture(autouse=True)
def _reset_storage():
    reset_object_storage_for_tests()
    yield
    reset_object_storage_for_tests()


def _course(session: Session, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id=f"p2-cue-{teacher_id}",
        fanya_course_name="P2 Cue Course",
        title="P2 Cue Course",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_id)
    session.commit()
    return course


def test_cue_worker_freezes_audio_bound_manifests_and_blocks_active_mutation(session, teacher_user):
    course = _course(session, teacher_user.id)
    storage = get_object_storage()
    audio_key = f"tts/course_{course.id}/p2-fixture.mp3"
    audio_sha = storage.put(audio_key, b"local-p2-audio", mime_type="audio/mpeg")

    # Mapping can contain multiple teacher-selected pages.  P2 freezes the
    # current selection and marks its within-node distribution as an estimate.
    mapping = CoursePptMapping(
        course_id=course.id,
        outline_node_id="outline-kp-1",
        page_start=4,
        page_end=5,
        page_refs=[4, 5],
        confidence=0.9,
        teacher_locked=True,
        created_by=teacher_user.id,
    )
    session.add(mapping)
    session.commit()

    source_job, _source_task_id = media_generation_job_service.create_job(
        session,
        course_id=course.id,
        job_type=MediaGenerationJobType.TTS,
        created_by=teacher_user.id,
        node_id=1,
        provider_key="fixture",
        provider_version="fixture-v1",
        idempotency_key="p2-source-audio",
    )
    media_generation_job_service.mark_running(
        session, course_id=course.id, job_id=source_job.job_id, stage="fixture_tts",
    )
    media_generation_job_service.mark_succeeded(
        session,
        course_id=course.id,
        job_id=source_job.job_id,
        output_object_key=audio_key,
        output_metadata={
            "audio_object_key": audio_key,
            "audio_sha256": audio_sha,
            "duration_ms": 2_000,
            "provider_key": "fixture",
            "provider_version": "fixture-v1",
            "subtitle_segments": [
                {"text": "第一页讲解。", "start_ms": 0, "end_ms": 800, "sentence_index": 0},
                {"text": "第二页讲解。", "start_ms": 1_000, "end_ms": 1_800, "sentence_index": 1},
            ],
            "timing_metadata": {
                "timing_source": "provider_word_timing",
                "timing_error_ms": 20,
                "word_timings": [
                    {"text": "第一页", "start_ms": 0, "end_ms": 400},
                    {"text": "讲解", "start_ms": 400, "end_ms": 800},
                    {"text": "第二页", "start_ms": 1_000, "end_ms": 1_400},
                    {"text": "讲解", "start_ms": 1_400, "end_ms": 1_800},
                ],
            },
        },
    )
    release = media_release_service.create_release(
        session,
        course_id=course.id,
        created_by=teacher_user.id,
        label="P2 fixture",
    )
    cue_job, cue_task_id = media_generation_job_service.create_job(
        session,
        course_id=course.id,
        job_type=MediaGenerationJobType.TIMELINE_PUBLISH,
        created_by=teacher_user.id,
        node_id=source_job.node_id,
        provider_key="avatar-cues",
        provider_version="v1",
        idempotency_key="p2-cue-freeze",
        media_release_id=release.release_id,
    )
    session.commit()

    engine = session.get_bind()
    asyncio.run(media_timeline_publish_handler(TaskHandlerContext(
        task_id=cue_task_id,
        input_payload={
            "course_id": course.id,
            "release_id": release.release_id,
            "source_tts_job_id": source_job.job_id,
            "outline_node_id": "outline-kp-1",
        },
        session_factory=lambda: Session(engine),
        service=task_service,
    )))

    session.expire_all()
    finished = media_generation_job_service.get_job(
        session, course_id=course.id, job_id=cue_job.job_id,
    )
    assert finished.status == MediaGenerationStatus.SUCCEEDED
    assert finished.output_metadata["viseme_count"] == 0
    assert finished.output_metadata["timing_source"] == "provider_word_timing"

    frozen_release = session.exec(select(MediaRelease).where(
        MediaRelease.release_id == release.release_id,
    )).one()
    assert frozen_release.audio_object_key == audio_key
    assert frozen_release.release_metadata["audio_sha256"] == audio_sha
    assert frozen_release.subtitle_manifest_object_key
    assert frozen_release.avatar_cues_object_key
    manifest = load_avatar_cue_manifest(storage, frozen_release.avatar_cues_object_key)
    assert manifest["schema"] == AVATAR_CUES_SCHEMA
    assert manifest["audio"]["sha256"] == audio_sha
    assert manifest["timing"]["precision"] == "word"
    assert manifest["visemes"] == []
    assert any(item["state"] == "silence" for item in manifest["mouth_activity"])

    cues = media_release_service.list_release_cues(
        session, course_id=course.id, release_id=release.release_id,
    )
    assert [cue.ppt_page for cue in cues] == [4, 5]
    assert cues[0].cue_metadata["ppt_timing_source"] == "mapping_sequence_estimate"

    # The P2 binding is checked again at activation, then the release cannot
    # be re-frozen or silently pointed to a different timing result.
    active = media_release_service.activate_release(
        session, course_id=course.id, release_id=release.release_id,
    )
    assert active.status.value == "active"
    playback = media_playback_service.get_current_playback(session, course_id=course.id)
    assert playback["avatar_cues"]["schema"] == AVATAR_CUES_SCHEMA
    assert playback["avatar_cues"]["precision"] == "word"
    assert playback["avatar_cues"]["manifest_url"]
    with pytest.raises(HTTPException) as exc_info:
        media_release_service.freeze_cue_snapshot(
            session,
            course_id=course.id,
            release_id=release.release_id,
            cue_rows=[],
        )
    assert exc_info.value.status_code == 409


def test_cue_worker_keeps_failure_honest_when_tts_has_no_node(session, teacher_user):
    course = _course(session, teacher_user.id)
    source_job, _source_task_id = media_generation_job_service.create_job(
        session,
        course_id=course.id,
        job_type=MediaGenerationJobType.TTS,
        created_by=teacher_user.id,
        idempotency_key="p2-source-without-node",
    )
    media_generation_job_service.mark_running(
        session, course_id=course.id, job_id=source_job.job_id, stage="fixture_tts",
    )
    media_generation_job_service.mark_succeeded(
        session,
        course_id=course.id,
        job_id=source_job.job_id,
        output_object_key="tts/unused.mp3",
        output_metadata={"audio_sha256": "not-used", "duration_ms": 1},
    )
    release = media_release_service.create_release(
        session, course_id=course.id, created_by=teacher_user.id,
    )
    cue_job, cue_task_id = media_generation_job_service.create_job(
        session,
        course_id=course.id,
        job_type=MediaGenerationJobType.TIMELINE_PUBLISH,
        created_by=teacher_user.id,
        idempotency_key="p2-cue-without-node",
        media_release_id=release.release_id,
    )
    session.commit()

    engine = session.get_bind()
    asyncio.run(media_timeline_publish_handler(TaskHandlerContext(
        task_id=cue_task_id,
        input_payload={
            "course_id": course.id,
            "release_id": release.release_id,
            "source_tts_job_id": source_job.job_id,
        },
        session_factory=lambda: Session(engine),
        service=task_service,
    )))
    session.expire_all()
    failed = media_generation_job_service.get_job(session, course_id=course.id, job_id=cue_job.job_id)
    assert failed.status == MediaGenerationStatus.FAILED
    assert failed.error_code == "TTS_JOB_NODE_REQUIRED"
    assert failed.output_object_key is None
