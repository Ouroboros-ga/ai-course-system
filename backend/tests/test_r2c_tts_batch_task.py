import asyncio
import importlib

import pytest

from app.models.course_model import CourseStatus
from app.models.user_model import UserRole
from app.platform.adapters.errors import AdapterErrorCode
from app.platform.tasks import TaskContext, TaskResult, TaskRunner, TaskStatus, TaskType
from fakes import BUSINESS_FAILURE_MESSAGE, FakeTTSClient
from test_m4b_main_flows import _create_course_graph, _create_user, _headers


class SelectiveTTSClient:
    def __init__(self):
        self.calls = []

    async def synthesize(self, text: str, voice=None, sample_rate=None, output_format=None, **kwargs):
        self.calls.append({"text": text, "voice": voice, "sample_rate": sample_rate, "output_format": output_format})
        mode = "business_failure" if "Recursion" in text else "success"
        return await FakeTTSClient(mode).synthesize(
            text=text,
            voice=voice,
            sample_rate=sample_rate,
            output_format=output_format,
            **kwargs,
        )


class UnexpectedThenSuccessTTSClient:
    def __init__(self):
        self.calls = []

    async def synthesize(self, text: str, voice=None, sample_rate=None, output_format=None, **kwargs):
        self.calls.append({"text": text, "voice": voice, "sample_rate": sample_rate, "output_format": output_format})
        if len(self.calls) == 1:
            raise ValueError("controlled unexpected TTS failure")
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


def _task_result(node_id: int, *, success: bool, error_code=None, status=None):
    context = TaskContext(
        task_id=f"1:{node_id}",
        task_type=TaskType.TTS_BATCH,
        course_id=1,
        node_id=node_id,
        provider="tts",
    )
    if success:
        return TaskResult.ok(data={"node_id": node_id}, context=context)
    return TaskResult.fail(
        error_code or AdapterErrorCode.UNKNOWN_ERROR,
        f"node {node_id} failed",
        status=status,
        context=context,
    )


def test_r2c_tts_batch_internal_status_mapping_and_aggregate_fields():
    document_endpoint = importlib.import_module("app.api.v1.endpoints.document")

    succeeded = document_endpoint._tts_batch_task_result(
        1,
        2,
        [_task_result(1, success=True), _task_result(2, success=True)],
        [],
        12.5,
    )
    assert succeeded.status == TaskStatus.SUCCEEDED
    assert succeeded.data == {
        "total_count": 2,
        "success_count": 2,
        "failed_count": 0,
        "completed_count": 2,
        "failed_nodes": [],
        "errors": [],
        "duration_ms": 12.5,
        "status": TaskStatus.SUCCEEDED.value,
    }
    assert document_endpoint._tts_public_status(succeeded.status) == "completed"

    partial = document_endpoint._tts_batch_task_result(
        1,
        2,
        [
            _task_result(1, success=True),
            _task_result(2, success=False, error_code=AdapterErrorCode.BUSINESS_FAILURE),
        ],
        [{"node_id": 2, "error": BUSINESS_FAILURE_MESSAGE}],
        13.5,
    )
    assert partial.success is True
    assert partial.status == TaskStatus.PARTIAL_SUCCESS
    assert partial.data["success_count"] == 1
    assert partial.data["failed_count"] == 1
    assert partial.data["completed_count"] == 2
    assert partial.data["failed_nodes"][0]["node_id"] == 2
    assert partial.data["failed_nodes"][0]["error_code"] == AdapterErrorCode.BUSINESS_FAILURE.value
    assert document_endpoint._tts_public_status(partial.status) == "partial"

    failed = document_endpoint._tts_batch_task_result(
        1,
        2,
        [
            _task_result(1, success=False, error_code=AdapterErrorCode.TIMEOUT, status=TaskStatus.TIMEOUT),
            _task_result(2, success=False, error_code=AdapterErrorCode.TIMEOUT, status=TaskStatus.TIMEOUT),
        ],
        [{"node_id": 1, "error": "timeout"}, {"node_id": 2, "error": "timeout"}],
        14.5,
    )
    assert failed.success is False
    assert failed.status == TaskStatus.FAILED
    assert failed.error_code == AdapterErrorCode.TIMEOUT.value
    assert failed.data["failed_count"] == 2
    assert all(item["status"] == TaskStatus.TIMEOUT.value for item in failed.data["failed_nodes"])

    no_work = document_endpoint._tts_batch_task_result(1, 0, [], [], 0.5)
    assert no_work.status == TaskStatus.SUCCEEDED
    assert no_work.data["completed_count"] == 0


def test_r2c_task_level_timeout_keeps_internal_timeout_and_public_compatibility():
    document_endpoint = importlib.import_module("app.api.v1.endpoints.document")
    task_level_timeout = TaskResult.fail(
        AdapterErrorCode.TIMEOUT,
        "batch deadline exceeded",
        status=TaskStatus.TIMEOUT,
    )

    result = document_endpoint._tts_batch_task_result(
        1,
        2,
        [],
        [{"error": "batch deadline exceeded"}],
        1000.0,
        task_level_result=task_level_timeout,
    )

    assert result.status == TaskStatus.TIMEOUT
    assert result.error_code == AdapterErrorCode.TIMEOUT.value
    assert result.data["status"] == TaskStatus.TIMEOUT.value
    assert document_endpoint._tts_public_status(result.status) == "failed"


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
    failed_node = session.get(type(nodes[0]), nodes[0].id)
    assert failed_node.audio_url in (None, "")
    assert failed_node.audio_duration in (None, 0)


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
    assert payload["data"]["audio_duration"] > 0
    assert "latency_ms" in payload["data"]

    session.expire_all()
    saved_node = session.get(type(nodes[0]), nodes[0].id)
    assert saved_node.audio_url == payload["data"]["audio_url"]
    assert saved_node.audio_duration == payload["data"]["audio_duration"]


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
    _, teacher, course, nodes, _ = _prepare_course(session, monkeypatch, test_artifact_dir, mode)

    response = client.post(
        f"/api/v1/document/course/{course.id}/synthesize-all-audio",
        headers=_headers(teacher),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert set(payload["data"]) == {"course_id", "success_count", "error_count", "results", "errors"}
    assert payload["data"]["success_count"] == expected_success_count
    assert payload["data"]["error_count"] == expected_error_count
    assert len(payload["data"]["errors"]) == expected_error_count
    if expected_error:
        assert all(expected_error in item["error"].lower() or expected_error in item["error"] for item in payload["data"]["errors"])

    session.expire_all()
    saved_nodes = [session.get(type(node), node.id) for node in nodes]
    if mode == "success":
        assert all(node.audio_url for node in saved_nodes)
        assert all(node.audio_duration and node.audio_duration > 0 for node in saved_nodes)
    else:
        assert all(node.audio_url in (None, "") for node in saved_nodes)
        assert all(node.audio_duration in (None, 0) for node in saved_nodes)


def test_r2c_sync_batch_partial_success_continues_after_business_failure(
    client,
    session,
    monkeypatch,
    test_artifact_dir,
):
    _, teacher, course, nodes, fake_client = _prepare_course(
        session,
        monkeypatch,
        test_artifact_dir,
        SelectiveTTSClient(),
    )

    response = client.post(
        f"/api/v1/document/course/{course.id}/synthesize-all-audio",
        headers=_headers(teacher),
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["code"] == 200
    assert payload["data"]["success_count"] == 1
    assert payload["data"]["error_count"] == 1
    assert len(fake_client.calls) == 2

    session.expire_all()
    assert session.get(type(nodes[0]), nodes[0].id).audio_url
    assert session.get(type(nodes[0]), nodes[0].id).audio_duration > 0
    assert session.get(type(nodes[1]), nodes[1].id).audio_url in (None, "")
    assert session.get(type(nodes[1]), nodes[1].id).audio_duration in (None, 0)


def test_r2c_background_batch_partial_success_keeps_status_route_contract(
    client,
    session,
    monkeypatch,
    test_artifact_dir,
):
    document_endpoint, teacher, course, nodes, fake_client = _prepare_course(
        session,
        monkeypatch,
        test_artifact_dir,
        SelectiveTTSClient(),
    )
    status_key = str(course.id)
    document_endpoint.tts_generation_status.pop(status_key, None)

    asyncio.run(document_endpoint._background_synthesize_audio(course.id, nodes[0].script_id))

    status = document_endpoint.tts_generation_status[status_key]
    assert {"status", "total", "completed", "errors"} <= set(status)
    assert status["status"] == "partial"
    assert status["total"] == 2
    assert status["completed"] == 1
    assert status["success_count"] == 1
    assert status["failed_count"] == 1
    assert status["completed_count"] == 2
    assert status["failed_nodes"][0]["node_id"] == nodes[1].id
    assert status["failed_nodes"][0]["error_code"] == AdapterErrorCode.BUSINESS_FAILURE.value
    assert status["duration_ms"] >= 0
    assert len(status["errors"]) == 1
    assert BUSINESS_FAILURE_MESSAGE in status["errors"][0]["error"]
    assert len(fake_client.calls) == 2

    response = client.get(
        f"/api/v1/document/course/{course.id}/tts-status",
        headers=_headers(teacher),
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["code"] == 200
    assert payload["data"]["status"] == "partial"
    assert {"status", "total", "completed", "errors"} <= set(payload["data"])

    session.expire_all()
    assert session.get(type(nodes[0]), nodes[0].id).audio_url
    assert session.get(type(nodes[0]), nodes[0].id).audio_duration > 0
    assert session.get(type(nodes[1]), nodes[1].id).audio_url in (None, "")
    assert session.get(type(nodes[1]), nodes[1].id).audio_duration in (None, 0)


def test_r2c_background_batch_unexpected_exception_does_not_stop_remaining_nodes(
    session,
    monkeypatch,
    test_artifact_dir,
):
    document_endpoint, _, course, nodes, fake_client = _prepare_course(
        session,
        monkeypatch,
        test_artifact_dir,
        UnexpectedThenSuccessTTSClient(),
    )

    asyncio.run(document_endpoint._background_synthesize_audio(course.id, nodes[0].script_id))

    status = document_endpoint.tts_generation_status[str(course.id)]
    assert status["status"] == "partial"
    assert status["completed_count"] == 2
    assert status["failed_count"] == 1
    assert status["failed_nodes"][0]["node_id"] == nodes[0].id
    assert status["failed_nodes"][0]["error_code"] == AdapterErrorCode.UNKNOWN_ERROR.value
    assert "controlled unexpected TTS failure" in status["failed_nodes"][0]["error"]
    assert len(fake_client.calls) == 2

    session.expire_all()
    assert session.get(type(nodes[0]), nodes[0].id).audio_url in (None, "")
    assert session.get(type(nodes[1]), nodes[1].id).audio_url


def test_r2c_background_batch_continues_if_task_runner_itself_raises(
    session,
    monkeypatch,
    test_artifact_dir,
):
    document_endpoint, _, course, nodes, _ = _prepare_course(
        session,
        monkeypatch,
        test_artifact_dir,
        "success",
    )
    real_runner = TaskRunner
    calls = {"count": 0}

    class RunnerRaisesOnce:
        async def run(self, context, operation):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("controlled TaskRunner failure")
            return await real_runner().run(context, operation)

    monkeypatch.setattr(document_endpoint, "TaskRunner", RunnerRaisesOnce)

    asyncio.run(document_endpoint._background_synthesize_audio(course.id, nodes[0].script_id))

    status = document_endpoint.tts_generation_status[str(course.id)]
    assert status["status"] == "partial"
    assert status["failed_count"] == 1
    assert status["completed_count"] == 2
    assert status["failed_nodes"][0]["node_id"] == nodes[0].id
    assert "controlled TaskRunner failure" in status["failed_nodes"][0]["error"]
    assert calls["count"] == 2

    session.expire_all()
    assert session.get(type(nodes[0]), nodes[0].id).audio_url in (None, "")
    assert session.get(type(nodes[1]), nodes[1].id).audio_url


def test_r2c_background_batch_no_eligible_nodes_keeps_noop_success(
    session,
    monkeypatch,
    test_artifact_dir,
):
    document_endpoint, _, course, nodes, fake_client = _prepare_course(
        session,
        monkeypatch,
        test_artifact_dir,
        "success",
    )
    for node in nodes:
        node.content = "short"
        session.add(node)
    session.commit()

    asyncio.run(document_endpoint._background_synthesize_audio(course.id, nodes[0].script_id))

    status = document_endpoint.tts_generation_status[str(course.id)]
    assert status["status"] == "completed"
    assert status["total"] == 0
    assert status["completed"] == 0
    assert status["success_count"] == 0
    assert status["failed_count"] == 0
    assert status["completed_count"] == 0
    assert status["errors"] == []
    assert fake_client.calls == []