import asyncio
import importlib

import pytest

from app.models.video_generation_model import GenerationStatus, VideoGenerationTask
from app.services.ppt_generation_service import PPTGenerationService
from app.services.qa_service import QAService
from fakes import (
    BUSINESS_FAILURE_MESSAGE,
    FakeDigitalHumanClient,
    FakeLLMClient,
    FakePPTClient,
    FakeTTSClient,
)
from test_m4b_main_flows import _create_course_graph, _create_user, _headers


def test_r1_qa_llm_adapter_success_and_failures(monkeypatch):
    qa_service_module = importlib.import_module("app.services.qa_service")

    async def run_checks():
        monkeypatch.setattr(qa_service_module, "llm_client", FakeLLMClient("success"))
        answer = await QAService().ask_question("What is binary search?", context_content="course")
        assert answer == "fake llm response"

        monkeypatch.setattr(qa_service_module, "llm_client", FakeLLMClient("business_failure"))
        with pytest.raises(RuntimeError) as business_exc:
            await QAService().ask_question("What is binary search?", context_content="course")
        assert "LLM" in str(business_exc.value)

        monkeypatch.setattr(qa_service_module, "llm_client", FakeLLMClient("timeout"))
        with pytest.raises(RuntimeError) as timeout_exc:
            await QAService().ask_question("What is binary search?", context_content="course")
        assert "timeout" in str(timeout_exc.value).lower()

    asyncio.run(run_checks())


def test_r1_ppt_adapter_migration_success_business_failure_and_timeout(test_artifact_dir, monkeypatch):
    async def fake_expand(*args, **kwargs):
        return "fake teaching script"

    async def run_checks():
        success_service = PPTGenerationService()
        success_service.ppt_storage_path = str(test_artifact_dir / "success")
        success_service.xfyun_client = FakePPTClient("success")
        monkeypatch.setattr(success_service, "expand_to_teaching_script", fake_expand)

        success = await success_service.generate_ppt(
            topic="R1 PPT Success",
            template_id="fake-template",
        )
        assert success.status == "done"
        assert success.ppt_file_path.endswith(".pptx")

        failure_service = PPTGenerationService()
        failure_service.ppt_storage_path = str(test_artifact_dir / "failure")
        failure_service.xfyun_client = FakePPTClient("business_failure")
        monkeypatch.setattr(failure_service, "expand_to_teaching_script", fake_expand)

        failure = await failure_service.generate_ppt(
            topic="R1 PPT Failure",
            template_id="fake-template",
        )
        assert failure.status == "failed"
        assert failure.error == BUSINESS_FAILURE_MESSAGE

        timeout_service = PPTGenerationService()
        timeout_service.ppt_storage_path = str(test_artifact_dir / "timeout")
        timeout_service.xfyun_client = FakePPTClient("timeout")
        monkeypatch.setattr(timeout_service, "expand_to_teaching_script", fake_expand)

        timeout = await timeout_service.generate_ppt(
            topic="R1 PPT Timeout",
            template_id="fake-template",
        )
        assert timeout.status == "failed"
        assert "timeout" in timeout.error.lower()

    asyncio.run(run_checks())


def test_r1_document_tts_adapter_business_failure_is_not_success(client, session, monkeypatch, test_artifact_dir):
    from app.models.course_model import CourseStatus
    from app.models.user_model import UserRole
    document_endpoint = importlib.import_module("app.api.v1.endpoints.document")
    tts_module = importlib.import_module("app.common.tts_client")

    teacher = _create_user(session, UserRole.TEACHER, "r1_tts_teacher")
    course, _, nodes, _ = _create_course_graph(session, teacher, status=CourseStatus.PUBLISHED)
    monkeypatch.setattr(document_endpoint, "AUDIO_STORAGE_DIR", test_artifact_dir / "document_audio")
    monkeypatch.setattr(tts_module, "tts_client", FakeTTSClient("business_failure"))

    response = client.post(
        f"/api/v1/document/course/{course.id}/node/{nodes[0].id}/synthesize-audio",
        headers=_headers(teacher),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 500
    assert BUSINESS_FAILURE_MESSAGE in payload["message"]


def test_r1_video_service_digital_human_business_failure_stays_failed(session, monkeypatch, test_artifact_dir):
    from app.models.course_model import CourseStatus
    from app.models.user_model import UserRole
    import app.services.video_generation_service as video_service_module

    teacher = _create_user(session, UserRole.TEACHER, "r1_video_teacher")
    _, _, nodes, _ = _create_course_graph(session, teacher, status=CourseStatus.PUBLISHED)

    monkeypatch.setattr(video_service_module, "AUDIO_ROOT", test_artifact_dir / "video_audio")
    monkeypatch.setattr(video_service_module, "GENERATED_ROOT", test_artifact_dir / "video_generated")
    monkeypatch.setattr(video_service_module, "tts_client", FakeTTSClient("success"))
    monkeypatch.setattr(video_service_module, "digital_human_client", FakeDigitalHumanClient("business_failure"))

    async def fake_resolve_face_video(face_video_asset_id, node, session):
        face_path = test_artifact_dir / "face.mp4"
        face_path.write_bytes(b"FAKE_FACE_VIDEO")
        return str(face_path)

    monkeypatch.setattr(video_service_module.video_generation_service, "_resolve_face_video", fake_resolve_face_video)

    task = asyncio.run(
        video_service_module.video_generation_service.generate_node_video(
            node_id=nodes[0].id,
            session=session,
            force=True,
        )
    )

    assert task.status == GenerationStatus.FAILED
    assert task.dh_video_path in (None, "")
    assert BUSINESS_FAILURE_MESSAGE in task.error_message
    stored = session.get(VideoGenerationTask, task.id)
    assert stored.status == GenerationStatus.FAILED
