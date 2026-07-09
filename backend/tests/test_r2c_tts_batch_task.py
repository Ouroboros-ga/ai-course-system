import asyncio
import importlib

import pytest

from app.models.course_model import CourseStatus
from app.models.user_model import UserRole
from app.platform.tasks import TaskStatus
from fakes import BUSINESS_FAILURE_MESSAGE, FakeTTSClient
from test_m4b_main_flows import _create_course_graph, _create_user, _headers


class SelectiveTTSClient:
    def __init__(self):
        self.calls = []

    async def synthesize(self, text: str, voice=None, sample_rate=None, output_format=None, **kwargs):
        self.calls.append({"text": text, "voice": voice, "sample_rate": sample_rate, "output_format": output_format})
        if "Recursion" in text:
            return await FakeTTSClient("business_failure").synthesize(
                text=text,
                voice=voice,
                sample_rate=sample_rate,
                output_format=output_format,
                **kwargs,
            )
        return await FakeTTSClient("success").synthesize(
            text=text,
            voice=voice,
            sample_rate=sample_rate,
            output_format=output_format,
            **kwargs,
        )


def _prepare_course(session, monkeypatch, test_artifact_dir, mode_or_client):
    document_endpoint = importlib.import_module("app.api.v1.endpoints.document")
    tts_module = importlib.import_module("app.common.tts_client")

    teacher = _create_user(session, UserRole.TEACHER, "r2c_tts_teacher")
    course, _, nodes, _ = _create_course_graph(session, teacher, status=CourseStatus.PUBLISHED)

    audio_root = test_artifact_dir / f"r2c_audio_{course.id}"
    audio_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(document_endpoint, "AUDIO_STORAGE_DIR", audio_root)

    fake_client = mode_or_client if not isinstance(mode_or_client, str) else FakeTTSClient(mode_or_client)
    monkeypatch.setattr(tts_module, "tts_client", fake_client)
    monkeypatch.setattr(document_endpoint, "tts_client", fake_client, raising=False)

    return document_endpoint, teacher, course, nodes, fake_client


def test_r2c_tts_batch_internal_status_mapping():
    document_endpoint = importlib.import_module("app.api.v1.endpoints.document")

    assert document_endpoint._tts_batch_task_status(2, 2, []) == TaskStatus.SUCCEEDED
    assert document_endpoint._tts_public_status(TaskStatus.SUCCEEDED) == "completed"

    partial = document_endpoint._tts_batch_task_result(
        course_id=1,
        total=2,
        completed=1,
        errors=[{"node_id": 2, "error": BUSINESS_FAILURE_MESSAGE}],
    )
    assert partial.success is True
    assert partial.status == TaskStatus.PARTIAL_SUCCESS
    assert document_endpoint._tts_public_status(partial.status) == "partial"

    failed = document_endpoint._tts_batch_task_result(
        course_id=1,
        total=2,
        completed=0,
        errors=[{"node_id": 1, "error": "timeout"}],
    )
    assert failed.success is False
    assert failed.status == TaskStatus.FAILED
    assert document_endpoint._tts_public_status(failed.status) == "failed"


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        ("timeout", "timeout"),
        ("service_unavailable", "unavailable"),
        ("malformed_response", "malformed"),
        ("business_failure", BUSINESS_FAILURE_MESSAGE),
    ],
)
def test_r2c_single_node_tts_task_result_failures_are_not_success(
    client,
    session,
    monkeypatch,
    test_artifact_dir,
    mode,
    expected_error,
):
    _, teacher, course, nodes, _ = _prepare_course(session, monkeypatch, test_artifact_dir, mode)

    response = client.post(
        f"/api/v1/document/course/{course.id}/node/{nodes[0].id}/synthesize-audio",
        headers=_headers(teacher),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 500
    assert expected_error in payload["message"].lower() or expected_error in payload["message"]
    session.expire_all()
    assert session.get(type(nodes[0]), nodes[0].id).audio_url in (None, "")


def test_r2c_single_node_tts_success_keeps_response_contract(client, session, monkeypatch, test_artifact_dir):
    _, teacher, course, nodes, _ = _prepare_course(session, monkeypatch, test_artifact_dir, "success")

    response = client.post(
        f"/api/v1/document/course/{course.id}/node/{nodes[0].id}/synthesize-audio",
        headers=_headers(teacher),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert payload["data"]["node_id"] == nodes[0].id
    assert payload["data"]["audio_url"].startswith(f"/api/v1/document/audio/{course.id}/")
    assert "latency_ms" in payload["data"]


@pytest.mark.parametrize(
    ("mode", "expected_success_count", "expected_error_count", "expected_error"),
    [
        ("success", 2, 0, ""),
        ("timeout", 0, 2, "timeout"),
        ("service_unavailable", 0, 2, "unavailable"),
        ("malformed_response", 0, 2, "malformed"),
        ("business_failure", 0, 2, BUSINESS_FAILURE_MESSAGE),
    ],
)
def test_r2c_sync_batch_tts_task_modes_record_error_nodes(
    client,
    session,
    monkeypatch,
    test_artifact_dir,
    mode,
    expected_success_count,
    expected_error_count,
    expected_error,
):
    _, teacher, course, _, _ = _prepare_course(session, monkeypatch, test_artifact_dir, mode)

    response = client.post(
        f"/api/v1/document/course/{course.id}/synthesize-all-audio",
        headers=_headers(teacher),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert payload["data"]["success_count"] == expected_success_count
    assert payload["data"]["error_count"] == expected_error_count
    assert len(payload["data"]["errors"]) == expected_error_count
    if expected_error:
        assert all(expected_error in item["error"].lower() or expected_error in item["error"] for item in payload["data"]["errors"])


def test_r2c_background_batch_partial_success_records_status_and_error_nodes(
    session,
    monkeypatch,
    test_artifact_dir,
):
    document_endpoint, _, course, nodes, fake_client = _prepare_course(
        session,
        monkeypatch,
        test_artifact_dir,
        SelectiveTTSClient(),
    )
    status_key = str(course.id)
    document_endpoint.tts_generation_status.pop(status_key, None)

    asyncio.run(document_endpoint._background_synthesize_audio(course.id, nodes[0].script_id))

    status = document_endpoint.tts_generation_status[status_key]
    assert status["status"] == "partial"
    assert status["total"] == 2
    assert status["completed"] == 1
    assert len(status["errors"]) == 1
    assert status["errors"][0]["node_id"] == nodes[1].id
    assert BUSINESS_FAILURE_MESSAGE in status["errors"][0]["error"]
    assert len(fake_client.calls) == 2

    session.expire_all()
    assert session.get(type(nodes[0]), nodes[0].id).audio_url
    assert session.get(type(nodes[1]), nodes[1].id).audio_url in (None, "")
