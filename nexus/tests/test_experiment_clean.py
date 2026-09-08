"""SR6 干净B：全新沙箱重放冻结配方，比对退出码（确定性，不经 LLM）。

行为契约：
- 只重放冻结步骤（与 T6 配方同源同过滤：非空＋排除路由探针），不发明、
  不修改、不跳过命令；模型不参与；
- 沙箱 id 与原 run 隔离（`{run}-clean1`，零复用）；用后即回收；
- 全等→passed，任一不等→failed；超时/中断如实抛错，不持久化 verdict；
- 结论幂等（已有 passed/failed 直接返回）；只接受本人终态 run；
- 报告生成自动带出已持久化 clean 结论（无→not_run）。

全调用真实业务代码；控制服务经 MockTransport 替身（ tracking 确保
干净 id 隔离与回收调用）。
"""

import httpx
import pytest

from nexus import approvals
from nexus import experiment_clean as clean_module
from nexus import experiment_runs as runs_module
from nexus import proposals as proposals_module


@pytest.fixture(autouse=True)
def _clean_stores():
    from nexus import experiment_clean as clean_module

    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()
    clean_module._VERIFYING.clear()
    yield
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()
    clean_module._VERIFYING.clear()


def _scope():
    return {
        "objective": "配置并试跑", "repo_url": "https://github.com/example/r",
        "repo_revision": "deadbeef1234567890", "source_refs": [], "data_refs": [],
        "network_profile": "pypi-allowed",
        "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                      "wall_time_s": 1800},
        "mode": "smoke", "allow_environment_repair": True,
    }


def _make_terminal_run(user_id="u-sr6", session_id="s-sr6", commands=(0, 0),
                       extra_attempts=()):
    """建已核验提案→核销→run→按给定退出码追加 attempt→落终态 succeeded。

    extra_attempts：[(command, exit_code)]，在落终态前追加（终态后不可追加）。
    """
    proposal = proposals_module.create_proposal(
        user_id=user_id, session_id=session_id, preset=None,
        kind="autonomous_experiment", scope=_scope(),
        license_info={"spdx": "MIT", "status": "verified"})
    req = proposals_module.request_approval_for_proposal(
        proposal["proposal_id"], user_id=user_id,
        expected_version=proposal["version"])
    aid = req["approval"]["approval_id"]
    approvals.decide_approval(aid, user_id, "approved")
    approvals.consume_approval(aid, user_id=user_id, session_id=session_id,
                               preset={})
    run = runs_module.create_or_get_run(
        run_id=aid, owner=user_id, session_id=session_id,
        proposal_id=proposal["proposal_id"], proposal_version=1,
        scope_hash=proposal["scope_hash"], approval_id=aid)
    for index, code in enumerate(commands):
        runs_module.record_attempt(
            run["run_id"], actual_command=f"step-{index} --do",
            operation_id=f"{run['run_id']}-op-{index + 2:04d}",
            exit_code=code, log_ref="ok")
    for extra_index, (extra_command, extra_code) in enumerate(extra_attempts):
        runs_module.record_attempt(
            run["run_id"], actual_command=extra_command,
            operation_id=f"{run['run_id']}-op-{9000 + extra_index:05d}",
            exit_code=extra_code, log_ref="ok")
    runs_module.set_status(run["run_id"], "succeeded", "")
    return runs_module.get_run(run["run_id"])


class _ReplayContainer:
    """假控制服务：按命令返回预设退出码；记录 ensure/cancel 与归属 id。"""

    def __init__(self, exits=None):
        self.exits = dict(exits or {})
        self.ensure_ids: list[str] = []
        self.posts: list[tuple[str, str]] = []
        self.cancel_ids: list[str] = []

    def responder(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        def _body():
            try:
                return dict(_json.loads(request.content.decode() or "{}"))
            except Exception:
                return {}

        path = request.url.path
        if request.method == "PUT" and "/sandboxes/" in path and "/files/" not in path:
            run_id = path.rsplit("/sandboxes/", 1)[-1]
            self.ensure_ids.append(run_id)
            return httpx.Response(200, json={"sandbox_id": f"sbx-{run_id}",
                                             "status": "ready"})
        if request.method == "POST" and path.endswith("/operations"):
            run_id = path.split("/sandboxes/", 1)[-1].split("/")[0]
            body = _body()
            command = str(body.get("command", ""))
            self.posts.append((run_id, command))
            code = self.exits.get(command, 0)
            return httpx.Response(200, json={
                "operation_id": body.get("operation_id", ""), "status": "succeeded",
                "exit_code": code, "output_tail": f"exit={code}",
                "output_truncated": False})
        if request.method == "POST" and path.endswith("/cancel"):
            run_id = path.split("/sandboxes/", 1)[-1].split("/")[0]
            self.cancel_ids.append(run_id)
            return httpx.Response(200, json={"status": "cancelled"})
        if request.method == "GET":
            return httpx.Response(200, json={"sandbox_id": "sbx-x", "status": "ready"})
        return httpx.Response(404, json={"detail": "unknown"})


def _backend_for(container, run_id):
    from nexus.experiment_sandbox import HttpSandboxBackend

    return HttpSandboxBackend(
        run_id=run_id, base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))


def test_replay_backend_op_ids_unique_per_replay():
    """op id 跨重放唯一（控制面同 id 不运行两次；复用会 409 误杀）。

    同一干净 id 建两个 Backend：op 序列号相同但 nonce 不同 → ids 全异；
    前缀仍为 `{clean_id}-op-`（可与控制面对账）。
    """
    from nexus import experiment_clean as clean_module

    backend_a = clean_module._ReplayBackend(
        run_id="apv_x-clean1", base_url="http://control.test", token="t",
        transport=httpx.MockTransport(_ReplayContainer().responder),
        _nonce="aaa")
    backend_b = clean_module._ReplayBackend(
        run_id="apv_x-clean1", base_url="http://control.test", token="t",
        transport=httpx.MockTransport(_ReplayContainer().responder),
        _nonce="bbb")
    ids_a = {backend_a._new_operation_id() for _ in range(3)}
    ids_b = {backend_b._new_operation_id() for _ in range(3)}
    assert ids_a.isdisjoint(ids_b)
    assert all(i.startswith("apv_x-clean1-op-") for i in ids_a | ids_b)


def test_file_tool_summaries_skipped_not_counted():
    """文件工具摘要（非 shell）跳过留痕、不计入 verdict；真 shell grep 重放。"""
    from nexus import experiment_clean as clean_module

    assert clean_module.is_shell_replayable("pip install x") is True
    assert clean_module.is_shell_replayable("ls -la /workspace") is True
    assert clean_module.is_shell_replayable("ls .") is True
    assert clean_module.is_shell_replayable("grep -r foo /workspace") is True
    assert clean_module.is_shell_replayable("glob **/{README*,setup.py}") is False
    assert clean_module.is_shell_replayable("write_file /workspace/a.txt") is False
    assert clean_module.is_shell_replayable("read_file /workspace/a.txt") is False
    assert clean_module.is_shell_replayable("grep fakepkg") is False
    assert clean_module.is_shell_replayable("") is False


async def test_replay_skips_file_tool_summaries():
    """含 glob 摘要的 run：跳过该步，其余 shell 步骤全等→passed。"""
    from nexus import experiment_clean as clean_module

    run = _make_terminal_run(
        extra_attempts=[("glob **/{README*,setup.py}", 0)])
    container = _ReplayContainer()
    backend = _backend_for(container, clean_module.clean_sandbox_id(run["run_id"]))
    outcome = await clean_module.run_clean_verification(
        run_id=run["run_id"], user_id="u-sr6", backend=backend)
    assert outcome["clean_verification"] == "passed"
    assert outcome["matched"] == 2 and outcome["total"] == 2
    assert len(outcome["skipped"]) == 1
    log = clean_module.render_clean_log_markdown(
        runs_module.get_run(run["run_id"]), outcome)
    assert "未重放" in log and "glob" in log


def test_clean_sandbox_id_isolated_and_bounded():
    from nexus import experiment_clean as clean_module

    clean_id = clean_module.clean_sandbox_id("apv_123456789012")
    assert clean_id == "apv_123456789012-clean1"
    assert clean_id != "apv_123456789012"
    assert len(clean_module.clean_sandbox_id("r" * 100)) <= 64
    # 调度 nonce：每次全新 id（cancel/终态不毒化后续重验），64 上限内。
    first = clean_module.clean_sandbox_id("apv_123456789012", "abc123")
    second = clean_module.clean_sandbox_id("apv_123456789012", "def456")
    assert first != second
    assert len(first) <= 64 and len(second) <= 64
    assert first.startswith("apv_123456789012-clean-")


def test_replayable_steps_match_report_recipe():
    run = _make_terminal_run()
    steps = clean_module.replayable_steps(run)
    assert [s["command"] for s in steps] == ["step-0 --do", "step-1 --do"]
    assert all(s["exit_code"] == 0 for s in steps)


async def test_replay_passed_on_identical_env():
    run = _make_terminal_run()
    container = _ReplayContainer()
    backend = _backend_for(container, clean_module.clean_sandbox_id(run["run_id"]))
    outcome = await clean_module.run_clean_verification(
        run_id=run["run_id"], user_id="u-sr6", backend=backend)
    assert outcome["clean_verification"] == "passed"
    assert outcome["matched"] == 2 and outcome["total"] == 2
    assert outcome["deduped"] is False
    # 隔离：ensure 与提交只走干净 id，原 run id 零触达；用后即回收。
    assert container.ensure_ids == [clean_module.clean_sandbox_id(run["run_id"])]
    assert all(pid == container.ensure_ids[0] for pid, _ in container.posts)
    assert container.cancel_ids == [container.ensure_ids[0]]
    # 结论落盘。
    assert runs_module.get_run(run["run_id"])["clean_status"] == "passed"


async def test_replay_failed_on_divergence():
    run = _make_terminal_run()
    container = _ReplayContainer(exits={"step-1 --do": 1})
    backend = _backend_for(container, clean_module.clean_sandbox_id(run["run_id"]))
    outcome = await clean_module.run_clean_verification(
        run_id=run["run_id"], user_id="u-sr6", backend=backend)
    assert outcome["clean_verification"] == "failed"
    assert outcome["matched"] == 1 and outcome["total"] == 2
    assert runs_module.get_run(run["run_id"])["clean_status"] == "failed"


async def test_start_returns_verifying_then_complete_persists():
    """异步语义：start 即返 verifying；后台 _complete 落盘；再 start 幂等。"""
    from nexus import experiment_clean as clean_module

    run = _make_terminal_run()
    container = _ReplayContainer()
    backend = _backend_for(container, clean_module.clean_sandbox_id(run["run_id"]))
    started = await clean_module.start_clean_verification(
        run_id=run["run_id"], user_id="u-sr6")
    assert started == {"run_id": run["run_id"], "clean_verification": "verifying",
                       "deduped": False}
    assert runs_module.get_run(run["run_id"])["clean_status"] == "verifying"
    # verifying 中重复触发不重复调度。
    again = await clean_module.start_clean_verification(
        run_id=run["run_id"], user_id="u-sr6")
    assert again["clean_verification"] == "verifying"
    assert again["deduped"] is True
    assert len(container.posts) == 0
    # 后台完成（测试内直接 await 确定性驱动）。
    done = await clean_module._complete_clean_verification(
        run_id=run["run_id"], user_id="u-sr6", backend=backend)
    assert done["clean_verification"] == "passed"
    assert runs_module.get_run(run["run_id"])["clean_status"] == "passed"
    # 终态结论幂等。
    final = await clean_module.start_clean_verification(
        run_id=run["run_id"], user_id="u-sr6")
    assert final["deduped"] is True
    assert final["clean_verification"] == "passed"


async def test_divergent_replay_persists_failed():
    """退出码不等→failed 落盘（非复位；复位只发生在超时/中断等未知态）。"""
    from nexus import experiment_clean as clean_module

    run = _make_terminal_run()
    container = _ReplayContainer(exits={"step-0 --do": 1, "step-1 --do": 1})
    backend = _backend_for(container, clean_module.clean_sandbox_id(run["run_id"]))
    await clean_module.start_clean_verification(
        run_id=run["run_id"], user_id="u-sr6")
    done = await clean_module._complete_clean_verification(
        run_id=run["run_id"], user_id="u-sr6", backend=backend)
    assert done["clean_verification"] == "failed"
    assert runs_module.get_run(run["run_id"])["clean_status"] == "failed"


async def test_step_timeout_resets_without_verdict():
    """步骤超时→复位为空（不持久化 passed/failed），可重试。"""
    from nexus import experiment_clean as clean_module

    run = _make_terminal_run()

    class _HangingBackend:
        async def aexecute(self, command, timeout=None):
            from nexus.experiment_sandbox import _operation_to_response

            return _operation_to_response({"status": "running",
                                           "output_tail": "",
                                           "output_truncated": True})

        async def cancel(self):
            return {"status": "cancelled"}

    await clean_module.start_clean_verification(
        run_id=run["run_id"], user_id="u-sr6")
    with pytest.raises(clean_module.CleanError) as exc:
        await clean_module._complete_clean_verification(
            run_id=run["run_id"], user_id="u-sr6",
            backend=_HangingBackend(), )
    assert exc.value.code == "CLEAN_STEP_TIMEOUT"
    assert runs_module.get_run(run["run_id"])["clean_status"] == ""


def test_reset_verifying_to_idle_for_restart():
    """重启自愈：残留 verifying 复位为空并计数；终态结论不受影响。"""
    run = _make_terminal_run()
    runs_module.set_clean_verdict(run["run_id"], "verifying", "运行中")
    assert runs_module.reset_verifying_to_idle() == 1
    assert runs_module.get_run(run["run_id"])["clean_status"] == ""
    runs_module.set_clean_verdict(run["run_id"], "passed", "2/2")
    assert runs_module.reset_verifying_to_idle() == 0
    assert runs_module.get_run(run["run_id"])["clean_status"] == "passed"


async def test_stale_rule_verdict_reverified():
    """旧规则结论（rule 缺失/过期）不直接采信：重新重放覆盖。"""
    from nexus import experiment_clean as clean_module

    run = _make_terminal_run()
    runs_module.set_clean_verdict(run["run_id"], "failed", "旧口径 1/2")
    assert runs_module.get_run(run["run_id"])["clean_rule"] == ""
    container = _ReplayContainer()
    backend = _backend_for(container, clean_module.clean_sandbox_id(run["run_id"]))
    started = await clean_module.start_clean_verification(
        run_id=run["run_id"], user_id="u-sr6")
    assert started["deduped"] is False
    assert started["clean_verification"] == "verifying"
    done = await clean_module._complete_clean_verification(
        run_id=run["run_id"], user_id="u-sr6", backend=backend)
    assert done["clean_verification"] == "passed"
    stored = runs_module.get_run(run["run_id"])
    assert stored["clean_rule"] == clean_module.CLEAN_RULE_VERSION
    # 同规则下再次触发幂等。
    again = await clean_module.start_clean_verification(
        run_id=run["run_id"], user_id="u-sr6")
    assert again["deduped"] is True
    assert again["clean_verification"] == "passed"


def test_console_snapshot_carries_clean_keys():
    """console 快照直通 clean_status/clean_note（只读投影）。"""
    from nexus import experiment_store as store_module

    run = _make_terminal_run()
    snap = store_module.console_snapshot(run["run_id"])
    assert snap["clean_status"] == ""
    runs_module.set_clean_verdict(run["run_id"], "passed", "2/2 一致")
    snap2 = store_module.console_snapshot(run["run_id"])
    assert snap2["clean_status"] == "passed"
    assert snap2["clean_note"] == "2/2 一致"


async def test_gate_rejects_unfinished_cancelled_foreign():
    run = _make_terminal_run()
    # 运行中 → 拒绝。
    running = runs_module.create_or_get_run(
        run_id="run-live", owner="u-sr6", session_id="s-sr6",
        proposal_id="pp-x", proposal_version=1, scope_hash="h" * 32,
        approval_id="apv-x")
    assert running["status"] == "running"
    with pytest.raises(clean_module.CleanError) as exc:
        await clean_module.run_clean_verification(
            run_id="run-live", user_id="u-sr6",
            backend=_backend_for(_ReplayContainer(), "run-live-clean1"))
    assert exc.value.code == "RUN_NOT_FINISHED"
    # 已取消 → 拒绝。
    runs_module.request_cancel(run["run_id"], "u-sr6")
    runs_module.set_status(run["run_id"], "cancelled", "")
    with pytest.raises(clean_module.CleanError) as exc2:
        await clean_module.run_clean_verification(
            run_id=run["run_id"], user_id="u-sr6",
            backend=_backend_for(_ReplayContainer(), "x"))
    assert exc2.value.code == "RUN_CANCELLED"
    # 他人 → 拒绝。
    with pytest.raises(clean_module.CleanError) as exc3:
        await clean_module.run_clean_verification(
            run_id="run-live", user_id="attacker",
            backend=_backend_for(_ReplayContainer(), "x"))
    assert exc3.value.code == "RUN_FORBIDDEN"


async def test_report_picks_up_persisted_clean_verdict(monkeypatch):
    """报告自动带出干净B结论（无→not_run；有→透出，不重算）。"""
    from nexus import experiment_report as report_module

    async def _ok_write(*, artifact_type, title, content, user_id, run_id=""):
        return {"status": "success",
                "artifact": {"artifact_id": "art-x", "artifact_type": artifact_type,
                             "title": title, "size_bytes": len(content),
                             "download_path": "/x/download"}}

    monkeypatch.setattr(report_module.artifact_client,
                        "write_artifact_via_backend", _ok_write)
    run = _make_terminal_run()
    # 未验证 → not_run。
    out = await report_module.generate_run_report(
        run_id=run["run_id"], user_id="u-sr6", backend=None)
    assert out["clean_verification"] == "not_run"
    # 落盘 passed → 报告透出 passed。
    runs_module.set_clean_verdict(run["run_id"], "passed", "2/2 一致")
    out2 = await report_module.generate_run_report(
        run_id=run["run_id"], user_id="u-sr6", backend=None)
    assert out2["clean_verification"] == "passed"


async def test_clean_endpoint_codes(monkeypatch):
    """Runtime clean-verify 端点：Auto 即返 verifying（异步）；Ask 403；
    未知模式 400；跨用户 404。重放在后台完成，不阻塞 HTTP。
    """
    from httpx import ASGITransport, AsyncClient

    from nexus.main import app

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    run = _make_terminal_run(user_id="u-http", session_id="s-http")
    user = {"X-Nexus-User-Id": "u-http"}
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        bad_mode = await client.post(
            f"/api/v1/nexus/repro/runs/{run['run_id']}/clean-verify",
            json={"research_execution_mode": "turbo"}, headers=user)
        assert bad_mode.status_code == 400
        ask = await client.post(
            f"/api/v1/nexus/repro/runs/{run['run_id']}/clean-verify",
            json={"research_execution_mode": "ask"}, headers=user)
        assert ask.status_code == 403
        cross = await client.post(
            f"/api/v1/nexus/repro/runs/{run['run_id']}/clean-verify",
            json={"research_execution_mode": "auto"},
            headers={"X-Nexus-User-Id": "attacker"})
        assert cross.status_code == 404
        first = await client.post(
            f"/api/v1/nexus/repro/runs/{run['run_id']}/clean-verify",
            json={"research_execution_mode": "auto"}, headers=user)
        assert first.status_code == 200, first.text
        assert first.json()["clean_verification"] == "verifying"
        assert first.json()["deduped"] is False
        # 去重语义在 start 层单测覆盖（端点后台任务时序不定，此处不断言二次）。


async def test_formats_endpoint_writes_word_and_tex(monkeypatch):
    """Runtime formats 端点：同报告门；落盘 .docx＋.tex 双产物；返回自检。"""
    from httpx import ASGITransport, AsyncClient

    from nexus import experiment_report as report_module
    from nexus.main import app

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    async def _ok_write(*, artifact_type, title, content, user_id, run_id=""):
        return {"status": "success",
                "artifact": {"artifact_id": f"art-{artifact_type}",
                             "artifact_type": artifact_type, "title": title,
                             "size_bytes": len(content),
                             "download_path": "/x/download"}}

    async def _ok_write_bin(*, artifact_type, title, raw, user_id, run_id=""):
        assert raw[:2] == b"PK"
        return {"status": "success",
                "artifact": {"artifact_id": "art-word",
                             "artifact_type": artifact_type, "title": title,
                             "size_bytes": len(raw),
                             "download_path": "/x/download"}}

    monkeypatch.setattr(report_module.artifact_client,
                        "write_artifact_via_backend", _ok_write)
    monkeypatch.setattr(report_module.artifact_client,
                        "write_binary_artifact_via_backend", _ok_write_bin)
    run = _make_terminal_run(user_id="u-http", session_id="s-http")
    user = {"X-Nexus-User-Id": "u-http"}
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        ok_resp = await client.post(
            f"/api/v1/nexus/repro/runs/{run['run_id']}/formats", headers=user)
        assert ok_resp.status_code == 200, ok_resp.text
        body = ok_resp.json()
        assert body["derived_from"] == "experiment-report/1"
        assert len(body["artifacts"]) == 2
        assert body["checks"]["docx"]["ok"] is True
        assert body["checks"]["tex"]["ok"] is True
        assert body["checks"]["compile"]["code"] in (
            "TOOLCHAIN_MISSING", "COMPILED", "COMPILE_FAILED",
            "COMPILE_TIMEOUT", "COMPILE_UNAVAILABLE")
        cross = await client.post(
            f"/api/v1/nexus/repro/runs/{run['run_id']}/formats",
            headers={"X-Nexus-User-Id": "attacker"})
        assert cross.status_code == 404
