import asyncio

from app.platform.adapters.base import AdapterResult
from app.platform.adapters.digital_human import DigitalHumanAdapter
from app.platform.adapters.errors import AdapterErrorCode
from app.platform.adapters.external_http import ExternalHTTPAdapter
from app.platform.adapters.llm import LLMAdapter
from app.platform.adapters.ppt import PPTAdapter
from app.platform.adapters.registry import (
    get_digital_human_adapter,
    get_llm_adapter,
    get_ppt_adapter,
    get_tts_adapter,
    get_voice_clone_adapter,
)
from app.platform.adapters.tts import TTSAdapter
from app.platform.adapters.voice_clone import VoiceCloneAdapter
from fakes import (
    BUSINESS_FAILURE_MESSAGE,
    FakeDigitalHumanClient,
    FakeHTTPXClient,
    FakeLLMClient,
    FakePPTClient,
    FakeTTSClient,
    FakeVoiceCloneClient,
)


def test_adapter_result_structure():
    ok = AdapterResult.ok(data={"id": 1}, provider="fake", duration_ms=1.5)
    assert ok.success is True
    assert ok.data == {"id": 1}
    assert ok.error_code is None
    assert ok.provider == "fake"
    assert ok.duration_ms == 1.5

    failed = AdapterResult.fail(
        AdapterErrorCode.BUSINESS_FAILURE,
        "business failed",
        provider="fake",
        raw={"status": "failed"},
    )
    assert failed.success is False
    assert failed.error_code == "business_failure"
    assert failed.error_message == "business failed"
    assert failed.raw == {"status": "failed"}


def test_registry_accepts_injected_clients_without_network():
    assert isinstance(get_llm_adapter(FakeLLMClient()), LLMAdapter)
    assert isinstance(get_tts_adapter(FakeTTSClient()), TTSAdapter)
    assert isinstance(get_voice_clone_adapter(FakeVoiceCloneClient()), VoiceCloneAdapter)
    assert isinstance(get_ppt_adapter(FakePPTClient()), PPTAdapter)
    assert isinstance(get_digital_human_adapter(FakeDigitalHumanClient()), DigitalHumanAdapter)




def test_registry_default_construction_does_not_call_network():
    assert isinstance(get_llm_adapter(), LLMAdapter)
    assert isinstance(get_tts_adapter(), TTSAdapter)
    assert isinstance(get_voice_clone_adapter(), VoiceCloneAdapter)
    assert isinstance(get_ppt_adapter(), PPTAdapter)
    assert isinstance(get_digital_human_adapter(), DigitalHumanAdapter)

def test_llm_adapter_fake_modes_are_classified():
    async def run_checks():
        success = await LLMAdapter(FakeLLMClient("success")).chat([])
        assert success.success is True
        assert success.data.content == "fake llm response"

        timeout = await LLMAdapter(FakeLLMClient("timeout")).chat([])
        assert timeout.success is False
        assert timeout.error_code == "timeout"

        unavailable = await LLMAdapter(FakeLLMClient("service_unavailable")).chat([])
        assert unavailable.success is False
        assert unavailable.error_code == "service_unavailable"

        malformed = await LLMAdapter(FakeLLMClient("malformed_response")).chat([])
        assert malformed.success is False
        assert malformed.error_code == "malformed_response"

        failure = await LLMAdapter(FakeLLMClient("business_failure")).chat([])
        assert failure.success is False
        assert failure.error_code == "business_failure"

    asyncio.run(run_checks())


def test_tts_adapter_fake_modes_are_classified():
    async def run_checks():
        success = await TTSAdapter(FakeTTSClient("success")).synthesize(text="hello")
        assert success.success is True
        assert success.data.audio_data == b"FAKE_AUDIO"

        timeout = await TTSAdapter(FakeTTSClient("timeout")).synthesize(text="hello")
        assert timeout.error_code == "timeout"

        unavailable = await TTSAdapter(FakeTTSClient("service_unavailable")).synthesize(text="hello")
        assert unavailable.error_code == "service_unavailable"

        malformed = await TTSAdapter(FakeTTSClient("malformed_response")).synthesize(text="hello")
        assert malformed.error_code == "malformed_response"

        failure = await TTSAdapter(FakeTTSClient("business_failure")).synthesize(text="hello")
        assert failure.error_code == "business_failure"
        assert failure.error_message == BUSINESS_FAILURE_MESSAGE

    asyncio.run(run_checks())


def test_ppt_adapter_fake_modes_are_classified(test_artifact_dir):
    async def run_checks():
        success = await PPTAdapter(FakePPTClient("success")).wait_for_completion("fake-sid")
        assert success.success is True
        assert success.data.status == "done"

        ppt_path = test_artifact_dir / "r1.pptx"
        download = await PPTAdapter(FakePPTClient("success")).download_ppt(
            "https://fake.invalid/fake.pptx",
            str(ppt_path),
        )
        assert download.success is True
        assert download.data == str(ppt_path)

        timeout = await PPTAdapter(FakePPTClient("timeout")).get_theme_list()
        assert timeout.error_code == "timeout"

        unavailable = await PPTAdapter(FakePPTClient("service_unavailable")).get_theme_list()
        assert unavailable.error_code == "service_unavailable"

        malformed = await PPTAdapter(FakePPTClient("malformed_response")).get_theme_list()
        assert malformed.error_code == "malformed_response"

        failure = await PPTAdapter(FakePPTClient("business_failure")).wait_for_completion("fake-sid")
        assert failure.error_code == "business_failure"
        assert failure.error_message == BUSINESS_FAILURE_MESSAGE
        assert failure.raw.status == "failed"

    asyncio.run(run_checks())


def test_digital_human_adapter_fake_modes_are_classified():
    async def run_checks():
        health = await DigitalHumanAdapter(FakeDigitalHumanClient("success")).check_health()
        assert health.success is True

        success = await DigitalHumanAdapter(FakeDigitalHumanClient("success")).generate_video(
            audio_path="audio.wav",
            video_path="face.mp4",
        )
        assert success.success is True
        assert success.data.video_path.endswith(".mp4")

        timeout = await DigitalHumanAdapter(FakeDigitalHumanClient("timeout")).check_health()
        assert timeout.error_code == "timeout"

        unavailable = await DigitalHumanAdapter(FakeDigitalHumanClient("service_unavailable")).check_health()
        assert unavailable.error_code == "service_unavailable"

        malformed = await DigitalHumanAdapter(FakeDigitalHumanClient("malformed_response")).check_health()
        assert malformed.error_code == "malformed_response"

        failure = await DigitalHumanAdapter(FakeDigitalHumanClient("business_failure")).generate_video(
            audio_path="audio.wav",
            video_path="face.mp4",
        )
        assert failure.error_code == "business_failure"
        assert failure.error_message == BUSINESS_FAILURE_MESSAGE

    asyncio.run(run_checks())


def test_voice_clone_adapter_fake_modes_are_classified():
    async def run_checks():
        success = await VoiceCloneAdapter(FakeVoiceCloneClient("success")).create_voice_clone("voice.wav")
        assert success.success is True
        assert success.data["speaker_id"] == "fake-speaker"

        timeout = await VoiceCloneAdapter(FakeVoiceCloneClient("timeout")).create_voice_clone("voice.wav")
        assert timeout.error_code == "timeout"

        unavailable = await VoiceCloneAdapter(FakeVoiceCloneClient("service_unavailable")).create_voice_clone("voice.wav")
        assert unavailable.error_code == "service_unavailable"

        malformed = await VoiceCloneAdapter(FakeVoiceCloneClient("malformed_response")).create_voice_clone("voice.wav")
        assert malformed.error_code == "malformed_response"

        failure = await VoiceCloneAdapter(FakeVoiceCloneClient("business_failure")).create_voice_clone("voice.wav")
        assert failure.error_code == "business_failure"
        assert failure.error_message == BUSINESS_FAILURE_MESSAGE

    asyncio.run(run_checks())


def test_external_http_adapter_fake_modes_are_classified():
    async def run_checks():
        success = await ExternalHTTPAdapter(
            client_factory=lambda **kwargs: FakeHTTPXClient("success", **kwargs),
        ).get("https://fake.invalid/resource")
        assert success.success is True
        assert success.data["status"] == "success"

        timeout = await ExternalHTTPAdapter(
            client_factory=lambda **kwargs: FakeHTTPXClient("timeout", **kwargs),
        ).get("https://fake.invalid/resource")
        assert timeout.error_code == "timeout"

        unavailable = await ExternalHTTPAdapter(
            client_factory=lambda **kwargs: FakeHTTPXClient("service_unavailable", **kwargs),
        ).post("https://fake.invalid/resource")
        assert unavailable.error_code == "service_unavailable"

        malformed = await ExternalHTTPAdapter(
            client_factory=lambda **kwargs: FakeHTTPXClient("malformed_response", **kwargs),
        ).get("https://fake.invalid/resource")
        assert malformed.error_code == "malformed_response"

        failure = await ExternalHTTPAdapter(
            client_factory=lambda **kwargs: FakeHTTPXClient("business_failure", **kwargs),
        ).post("https://fake.invalid/resource", json={})
        assert failure.error_code == "business_failure"
        assert failure.error_message == BUSINESS_FAILURE_MESSAGE

    asyncio.run(run_checks())
