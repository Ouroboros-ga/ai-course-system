"""NX-LB2 回归：结构化提案＋参数编译＋审批绑定＋指标基线。

全 mock：能调真实 Worker（respx 拦截出站）、不用 PG（内存提案/审批）。
验收映射（P2 计划 §9.3）：
- 同 preset 两版参数 diff 可审阅；越界/注入被拒；
- 旧批准不能执行新配置；重复批准/执行只产生一个 job；
- 修改与核销并发无混用（先改后核销拒绝、先核销后修改须走新提案）；
- Worker 实际参数与冻结配置一致；改参后未知基线诚实显示。
"""

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from nexus import approvals, proposals
from nexus.main import app
from nexus.tools.reproduction import REPRO_PRESETS

_NANOGPT = REPRO_PRESETS["nanogpt"]


@pytest.fixture(autouse=True)
def _clean_stores():
    proposals.clear_memory_store()
    approvals.clear_memory_store()
    yield
    proposals.clear_memory_store()
    approvals.clear_memory_store()


def _make(user="7", session="s1", **kw):
    args = {"user_id": user, "session_id": session, "preset": _NANOGPT}
    args.update(kw)
    return proposals.create_proposal(**args)


# ---------------------------------------------------------------------------
# 参数 schema 与确定性编译
# ---------------------------------------------------------------------------


def test_param_validation_rejects_unknown_type_range():
    ok = proposals.validate_parameters("nanogpt", {"max_iters": 500, "batch_size": 8})
    assert ok["max_iters"] == 500 and ok["batch_size"] == 8
    # 缺省回填默认值。
    assert proposals.validate_parameters("nanogpt", {})["max_iters"] == 2000
    with pytest.raises(proposals.ProposalError) as e1:
        proposals.validate_parameters("nanogpt", {"rm_rf": 1})
    assert e1.value.code == "PROPOSAL_PARAM_UNKNOWN"
    with pytest.raises(proposals.ProposalError) as e2:
        proposals.validate_parameters("nanogpt", {"max_iters": 999999})
    assert e2.value.code == "PROPOSAL_PARAM_OUT_OF_RANGE"
    with pytest.raises(proposals.ProposalError) as e3:
        proposals.validate_parameters("nanogpt", {"max_iters": "fast"})
    assert e3.value.code == "PROPOSAL_PARAM_TYPE"
    with pytest.raises(proposals.ProposalError) as e4:
        proposals.validate_parameters("nanogpt", {"dropout": True})
    assert e4.value.code == "PROPOSAL_PARAM_TYPE"


def test_compiler_deterministic_and_matches_preset_defaults():
    params = proposals.validate_parameters("nanogpt", {})
    steps = proposals.compile_steps("nanogpt", params)
    # 默认参数编译结果与预设固定命令逐字一致（确定性锁定）。
    assert steps == _NANOGPT["steps"]
    twice = proposals.compile_steps("nanogpt", dict(params))
    assert twice == steps
    changed = proposals.compile_steps("nanogpt", {**params, "max_iters": 500})
    assert changed != steps
    assert "--max_iters=500" in changed[3] and "--lr_decay_iters=500" in changed[3]


def test_compiler_lr_decay_floor_avoids_warmup_division_by_zero():
    """线上 E2E 回归：max_iters<=100 时 lr_decay_iters 至少 101，
    否则 train.py get_lr 除零（warmup 默认 100）"""
    params = proposals.validate_parameters("nanogpt", {"max_iters": 100})
    steps = proposals.compile_steps("nanogpt", params)
    assert "--max_iters=100" in steps[3]
    assert "--lr_decay_iters=101" in steps[3]


def test_compiler_eval_interval_clamped_for_checkpoint():
    """线上 E2E 回归：ckpt 只在整除步写盘，eval_interval 钳到 <= max_iters，
    否则小步数运行无 ckpt 可采样；默认值不拼 flag（预设逐字一致）。"""
    params = proposals.validate_parameters("nanogpt", {"max_iters": 100})
    steps = proposals.compile_steps("nanogpt", params)
    assert "--eval_interval=100" in steps[3]
    default_steps = proposals.compile_steps(
        "nanogpt", proposals.validate_parameters("nanogpt", {}))
    assert "--eval_interval" not in default_steps[3]


def test_metric_basis_verified_only_on_defaults():
    defaults = proposals.validate_parameters("nanogpt", {})
    data = dict(proposals.NANOGPT_DEFAULT_DATA)
    verified = proposals.resolve_metric_policy(_NANOGPT, defaults, data)
    assert verified["basis"] == "verified"
    assert verified["expected_metrics"]["val_loss"]["target"] == 1.88
    changed = proposals.validate_parameters("nanogpt", {"batch_size": 8})
    exploratory = proposals.resolve_metric_policy(_NANOGPT, changed, data)
    assert exploratory["basis"] == "exploratory"
    assert exploratory["expected_metrics"] == {}
    assert "batch_size" in exploratory["reason"]
    # 非测量类参数也不行——保守规则：任何敏感参数偏离即 exploratory。
    safe_only = proposals.validate_parameters("nanogpt", {"eval_iters": 50, "log_interval": 5})
    assert proposals.resolve_metric_policy(_NANOGPT, safe_only, data)["basis"] == "verified"


# ---------------------------------------------------------------------------
# 提案 CRUD：版本/diff/锁
# ---------------------------------------------------------------------------


def test_proposal_create_patch_diff_lock():
    created = _make(objective="复现基线")
    assert created["version"] == 1 and created["status"] == "draft"
    assert created["metric_policy"]["basis"] == "verified"
    assert created["history"] and len(created["history"]) == 1
    patched = proposals.patch_proposal(
        created["proposal_id"], user_id="7", expected_version=1,
        parameters={"max_iters": 500})
    assert patched["proposal"]["version"] == 2
    assert patched["proposal"]["metric_policy"]["basis"] == "exploratory"
    diff = patched["diff"]
    assert diff["from_version"] == 1 and diff["to_version"] == 2
    assert {"name": "max_iters", "old": 2000, "new": 500} in diff["parameters_changed"]
    assert diff["steps_changed"] is True
    assert diff["metric_basis_changed"] is True
    assert diff["plan_hash_changed"] is True
    # 陈旧版本再改 → 409 类错误。
    with pytest.raises(proposals.ProposalError) as exc:
        proposals.patch_proposal(
            created["proposal_id"], user_id="7", expected_version=1,
            parameters={"max_iters": 600})
    assert exc.value.code == "PROPOSAL_VERSION_CONFLICT"
    # 跨用户改 → 拒绝。
    with pytest.raises(proposals.ProposalError) as exc2:
        proposals.patch_proposal(
            created["proposal_id"], user_id="8", expected_version=2,
            parameters={"max_iters": 600})
    assert exc2.value.code == "PROPOSAL_FORBIDDEN"
    # 执行锁定后修改 → 须走新提案。
    assert proposals.mark_proposal_executed(created["proposal_id"], 2) is True
    with pytest.raises(proposals.ProposalError) as exc3:
        proposals.patch_proposal(
            created["proposal_id"], user_id="7", expected_version=2,
            parameters={"max_iters": 700})
    assert exc3.value.code == "PROPOSAL_LOCKED"


def test_proposal_create_idempotent_by_client_request_id():
    first = _make(client_request_id="req-1")
    second = _make(client_request_id="req-1")
    assert second.get("deduped") is True
    assert second["proposal_id"] == first["proposal_id"]
    third = _make(client_request_id="req-2")
    assert third["proposal_id"] != first["proposal_id"]


# ---------------------------------------------------------------------------
# 审批绑定：旧批准失效、执行冻结、重复执行幂等
# ---------------------------------------------------------------------------


def _submit_calls(monkeypatch, calls: list):
    import nexus.tools.reproduction as repro_module

    async def _fake_submit(preset):
        calls.append(list(preset.get("steps") or [])[3] if preset.get("steps") else "")
        return {"status": "submitted", "job": {"job_id": "job-pp", "status": "queued"}}

    async def _fake_ownership(job_id, preset, user_id=None):
        return True

    async def _fake_linkage(**kwargs):
        return True

    monkeypatch.setattr(repro_module, "_submit_to_worker", _fake_submit)
    monkeypatch.setattr(repro_module, "_record_job_ownership", _fake_ownership)
    monkeypatch.setattr(repro_module, "_record_run_linkage", _fake_linkage)


async def _approve_and_execute(monkeypatch, calls, proposal, user="7", session="s1"):
    """批准已 pin 的审批并执行一次；返回执行结果。"""
    from nexus.tools.reproduction import execute_approved_reproduction

    _submit_calls(monkeypatch, calls)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        req = await client.post(
            f"/api/v1/nexus/repro/proposals/{proposal['proposal_id']}/request-approval",
            json={"expected_version": proposal["version"]},
            headers={"X-Nexus-User-Id": user},
        )
        assert req.status_code == 200, req.text
        approval = req.json()["approval"]
        decided = approvals.decide_approval(approval["approval_id"], user, "approved")
        assert decided["status"] == "approved"
        return await execute_approved_reproduction(
            approval_id=approval["approval_id"], user_id=user,
            session_id=session, preset_id="nanogpt")


async def test_modify_before_consume_rejects_old_ticket(monkeypatch):
    """先改后核销：旧票据拒绝，Worker 零提交。"""
    calls: list = []
    _submit_calls(monkeypatch, calls)
    created = _make()
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        req = await client.post(
            f"/api/v1/nexus/repro/proposals/{created['proposal_id']}/request-approval",
            json={"expected_version": 1}, headers={"X-Nexus-User-Id": "7"})
        approval_id = req.json()["approval"]["approval_id"]
        approvals.decide_approval(approval_id, "7", "approved")
        # 批准后修改提案（版本 1→2，hash 漂移）。
        patched = await client.patch(
            f"/api/v1/nexus/repro/proposals/{created['proposal_id']}",
            json={"expected_version": 1, "parameters": {"max_iters": 500}},
            headers={"X-Nexus-User-Id": "7"})
        assert patched.status_code == 200
        # 旧票据执行 → 拒绝。
        from nexus.tools.reproduction import execute_approved_reproduction

        with pytest.raises(approvals.ApprovalError) as exc:
            await execute_approved_reproduction(
                approval_id=approval_id, user_id="7", session_id="s1",
                preset_id="nanogpt")
        assert exc.value.code == "APPROVAL_PROPOSAL_CHANGED"
    assert calls == []


async def test_execute_freezes_proposal_and_uses_frozen_steps(monkeypatch):
    """执行用冻结步骤提交；成功后提案锁定，后续修改须走新提案。"""
    calls: list = []
    created = _make(parameters={"max_iters": 500})
    result = await _approve_and_execute(monkeypatch, calls, created)
    assert result["status"] == "submitted"
    # Worker 实际收到的是冻结命令（max_iters=500），不是预设默认。
    assert "--max_iters=500" in calls[0]
    assert len(calls) == 1
    # 提案已冻结：再改 → LOCKED。
    with pytest.raises(proposals.ProposalError) as exc:
        proposals.patch_proposal(
            created["proposal_id"], user_id="7", expected_version=1,
            parameters={"max_iters": 600})
    assert exc.value.code == "PROPOSAL_LOCKED"
    # 同一票据重试 → 幂等返原 job，不重提交。
    from nexus.tools.reproduction import execute_approved_reproduction

    row = approvals.list_approvals(user_id="7", status="consumed")[0]
    second = await execute_approved_reproduction(
        approval_id=row["approval_id"], user_id="7", session_id="s1",
        preset_id="nanogpt")
    assert second.get("deduped") is True
    assert len(calls) == 1


async def test_request_approval_idempotent_and_version_pinned(monkeypatch):
    created = _make()
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        first = await client.post(
            f"/api/v1/nexus/repro/proposals/{created['proposal_id']}/request-approval",
            json={"expected_version": 1}, headers={"X-Nexus-User-Id": "7"})
        second = await client.post(
            f"/api/v1/nexus/repro/proposals/{created['proposal_id']}/request-approval",
            json={"expected_version": 1}, headers={"X-Nexus-User-Id": "7"})
        assert first.status_code == 200 and second.status_code == 200
        assert second.json().get("deduped") is True
        assert (second.json()["approval"]["approval_id"]
                == first.json()["approval"]["approval_id"])
        # 版本号对不上 → 409。
        stale = await client.post(
            f"/api/v1/nexus/repro/proposals/{created['proposal_id']}/request-approval",
            json={"expected_version": 99}, headers={"X-Nexus-User-Id": "7"})
        assert stale.status_code == 409


# ---------------------------------------------------------------------------
# HTTP：提案 CRUD、待办列表、presets 投影
# ---------------------------------------------------------------------------


async def test_proposal_http_crud_and_pending_list(monkeypatch):
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        created = await client.post(
            "/api/v1/nexus/repro/proposals",
            json={"preset_id": "nanogpt", "session_id": "s1",
                  "objective": "验证基线", "client_request_id": "c1"},
            headers={"X-Nexus-User-Id": "7"},
        )
        assert created.status_code == 200, created.text
        pid = created.json()["proposal"]["proposal_id"]
        # 跨用户读 → 404。
        assert (await client.get(f"/api/v1/nexus/repro/proposals/{pid}",
                                 headers={"X-Nexus-User-Id": "8"})).status_code == 404
        # 本人读：完整方案＋上一版本 diff（v1 无上一版 → null）。
        detail = await client.get(f"/api/v1/nexus/repro/proposals/{pid}",
                                  headers={"X-Nexus-User-Id": "7"})
        assert detail.status_code == 200
        assert detail.json()["proposal"]["metric_policy"]["basis"] == "verified"
        assert detail.json()["diff_previous"] is None
        # 非法字段 → 422（extra=forbid 在 Runtime 层先拦）。
        bad = await client.patch(
            f"/api/v1/nexus/repro/proposals/{pid}",
            json={"expected_version": 1, "steps": ["rm -rf /"]},
            headers={"X-Nexus-User-Id": "7"})
        assert bad.status_code == 422
        # 未知参数 → 422。
        bad_param = await client.patch(
            f"/api/v1/nexus/repro/proposals/{pid}",
            json={"expected_version": 1, "parameters": {"cuda": True}},
            headers={"X-Nexus-User-Id": "7"})
        assert bad_param.status_code == 422
        assert "PROPOSAL_PARAM_UNKNOWN" in bad_param.json()["detail"]
        # 改参 → v2 exploratory。
        patched = await client.patch(
            f"/api/v1/nexus/repro/proposals/{pid}",
            json={"expected_version": 1, "parameters": {"batch_size": 8}},
            headers={"X-Nexus-User-Id": "7"})
        assert patched.status_code == 200
        assert patched.json()["proposal"]["version"] == 2
        assert patched.json()["proposal"]["metric_policy"]["basis"] == "exploratory"
        # 待办为空（未 request-approval）；请求后出现，带提案摘要。
        empty = await client.get("/api/v1/nexus/approvals?session_id=s1&status=pending",
                                 headers={"X-Nexus-User-Id": "7"})
        assert empty.json()["items"] == []
        req = await client.post(
            f"/api/v1/nexus/repro/proposals/{pid}/request-approval",
            json={"expected_version": 2}, headers={"X-Nexus-User-Id": "7"})
        assert req.status_code == 200
        pending = await client.get("/api/v1/nexus/approvals?session_id=s1&status=pending",
                                   headers={"X-Nexus-User-Id": "7"})
        items = pending.json()["items"]
        assert len(items) == 1
        assert items[0]["proposal"]["version"] == 2
        assert items[0]["proposal"]["metric_basis"] == "exploratory"
        # 非法 status → 422。
        assert (await client.get("/api/v1/nexus/approvals?status=bogus",
                                 headers={"X-Nexus-User-Id": "7"})).status_code == 422
        # presets 投影：无凭据无命令，只有只读元数据＋schema。
        presets = await client.get("/api/v1/nexus/repro/presets")
        assert presets.status_code == 200
        nano = [p for p in presets.json()["presets"] if p["preset_id"] == "nanogpt"][0]
        assert nano["display_name"] == "nanoGPT"
        assert nano["parameters"]["defaults"]["max_iters"] == 2000
        assert "steps" not in nano and "repo_revision" not in str(nano.get("environment", {}))


async def test_report_exploratory_verdict_and_no_writeback(monkeypatch):
    """改参执行的作业：报告 EXPLORATORY（只记实测），不回写 metric，不宣称通过。"""
    import nexus.main as main_module
    from nexus.config import get_settings

    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "tok")
    monkeypatch.setenv("NEXUS_REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setenv("NEXUS_REPRO_WORKER_TOKEN", "wtok")
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    get_settings.cache_clear()

    job = {
        "job_id": "job-expl", "preset_id": "nanogpt", "status": "succeeded",
        "requested_license": "MIT",
        "license_checks": {"github_spdx": "MIT", "local_spdx": "MIT", "effective": "MIT"},
        "seed_used": True,
        "steps_result": [
            {"command": "python train.py ...", "exit_code": 0, "timed_out": False,
             "duration_s": 10, "log_tail": "step 500: train loss 2.1, val loss 1.91"},
        ],
    }
    linkage = {"run_id": "run-expl", "proposal_id": "pp-x", "proposal_version": 2,
               "config_snapshot": {"metric_policy": {"basis": "exploratory",
                                                     "reason": "参数偏离默认：max_iters"}}}
    writebacks: list = []

    async def fake_writeback(job_id, verdict, summary):
        writebacks.append((job_id, verdict))

    async def fake_linkage(job_id, user_id):
        return dict(linkage)

    monkeypatch.setattr(main_module, "_writeback_metric_verdict", fake_writeback)
    monkeypatch.setattr(main_module, "_fetch_run_linkage", fake_linkage)

    class _Resp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    real_client = httpx.AsyncClient

    def factory(**kwargs):
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, headers=None, params=None):
                return _Resp(job)

            async def post(self, url, json=None, headers=None):
                return _Resp({"code": 200,
                              "data": {"artifact_id": "a1", "artifact_type": "markdown",
                                       "title": "t", "size_bytes": 10}})
        return _Client()

    monkeypatch.setattr(main_module.httpx, "AsyncClient", factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nexus/repro/jobs/job-expl/report",
                headers={"X-Nexus-User-Id": "42"},
            )
    finally:
        get_settings.cache_clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "EXPLORATORY"
    assert body["comparison"] == []
    assert body["metrics_observed"]["val_loss"] == 1.91
    assert "探索性" in body["metric_note"]
    # 探索性不回写 Worker metric（Worker 只接受 PASS/FAIL/INCOMPLETE）。
    assert writebacks == []
