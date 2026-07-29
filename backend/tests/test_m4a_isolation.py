import asyncio
import socket

import pytest
from sqlmodel import Session, select

from app.models.user_model import User, UserRole
from fakes import FakeDigitalHumanClient, FakeLLMClient, FakePPTClient, FakeTTSClient, FakeVoiceCloneClient


async def _call_fake(fake, method_name, *args, **kwargs):
    method = getattr(fake, method_name)
    return await method(*args, **kwargs)


def test_app_import_is_safe_and_startup_side_effects_are_skipped(fastapi_app):
    assert fastapi_app.state.startup_side_effects_skipped is True


def test_app_registers_durable_parse_handler_when_startup_side_effects_are_skipped(fastapi_app):
    """Test-mode imports still need to execute queued local parse work."""
    from app.platform.tasks.worker import local_task_worker

    assert local_task_worker.has_handler("document_parse")
    assert fastapi_app.state.startup_dependency_report is None


def test_app_uses_test_database_and_never_production_database(temp_db_path):
    from app.models import database

    assert database.DATABASE_URL.startswith("sqlite:///")
    assert str(temp_db_path).replace("\\", "/") in database.DATABASE_URL
    assert database.DATABASE_URL != database.DEFAULT_DATABASE_URL
    assert str(database.PRODUCTION_DATABASE_PATH).replace("\\", "/") not in database.DATABASE_URL


def test_testclient_health_check_works_without_side_effects(client):
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert payload["data"]["version"] == "v1"


def test_temporary_database_can_create_models(session: Session, temp_db_path):
    user = User(
        username="m4a_db_guard",
        real_name="DB Guard",
        hashed_password="not-used",
        role=UserRole.STUDENT,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    fetched = session.exec(select(User).where(User.username == "m4a_db_guard")).first()
    assert fetched is not None
    assert fetched.id == user.id
    assert temp_db_path.exists()


def test_unmocked_external_network_call_is_blocked():
    with pytest.raises(RuntimeError, match="External network calls are blocked"):
        socket.create_connection(("example.com", 80), timeout=1)


def test_common_fakes_support_success_timeout_unavailable_and_malformed_modes(test_artifact_dir):
    async def run_checks():
        llm = FakeLLMClient("success")
        assert (await llm.chat([])).content == "fake llm response"
        assert llm.calls

        tts = FakeTTSClient("success")
        assert (await tts.synthesize("hello")).audio_data == b"FAKE_AUDIO"
        assert tts.calls

        voice_clone = FakeVoiceCloneClient("success")
        assert (await voice_clone.create_voice_clone("voice.wav"))["status"] == "success"

        ppt = FakePPTClient("success")
        assert (await ppt.get_theme_list())["data"]["records"][0]["templateIndexId"] == "fake-template"
        ppt_path = test_artifact_dir / "fake.pptx"
        await ppt.download_ppt("https://fake.invalid/fake.pptx", str(ppt_path))
        assert ppt_path.read_bytes() == b"FAKE_PPTX"

        digital = FakeDigitalHumanClient("success")
        assert await digital.check_health() is True
        assert (await digital.generate_video("audio.wav", "face.mp4")).video_path.endswith(".mp4")

        for fake, method_name, args in [
            (FakeLLMClient("timeout"), "chat", [[]]),
            (FakeTTSClient("timeout"), "synthesize", ["hello"]),
            (FakePPTClient("timeout"), "get_theme_list", []),
            (FakeDigitalHumanClient("timeout"), "check_health", []),
        ]:
            with pytest.raises(TimeoutError):
                await _call_fake(fake, method_name, *args)

        for fake, method_name, args in [
            (FakeLLMClient("service_unavailable"), "chat", [[]]),
            (FakeTTSClient("service_unavailable"), "synthesize", ["hello"]),
            (FakePPTClient("service_unavailable"), "get_theme_list", []),
            (FakeDigitalHumanClient("service_unavailable"), "check_health", []),
        ]:
            with pytest.raises(RuntimeError):
                await _call_fake(fake, method_name, *args)

        assert await FakeLLMClient("malformed").chat([]) == {"malformed": True}
        assert await FakeTTSClient("malformed").synthesize("hello") == {"malformed": True}
        assert await FakePPTClient("malformed").get_theme_list() == {"malformed": True}
        assert await FakeDigitalHumanClient("malformed").check_health() == {"malformed": True}

    asyncio.run(run_checks())


def test_fixture_users_and_tokens_are_available(teacher_user, student_user, teacher_token, student_token, temp_upload_dir, temp_media_dir):
    assert teacher_user.role == UserRole.TEACHER
    assert student_user.role == UserRole.STUDENT
    assert isinstance(teacher_token, str) and teacher_token
    assert isinstance(student_token, str) and student_token
    assert temp_upload_dir.exists()
    assert temp_media_dir.exists()
