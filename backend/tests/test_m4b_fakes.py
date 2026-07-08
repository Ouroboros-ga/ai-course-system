import asyncio
import json

import pytest

from fakes import (
    BUSINESS_FAILURE_MESSAGE,
    FakeDigitalHumanClient,
    FakeHTTPXClient,
    FakeLLMClient,
    FakePPTClient,
    FakeTTSClient,
    FakeVoiceCloneClient,
)


async def _expect_timeout(call):
    with pytest.raises(TimeoutError):
        await call()


async def _expect_service_unavailable(call):
    with pytest.raises(RuntimeError):
        await call()


def test_fake_llm_modes_are_stable():
    async def run_checks():
        success = await FakeLLMClient("success").chat([])
        assert success.content == "fake llm response"
        assert success.finish_reason == "stop"

        await _expect_timeout(lambda: FakeLLMClient("timeout").chat([]))
        await _expect_service_unavailable(lambda: FakeLLMClient("service_unavailable").chat([]))
        assert await FakeLLMClient("malformed_response").chat([]) == {"malformed": True}

        failure = await FakeLLMClient("business_failure").chat([])
        assert failure.content == ""
        assert failure.finish_reason == "business_failure"

        simple_failure = await FakeLLMClient("business_failure").simple_chat("generate")
        payload = json.loads(simple_failure)
        assert payload["status"] == "failed"
        assert payload["content"] == ""

    asyncio.run(run_checks())


def test_fake_tts_modes_are_stable():
    async def run_checks():
        success = await FakeTTSClient("success").synthesize("hello")
        assert success.audio_data == b"FAKE_AUDIO"

        await _expect_timeout(lambda: FakeTTSClient("timeout").synthesize("hello"))
        await _expect_service_unavailable(lambda: FakeTTSClient("service_unavailable").synthesize("hello"))
        assert await FakeTTSClient("malformed_response").synthesize("hello") == {"malformed": True}

        failure = await FakeTTSClient("business_failure").synthesize("hello")
        assert failure["status"] == "failed"
        assert failure["code"] == "TTS_SYNTHESIS_FAILED"
        assert failure["message"] == BUSINESS_FAILURE_MESSAGE
        assert failure["audio_data"] == b""

    asyncio.run(run_checks())


def test_fake_voice_clone_modes_are_stable():
    async def run_checks():
        success = await FakeVoiceCloneClient("success").create_voice_clone("voice.wav")
        assert success["status"] == "success"
        assert success["speaker_id"] == "fake-speaker"

        await _expect_timeout(lambda: FakeVoiceCloneClient("timeout").create_voice_clone("voice.wav"))
        await _expect_service_unavailable(lambda: FakeVoiceCloneClient("service_unavailable").create_voice_clone("voice.wav"))
        assert await FakeVoiceCloneClient("malformed_response").create_voice_clone("voice.wav") == {"malformed": True}

        failure = await FakeVoiceCloneClient("business_failure").create_voice_clone("voice.wav")
        assert failure["status"] == "success"
        assert failure["clone_status"] == "failed"
        assert failure["message"] == BUSINESS_FAILURE_MESSAGE

        status_failure = await FakeVoiceCloneClient("business_failure").query_status("fake-speaker")
        assert status_failure["clone_status"] == "failed"

    asyncio.run(run_checks())


def test_fake_ppt_modes_are_stable(test_artifact_dir):
    async def run_checks():
        success = await FakePPTClient("success").wait_for_completion("fake-sid")
        assert success.status == "done"
        assert success.ppt_url.endswith(".pptx")

        ppt_path = test_artifact_dir / "fake.pptx"
        assert await FakePPTClient("success").download_ppt("https://fake.invalid/fake.pptx", str(ppt_path)) == str(ppt_path)
        assert ppt_path.read_bytes() == b"FAKE_PPTX"

        await _expect_timeout(lambda: FakePPTClient("timeout").get_theme_list())
        await _expect_service_unavailable(lambda: FakePPTClient("service_unavailable").get_theme_list())
        assert await FakePPTClient("malformed_response").get_theme_list() == {"malformed": True}

        create_result = await FakePPTClient("business_failure").create_ppt_task("topic", "template")
        assert create_result["code"] == 0
        assert create_result["data"]["sid"] == "fake-sid"

        failure = await FakePPTClient("business_failure").wait_for_completion("fake-sid")
        assert failure.status == "failed"
        assert failure.ppt_url == ""
        assert failure.error == BUSINESS_FAILURE_MESSAGE

        progress = await FakePPTClient("business_failure").get_task_progress("fake-sid")
        assert progress["code"] == 0
        assert progress["data"]["pptStatus"] == "failed"
        assert progress["data"]["error"] == BUSINESS_FAILURE_MESSAGE

    asyncio.run(run_checks())


def test_fake_digital_human_modes_are_stable():
    async def run_checks():
        assert await FakeDigitalHumanClient("success").check_health() is True
        success = await FakeDigitalHumanClient("success").generate_video("audio.wav", "face.mp4")
        assert success.video_path.endswith(".mp4")

        await _expect_timeout(lambda: FakeDigitalHumanClient("timeout").check_health())
        await _expect_service_unavailable(lambda: FakeDigitalHumanClient("service_unavailable").check_health())
        assert await FakeDigitalHumanClient("malformed_response").check_health() == {"malformed": True}

        assert await FakeDigitalHumanClient("business_failure").check_health() is True
        failure = await FakeDigitalHumanClient("business_failure").generate_video("audio.wav", "face.mp4")
        assert failure.video_path == ""
        assert failure.download_path == ""
        assert failure.status == "failed"
        assert failure.error == BUSINESS_FAILURE_MESSAGE

    asyncio.run(run_checks())


def test_fake_httpx_modes_are_stable():
    async def run_checks():
        async with FakeHTTPXClient("success") as client:
            success = await client.get("https://fake.invalid/resource")
        assert success.status_code == 200
        assert success.json()["status"] == "success"
        success.raise_for_status()

        await _expect_timeout(lambda: FakeHTTPXClient("timeout").get("https://fake.invalid/resource"))
        await _expect_service_unavailable(lambda: FakeHTTPXClient("service_unavailable").get("https://fake.invalid/resource"))

        malformed = await FakeHTTPXClient("malformed_response").get("https://fake.invalid/resource")
        assert malformed.status_code == 200
        assert malformed.json() == {"malformed": True}

        failure = await FakeHTTPXClient("business_failure").post("https://fake.invalid/progress", json={})
        assert failure.status_code == 200
        assert failure.json()["status"] == "failed"
        assert failure.json()["code"] != 0
        assert failure.json()["message"] == BUSINESS_FAILURE_MESSAGE

    asyncio.run(run_checks())