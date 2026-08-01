"""Local-only checks for the Doubao TTS Provider boundary.

These tests replace the WebSocket client with a deterministic fixture.  They
must never contact the billable provider.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlmodel import Session

from app.models.course_model import Course, CourseStatus
from app.models.media_release_model import MediaGenerationJobType, MediaGenerationStatus
from app.platform.tasks.handlers import media_tts_handler
from app.platform.tasks.worker import TaskHandlerContext
from app.services.media_release_service import media_generation_job_service
from app.services.object_storage import get_object_storage, reset_object_storage_for_tests
from app.services.task_service import task_service
from app.services.tts_provider import (
    SubtitleSegment,
    TTSProvider,
    TtsProviderConfigurationError,
    TtsSynthesisRequest,
    TtsSynthesisResult,
    VolcengineDoubaoTtsProvider,
    _subtitle_segments_from_doubao_words,
    get_tts_provider,
    register_tts_provider,
    reset_tts_registry_for_tests,
)
from app.services.volcengine_tts_v3 import VolcengineTtsV3Result


@pytest.fixture(autouse=True)
def _reset_tts_state():
    reset_tts_registry_for_tests()
    reset_object_storage_for_tests()
    yield
    reset_tts_registry_for_tests()
    reset_object_storage_for_tests()


def _configure_doubao(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.VOLCENGINE_DOUBAO_TTS_API_KEY", "test-api-key")
    monkeypatch.setattr("app.core.config.settings.VOLCENGINE_DOUBAO_TTS_RESOURCE_ID", "seed-tts-2.0")
    monkeypatch.setattr("app.core.config.settings.VOLCENGINE_DOUBAO_TTS_SPEAKER", "test-speaker")
    monkeypatch.setattr("app.core.config.settings.VOLCENGINE_DOUBAO_TTS_FORMAT", "mp3")
    monkeypatch.setattr("app.core.config.settings.VOLCENGINE_DOUBAO_TTS_SAMPLE_RATE", 24000)
    monkeypatch.setattr("app.core.config.settings.VOLCENGINE_DOUBAO_TTS_ENABLE_SUBTITLE", True)


def test_doubao_provider_normalizes_word_timing_and_never_persists_speaker(monkeypatch):
    _configure_doubao(monkeypatch)

    class FixtureClient:
        def __init__(self, config):
            self.config = config

        def synthesize(self, text):
            assert text == "第一句。第二句！"
            return VolcengineTtsV3Result(
                audio_bytes=b"fixture-mp3-bytes",
                words=[
                    {"word": "第一句。", "startTime": 0.0, "endTime": 0.8},
                    {"word": "第二句！", "startTime": 0.9, "endTime": 1.7},
                ],
                phoneme_count=0,
                duration_ms=1700,
            )

    monkeypatch.setattr("app.services.volcengine_tts_v3.VolcengineTtsV3Client", FixtureClient)
    provider = VolcengineDoubaoTtsProvider()
    result = provider.synthesize(TtsSynthesisRequest(
        script_text="第一句。第二句！",
        course_id=17,
        idempotency_key="fixture-job",
    ))

    assert provider.requires_async_worker is True
    assert provider.health_check() is True
    assert result.duration_ms == 1700
    assert [(s.text, s.start_ms, s.end_ms) for s in result.subtitle_segments] == [
        ("第一句。", 0, 800),
        ("第二句！", 900, 1700),
    ]
    assert result.timing_metadata["word_count"] == 2
    assert result.timing_metadata["phoneme_count"] == 0
    assert all("test-speaker" not in str(value) for value in result.timing_metadata.values())
    assert get_object_storage().get(result.audio_object_key) == b"fixture-mp3-bytes"


def test_doubao_cache_key_changes_when_non_secret_output_configuration_changes(monkeypatch):
    _configure_doubao(monkeypatch)
    provider = VolcengineDoubaoTtsProvider()
    request = TtsSynthesisRequest(script_text="同一讲稿", course_id=1)
    first = provider.cache_key(request)
    monkeypatch.setattr("app.core.config.settings.VOLCENGINE_DOUBAO_TTS_SAMPLE_RATE", 16000)
    second = provider.cache_key(request)
    assert first != second


def test_subtitle_word_grouping_ignores_invalid_timing():
    segments = _subtitle_segments_from_doubao_words([
        {"word": "有效。", "startTime": 0.0, "endTime": 0.5},
        {"word": "坏", "startTime": "bad", "endTime": 1.0},
    ])
    assert [(s.text, s.start_ms, s.end_ms) for s in segments] == [("有效。", 0, 500)]


def test_strict_lookup_does_not_fall_back_to_fake_for_generation():
    with pytest.raises(TtsProviderConfigurationError):
        get_tts_provider("not-a-provider", strict=True)


def test_media_tts_handler_executes_worker_only_provider_off_request_loop(session, teacher_user):
    """The durable media handler uses an independent session in a worker thread."""
    class WorkerOnlyFixtureProvider(TTSProvider):
        provider_key = "worker_fixture"
        provider_version = "worker-fixture-v1"
        requires_async_worker = True

        def synthesize(self, request):
            key = f"tts/course_{request.course_id}/worker-fixture.mp3"
            sha = get_object_storage().put(key, b"worker-fixture-audio", mime_type="audio/mpeg")
            return TtsSynthesisResult(
                audio_object_key=key,
                duration_ms=400,
                subtitle_segments=[SubtitleSegment(text="测试", start_ms=0, end_ms=400)],
                audio_sha256=sha,
                provider_key=self.provider_key,
                provider_version=self.provider_version,
            )

    register_tts_provider("worker_fixture", WorkerOnlyFixtureProvider())
    course = Course(
        fanya_course_id="doubao-worker-fixture",
        fanya_course_name="Worker fixture",
        title="Worker fixture",
        teacher_id=teacher_user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    job, task_id = media_generation_job_service.create_job(
        session,
        course_id=course.id,
        job_type=MediaGenerationJobType.TTS,
        created_by=teacher_user.id,
        provider_key="worker_fixture",
        input_summary="worker fixture",
        idempotency_key="worker-fixture",
    )
    session.commit()

    engine = session.get_bind()
    asyncio.run(media_tts_handler(TaskHandlerContext(
        task_id=task_id,
        input_payload={
            "course_id": course.id,
            "job_id": job.job_id,
            "script_text": "测试",
            "provider_key": "worker_fixture",
        },
        session_factory=lambda: Session(engine),
        service=task_service,
    )))

    session.expire_all()
    refreshed = media_generation_job_service.get_job(session, course_id=course.id, job_id=job.job_id)
    assert refreshed.status == MediaGenerationStatus.SUCCEEDED
    assert refreshed.output_metadata["provider_key"] == "worker_fixture"
