import asyncio

import pytest

from app.services.ppt_generation_service import PPTGenerationService, PPTTaskResult
from fakes import BUSINESS_FAILURE_MESSAGE, FakePPTClient


async def _fake_expand(*args, **kwargs):
    return "fake teaching script"


class WaitTimeoutPPTClient(FakePPTClient):
    async def wait_for_completion(self, sid: str, max_wait_seconds: int = 300, poll_interval: int = 5):
        self.calls.append({"method": "wait_for_completion", "sid": sid})
        return PPTTaskResult(sid=sid, status="timeout", ppt_url="", error="PPT generation timed out")


def _service_with_fake(monkeypatch, test_artifact_dir, fake_client, name: str) -> PPTGenerationService:
    service = PPTGenerationService()
    service.ppt_storage_path = str(test_artifact_dir / name)
    service.xfyun_client = fake_client
    monkeypatch.setattr(service, "expand_to_teaching_script", _fake_expand)
    return service


def test_r2b_ppt_task_success_maps_to_done(monkeypatch, test_artifact_dir):
    service = _service_with_fake(monkeypatch, test_artifact_dir, FakePPTClient("success"), "ppt_success")

    result = asyncio.run(
        service.generate_ppt(
            topic="R2B PPT Success",
            template_id="fake-template",
        )
    )

    assert result.status == "done"
    assert result.ppt_url == "https://fake.invalid/fake.pptx"
    assert result.ppt_file_path.endswith(".pptx")


def test_r2b_ppt_task_business_failure_maps_to_failed(monkeypatch, test_artifact_dir):
    service = _service_with_fake(monkeypatch, test_artifact_dir, FakePPTClient("business_failure"), "ppt_business")

    result = asyncio.run(
        service.generate_ppt(
            topic="R2B PPT Business Failure",
            template_id="fake-template",
        )
    )

    assert result.status == "failed"
    assert result.error == BUSINESS_FAILURE_MESSAGE


def test_r2b_ppt_task_timeout_result_is_preserved(monkeypatch, test_artifact_dir):
    service = _service_with_fake(monkeypatch, test_artifact_dir, WaitTimeoutPPTClient("success"), "ppt_timeout")

    result = asyncio.run(
        service.generate_ppt(
            topic="R2B PPT Timeout",
            template_id="fake-template",
        )
    )

    assert result.status == "timeout"
    assert "timed out" in result.error.lower()


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        ("timeout", "timeout"),
        ("service_unavailable", "unavailable"),
        ("malformed_response", "malformed"),
    ],
)
def test_r2b_ppt_task_non_success_create_modes_return_failed(
    monkeypatch,
    test_artifact_dir,
    mode,
    expected_error,
):
    service = _service_with_fake(monkeypatch, test_artifact_dir, FakePPTClient(mode), f"ppt_{mode}")

    result = asyncio.run(
        service.generate_ppt(
            topic=f"R2B PPT {mode}",
            template_id="fake-template",
        )
    )

    assert result.status == "failed"
    assert expected_error in result.error.lower()
