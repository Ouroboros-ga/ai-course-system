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
        "repo_revision": "deadbeef1234567890", "source_refs": [], "data_refs": [],
        "network_profile": "pypi-allowed",
        "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                      "wall_time_s": 1800},
        "mode": "smoke", "allow_environment_repair": True,
    }


def _make_terminal_run(user_id="u-sr6", session_id="s-sr6", commands=(0, 0)):
    """建已核验提案→核销→run→按给定退出码追加 attempt→落终态 succeeded。"""
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


def test_clean_sandbox_id_isolated_and_bounded():
    clean_id = clean_module.clean_sandbox_id("apv_123456789012")
    assert clean_id == "apv_123456789012-clean1"
    assert clean_id != "apv_123456789012"
    assert len(clean_module.clean_sandbox_id("r" * 100)) <= 64


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


async def test_verdict_idempotent_no_replay():
    run = _make_terminal_run()
    container = _ReplayContainer()
    backend = _backend_for(container, clean_module.clean_sandbox_id(run["run_id"]))
    first = await clean_module.run_clean_verification(
        run_id=run["run_id"], user_id="u-sr6", backend=backend)
    assert first["deduped"] is False
    posts_before = len(container.posts)
    second = await clean_module.run_clean_verification(
        run_id=run["run_id"], user_id="u-sr6", backend=backend)
    assert second["deduped"] is True
    assert second["clean_verification"] == "passed"
    assert len(container.posts) == posts_before


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
    """Runtime clean-verify 端点：Auto 执行；Ask 403；未知模式 400；跨用户 404。"""
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
