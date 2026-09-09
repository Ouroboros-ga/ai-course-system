"""swerex_adapter 单测：FakeDeployment（无 Docker、无网络）。

断言适配映射（构造参数→DockerDeployment 调用、远端响应→返回形态、
取消/存活语义）；真实容器语义见 test_live_docker.py，不在此冒充。
"""
from __future__ import annotations

import pytest

from swerex_adapter import DockerBackendUnavailableError, SwerexDockerAdapter


class _CmdResp:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout = stdout
        self.stderr =stderr
        self.exit_code = exit_code


class _FakeRuntime:
    def __init__(self) -> None:
        self.executed: list[object] = []
        self.written: dict[str, str] = {}
        self.reads: dict[str, str] = {}
        self.uploaded: list[tuple[str, str]] = []
        self.fail_next: str | None = None

    async def execute(self, command):
        self.executed.append(command)
        if self.fail_next:
            raise RuntimeError(self.fail_next)
        return _CmdResp(stdout=f"out:{command.command[:40]}", exit_code=0)

    async def read_file(self, request):
        if request.path in self.reads:
            return _ReadResp(self.reads[request.path])
        raise FileNotFoundError(request.path)

    async def write_file(self, request):
        self.written[request.path] = request.content
        return _WriteResp()

    async def upload(self, request):
        self.uploaded.append((request.source_path, request.target_path))
        return _UploadResp()


class _ReadResp:
    def __init__(self, content):
        self.content = content


class _WriteResp:
    pass


class _UploadResp:
    pass


class _FakeDeployment:
    instances: list["_FakeDeployment"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.runtime = _FakeRuntime()
        self.started = False
        self.stopped = False
        self.container_name = "fake-container-1"
        _FakeDeployment.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def is_alive(self) -> bool:
        return self.started and not self.stopped


@pytest.fixture(autouse=True)
def _reset():
    _FakeDeployment.instances.clear()
    yield
    _FakeDeployment.instances.clear()


def _adapter(**kwargs) -> SwerexDockerAdapter:
    args = {"run_id": "run-a", "image": "python:3.12-slim",
            "docker_args": ["--memory=2g"],
            "deployment_factory": _FakeDeployment}
    args.update(kwargs)
    return SwerexDockerAdapter(**args)


async def test_start_passes_image_and_resource_args():
    adapter = _adapter()
    name = await adapter.start()
    assert name == "fake-container-1"
    built = _FakeDeployment.instances[0].kwargs
    assert built["image"] == "python:3.12-slim"
    assert built["docker_args"] == ["--memory=2g"]
    assert await adapter.is_alive() is True
    # 幂等：二次 start 不重建。
    await adapter.start()
    assert len(_FakeDeployment.instances) == 1


async def test_execute_maps_response_and_records_command():
    adapter = _adapter()
    await adapter.start()
    result = await adapter.execute("echo hi", timeout_s=30.0)
    assert result["output"] == "out:echo hi"
    assert result["exit_code"] == 0
    assert result["truncated"] is False
    assert adapter.container_name == "fake-container-1"


async def test_execute_failure_maps_honestly():
    adapter = _adapter()
    await adapter.start()
    adapter._deployment.runtime.fail_next = "boom"
    with pytest.raises(DockerBackendUnavailableError) as exc:
        await adapter.execute("echo hi")
    assert exc.value.code == "EXECUTE_FAILED"


async def test_write_read_upload_round_trip_on_fake():
    adapter = _adapter()
    await adapter.start()
    await adapter.write_text("/workspace/a.txt", "hello")
    assert adapter._deployment.runtime.written["/workspace/a.txt"] == "hello"
    adapter._deployment.runtime.reads["/workspace/a.txt"] = "hello"
    assert await adapter.read_text("/workspace/a.txt") == "hello"
    await adapter.upload_bytes("/workspace/b.bin", b"\x00\x01")
    src, dst = adapter._deployment.runtime.uploaded[0]
    assert dst == "/workspace/b.bin"
    assert src.startswith(__import__("tempfile").gettempdir())
    import os

    assert not os.path.exists(src), "staging 用后即清理"


async def test_stop_is_idempotent_and_clears_state():
    adapter = _adapter()
    await adapter.stop()  # 未启动直接返回
    await adapter.start()
    await adapter.stop()
    await adapter.stop()
    assert _FakeDeployment.instances[0].stopped is True
    assert await adapter.is_alive() is False


async def test_kill_uses_daemon_plane_without_container_cooperation(monkeypatch):
    import swerex_adapter as adapter_module

    calls: list = []

    def fake_docker(*args):
        calls.append(args)
        return 0, ""

    monkeypatch.setattr(adapter_module, "_docker_cli", fake_docker)
    adapter = _adapter()
    await adapter.start()
    await adapter.kill()
    assert calls[0][:2] == ("kill", "fake-container-1")
    assert calls[1][:3] == ("rm", "-f", "fake-container-1")
    assert await adapter.is_alive() is False


async def test_operations_require_started_instance():
    adapter = _adapter()
    with pytest.raises(DockerBackendUnavailableError) as exc:
        await adapter.execute("echo hi")
    assert exc.value.code == "NOT_STARTED"
