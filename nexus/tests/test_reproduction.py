import httpx
import respx

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


async def test_run_reproduction_without_worker_fails_closed():
    result = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
    assert result["status"] == "unavailable"
    assert result["code"] == "REPRO_WORKER_UNAVAILABLE"
    assert result["plan"]["repo_license"] == "MIT"


async def test_run_reproduction_unknown_preset_rejected():
    result = await run_reproduction.ainvoke({"preset_id": "unknown"})
    assert result["status"] == "rejected"
    assert result["code"] == "UNKNOWN_PRESET"


async def test_run_reproduction_submits_to_worker(monkeypatch):
    monkeypatch.setenv("NEXUS_REPRO_WORKER_URL", "http://127.0.0.1:9100")
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        with respx.mock:
            respx.post("http://127.0.0.1:9100/jobs").mock(
                return_value=httpx.Response(200, json={"job_id": "job-1", "status": "queued"})
            )
            result = await run_reproduction.ainvoke({"preset_id": "nanogpt"})
        assert result["status"] == "submitted"
        assert result["job"]["job_id"] == "job-1"
    finally:
        get_settings.cache_clear()
