import asyncio

import pytest
from sqlmodel import select

from app.common.digital_human_client import DigitalHumanError
from app.models.course_model import CourseStatus
from app.models.user_model import UserRole
from app.models.video_generation_model import GenerationStatus, VideoGenerationTask
from fakes import BUSINESS_FAILURE_MESSAGE, FakeDigitalHumanClient, FakeTTSClient
from test_m4b_main_flows import _create_course_graph, _create_user


async def _fake_resolve_face_video(face_video_asset_id, node, session):
    return "fake-face.mp4"


def _prepare_video_service(session, monkeypatch, test_artifact_dir, digital_human_mode: str):
    import app.services.video_generation_service as video_service_module

    teacher = _create_user(session, UserRole.TEACHER, f"r2b_video_{digital_human_mode}")
    _, _, nodes, _ = _create_course_graph(session, teacher, status=CourseStatus.PUBLISHED)

    monkeypatch.setattr(video_service_module, "AUDIO_ROOT", test_artifact_dir / f"audio_{digital_human_mode}")
    monkeypatch.setattr(video_service_module, "GENERATED_ROOT", test_artifact_dir / f"generated_{digital_human_mode}")
    monkeypatch.setattr(video_service_module, "tts_client", FakeTTSClient("success"))
    monkeypatch.setattr(video_service_module, "digital_human_client", FakeDigitalHumanClient(digital_human_mode))
    monkeypatch.setattr(video_service_module.video_generation_service, "_resolve_face_video", _fake_resolve_face_video)
    return video_service_module, nodes[0]


def test_r2b_video_task_success_maps_to_completed(session, monkeypatch, test_artifact_dir):
    video_service_module, node = _prepare_video_service(session, monkeypatch, test_artifact_dir, "success")

    task = asyncio.run(
        video_service_module.video_generation_service.generate_node_video(
            node_id=node.id,
            session=session,
            force=True,
        )
    )

    assert task.status == GenerationStatus.COMPLETED
    assert task.dh_video_path == "/tmp/fake-digital-human.mp4"
    assert task.error_message is None
    stored = session.get(VideoGenerationTask, task.id)
    assert stored.status == GenerationStatus.COMPLETED


def test_r2b_video_task_business_failure_maps_to_failed(session, monkeypatch, test_artifact_dir):
    video_service_module, node = _prepare_video_service(session, monkeypatch, test_artifact_dir, "business_failure")

    task = asyncio.run(
        video_service_module.video_generation_service.generate_node_video(
            node_id=node.id,
            session=session,
            force=True,
        )
    )

    assert task.status == GenerationStatus.FAILED
    assert task.dh_video_path in (None, "")
    assert BUSINESS_FAILURE_MESSAGE in task.error_message
    stored = session.get(VideoGenerationTask, task.id)
    assert stored.status == GenerationStatus.FAILED
    assert BUSINESS_FAILURE_MESSAGE in stored.error_message


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        ("timeout", "timeout"),
        ("service_unavailable", "unavailable"),
        ("malformed_response", "malformed"),
    ],
)
def test_r2b_video_task_non_success_modes_record_failed_status(
    session,
    monkeypatch,
    test_artifact_dir,
    mode,
    expected_error,
):
    video_service_module, node = _prepare_video_service(session, monkeypatch, test_artifact_dir, mode)

    with pytest.raises(DigitalHumanError):
        asyncio.run(
            video_service_module.video_generation_service.generate_node_video(
                node_id=node.id,
                session=session,
                force=True,
            )
        )

    stored = session.exec(
        select(VideoGenerationTask).where(VideoGenerationTask.node_id == node.id)
    ).first()
    assert stored is not None
    assert stored.status == GenerationStatus.FAILED
    assert expected_error in stored.error_message.lower()
    assert stored.dh_video_path in (None, "")
