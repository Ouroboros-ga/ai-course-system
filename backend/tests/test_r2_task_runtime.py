import asyncio

from app.platform.adapters.base import AdapterResult
from app.platform.adapters.errors import AdapterErrorCode
from app.platform.tasks import TaskContext, TaskResult, TaskRunner, TaskStatus, TaskType


def test_r2_task_status_and_type_values():
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.SUCCEEDED.value == "succeeded"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.CANCELLED.value == "cancelled"
    assert TaskStatus.TIMEOUT.value == "timeout"
    assert TaskStatus.PARTIAL_SUCCESS.value == "partial_success"
    assert TaskType.PPT_GENERATION.value == "ppt_generation"
    assert TaskType.DIGITAL_HUMAN_VIDEO.value == "digital_human_video"


def test_r2_task_result_success_failure_and_adapter_mapping():
    context = TaskContext(task_id="fake-task", task_type=TaskType.PPT_GENERATION, provider="fake")

    success = TaskResult.ok({"ok": True}, context=context)
    assert success.success is True
    assert success.status == TaskStatus.SUCCEEDED
    assert success.provider == "fake"
    assert success.context is context

    timeout = TaskResult.fail(AdapterErrorCode.TIMEOUT, "fake timeout", context=context)
    assert timeout.success is False
    assert timeout.status == TaskStatus.TIMEOUT
    assert timeout.error_code == "timeout"

    business_failure = TaskResult.from_adapter_result(
        AdapterResult.fail(
            AdapterErrorCode.BUSINESS_FAILURE,
            "business failed",
            provider="fake-provider",
            raw={"status": "failed"},
        ),
        context=context,
    )
    assert business_failure.status == TaskStatus.FAILED
    assert business_failure.error_code == "business_failure"
    assert business_failure.provider == "fake-provider"


def test_r2_task_runner_success_and_adapter_failures():
    async def run_checks():
        runner = TaskRunner()
        context = TaskContext(task_id=1, task_type=TaskType.DIGITAL_HUMAN_VIDEO, provider="fake")

        success = await runner.run(
            context,
            lambda: AdapterResult.ok({"video": "ok"}, provider="fake"),
        )
        assert success.success is True
        assert success.status == TaskStatus.SUCCEEDED
        assert success.data == {"video": "ok"}
        assert success.started_at is not None
        assert success.finished_at is not None
        assert success.duration_ms >= 0

        timeout = await runner.run(
            context,
            lambda: AdapterResult.fail(AdapterErrorCode.TIMEOUT, "fake timeout", provider="fake"),
        )
        assert timeout.success is False
        assert timeout.status == TaskStatus.TIMEOUT
        assert timeout.error_code == "timeout"

        service_unavailable = await runner.run(
            context,
            lambda: AdapterResult.fail(AdapterErrorCode.SERVICE_UNAVAILABLE, "service unavailable", provider="fake"),
        )
        assert service_unavailable.success is False
        assert service_unavailable.status == TaskStatus.FAILED
        assert service_unavailable.error_code == "service_unavailable"

        malformed = await runner.run(
            context,
            lambda: AdapterResult.fail(AdapterErrorCode.MALFORMED_RESPONSE, "malformed response", provider="fake"),
        )
        assert malformed.success is False
        assert malformed.status == TaskStatus.FAILED
        assert malformed.error_code == "malformed_response"

        business_failure = await runner.run(
            context,
            lambda: AdapterResult.fail(AdapterErrorCode.BUSINESS_FAILURE, "business failed", provider="fake"),
        )
        assert business_failure.success is False
        assert business_failure.status == TaskStatus.FAILED
        assert business_failure.error_code == "business_failure"

    asyncio.run(run_checks())


def test_r2_task_runner_exception_becomes_failed():
    async def run_checks():
        runner = TaskRunner()
        context = TaskContext(task_id=2, task_type=TaskType.PPT_GENERATION)

        def explode():
            raise RuntimeError("unexpected task failure")

        result = await runner.run(context, explode)

        assert result.success is False
        assert result.status == TaskStatus.FAILED
        assert result.error_code == "unknown_error"
        assert "unexpected task failure" in result.error_message

    asyncio.run(run_checks())
