import asyncio

import pytest

from app.platform.adapters.digital_human import DigitalHumanAdapter
from app.platform.adapters.duix_avatar import DuixAvatarProvider
from app.platform.adapters.registry import get_digital_human_adapter
from fakes import BUSINESS_FAILURE_MESSAGE, FakeDigitalHumanClient


class FakeDuixHTTPError(RuntimeError):
    pass


class FakeDuixResponse:
    def __init__(self, payload=None, status_code=200, json_error=False):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error
        self.text = str(payload)

    def json(self):
        if self.json_error:
            raise ValueError("fake malformed json")
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise FakeDuixHTTPError(f"fake http error: {self.status_code}")


class FakeDuixHTTPXClient:
    instances = []

    def __init__(self, mode="success", **kwargs):
        self.mode = mode
        self.kwargs = kwargs
        self.calls = []
        FakeDuixHTTPXClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, **kwargs):
        self.calls.append({"method": "get", "url": url, "kwargs": kwargs})
        if url == "http://fake-duix.local":
            return FakeDuixResponse({"code": 0, "status": "success"})
        if self.mode == "timeout":
            raise TimeoutError("fake duix timeout")
        if self.mode == "service_unavailable":
            raise FakeDuixHTTPError("fake duix service unavailable")
        if self.mode == "malformed_response":
            return FakeDuixResponse(json_error=True)
        if self.mode == "business_failure":
            return FakeDuixResponse(
                {
                    "code": 0,
                    "status": "failed",
                    "message": BUSINESS_FAILURE_MESSAGE,
                    "data": {"video_url": ""},
                }
            )
        return FakeDuixResponse(
            {
                "code": 0,
                "status": "done",
                "data": {
                    "status": "done",
                    "video_url": "/tmp/fake-duix-output.mp4",
                    "generation_time": "0.2s",
                },
            }
        )

    async def post(self, url, **kwargs):
        self.calls.append({"method": "post", "url": url, "kwargs": kwargs})
        if self.mode == "timeout":
            raise TimeoutError("fake duix timeout")
        if self.mode == "service_unavailable":
            raise FakeDuixHTTPError("fake duix service unavailable")
        if self.mode == "malformed_response":
            return FakeDuixResponse(json_error=True)
        request_code = kwargs["json"]["code"]
        return FakeDuixResponse(
            {
                "code": 0,
                "status": "success",
                "data": {"taskCode": request_code},
            }
        )


def _factory(mode):
    FakeDuixHTTPXClient.instances.clear()

    def create_client(**kwargs):
        return FakeDuixHTTPXClient(mode, **kwargs)

    return create_client


def test_duix_provider_success_submits_expected_payload_without_real_network():
    async def run_check():
        provider = DuixAvatarProvider(
            base_url="http://fake-duix.local",
            client_factory=_factory("success"),
            poll_interval=0,
            max_polls=1,
        )
        result = await DigitalHumanAdapter(provider, provider="duix").generate_video(
            audio_path="/tmp/input.wav",
            video_path="/tmp/face.mp4",
            code="task-001",
        )

        assert result.success is True
        assert result.provider == "duix"
        assert result.data.video_path == "/tmp/fake-duix-output.mp4"
        assert result.data.generation_time == "0.2s"

        fake_client = FakeDuixHTTPXClient.instances[0]
        submit = fake_client.calls[0]
        query = fake_client.calls[1]
        assert submit["method"] == "post"
        assert submit["url"] == "http://fake-duix.local/easy/submit"
        assert submit["kwargs"]["json"] == {
            "audio_url": "/tmp/input.wav",
            "video_url": "/tmp/face.mp4",
            "code": "task-001",
            "chaofen": 0,
            "watermark_switch": 0,
            "pn": 1,
        }
        assert query["url"] == "http://fake-duix.local/easy/query?code=task-001"

    asyncio.run(run_check())


@pytest.mark.parametrize(
    ("mode", "expected_error_code"),
    [
        ("timeout", "timeout"),
        ("service_unavailable", "service_unavailable"),
        ("malformed_response", "malformed_response"),
        ("business_failure", "business_failure"),
    ],
)
def test_duix_provider_failure_modes_are_classified(mode, expected_error_code):
    async def run_check():
        provider = DuixAvatarProvider(
            base_url="http://fake-duix.local",
            client_factory=_factory(mode),
            poll_interval=0,
            max_polls=1,
        )
        result = await DigitalHumanAdapter(provider, provider="duix").generate_video(
            audio_path="/tmp/input.wav",
            video_path="/tmp/face.mp4",
            code="task-002",
        )

        assert result.success is False
        assert result.error_code == expected_error_code
        if expected_error_code == "business_failure":
            assert result.error_message == BUSINESS_FAILURE_MESSAGE
            assert result.raw.status == "failed"
            assert result.raw.video_path == ""
        assert FakeDuixHTTPXClient.instances

    asyncio.run(run_check())


def test_duix_provider_health_uses_fake_client():
    async def run_check():
        provider = DuixAvatarProvider(
            base_url="http://fake-duix.local",
            client_factory=_factory("success"),
        )
        result = await DigitalHumanAdapter(provider, provider="duix").check_health()

        assert result.success is True
        assert FakeDuixHTTPXClient.instances[0].calls == [
            {"method": "get", "url": "http://fake-duix.local", "kwargs": {}}
        ]

    asyncio.run(run_check())


def test_registry_selects_duix_provider_from_environment(monkeypatch):
    monkeypatch.setenv("DIGITAL_HUMAN_PROVIDER", "duix")
    monkeypatch.setenv("DUIX_BASE_URL", "http://fake-duix.local")

    adapter = get_digital_human_adapter()

    assert isinstance(adapter.client, DuixAvatarProvider)
    assert adapter.provider == "duix"
    assert adapter.client.base_url == "http://fake-duix.local"


def test_registry_keeps_injected_default_client_when_provider_is_not_duix(monkeypatch):
    monkeypatch.delenv("DIGITAL_HUMAN_PROVIDER", raising=False)
    fake_client = FakeDigitalHumanClient("success")

    adapter = get_digital_human_adapter(fake_client)

    assert adapter.client is fake_client
    assert adapter.provider == "digital_human"
