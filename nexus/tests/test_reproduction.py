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
