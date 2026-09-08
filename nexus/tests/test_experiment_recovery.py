"""T5 持久运行与恢复（最小 SR4 Runtime 侧）。

行为契约（任务书 T5）：
- Nexus 重启时已有 operation 运行中 → 只接管查询，不再次 submit；
- 控制服务失联 → console 显示 reconciling，不冒称 failed/cancelled；
- attempt 只在 operation 完成后追加；恢复按已完成 attempt 的 operation_id
  续查，不重放未知命令；
- 用户取消 → 置旗＋控制服务操作取消确认后终态 cancelled；
- 跨用户不可见。

全调用真实业务代码；控制服务由 FakeControl 仿（记 POST 数为凭）。
"""

import httpx
import pytest

from nexus import approvals
from nexus import experiment_runs as runs_module
from nexus import proposals as proposals_module


@pytest.fixture(autouse=True)
def _clean_stores():
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()
    yield
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()


def _scope():
    return {
        "objective": "配置并试跑", "repo_url": "https://github.com/example/r",
        "repo_revision": "abc", "source_refs": [], "data_refs": [],
        "network_profile": "pypi-allowed",
        "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                      "wall_time_s": 1800},
        "mode": "smoke", "allow_environment_repair": True,
    }


class _FakeControl:
    """假控制服务：operations POST 计数；GET 查询返回登记态；可断联。"""

    def __init__(self):
        self.posts: list[dict] = []
        self.operations: dict[str, dict] = {}
        self.online = True
        self.cancelled: list[str] = []

    def responder(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        def _body():
            try:
                return dict(_json.loads(request.content.decode() or "{}"))
            except Exception:
                return {}

        if not self.online:
            return httpx.Response(503, json={"detail": "down"})
        path = request.url.path
        if request.method == "PUT" and "/sandboxes/" in path and "/files/" not in path:
            return httpx.Response(200, json={"sandbox_id": "sbx", "status": "ready"})
        if request.method == "POST" and path.endswith("/operations"):
            body = _body()
            op_id = str(body.get("operation_id", ""))
            self.posts.append(body)
            self.operations[op_id] = {"operation_id": op_id, "status": "running",
                                      "exit_code": None, "output_tail": "",
                                      "output_truncated": False}
            return httpx.Response(200, json=dict(self.operations[op_id]))
        if request.method == "GET" and "/operations/" in path:
            op_id = path.rsplit("/", 1)[-1]
            known = self.operations.get(op_id)
            if known is None:
                return httpx.Response(404, json={"detail": "unknown"})
            return httpx.Response(200, json=dict(known))
        if request.method == "POST" and path.endswith("/cancel"):
            self.cancelled.append(path)
            for op in self.operations.values():
                if op["status"] == "running":
                    op.update(status="cancelled", exit_code=-9)
            return httpx.Response(200, json={"status": "cancelled"})
        if request.method == "GET" and "/sandboxes/" in path:
            return httpx.Response(200, json={"sandbox_id": "sbx", "status": "ready"})
        return httpx.Response(404, json={"detail": "unknown"})

    def complete(self, op_id, exit_code=0, output="done"):
        if op_id in self.operations:
            self.operations[op_id].update(status="succeeded", exit_code=exit_code,
                                          output_tail=output)


def _backend(run_id, control):
    from nexus.experiment_sandbox import HttpSandboxBackend

    return HttpSandboxBackend(
        run_id=run_id, base_url="http://control.test", token="t",
        transport=httpx.MockTransport(control.responder))


class _RecoveryFlow:
    """任务书示例形态夹具：真 run 存储＋可替换 Backend（模拟重启）。"""

    def __init__(self, control, user_id="u-t5", session_id="s-t5"):
        self.control = control
        self.user_id = user_id
        self.session_id = session_id

    async def start_running_install(self):
        proposal = proposals_module.create_proposal(
            user_id=self.user_id, session_id=self.session_id, preset=None,
            kind="autonomous_experiment", scope=_scope())
        req = proposals_module.request_approval_for_proposal(
            proposal["proposal_id"], user_id=self.user_id,
            expected_version=proposal["version"])
        aid = req["approval"]["approval_id"]
        approvals.decide_approval(aid, self.user_id, "approved")
        approvals.consume_approval(aid, user_id=self.user_id,
                                   session_id=self.session_id, preset={})
        run = runs_module.create_or_get_run(
            run_id=aid, owner=self.user_id, session_id=self.session_id,
            proposal_id=proposal["proposal_id"], proposal_version=1,
            scope_hash=proposal["scope_hash"], approval_id=aid)
        backend = _backend(run["run_id"], self.control)
        # 提交安装（控制侧保持 running；短轮询截止即返，不阻塞）。
        await backend.aexecute("pip install -r requirements.txt", timeout=1)
        # 生产语义：提交即记 attempt（未完成，exit 空），恢复凭 id 续查。
        runs_module.record_attempt(
            run["run_id"], actual_command="pip install -r requirements.txt",
            operation_id=backend.last_operation_id, exit_code=None, log_ref="")
        return run

    async def restart_nexus(self):
        """模拟重启：丢弃 Backend 实例状态（op 计数器/last_operation_id）。"""

    async def resume(self, run):
        from nexus import experiment_store as store_module

        backend = _backend(run["run_id"], self.control)
        return await store_module.adopt_running_operation(
            run["run_id"], backend=backend)

    def provider_operation_count(self, run):
        return len([p for p in self.control.posts])

    def console_status(self, run):
        from nexus import experiment_store as store_module

        return store_module.console_snapshot(
            run["run_id"],
            control_reachable=self.control.online)["console_status"]


@pytest.fixture()
def recovery_flow():
    return _RecoveryFlow(_FakeControl())


async def test_resume_does_not_repeat_install(recovery_flow):
    run = await recovery_flow.start_running_install()
    assert recovery_flow.provider_operation_count(run) == 1
    await recovery_flow.restart_nexus()
    adopted = await recovery_flow.resume(run)
    assert adopted["operation_id"].endswith("-op-0001")
    assert adopted["resubmitted"] is False
    assert recovery_flow.provider_operation_count(run) == 1
    assert recovery_flow.console_status(run) in {"running", "completed"}


async def test_control_down_shows_reconciling_not_failed(recovery_flow):
    from nexus import experiment_store as store_module

    run = await recovery_flow.start_running_install()
    recovery_flow.control.online = False
    snapshot = store_module.console_snapshot(run["run_id"], control_reachable=False)
    assert snapshot["console_status"] == "reconciling"
    assert snapshot["status"] == "running"
    # 存储快照仍为 running（未被冒称为 failed/cancelled）。
    assert runs_module.get_run(run["run_id"])["status"] == "running"


async def test_cancel_confirmed_terminal(recovery_flow):
    from nexus import experiment_agent as agent_module

    run = await recovery_flow.start_running_install()
    backend = _backend(run["run_id"], recovery_flow.control)
    result = await agent_module.cancel_bound_run(
        run["run_id"], user_id=recovery_flow.user_id, backend=backend)
    assert result["status"] == "cancelled"
    assert runs_module.get_run(run["run_id"])["status"] == "cancelled"
    # 取消后恢复认领直接返回终态，不重放。
    resumed = await recovery_flow.resume(run)
    assert resumed["status"] == "cancelled"


async def test_recovery_cross_user_denied(recovery_flow):
    from nexus import experiment_store as store_module

    run = await recovery_flow.start_running_install()
    backend = _backend(run["run_id"], recovery_flow.control)
    with pytest.raises(Exception) as exc:
        await store_module.adopt_running_operation(
            run["run_id"], backend=backend, user_id="attacker",
            session_id=recovery_flow.session_id)
    assert "FORBIDDEN" in str(getattr(exc.value, "code", exc.value))


async def test_completed_attempts_never_replayed(recovery_flow):
    """已完成 attempt 的 op 不再提交：恢复只续查未完成的尾部。"""
    from nexus import experiment_store as store_module

    run = await recovery_flow.start_running_install()
    first_op = f"{run['run_id']}-op-0001"
    recovery_flow.control.complete(first_op, exit_code=0, output="ok")
    runs_module.record_attempt(run["run_id"], actual_command="pip install -r requirements.txt",
                               operation_id=first_op, exit_code=0, log_ref="ok")
    await recovery_flow.restart_nexus()
    backend = _backend(run["run_id"], recovery_flow.control)
    adopted = await store_module.adopt_running_operation(
        run["run_id"], backend=backend)
    # 尾部已完成 → 无运行中 op 可接管，且零新提交。
    assert adopted["operation_id"] == first_op
    assert adopted["resubmitted"] is False
    assert recovery_flow.provider_operation_count(run) == 1
