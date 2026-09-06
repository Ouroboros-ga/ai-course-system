"""M4-B3 回归：确定性报告构建与判定（LLM 不参与 PASS/FAIL）+ 报告端点契约。

判定逻辑必须可复算：给定同样的 worker 记录与预设期望，verdict 恒定；
PASS/FAIL 不受任何模型输出影响。
"""

import json

import httpx

import pytest
from httpx import ASGITransport, AsyncClient

import nexus.main as main_module
from nexus import repro_report
from nexus.config import get_settings
from nexus.main import app
from nexus.tools.reproduction import REPRO_PRESETS


def _nanogpt_steps(final_val_loss: str = "1.8857") -> list[dict]:
    train_log = (
        "iter 1999: loss 1.9002, time 73.72ms\n"
        "step 2000: train loss 1.7648, val loss " + final_val_loss + "\n"
        "saving checkpoint to out-shakespeare-char"
    )
    return [
        {"command": "true && cd nanoGPT", "exit_code": 0, "timed_out": False, "duration_s": 0.0, "log_tail": ""},
        {"command": "pip install ...", "exit_code": 0, "timed_out": False, "duration_s": 97.3, "log_tail": "Successfully installed ..."},
        {"command": "python data/shakespeare_char/prepare.py", "exit_code": 0, "timed_out": False, "duration_s": 0.4, "log_tail": "vocab size: 65"},
        {"command": "python train.py ...", "exit_code": 0, "timed_out": False, "duration_s": 170.9, "log_tail": train_log},
        {"command": "python sample.py ...", "exit_code": 0, "timed_out": False, "duration_s": 23.2, "log_tail": "生成文本样例"},
    ]


def _succeeded_job(val_loss: str = "1.8857") -> dict:
    preset = REPRO_PRESETS["nanogpt"]
    return {
        "job_id": "abc123def456",
        "status": "succeeded",
        "preset_id": "nanogpt",
        "repo_url": preset["repo_url"],
        "requested_license": "MIT",
        "license_checks": {"github_spdx": "MIT", "local_spdx": "MIT", "effective": "MIT", "allowed": True},
        "seed_used": True,
        "steps_result": _nanogpt_steps(val_loss),
    }


def test_extract_metrics_takes_last_occurrence():
    metrics = repro_report.extract_metrics(_nanogpt_steps("1.8857"))
    assert metrics["val_loss"] == 1.8857
    assert metrics["train_loss_final"] == 1.7648


def test_extract_metrics_empty_logs():
    metrics = repro_report.extract_metrics([{"log_tail": ""}, {}])
    assert metrics == {"val_loss": None, "train_loss_final": None}


def test_verdict_pass_within_tolerance():
    report = repro_report.build_report(job=_succeeded_job("1.8857"), preset=REPRO_PRESETS["nanogpt"])
    assert report["verdict"] == "PASS"
    assert report["comparison"][0]["observed"] == 1.8857
    assert report["comparison"][0]["pass"] is True


def test_verdict_fail_beyond_tolerance():
    report = repro_report.build_report(job=_succeeded_job("2.75"), preset=REPRO_PRESETS["nanogpt"])
    assert report["verdict"] == "FAIL"
    assert report["comparison"][0]["pass"] is False


def test_verdict_incomplete_without_expected():
    job = _succeeded_job()
    job["preset_id"] = "unknown-preset"
    report = repro_report.build_report(job=job, preset=None)
    assert report["verdict"] == "INCOMPLETE"


def test_verdict_deterministic():
    """同一输入重复判定，结果恒定（LLM 不参与）。"""
    reports = [repro_report.build_report(job=_succeeded_job(), preset=REPRO_PRESETS["nanogpt"]) for _ in range(3)]
    assert {r["verdict"] for r in reports} == {"PASS"}
    assert {json.dumps(r["comparison"], sort_keys=True) for r in reports}.__len__() == 1


def test_report_markdown_contains_required_sections():
    markdown = repro_report.render_report_markdown(
        repro_report.build_report(job=_succeeded_job(), preset=REPRO_PRESETS["nanogpt"])
    )
    for token in ("**结论：PASS**", "指标对比", "执行步骤", "非 LLM 判定", "《算法导论》" if False else "MIT"):
        assert token in markdown, token


# ---------------------------------------------------------------------------
# 报告端点契约（mock worker 与 artifact 写入）
# ---------------------------------------------------------------------------


class _FakeAsyncClient:
    """按 URL 前缀分流：/jobs/ → worker 记录；/nexus-internal/artifacts → 写入成功。"""

    def __init__(self, worker_record=None, *, transport=None):
        self._record = worker_record

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers=None):
        class _Resp:
            status_code = 200
            def json(self):
                return self._data
        resp = _Resp()
        resp._data = self._record
        return resp

    async def post(self, url, json=None, headers=None):
        class _Resp:
            status_code = 200
            def json(self):
                return {"code": 200, "data": {"artifact_id": "rep111222333", "artifact_type": "markdown", "title": json.get("title", ""), "size_bytes": len(json.get("content", ""))}}
        return _Resp()


async def _report_response(monkeypatch: pytest.MonkeyPatch, job: dict, user_id: str | None = "42"):
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "tok")
    monkeypatch.setenv("NEXUS_REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setenv("NEXUS_REPRO_WORKER_TOKEN", "wtok")
    get_settings.cache_clear()

    def fake_async_client(**kwargs):
        return _FakeAsyncClient(worker_record=job)

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)
    headers = {"X-Nexus-User-Id": user_id} if user_id else {}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/nexus/repro/jobs/abc123def456/report", headers=headers)
    finally:
        get_settings.cache_clear()


async def test_report_endpoint_writes_two_artifacts(monkeypatch: pytest.MonkeyPatch):
    response = await _report_response(monkeypatch, _succeeded_job())
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "PASS"
    assert len(body["artifacts"]) == 2
    assert body["artifacts"][0]["download_path"].endswith("/download")


async def test_report_endpoint_rejects_unfinished_job(monkeypatch: pytest.MonkeyPatch):
    job = _succeeded_job()
    job["status"] = "running"
    monkeypatch.setenv("NEXUS_REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setenv("NEXUS_REPRO_WORKER_TOKEN", "wtok")
    get_settings.cache_clear()

    def fake_async_client(**kwargs):
        return _FakeAsyncClient(worker_record=job)

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nexus/repro/jobs/abc123def456/report",
                headers={"X-Nexus-User-Id": "42"},
            )
    finally:
        get_settings.cache_clear()
    assert response.status_code == 409
    assert "JOB_NOT_FINISHED" in response.json()["detail"]

