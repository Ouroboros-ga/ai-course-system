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
        self.pull = kwargs.get("pull", "")
        self.container_name = f"fake-{run_id}"
        self.start_calls = 0
        self.stop_calls = 0
        self.executed: list[str] = []
        self.files: dict[str, bytes] = {"/workspace/seed.txt": b"seed"}
        _FakeAdapter.instances.append(self)

    async def image_digest(self) -> str:
        return "sha256:fake-digest"

    async def resolve_real_path(self, path: str) -> str:
        return path

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

    # -- F3 会话替身（行为脚本化；容器侧 pexpect 语义由适配器单测覆盖） --
    async def read_text(self, path):
        from swerex_adapter import DockerBackendUnavailableError

        if path not in self.files:
            raise DockerBackendUnavailableError("READ_FAILED",
                                               f"file_not_found: {path}")
        data = self.files[path]
        return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)

    async def create_session(self, session):
        from swerex_adapter import DockerBackendUnavailableError

        sessions = self.__dict__.setdefault("sessions", {})
        if session in sessions:
            raise DockerBackendUnavailableError("SESSION_EXISTS", "exists")
        sessions[session] = {"created": True}
        return ""

    async def run_in_session(self, session, command, timeout_s=None):
        from swerex_adapter import DockerBackendUnavailableError

        sessions = self.__dict__.setdefault("sessions", {})
        if session not in sessions:
            raise DockerBackendUnavailableError("SESSION_MISSING", "missing")
        if (command or "").strip() == ":":
            # 探针：空闲即回显，忙即超时。
            if getattr(self, "probe_free", True):
                return {"output": "", "exit_code": 0}
            raise DockerBackendUnavailableError("SESSION_TIMEOUT", "busy")
        if getattr(self, "session_hang", False):
            # 长命令：首窗超时（仍在跑，文件不动）。
            raise DockerBackendUnavailableError("SESSION_TIMEOUT", "running")
        exit_code = getattr(self, "session_fixed_exit", 0)
        # 落标记＋日志（脚本化终态；伪造标记场景由调用方直接写 files）。
        for path, content in self.__dict__.get("session_writes", {}).items():
            self.files[path] = content
        return {"output": getattr(self, "session_output", "done"),
                "exit_code": exit_code}

    async def interrupt_session(self, session, timeout_s=2.0, n_retry=3):
        from swerex_adapter import DockerBackendUnavailableError

        self.__dict__.setdefault("interrupts", []).append(session)
        if not getattr(self, "interruptible", True):
            raise DockerBackendUnavailableError("SESSION_INTERRUPT_FAILED",
                                               "stuck")
        self.probe_free = True
        return {"output": getattr(self, "interrupt_output", "interrupted")}

    async def probe_session(self, session, timeout_s=2.0):
        from swerex_adapter import DockerBackendUnavailableError

        sessions = self.__dict__.setdefault("sessions", {})
        if session not in sessions:
            return False
        if getattr(self, "probe_free", True):
            return True
        raise DockerBackendUnavailableError("SESSION_TIMEOUT", "busy")

    async def close_session(self, session):
        self.__dict__.setdefault("sessions", {}).pop(session, None)

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


async def test_ensure_scope_hash_idempotent_and_conflict(api):
    """§2：同 run 同 scope 幂等；异 hash 409，不静默复用实例。"""
    first = await api.put("/sandboxes/run-scope",
                          json={"scope_hash": "a" * 32})
    assert first.status_code == 200 and first.json()["deduped"] is False
    same = await api.put("/sandboxes/run-scope", json={"scope_hash": "a" * 32})
    assert same.status_code == 200 and same.json()["deduped"] is True
    conflict = await api.put("/sandboxes/run-scope",
                             json={"scope_hash": "b" * 32})
    assert conflict.status_code == 409
    assert "SCOPE_HASH_MISMATCH" in conflict.json()["detail"]
    assert len(_FakeAdapter.instances) == 1, "冲突不得重建实例"


async def test_ensure_derives_limits_from_resources_and_never_pulls(api):
    """§2/T4：已确认 resources 派生容器限额；镜像策略默认 never。"""
    await api.put("/sandboxes/run-res", json={
        "scope_hash": "c" * 32,
        "resources": {"cpu": 1.5, "memory_mb": 1024, "disk_mb": 2048,
                      "wall_time_s": 600}})
    fake = _FakeAdapter.instances[0]
    assert "--memory=1024m" in fake.docker_args
    assert "--cpus=1.5" in fake.docker_args
    assert "--storage-opt=size=2048m" in fake.docker_args
    assert fake.pull == "never"
    view = (await api.get("/sandboxes/run-res")).json()
    assert view["image_digest"] == "sha256:fake-digest"
    assert view["wall_time_s"] == 600 and view["deadline_at"] > 0


async def test_resources_over_server_limit_rejected(api, monkeypatch):
    monkeypatch.setattr(service_module, "MAX_MEMORY_MB", 1024)
    response = await api.put("/sandboxes/run-big",
                             json={"resources": {"memory_mb": 2048}})
    assert response.status_code == 422
    assert "RESOURCE_LIMIT_EXCEEDED" in response.json()["detail"]
    assert _FakeAdapter.instances == [], "超限不得创建实例"


async def test_wall_time_exceeded_rejects_new_operations(api):
    await api.put("/sandboxes/run-wt",
                  json={"resources": {"wall_time_s": 600}})
    service_module.store.runs["run-wt"]["deadline_at"] = service_module._now() - 1
    response = await api.post("/sandboxes/run-wt/operations",
                              json={"operation_id": "op-1", "command": "echo hi"})
    assert response.status_code == 409
    assert "WALL_TIME_EXCEEDED" in response.json()["detail"]


async def test_path_outside_workspace_and_symlink_escape_rejected(api, monkeypatch):
    """§2：path 限定任务工作区；容器内 symlink 解析逃出工作区即拒绝。"""
    await api.put("/sandboxes/run-ws")
    outside = await api.put("/sandboxes/run-ws/files/etc/passwd",
                            content=b"x")
    assert outside.status_code == 422
    assert outside.json()["detail"] == "PATH_OUTSIDE_WORKSPACE"
    fake = _FakeAdapter.instances[0]

    async def _escaped(_path):
        return "/etc/passwd"

    monkeypatch.setattr(fake, "resolve_real_path", _escaped)
    escaped = await api.put("/sandboxes/run-ws/files/workspace/link.txt",
                            content=b"x")
    assert escaped.status_code == 422
    assert escaped.json()["detail"] == "PATH_SYMLINK_ESCAPE"


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
    # F2：同 id 同请求仍去重（不运行两次）。
    same = await api.post("/sandboxes/run-2/operations",
                          json={"operation_id": "op-1", "command": "echo hi",
                                "timeout_s": 30})
    assert same.json()["deduped"] is True
    assert same.json()["status"] == "succeeded"
    # F2：同 id 不同请求 → 409 OPERATION_ID_CONFLICT（旧进程无退出证明
    # 不得重跑；此前“echo evil 被吞”属缺口，本断言锁定新语义）。
    evil = await api.post("/sandboxes/run-2/operations",
                          json={"operation_id": "op-1", "command": "echo evil",
                                "timeout_s": 30})
    assert evil.status_code == 409
    assert "OPERATION_ID_CONFLICT" in evil.json()["detail"]
    assert _FakeAdapter.instances[0].executed == ["echo hi"], "同 id 不运行两次"
    missing = await api.get("/sandboxes/run-2/operations/nope")
    assert missing.json()["status"] == "unknown"


async def test_operation_id_conflict_by_request_hash(api):
    """F2：双方都带哈希即比哈希（命令文本相同但哈希不同同样冲突）。"""
    await api.put("/sandboxes/run-7")
    first = await api.post("/sandboxes/run-7/operations",
                           json={"operation_id": "op-1", "command": "echo hi",
                                 "timeout_s": 30, "request_hash": "a" * 32})
    assert first.status_code == 200
    conflict = await api.post("/sandboxes/run-7/operations",
                              json={"operation_id": "op-1", "command": "echo hi",
                                    "timeout_s": 30, "request_hash": "b" * 32})
    assert conflict.status_code == 409
    assert "OPERATION_ID_CONFLICT" in conflict.json()["detail"]
    same_hash = await api.post("/sandboxes/run-7/operations",
                               json={"operation_id": "op-1", "command": "echo hi",
                                     "timeout_s": 30, "request_hash": "a" * 32})
    assert same_hash.json()["deduped"] is True


async def test_fencing_rejects_stale_holder(api):
    """F2：首次提交锁定 fencing；旧 token 新提交 409；轮换后新 token 可提交。"""
    await api.put("/sandboxes/run-8")
    first = await api.post("/sandboxes/run-8/operations",
                           json={"operation_id": "op-1", "command": "echo one",
                                 "fencing": "token-A"})
    assert first.status_code == 200
    stale = await api.post("/sandboxes/run-8/operations",
                           json={"operation_id": "op-2", "command": "echo two",
                                 "fencing": "token-OLD"})
    assert stale.status_code == 409
    assert "FENCING_REJECTED" in stale.json()["detail"]
    # 锁定后空 token 同样拒绝（fencing 随本批引入，无旧客户端包袱）。
    legacy = await api.post("/sandboxes/run-8/operations",
                            json={"operation_id": "op-2", "command": "echo two"})
    assert legacy.status_code == 409
    assert "FENCING_REJECTED" in legacy.json()["detail"]
    rotated = await api.put("/sandboxes/run-8/fencing",
                            json={"fencing": "token-B"})
    assert rotated.status_code == 200
    assert rotated.json()["fencing"] == "token-B"
    now_stale = await api.post("/sandboxes/run-8/operations",
                               json={"operation_id": "op-3", "command": "echo 3",
                                     "fencing": "token-A"})
    assert now_stale.status_code == 409
    fresh = await api.post("/sandboxes/run-8/operations",
                           json={"operation_id": "op-3", "command": "echo 3",
                                 "fencing": "token-B"})
    assert fresh.status_code == 200


# ── F3：会话执行＋操作级取消＋日志游标＋在途时限 ──

def _op_paths(operation_id):
    import service as service_module

    return service_module._op_state_paths(operation_id)


async def test_session_submit_completes_in_first_window(api):
    """会话提交首窗完成：设施退出码权威＋标记交叉注记。"""
    await api.put("/sandboxes/run-s1")
    fake = _FakeAdapter.instances[0]
    fake.session_writes = {_op_paths("op-1")["done"]: b"EXIT:0",
                           _op_paths("op-1")["log"]: b"hello-log"}
    first = await api.post("/sandboxes/run-s1/operations",
                           json={"operation_id": "op-1", "command": "echo hi",
                                 "session": True})
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "succeeded"
    assert body["exit_code"] == 0
    assert body["session"] is True
    assert body["facility_confirmed"] is True
    assert body["declared_exit"] == 0
    assert "hello-log" in body["output_tail"]


async def test_session_long_op_running_probe_adopt_and_cursor(api):
    """长操作：首窗超时即返 running；增量游标；探针采信终态。"""
    await api.put("/sandboxes/run-s2")
    fake = _FakeAdapter.instances[0]
    fake.session_hang = True
    first = await api.post("/sandboxes/run-s2/operations",
                           json={"operation_id": "op-1", "command": "sleep 600",
                                 "timeout_s": 600, "session": True})
    assert first.json()["status"] == "running"
    # 在途增量：日志文件渐进可读。
    fake.files[_op_paths("op-1")["log"]] = b"line1\nline2\n"
    running = await api.get("/sandboxes/run-s2/operations/op-1?cursor=0")
    assert running.json()["status"] == "running"
    assert running.json()["increment"] == "line1\nline2\n"
    assert running.json()["offset"] == 12
    again = await api.get("/sandboxes/run-s2/operations/op-1?cursor=12")
    assert again.json()["increment"] == ""
    # 命令结束＋探针空闲 → 采信终态（设施序列化证明）。
    fake.session_hang = False
    fake.files[_op_paths("op-1")["done"]] = b"EXIT:0"
    fake.files[_op_paths("op-1")["log"]] = b"line1\nline2\ndone\n"
    probed = await api.get("/sandboxes/run-s2/operations/op-1?probe=1")
    assert probed.json()["status"] == "succeeded"
    assert probed.json()["facility_confirmed"] is True
    tailed = await api.get("/sandboxes/run-s2/operations/op-1?cursor=0")
    assert tailed.json()["reset"] is True
    assert "done" in tailed.json()["increment"]


async def test_session_marker_mismatch_facility_wins(api):
    """自述与设施不一致 → 设施为准＋注记（自述不可伪造成功）。"""
    await api.put("/sandboxes/run-s3")
    fake = _FakeAdapter.instances[0]
    fake.session_fixed_exit = 1
    fake.session_writes = {_op_paths("op-1")["done"]: b"EXIT:0",
                           _op_paths("op-1")["log"]: b"traceback"}
    first = await api.post("/sandboxes/run-s3/operations",
                           json={"operation_id": "op-1", "command": "exit 1",
                                 "session": True})
    body = first.json()
    assert body["status"] == "failed"
    assert body["exit_code"] == 1
    assert "不一致" in body["note"]


async def test_cancel_session_op_confirmed(api):
    """操作级取消：中断＋确认停止，实验继续（不回收容器）。"""
    await api.put("/sandboxes/run-s4")
    fake = _FakeAdapter.instances[0]
    fake.session_hang = True
    await api.post("/sandboxes/run-s4/operations",
                   json={"operation_id": "op-1", "command": "sleep 600",
                         "timeout_s": 600, "session": True})
    fake.files[_op_paths("op-1")["log"]] = b"partial\n"
    cancelled = await api.post("/sandboxes/run-s4/operations/op-1/cancel", json={})
    body = cancelled.json()
    assert cancelled.status_code == 200
    assert body["status"] == "cancelled"
    assert body.get("unconfirmed", False) is False
    assert "partial" in body["output_tail"]
    # 容器未回收：新会话提交不重建实例。
    before = len(_FakeAdapter.instances)
    await api.post("/sandboxes/run-s4/operations",
                   json={"operation_id": "op-2", "command": "echo next",
                         "session": True})
    assert len(_FakeAdapter.instances) == before


async def test_cancel_unconfirmed_recycles_and_rebuilds(api):
    """中断未确认 → INTERRUPT_UNCONFIRMED＋回收；下次会话提交重建。"""
    await api.put("/sandboxes/run-s5")
    fake = _FakeAdapter.instances[0]
    fake.session_hang = True
    fake.interruptible = False
    fake.probe_free = False
    await api.post("/sandboxes/run-s5/operations",
                   json={"operation_id": "op-1", "command": "sleep 600",
                         "timeout_s": 600, "session": True})
    cancelled = await api.post("/sandboxes/run-s5/operations/op-1/cancel", json={})
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert body.get("unconfirmed", False) is True
    assert body.get("code") == "INTERRUPT_UNCONFIRMED"
    before = len(_FakeAdapter.instances)
    second = await api.post("/sandboxes/run-s5/operations",
                            json={"operation_id": "op-2", "command": "echo ok",
                                  "session": True})
    assert len(_FakeAdapter.instances) == before + 1, "回收后重建新实例"
    assert second.json()["status"] == "succeeded"


async def test_cancel_oneshot_not_interruptible(api):
    """one-shot 运行中操作无会话中断语义 → 409（请走 run 级取消）。"""
    import asyncio as _asyncio

    await api.put("/sandboxes/run-s6")
    gate = _asyncio.Event()
    fake = _FakeAdapter.instances[0]
    orig_execute = _FakeAdapter.execute

    async def _gated(command, timeout_s=None):
        await gate.wait()
        return await orig_execute(fake, command, timeout_s)

    fake.execute = _gated
    await api.post("/sandboxes/run-s6/operations",
                   json={"operation_id": "op-1", "command": "echo hi"})
    # 事件未放行：操作仍 running → 操作级取消必须 409，不伪装。
    refused = await api.post("/sandboxes/run-s6/operations/op-1/cancel", json={})
    assert refused.status_code == 409
    assert "OPERATION_NOT_INTERRUPTIBLE" in refused.json()["detail"]
    gate.set()
    # 放行后终态 → 幂等返回现态。
    for _ in range(100):
        done = await api.post("/sandboxes/run-s6/operations/op-1/cancel", json={})
        if done.json().get("status") in ("succeeded", "failed", "cancelled"):
            break
        await _asyncio.sleep(0.02)
    assert done.json()["status"] == "succeeded"
    assert done.json()["deduped"] is True


async def test_cancel_op_fencing_and_unknown(api):
    """操作取消同样受 fencing 约束；未知 id 诚实 unknown。"""
    await api.put("/sandboxes/run-s7")
    await api.post("/sandboxes/run-s7/operations",
                   json={"operation_id": "op-1", "command": "echo hi",
                         "fencing": "token-A"})
    stale = await api.post("/sandboxes/run-s7/operations/op-1/cancel",
                           json={"fencing": "token-OLD"})
    assert stale.status_code == 409
    missing = await api.post("/sandboxes/run-s7/operations/nope/cancel",
                             json={"fencing": "token-A"})
    assert missing.json()["status"] == "unknown"


async def test_network_profile_mapping(api, monkeypatch):
    """网络档案：未知 422；映射进 docker_args＋生效字段；缺省未隔离。"""
    import service as service_module

    bad = await api.put("/sandboxes/run-n1", json={"network_profile": "nope"})
    assert bad.status_code == 422
    monkeypatch.setenv("REPRO_NETWORK_MAP", '{"restricted": "nexus-exp-x"}')
    monkeypatch.setenv("REPRO_ISOLATED_NETWORK", "nexus-exp-x")
    ok = await api.put("/sandboxes/run-n2", json={"network_profile": "restricted"})
    assert ok.status_code == 200
    assert "--network=nexus-exp-x" in _FakeAdapter.instances[-1].docker_args
    view = ok.json()
    assert view["effective_network"] == "nexus-exp-x"
    assert view["network_isolated"] is True
    plain = await api.put("/sandboxes/run-n3")
    assert plain.json()["network_isolated"] is False
    assert plain.json()["effective_network"] == "bridge"


async def test_session_windows_causes():
    """在途时限裁决：op 超时 / wall 到期分别命名，不混为一谈。"""
    import time as _time

    import service as service_module

    run = {"deadline_at": 0}
    op = {"timeout_s": 60, "started_at": _time.time()}
    window, cause = service_module._session_windows(op, run)
    assert window > 0 and cause == ""
    op_expired = {"timeout_s": 0.001, "started_at": _time.time() - 10}
    _, cause = service_module._session_windows(op_expired, run)
    assert cause == "OPERATION_TIMEOUT"
    run_wall = {"deadline_at": _time.time() - 1}
    op_long = {"timeout_s": 3600, "started_at": _time.time()}
    _, cause = service_module._session_windows(op_long, run_wall)
    assert cause == "WALL_TIME_EXCEEDED"


def test_session_wrapper_keeps_repl_alive():
    """包装器不得裸 exit（会退出 REPL 本体致 pty EOF；线上实证）。

    退出码经子 shell `(exit $code)` 传递：设施提取 intact，会话保活。
    """
    import service as service_module

    wrapped = service_module._wrap_session_command("/tmp/.x.sh", "/tmp/.x.log",
                                                   "/tmp/.x.done")
    assert wrapped.rstrip().endswith("(exit $code)")
    assert "\nexit " not in wrapped and not wrapped.rstrip().endswith("exit $code")


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
    import shutil as _shutil
    import tempfile as _tempfile

    import service as service_module

    # B10：快照写系统临时目录（不污染仓库；本机 pytest tmp 根目录无权限，
    # 故不用 tmp_path fixture）。
    snap_dir = _tempfile.mkdtemp(prefix="repro-snap-")
    snap = _os.path.join(snap_dir, "snap-test.json")
    monkeypatch.setenv("REPRO_SNAPSHOT_PATH", snap)
    try:
        await _snapshot_body(api, snap)
    finally:
        _shutil.rmtree(snap_dir, ignore_errors=True)


async def _snapshot_body(api, snap):
    import json as _json
    import os as _os

    import service as service_module

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
