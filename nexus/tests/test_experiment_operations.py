"""F2 持久执行与恢复（计划 §7）。

行为契约：
- 外部副作用前原子登记意图（stable id＋请求哈希）；同 id 同请求去重，
  同 id 不同请求 OPERATION_ID_CONFLICT（未知先对账，不重跑）；
- 租约＋ fencing：拿不到只观察；完成/取消/失败释放；
- 对账决策矩阵；恢复认领只查不交，终态证据回写 attempt；
- 持久层门：本地无 DSN 放行内存；DSN 已配但 saver 未就绪拒绝新长实验。

全调用真实业务代码；PG 不可用时走内存分支（与 runs 同降级语义）。
"""

import pytest

from nexus import experiment_operations as ops_module
from nexus import experiment_runs as runs_module


@pytest.fixture(autouse=True)
def _clean():
    ops_module.clear_memory_store()
    runs_module.clear_memory_store()
    yield
    ops_module.clear_memory_store()
    runs_module.clear_memory_store()


def test_request_hash_stable_and_sensitive():
    h1 = ops_module.request_hash("echo hi", 30)
    assert h1 == ops_module.request_hash("  echo hi  ", 30.0)
    assert h1 != ops_module.request_hash("echo evil", 30)
    assert h1 != ops_module.request_hash("echo hi", 31)
    assert h1 != ops_module.request_hash("echo hi", None)
    assert ops_module.stable_operation_id("run-1", 2) == "run-1-op-0002"


def test_prepare_dedupe_same_request():
    first = ops_module.prepare_intent(
        run_id="run-1", seq=1, command="echo hi", timeout_s=30)
    assert first["deduped"] is False
    assert first["intent"]["status"] == "prepared"
    second = ops_module.prepare_intent(
        run_id="run-1", seq=1, command="echo hi", timeout_s=30)
    assert second["deduped"] is True
    assert second["intent"]["operation_id"] == "run-1-op-0001"


def test_prepare_conflict_different_request():
    ops_module.prepare_intent(run_id="run-1", seq=1, command="echo hi")
    with pytest.raises(ops_module.OperationError) as exc:
        ops_module.prepare_intent(run_id="run-1", seq=1, command="echo evil")
    assert exc.value.code == "OPERATION_ID_CONFLICT"


def test_intent_terminal_immutable():
    ops_module.prepare_intent(run_id="run-1", seq=1, command="echo hi")
    ops_module.set_intent_status("run-1", "run-1-op-0001", "submitted")
    done = ops_module.set_intent_status(
        "run-1", "run-1-op-0001", "succeeded", exit_code=0, output_tail="ok")
    assert done["status"] == "succeeded"
    # 终态不可改写（迟到的取消/失败不得覆盖）。
    again = ops_module.set_intent_status("run-1", "run-1-op-0001", "cancelled")
    assert again["status"] == "succeeded"


def test_reconcile_decision_matrix():
    decide = ops_module.reconcile_decision
    assert decide(None, None) == "no_intent"
    prepared = {"status": "prepared"}
    assert decide(prepared, None) == "submittable"
    assert decide(prepared, {"status": "unknown"}) == "submittable"
    assert decide(prepared, {"status": "running"}) == "adopt_running"
    assert decide(prepared, {"status": "succeeded"}) == "adopt_terminal"
    assert decide({"status": "submitted"}, {"status": "unknown"}) == "unknown_hold"
    assert decide({"status": "running"}, None) == "unknown_hold"


def test_lease_acquire_observe_release():
    first = ops_module.acquire_lease("run-1", "holder-a")
    assert first["acquired"] is True
    fencing_a = first["fencing"]
    assert fencing_a
    second = ops_module.acquire_lease("run-1", "holder-b")
    assert second["acquired"] is False, "拿不到租约只观察"
    assert second["holder"] == "holder-a"
    # holder 不符不释放。
    assert ops_module.release_lease("run-1", "holder-b", "wrong") is False
    assert ops_module.release_lease("run-1", "holder-a", fencing_a) is True
    third = ops_module.acquire_lease("run-1", "holder-b")
    assert third["acquired"] is True
    assert third["fencing"] != fencing_a, "fencing 单调更新"


def test_lease_expiry_takeover():
    got = ops_module.acquire_lease("run-1", "holder-a", ttl_s=5.0)
    assert got["acquired"] is True
    # 过期租约可被接管（接管者须先核对控制面——调用方职责，此处只验权转移）。
    ops_module._memory_leases["run-1"]["expires_at"] = 0.0
    took = ops_module.acquire_lease("run-1", "holder-b")
    assert took["acquired"] is True


def test_force_release_on_terminal():
    ops_module.acquire_lease("run-1", "holder-a")
    ops_module.force_release_run("run-1")
    assert ops_module.acquire_lease("run-1", "holder-b")["acquired"] is True


def test_backend_prepare_submit_caches_terminal():
    from nexus.experiment_sandbox import HttpSandboxBackend

    backend = HttpSandboxBackend(run_id="run-9")
    operation_id, payload, cached = backend._prepare_submit("echo hi", 30)
    assert operation_id == "run-9-op-0001"
    assert cached is None
    assert payload["request_hash"] == ops_module.request_hash("echo hi", 30)
    ops_module.set_intent_status(
        "run-9", operation_id, "succeeded", exit_code=0, output_tail="ran")
    # 重建 Backend（序号归零模拟）同 id 同请求重登记 → 终态缓存，不再 submit。
    rebuilt = HttpSandboxBackend(run_id="run-9")
    _id2, _payload2, cached2 = rebuilt._prepare_submit("echo hi", 30)
    assert _id2 == operation_id
    assert cached2 is not None
    assert cached2.exit_code == 0
    # 同 id 不同请求 → 冲突（写失败即不执行；新实例同序号复现崩溃恢复路径）。
    from nexus.experiment_sandbox import ExperimentSandboxError

    rebuilt_evil = HttpSandboxBackend(run_id="run-9")
    with pytest.raises(ExperimentSandboxError) as exc:
        rebuilt_evil._prepare_submit("echo evil", 30)
    assert exc.value.code == "OPERATION_ID_CONFLICT"


def test_backend_seq_restores_from_run():
    from nexus.experiment_sandbox import HttpSandboxBackend

    run = _make_running_run(run_id="run-seq")
    # 模拟崩溃前已落盘 3 条 attempt：重建 Backend 不得归零。
    for index in range(1, 4):
        runs_module.record_attempt(
            run["run_id"], actual_command=f"echo {index}",
            operation_id=f"{run['run_id']}-op-{index:04d}",
            exit_code=0, log_ref="ok")
    stored = runs_module.get_run(run["run_id"])
    backend = HttpSandboxBackend(
        run_id=run["run_id"], initial_seq=int(stored["attempt_no"]))
    assert backend._new_operation_id() == f"{run['run_id']}-op-0004"


class _FakeBackend:
    """恢复对账替身：只实现 query_operation（只查不交）。"""

    def __init__(self, remote_by_id):
        self.remote_by_id = dict(remote_by_id)
        self.queried: list[str] = []

    async def query_operation(self, operation_id):
        self.queried.append(operation_id)
        return self.remote_by_id.get(
            operation_id, {"operation_id": operation_id, "status": "unknown"})

    def reset_seq(self, seq):
        self.reset_to = seq


def _make_running_run(run_id="run-resume", user_id="u-f2", session_id="s-f2"):
    run = runs_module.create_or_get_run(
        run_id=run_id, owner=user_id, session_id=session_id,
        proposal_id="pp-1", proposal_version=1,
        scope_hash="h" * 16, approval_id=run_id)
    return run


async def test_resume_adopts_terminal_evidence():
    from nexus import experiment_agent as agent_module

    run = _make_running_run()
    ops_module.prepare_intent(
        run_id=run["run_id"], seq=1, command="pip install x", timeout_s=60)
    ops_module.set_intent_status(
        run["run_id"], f"{run['run_id']}-op-0001", "submitted")
    fake = _FakeBackend({
        f"{run['run_id']}-op-0001": {
            "operation_id": f"{run['run_id']}-op-0001", "status": "succeeded",
            "exit_code": 0, "output_tail": "installed"},
    })
    result = await agent_module.resume_bound_run(
        run_id=run["run_id"], owner="u-f2", session_id="s-f2", backend=fake)
    assert result["adopted_terminal"] == 1
    assert result["needs_continue"] is True
    assert fake.reset_to == 1, "序号对齐到补记 attempt"
    stored = runs_module.get_run(run["run_id"])
    assert stored["attempt_no"] == 1
    assert stored["attempts"][0]["exit_code"] == 0
    assert "pip install x" in stored["attempts"][0]["actual_command"]


async def test_resume_unknown_holds_without_resubmit():
    from nexus import experiment_agent as agent_module

    run = _make_running_run(run_id="run-unknown")
    ops_module.prepare_intent(
        run_id=run["run_id"], seq=1, command="sleep 600", timeout_s=60)
    ops_module.set_intent_status(
        run["run_id"], f"{run['run_id']}-op-0001", "submitted")
    fake = _FakeBackend({})
    result = await agent_module.resume_bound_run(
        run_id=run["run_id"], owner="u-f2", session_id="s-f2", backend=fake)
    assert result["unknown"] == 1
    assert result["needs_continue"] is False, "未知禁重交"
    assert runs_module.get_run(run["run_id"])["attempt_no"] == 0


async def test_resume_rejects_foreign_and_terminal():
    from nexus import experiment_agent as agent_module

    run = _make_running_run(run_id="run-guard")
    foreign = await agent_module.resume_bound_run(
        run_id=run["run_id"], owner="attacker", session_id="s-f2",
        backend=_FakeBackend({}))
    assert foreign["code"] == "RUN_FORBIDDEN"
    runs_module.set_status(run["run_id"], "failed", "done")
    terminal = await agent_module.resume_bound_run(
        run_id=run["run_id"], owner="u-f2", session_id="s-f2",
        backend=_FakeBackend({}))
    assert terminal.get("already_terminal") is True


def test_persistence_gate_local_memory_passes(monkeypatch):
    """本地无 DSN → 内存模式放行（不承诺恢复）."""
    from nexus import config as config_module
    from nexus.tools import reproduction as repro_module

    class _Settings:
        postgres_dsn = ""
        postgres_schema = "nexus_checkpoints"

    monkeypatch.setattr(config_module, "get_settings", lambda: _Settings())
    repro_module._require_experiment_persistence()  # 不抛即过


def test_persistence_gate_degraded_rejects(monkeypatch):
    """DSN 已配但 saver 未就绪 → 拒绝新长实验（不核销由调用方保证）."""
    from nexus import config as config_module
    from nexus import approvals as approvals_module
    from nexus import main as main_module
    from nexus.tools import reproduction as repro_module

    class _Settings:
        postgres_dsn = "postgresql://db/nexus"
        postgres_schema = "nexus_checkpoints"

    monkeypatch.setattr(config_module, "get_settings", lambda: _Settings())
    monkeypatch.setattr(main_module, "_pg_saver", None)
    with pytest.raises(approvals_module.ApprovalError) as exc:
        repro_module._require_experiment_persistence()
    assert exc.value.code == "PERSISTENCE_UNAVAILABLE"


def test_backend_submit_carries_fencing():
    """提交携带 fencing；旧 token 拒绝映射为 FENCING_REJECTED."""
    import httpx

    from nexus.experiment_sandbox import (
        ExperimentSandboxError,
        HttpSandboxBackend,
    )

    backend = HttpSandboxBackend(run_id="run-fence")
    backend.set_fencing("token-A")
    operation_id, payload, cached = backend._prepare_submit("echo hi", 30)
    assert cached is None
    assert payload["fencing"] == "token-A"

    def _handler(request):
        return httpx.Response(409, json={"detail": "FENCING_REJECTED:过期"})

    transport = httpx.MockTransport(_handler)
    backend2 = HttpSandboxBackend(
        run_id="run-fence2", base_url="http://control.test",
        transport=transport)
    with pytest.raises(ExperimentSandboxError) as exc:
        backend2._read_json(
            transport.handle_request(
                httpx.Request("POST", "http://control.test/x")),
            "/sandboxes/run-fence2/operations")
    assert exc.value.code == "FENCING_REJECTED"


def test_replay_nonce_ids_registered_with_nonce():
    """干净B重放 nonce 后缀不得被意图登记绕过（意图键与提交 id 一致）."""
    from nexus.experiment_clean import _ReplayBackend

    backend = _ReplayBackend(
        run_id="run-clean-abc123", base_url="http://control.test",
        _nonce="deadbeef")
    operation_id, payload, cached = backend._prepare_submit("echo hi", 30)
    assert cached is None
    assert operation_id.endswith("-deadbeef")
    assert payload["operation_id"] == operation_id
    intent = ops_module.get_intent("run-clean-abc123", operation_id)
    assert intent is not None
    assert intent["operation_id"] == operation_id
