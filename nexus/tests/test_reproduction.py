import httpx
import respx

from nexus import approvals
from nexus import request_scope
from nexus.tools.reproduction import plan_reproduction, run_reproduction


async def test_plan_reproduction_preset_by_id():
    result = await plan_reproduction.ainvoke({"target": "nanogpt"})
    assert result["status"] == "success"
    assert result["source"] == "verified_preset"
    assert result["plan"]["repo_url"] == "https://github.com/karpathy/nanoGPT"
    assert result["plan"]["repo_license"] == "MIT"
    assert "device=cpu" in result["plan"]["steps"][3]


async def test_plan_reproduction_by_paper_title():
    result = await plan_reproduction.ainvoke(
        {"target": "Language Models are Unsupervised Multitask Learners"}
    )
    assert result["status"] == "success"
    assert result["plan"]["preset_id"] == "nanogpt"


async def test_plan_reproduction_unknown_target_no_fabrication():
    result = await plan_reproduction.ainvoke({"target": "some random paper"})
    assert result["status"] == "no_preset"
    assert "调研" in result["detail"]
    assert "nanogpt" in result["known_presets"]


async def test_run_reproduction_without_approval_proposes_zero_submit(monkeypatch):
    """NX-G2：无票据时只提案（approval_required），Worker 零接触。"""
    import nexus.tools.reproduction as repro_module

    approvals.clear_memory_store()

    async def _must_not_submit(preset):
        raise AssertionError("无批准不得提交 Worker")

    monkeypatch.setattr(repro_module, "_submit_to_worker", _must_not_submit)
    result = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
    assert result["status"] == "approval_required"
    assert result["code"] == "APPROVAL_REQUIRED"
    assert result["approval"]["approval_id"].startswith("apv_")
    assert result["approval"]["status"] == "pending"
    # 提案已持久化归属（批准前落库，不依赖提交后登记）。
    stored = approvals.get_approval(result["approval"]["approval_id"])
    assert stored is not None and stored["status"] == "pending"


async def test_run_reproduction_unknown_preset_rejected():
    result = await run_reproduction.ainvoke({"preset_id": "unknown"})
    assert result["status"] == "rejected"
    assert result["code"] == "UNKNOWN_PRESET"


async def test_run_reproduction_submits_to_worker(monkeypatch):
    monkeypatch.setenv("NEXUS_REPRO_WORKER_URL", "http://127.0.0.1:9100")
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        approvals.clear_memory_store()
        proposal = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
        approval_id = proposal["approval"]["approval_id"]
        approvals.decide_approval(approval_id, "", "approved")
        tokens = request_scope.set_execution_scope("", approval_id)
        try:
            with respx.mock:
                respx.post("http://127.0.0.1:9100/jobs").mock(
                    return_value=httpx.Response(200, json={"job_id": "job-1", "status": "queued"})
                )
                result = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
        finally:
            request_scope.reset_execution_scope(tokens)
        assert result["status"] == "submitted"
        assert result["job"]["job_id"] == "job-1"
        assert result["approval_id"] == approval_id
    finally:
        get_settings.cache_clear()


async def test_run_reproduction_sends_bearer_token_when_configured(monkeypatch):
    """Worker 侧开启认证时，Nexus 必须携带 REPRO_WORKER_TOKEN 对应的 Bearer 头。"""
    monkeypatch.setenv("NEXUS_REPRO_WORKER_URL", "http://127.0.0.1:9100")
    monkeypatch.setenv("NEXUS_REPRO_WORKER_TOKEN", "worker-secret")
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        approvals.clear_memory_store()
        proposal = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
        approval_id = proposal["approval"]["approval_id"]
        approvals.decide_approval(approval_id, "", "approved")
        tokens = request_scope.set_execution_scope("", approval_id)
        try:
            with respx.mock:
                seen = {}

                def _capture(request: httpx.Request) -> httpx.Response:
                    seen["authorization"] = request.headers.get("Authorization")
                    return httpx.Response(200, json={"job_id": "job-2", "status": "queued"})

                respx.post("http://127.0.0.1:9100/jobs").mock(side_effect=_capture)
                result = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
        finally:
            request_scope.reset_execution_scope(tokens)
        assert result["status"] == "submitted"
        assert seen["authorization"] == "Bearer worker-secret"
    finally:
        get_settings.cache_clear()


async def test_run_reproduction_reuses_pending_approval_same_plan():
    """对话确认不再建重复卡：同用户同会话同方案复用待批审批。"""
    import nexus.tools.reproduction as repro_module

    approvals.clear_memory_store()

    async def _must_not_submit(preset):
        raise AssertionError("无批准不得提交 Worker")

    orig = repro_module._submit_to_worker
    repro_module._submit_to_worker = _must_not_submit
    scope_tokens = request_scope.set_scope("u-dedupe", None)
    exec_tokens = request_scope.set_execution_scope("s-dedupe", None)
    try:
        first = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
        second = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
    finally:
        request_scope.reset_scope(scope_tokens)
        request_scope.reset_execution_scope(exec_tokens)
        repro_module._submit_to_worker = orig
    assert first["code"] == "APPROVAL_REQUIRED"
    assert first.get("deduped") is False
    assert second["code"] == "APPROVAL_REQUIRED"
    assert second.get("deduped") is True
    assert second["approval"]["approval_id"] == first["approval"]["approval_id"]
    pending = approvals.list_approvals(
        user_id="u-dedupe", status="pending", session_id="s-dedupe")
    assert len(pending) == 1


async def test_run_reproduction_new_card_for_other_session_or_expired(monkeypatch):
    """他会话隔离；过期不复活。"""
    approvals.clear_memory_store()
    scope_tokens = request_scope.set_scope("u-dedupe2", None)
    exec_a = request_scope.set_execution_scope("s-a", None)
    try:
        first = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
    finally:
        request_scope.reset_execution_scope(exec_a)
    exec_b = request_scope.set_execution_scope("s-b", None)
    try:
        other = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
    finally:
        request_scope.reset_execution_scope(exec_b)
        request_scope.reset_scope(scope_tokens)
    assert other["approval"]["approval_id"] != first["approval"]["approval_id"]
    assert other.get("deduped") is False
    # 时间快进到过期后：同会话也不复用。
    monkeypatch.setattr(approvals, "_now", lambda: 1e12)
    scope_tokens = request_scope.set_scope("u-dedupe2", None)
    exec_a = request_scope.set_execution_scope("s-a", None)
    try:
        again = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
    finally:
        request_scope.reset_execution_scope(exec_a)
        request_scope.reset_scope(scope_tokens)
    assert again["approval"]["approval_id"] != first["approval"]["approval_id"]
    assert again.get("deduped") is False


def test_find_pending_approval_matching_rules():
    """helper 直测：键全对才命中，过期/串户/串工具/串方案一律 None。"""
    approvals.clear_memory_store()
    row = approvals.create_approval(
        user_id="u-match", session_id="s-match", tool="run_reproduction",
        preset={"preset_id": "nanogpt"}, ttl_s=600)
    plan_hash = row["plan_hash"]
    assert plan_hash
    found = approvals.find_pending_approval(
        user_id="u-match", session_id="s-match",
        tool="run_reproduction", plan_hash=plan_hash)
    assert found is not None and found["approval_id"] == row["approval_id"]
    assert approvals.find_pending_approval(
        user_id="u-match", session_id="s-match",
        tool="run_reproduction", plan_hash="other") is None
    assert approvals.find_pending_approval(
        user_id="u-match", session_id="s-match",
        tool="other_tool", plan_hash=plan_hash) is None
    assert approvals.find_pending_approval(
        user_id="stranger", session_id="s-match",
        tool="run_reproduction", plan_hash=plan_hash) is None
    assert approvals.find_pending_approval(
        user_id="u-match", session_id="s-match",
        tool="run_reproduction", plan_hash="") is None
