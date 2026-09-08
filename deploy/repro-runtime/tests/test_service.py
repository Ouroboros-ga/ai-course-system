"""控制服务契约测试：ASGI＋FakeAdapter（无 Docker、无网络）。

覆盖任务书 §2 全部 7 个控制端点：ensure 幂等、operation 登记后执行＋同 id
去重、查询 unknown 诚实、文件上传下载、取消幂等、鉴权门。真实容器语义见
test_live_docker.py。
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import service as service_module
from service import app


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("REPRO_RUNTIME_TOKEN", "test-token")
    monkeypatch.setenv("REPRO_SNAPSHOT_PATH", "/tmp/pytest-repro-runtime-snap.json")
    service_module.store.runs.clear()
    service_module.store.adapters.clear()
    service_module.store.locks.clear()
    yield
    service_module.store.runs.clear()
    service_module.store.adapters.clear()
    service_module.store.locks.clear()


class _FakeAdapter:
    instances: list["_FakeAdapter"] = []

    def __init__(self, *, run_id, image, docker_args=None, **kwargs) -> None:
        self.run_id = run_id
        self.image = image
        self.docker_args = list(docker_args or [])
        self.container_name = f"fake-{run_id}"
        self.start_calls = 0
        self.stop_calls = 0
        self.executed: list[str] = []
        self.files: dict[str, bytes] = {"/workspace/seed.txt": b"seed"}
        _FakeAdapter.instances.append(self)

    async def start(self) -> str:
        self.start_calls += 1
        return self.container_name

    async def stop(self) -> None:
        self.stop_calls += 1

    async def kill(self) -> None:
        self.kill_calls = getattr(self, "kill_calls", 0) + 1
        self.stop_calls += 1

    async def execute(self, command, timeout_s=None):
        self.executed.append(command)
        return {"output": f"ran:{command[:60]}", "exit_code": 0, "truncated": False}

    async def upload_bytes(self, target_path, data):
        self.files[target_path] = bytes(data)

    async def read_bytes(self, path, max_bytes=1048576):
        from swerex_adapter import DockerBackendUnavailableError

        if path not in self.files:
            raise DockerBackendUnavailableError("READ_FAILED",
                                               f"file_not_found: {path}")
        return self.files[path]


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(service_module, "SwerexDockerAdapter", _FakeAdapter)
    _FakeAdapter.instances.clear()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test",
                       headers={"Authorization": "Bearer test-token"})


async def test_health_ok():
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_auth_gate_rejects_without_token(api):
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        assert (await client.put("/sandboxes/r1")).status_code in (401, 503)


async def test_ensure_idempotent_same_run(api):
    first = await api.put("/sandboxes/run-1")
    assert first.status_code == 200
    assert first.json()["deduped"] is False
    assert first.json()["sandbox_id"] == "sb-run-1"
    second = await api.put("/sandboxes/run-1")
    assert second.json()["deduped"] is True
    assert len(_FakeAdapter.instances) == 1, "同 run 不重建实例"


async def test_operation_submit_query_dedupe(api):
    import asyncio as _asyncio

    await api.put("/sandboxes/run-2")
    first = await api.post("/sandboxes/run-2/operations",
                           json={"operation_id": "op-1", "command": "echo hi",
                                 "timeout_s": 30})
    assert first.status_code == 200
    # POST 即返回 running（先登记后执行）；轮询等终态。
    assert first.json()["status"] == "running"
    terminal = None
    for _ in range(100):
        await _asyncio.sleep(0.05)
        query = await api.get("/sandboxes/run-2/operations/op-1")
        if query.json()["status"] in ("succeeded", "failed", "cancelled"):
            terminal = query.json()
            break
    assert terminal is not None and terminal["exit_code"] == 0
    again = await api.post("/sandboxes/run-2/operations",
                           json={"operation_id": "op-1", "command": "echo evil",
                                 "timeout_s": 30})
    assert again.json()["deduped"] is True
    assert again.json()["status"] == "succeeded"
    assert _FakeAdapter.instances[0].executed == ["echo hi"], "同 id 不运行两次"
    missing = await api.get("/sandboxes/run-2/operations/nope")
    assert missing.json()["status"] == "unknown"


async def test_files_round_trip_and_missing(api):
    await api.put("/sandboxes/run-3")
    put = await api.put("/sandboxes/run-3/files/workspace/out.txt",
                        content=b"hello-files")
    assert put.status_code == 200
    get = await api.get("/sandboxes/run-3/files/workspace/out.txt")
    assert get.status_code == 200 and get.content == b"hello-files"
    gone = await api.get("/sandboxes/run-3/files/workspace/nope")
    assert gone.status_code == 404
    bad = await api.put("/sandboxes/run-3/files/%2E%2E/escape",
                        content=b"x")
    assert bad.status_code == 422


async def test_cancel_is_idempotent_and_terminal_runs_reject_new_ops(api):
    await api.put("/sandboxes/run-4")
    await api.post("/sandboxes/run-4/operations",
                   json={"operation_id": "op-9", "command": "sleep 60"})
    first = await api.post("/sandboxes/run-4/cancel")
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    fake = _FakeAdapter.instances[0]
    assert fake.kill_calls == 1, "kill-first 只执行一次"
    calls_after_first = fake.stop_calls
    again = await api.post("/sandboxes/run-4/cancel")
    assert again.json()["deduped"] is True
    assert fake.kill_calls == 1 and fake.stop_calls == calls_after_first, \
        "重复取消不再触碰实例"
    rejected = await api.post(
        "/sandboxes/run-4/operations",
        json={"operation_id": "op-10", "command": "echo hi"})
    assert rejected.status_code == 409


async def test_unknown_run_and_sandbox_status(api):
    assert (await api.get("/sandboxes/nope")).status_code == 404
    await api.put("/sandboxes/run-5")
    view = await api.get("/sandboxes/run-5")
    assert view.json()["status"] == "ready"
    assert view.json()["sandbox_id"] == "sb-run-5"


async def test_snapshot_restart_reconciles_unknown_without_replay(
    api, monkeypatch
):
    import json as _json
    import os as _os

    import service as service_module

    # 注：本机默认 pytest tmp 根目录无写权限（环境问题），用项目内临时文件。
    snap = _os.path.join(_os.path.dirname(__file__), ".tmp-snap-test.json")
    if _os.path.exists(snap):
        _os.remove(snap)
    monkeypatch.setenv("REPRO_SNAPSHOT_PATH", snap)
    await api.put("/sandboxes/run-6")
    await api.post("/sandboxes/run-6/operations",
                   json={"operation_id": "op-1", "command": "echo hi"})
    assert _os.path.exists(snap), "每次变更落快照"
    saved = _json.loads(open(snap, encoding="utf-8").read())
    assert saved["run-6"]["docker_args"] == ["--memory=2g", "--cpus=2",
                                            "--pids-limit=512"], \
        "默认资源限额如实落快照（对账可见）"
    fresh = service_module._Store()
    fresh.load_snapshot()
    assert fresh.runs["run-6"]["status"] == "unknown"
    assert "不重放" in fresh.runs["run-6"]["note"]
    # 已完成操作保留结果（只把未终态标 unknown），未知操作查不到报 unknown。
    assert fresh.runs["run-6"]["operations"]["op-1"]["status"] in (
        "succeeded", "unknown")
    _os.remove(snap)
