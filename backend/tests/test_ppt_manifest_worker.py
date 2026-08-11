"""Regression tests for the asynchronous, cache-first PPT manifest worker."""
from __future__ import annotations

import asyncio
import json

from sqlmodel import Session, select

from app.core.security import create_access_token, get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.media_release_model import MediaGenerationJob, MediaGenerationJobType, MediaGenerationStatus
from app.models.task_model import TaskRecord
from app.models.user_model import User, UserRole
from app.platform.tasks.handlers import media_ppt_manifest_handler
from app.platform.tasks.worker import TaskHandlerContext
from app.services.media_release_service import (
    media_generation_job_service,
    media_release_service,
)
from app.services.course_access_service import establish_course_access_baseline
from app.services.task_service import task_service


def _draft_course(session, *, fixture_key: str) -> tuple[User, Course]:
    teacher = User(
        username=f"ppt-manifest-worker-teacher-{fixture_key}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
    )
    session.add(teacher)
    session.flush()
    course = Course(
        fanya_course_id=f"ppt-manifest-worker-course-{fixture_key}",
        fanya_course_name="PPT manifest worker course",
        title="PPT manifest worker course",
        teacher_id=teacher.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    establish_course_access_baseline(session, course.id, teacher.id)
    return teacher, course


def test_ppt_manifest_worker_persists_safe_page_progress(session, monkeypatch):
    """The HTTP layer can poll progress without running LibreOffice itself."""
    teacher, course = _draft_course(session, fixture_key="worker")
    release = media_release_service.create_release(
        session,
        course_id=course.id,
        created_by=teacher.id,
        label="PPT manifest fixture",
    )
    job, task_id = media_generation_job_service.create_job(
        session,
        course_id=course.id,
        job_type=MediaGenerationJobType.PPT_MANIFEST,
        created_by=teacher.id,
        provider_key="ppt-source-cache",
        provider_version="ppt-manifest/v1",
        input_summary="fixture PPT manifest",
        input_payload={"course_id": course.id, "release_id": release.release_id},
        input_hash="fixture-input",
        idempotency_key="ppt-manifest-worker-fixture",
        media_release_id=release.release_id,
    )
    session.commit()

    def fake_build(session, *, course_id, release, progress_callback=None, **_kwargs):
        assert course_id == course.id
        if progress_callback:
            progress_callback({
                "stage": "checking_cache",
                "completed_pages": 60,
                "total_pages": 62,
                "cached_pages": 60,
                "missing_pages": 2,
                "deck_count": 2,
            })
            progress_callback({
                "stage": "rendering_pages",
                "completed_pages": 62,
                "total_pages": 62,
                "cached_pages": 60,
                "missing_pages": 2,
                "deck_count": 2,
            })
        release.ppt_manifest_object_key = "media-release/course/ppt-manifest-fixture.json"
        session.add(release)
        return {
            "schema": "ppt-manifest/v1",
            "pages": [{"page": 1}, {"page": 2}],
            "decks": [{"material_version_id": "fixture-deck"}],
        }

    import app.services.ppt_manifest_service as manifest_service
    monkeypatch.setattr(manifest_service, "build_ppt_manifest", fake_build)

    engine = session.get_bind()
    asyncio.run(media_ppt_manifest_handler(TaskHandlerContext(
        task_id=task_id,
        input_payload={
            "course_id": course.id,
            "release_id": release.release_id,
            "job_id": job.job_id,
        },
        session_factory=lambda: Session(engine),
        service=task_service,
    )))

    session.expire_all()
    completed = media_generation_job_service.get_job(
        session, course_id=course.id, job_id=job.job_id,
    )
    assert completed.status == MediaGenerationStatus.SUCCEEDED
    assert completed.output_metadata["page_progress"] == {
        "stage": "completed",
        "completed_pages": 62,
        "total_pages": 62,
        "cached_pages": 60,
        "missing_pages": 2,
        "deck_count": 2,
    }
    task = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).first()
    assert task.status == "succeeded"
    assert task.progress == 100


def test_ppt_manifest_endpoint_only_enqueues_worker(client, session, monkeypatch):
    """Submitting the manifest returns a task instead of rendering in HTTP."""
    teacher, course = _draft_course(session, fixture_key="endpoint")
    release = media_release_service.create_release(
        session,
        course_id=course.id,
        created_by=teacher.id,
        label="PPT manifest endpoint fixture",
    )
    session.commit()

    from app.platform.tasks.worker import local_task_worker
    submitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(local_task_worker, "has_handler", lambda task_type: task_type == "media.ppt_manifest")
    monkeypatch.setattr(
        local_task_worker,
        "submit",
        lambda _factory, task_id, payload: submitted.append((task_id, payload)),
    )
    token = create_access_token({
        "sub": str(teacher.id),
        "username": teacher.username,
        "role": teacher.role.value,
        "school_id": "test-school",
    })
    response = client.post(
        f"/api/v1/media/course/{course.id}/releases/{release.release_id}/ppt-manifest",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 202
    assert body["data"]["async"] is True
    assert body["data"]["job_type"] == "ppt_manifest"
    assert len(submitted) == 1
    assert submitted[0][1]["release_id"] == release.release_id
    stored = session.exec(select(MediaGenerationJob).where(
        MediaGenerationJob.job_id == body["data"]["job_id"],
    )).one()
    assert stored.input_payload["job_id"] == stored.job_id


def test_interrupted_manifest_task_is_requeued_after_restart(session):
    """A restart must not leave the media page in a permanent running state."""
    teacher, course = _draft_course(session, fixture_key="recovery")
    release = media_release_service.create_release(
        session,
        course_id=course.id,
        created_by=teacher.id,
        label="PPT manifest recovery fixture",
    )
    job, task_id = media_generation_job_service.create_job(
        session,
        course_id=course.id,
        job_type=MediaGenerationJobType.PPT_MANIFEST,
        created_by=teacher.id,
        provider_key="ppt-source-cache",
        provider_version="ppt-manifest/v1",
        input_summary="recovery fixture",
        input_payload={"course_id": course.id, "release_id": release.release_id},
        input_hash="recovery-input",
        idempotency_key="ppt-manifest-recovery-fixture",
        media_release_id=release.release_id,
    )
    payload = {"course_id": course.id, "release_id": release.release_id, "job_id": job.job_id}
    task = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).one()
    task.status = "interrupted"
    task.input_payload = json.dumps(payload)
    job.status = MediaGenerationStatus.RUNNING
    session.add(task)
    session.add(job)
    session.commit()

    class _RecordingWorker:
        def __init__(self):
            self.submissions: list[tuple[str, dict]] = []

        def submit(self, _session_factory, recovered_task_id, recovered_payload):
            self.submissions.append((recovered_task_id, recovered_payload))

    from app.platform.tasks.media_manifest_queue import recover_media_manifest_tasks
    worker = _RecordingWorker()
    engine = session.get_bind()
    recovered = asyncio.run(recover_media_manifest_tasks(lambda: Session(engine), worker))

    assert recovered == 1
    assert worker.submissions == [(task_id, payload)]
    session.expire_all()
    assert session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).one().status == "pending"
    assert media_generation_job_service.get_job(
        session, course_id=course.id, job_id=job.job_id,
    ).status == MediaGenerationStatus.PENDING


def test_activation_never_starts_sync_ppt_render(client, session):
    """A release with a declared deck must wait for the worker output."""
    teacher, course = _draft_course(session, fixture_key="activation-gate")
    course.source_file_path = "source-material/course/deck.pptx"
    course.source_file_name = "deck.pptx"
    session.add(course)
    release = media_release_service.create_release(
        session,
        course_id=course.id,
        created_by=teacher.id,
        label="PPT activation gate fixture",
    )
    session.commit()
    token = create_access_token({
        "sub": str(teacher.id),
        "username": teacher.username,
        "role": teacher.role.value,
        "school_id": "test-school",
    })
    response = client.post(
        f"/api/v1/media/course/{course.id}/releases/{release.release_id}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["data"]["details"]["error_code"] == "PPT_MANIFEST_PENDING"
