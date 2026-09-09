"""F3 Nexus 侧：语义路由＋在途延迟落盘＋操作工具（计划 §8）。

行为契约：
- environment/target 走会话，其余一次性（不仅按 timeout）；
- funnel 侧在途会话操作不记完成 attempt（终态由工具/认领补记）；
- describe/interrupt 窄范围（仅本 run，跨 run 拒绝）；
- 在途返回附 op 引用，exit None 不得当失败重跑（注记文本锁定）。
"""

import pytest

from nexus import experiment_operations as ops_module
from nexus import experiment_runs as runs_module
from nexus.experiment_sandbox import _operation_ref_note


@pytest.fixture(autouse=True)
def _clean():
    ops_module.clear_memory_store()
    runs_module.clear_memory_store()
    yield
    ops_module.clear_memory_store()
    runs_module.clear_memory_store()


def _make_run(run_id="run-f3tools", user_id="u-f3", session_id="s-f3"):
    return runs_module.create_or_get_run(
        run_id=run_id, owner=user_id, session_id=session_id,
        proposal_id="pp-1", proposal_version=1,
        scope_hash="h" * 16, approval_id=run_id)


def test_route_session_by_semantics():
    from nexus.experiment_sandbox import HttpSandboxBackend

    assert HttpSandboxBackend._route_session("pip install -r requirements.txt") is True
    assert HttpSandboxBackend._route_session("python train.py --epochs 3") is True
    assert HttpSandboxBackend._route_session("curl -O https://example.com/a.tgz") is True
    assert HttpSandboxBackend._route_session("pwd") is False
    assert HttpSandboxBackend._route_session("ls /workspace") is False
    assert HttpSandboxBackend._route_session("python --version") is False
    assert HttpSandboxBackend._route_session("pytest tests/") is False
    # 文件工具摘要形（`write_file <单token>`）归 probe 类 → 一次性；
    # 真 shell 命令不受影响（见 clean 侧同形判别）。
    assert HttpSandboxBackend._route_session("write_file x") is False
    # kind_hint=file_tool 恒为一次性（文件工具内部操作不进会话语义路由）。
    from nexus import experiment_contracts as contracts_module

    assert contracts_module.classify_operation("write_file x", "file_tool") == "file_tool"


def test_operation_ref_note_distinguishes_session():
    session_note = _operation_ref_note("run-op-0002", 42, True)
    assert "run-op-0002" in session_note
    assert "describe_operation" in session_note
    assert "interrupt_operation" in session_note
    assert "重发" in session_note
    oneshot_note = _operation_ref_note("run-op-0003", 5, False)
    assert "无中断语义" in oneshot_note
    assert "不要重发" in oneshot_note


def test_inflight_helpers():
    from nexus import experiment_agent as agent_module

    run = _make_run()
    assert agent_module._inflight_session_ops(run["run_id"]) == []
    ops_module.prepare_intent(run_id=run["run_id"], seq=1,
                              command="pip install x", timeout_s=60)
    assert agent_module._intent_in_flight(run["run_id"], f"{run['run_id']}-op-0001") is True
    assert agent_module._inflight_session_ops(run["run_id"]) == [f"{run['run_id']}-op-0001"]
    ops_module.set_intent_status(run["run_id"], f"{run['run_id']}-op-0001",
                                 "succeeded", exit_code=0, output_tail="ok")
    assert agent_module._intent_in_flight(run["run_id"], f"{run['run_id']}-op-0001") is False
    assert agent_module._last_terminal_exit(run["run_id"]) is None
    runs_module.record_attempt(run["run_id"], actual_command="pip install x",
                               config_changes={"kind": "execute", "op_kind": "environment"},
                               operation_id=f"{run['run_id']}-op-0001",
                               exit_code=0, log_ref="ok")
    assert agent_module._inflight_session_ops(run["run_id"]) == []
    assert agent_module._last_terminal_exit(run["run_id"]) == 0


class _OpsBackend:
    """工具测试替身：query/cancel 可脚本化，归属 run-f3tools。"""

    _run_id = "run-f3tools"

    def __init__(self):
        self.observed = {"status": "running", "exit_code": None,
                         "increment": "partial\n", "offset": 8,
                         "reset": False, "output_tail": "partial\n"}
        self.cancelled = {"status": "cancelled", "exit_code": None,
                          "output_tail": "partial\n[killed]",
                          "unconfirmed": False}

    async def query_operation(self, operation_id, cursor=0, probe=False):
        assert operation_id == "run-f3tools-op-0001"
        self.last_query = {"cursor": cursor, "probe": probe}
        return dict(self.observed)

    async def cancel_operation(self, operation_id):
        assert operation_id == "run-f3tools-op-0001"
        return dict(self.cancelled)


def _tools():
    from nexus import experiment_agent as agent_module

    return agent_module._operation_tools("run-f3tools", _OpsBackend())


async def test_describe_rejects_foreign_operation():
    describe, _ = _tools()
    out = await describe.ainvoke({"operation_id": "other-run-op-0001"})
    assert "拒绝" in out
    assert "不属于当前实验" in out


async def test_describe_running_returns_increment():
    _make_run()
    ops_module.prepare_intent(run_id="run-f3tools", seq=1,
                              command="pip install x", timeout_s=600)
    describe, _ = _tools()
    out = await describe.ainvoke({"operation_id": "run-f3tools-op-0001"})
    assert "running" in out
    assert "partial" in out
    # 在途不补记 attempt。
    assert runs_module.get_run("run-f3tools")["attempt_no"] == 0


async def test_describe_terminal_backfills_attempt():
    _make_run()
    ops_module.prepare_intent(run_id="run-f3tools", seq=1,
                              command="pip install x", timeout_s=600)
    backend = _OpsBackend()
    backend.observed = {"status": "succeeded", "exit_code": 0,
                        "increment": "done\n", "offset": 5, "reset": True,
                        "output_tail": "done\n", "declared_exit": 0,
                        "facility_confirmed": True}
    from nexus import experiment_agent as agent_module

    describe, _ = agent_module._operation_tools("run-f3tools", backend)
    out = await describe.ainvoke({"operation_id": "run-f3tools-op-0001"})
    assert "succeeded" in out
    stored = runs_module.get_run("run-f3tools")
    assert stored["attempt_no"] == 1
    assert stored["attempts"][0]["exit_code"] == 0
    # 幂等：重复观测不重复补记。
    await describe.ainvoke({"operation_id": "run-f3tools-op-0001"})
    assert runs_module.get_run("run-f3tools")["attempt_no"] == 1


async def test_interrupt_records_cancelled_attempt():
    _make_run()
    ops_module.prepare_intent(run_id="run-f3tools", seq=1,
                              command="sleep 600", timeout_s=600)
    _, interrupt = _tools()
    out = await interrupt.ainvoke({"operation_id": "run-f3tools-op-0001"})
    assert "已中断并确认停止" in out
    stored = runs_module.get_run("run-f3tools")
    assert stored["attempt_no"] == 1
    assert stored["attempts"][0]["exit_code"] is None


async def test_interrupt_rejects_foreign_operation():
    _, interrupt = _tools()
    out = await interrupt.ainvoke({"operation_id": "other-run-op-0009"})
    assert "拒绝" in out
