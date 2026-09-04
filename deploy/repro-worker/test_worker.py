"""Repro Worker 契约测试（P1-W2/W3）。

直接以 ASGI transport 打 worker.app；GitHub API 用 respx 拦截，执行步骤用
真实 bash 子进程（echo/mkdir 级小命令），不调用任何真实论文仓库与付费服务。

运行（复用 nexus 独立 venv 的 pytest-asyncio/respx）：
  <nexus-venv>/python -m pytest deploy/repro-worker/test_worker.py -q
  --basetemp=<仓库内可写目录>（Windows 系统临时目录可能拒绝访问）
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx

import worker


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker, "WORKSPACE_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(worker, "API_TOKEN", "")
    monkeypatch.setattr(worker, "_jobs", {})
    worker._semaphore = asyncio.Semaphore(1)
    yield


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=worker.app), base_url="http://worker")


def _stub_clone(seed: Path):
    """返回替代 _run_step 的桩：git clone 步改为本地复制种子目录。

    必须在工厂调用时（即替换前）捕获原函数——若桩内引用 worker._run_step，
    替换后会指向桩自身造成无限递归。
    """
    original = worker._run_step

    async def fake_run_step(command: str, cwd: Path) -> dict:
        if command.startswith("git clone"):
            target = Path(command.split()[-1])
            shutil.copytree(seed, cwd / target.name)
            return {"command": command, "exit_code": 0, "timed_out": False,
                    "duration_s": 0, "log_tail": ""}
        return await original(command, cwd)

    return fake_run_step


async def _wait_done(job_id: str, timeout: float = 10.0, token: str = "") -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for _ in range(int(timeout / 0.1)):
        async with _client() as client:
            response = await client.get(f"/jobs/{job_id}", headers=headers)
        record = response.json()
        if record["status"] in {"succeeded", "failed", "rejected"}:
            return record
        await asyncio.sleep(0.1)
    raise AssertionError("job did not finish in time")


async def test_health_reports_config():
    async with _client() as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "MIT" in body["allowed_licenses"]
    assert body["disk_quota_mb"] >= 1


async def test_rejects_non_github_repo_url():
    async with _client() as client:
        response = await client.post("/jobs", json={
            "preset_id": "x", "repo_url": "https://evil.example.com/repo.git",
            "repo_license": "MIT", "steps": ["echo hi"],
        })
    assert response.status_code == 422
    assert response.json()["detail"] == "REPO_URL_MUST_BE_GITHUB"


async def test_rejects_gpl_license_at_submit_time():
    """GitHub 明确返回 GPL → 提交期即拒（LICENSE_VIOLATION），不进入执行队列。"""
    with respx.mock:
        respx.get("https://api.github.com/repos/a/b/license").mock(
            return_value=httpx.Response(200, json={"license": {"spdx_id": "GPL-3.0"}})
        )
        async with _client() as client:
            response = await client.post("/jobs", json={
                "preset_id": "x", "repo_url": "https://github.com/a/b",
                "repo_license": "MIT", "steps": ["echo hi"],
            })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["code"] == "LICENSE_VIOLATION"


async def test_rejects_when_no_license_verifiable(tmp_path: Path):
    """GitHub 无 License + clone 后无 LICENSE 文件 → fail-closed 拒绝。"""
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "README.md").write_text("no license file here")

    original = worker._run_step
    worker._run_step = _stub_clone(seed)
    try:
        with respx.mock:
            respx.get("https://api.github.com/repos/a/nolicense").mock(
                return_value=httpx.Response(200, json={"license": None})
            )
            async with _client() as client:
                response = await client.post("/jobs", json={
                    "preset_id": "x", "repo_url": "https://github.com/a/nolicense",
                    "repo_license": "MIT", "steps": ["echo hi"],
                })
                assert response.status_code == 200
                record = await _wait_done(response.json()["job_id"])
    finally:
        worker._run_step = original

    assert record["status"] == "rejected"
    assert record["code"] == "LICENSE_VIOLATION"
    assert "no verifiable license" in record["detail"]


async def test_successful_run_with_local_license_check(tmp_path: Path):
    """GitHub API 不可达时靠本地 LICENSE 兜底判定；步骤成功 + artifact 清单 +
    跨步 cd 语义（step1 末尾 cd sub，step2 应在 sub/ 内执行）。"""
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "LICENSE").write_text("MIT License\n\nCopyright (c) 2026 somebody")

    original = worker._run_step
    worker._run_step = _stub_clone(seed)
    try:
        with respx.mock:
            respx.get("https://api.github.com/repos/a/mit").mock(
                return_value=httpx.Response(503, text="github down")
            )
            async with _client() as client:
                response = await client.post("/jobs", json={
                    "preset_id": "demo", "repo_url": "https://github.com/a/mit",
                    "repo_license": "MIT",
                    "steps": [
                        "mkdir -p out sub && echo 'loss 1.88' > out/train.log && cd sub",
                        "echo done > step2.txt",
                    ],
                })
                assert response.status_code == 200
                assert response.json()["status"] == "queued"
                record = await _wait_done(response.json()["job_id"])
    finally:
        worker._run_step = original

    assert record["status"] == "succeeded", record
    assert record["license_checks"]["local_spdx"] == "MIT"
    assert record["license_checks"]["effective"] == "MIT"
    artifact_paths = [item["path"].replace("\\", "/") for item in record["artifacts"]]
    assert any(item.endswith("out/train.log") for item in artifact_paths)
    assert any(item.endswith("sub/step2.txt") for item in artifact_paths), artifact_paths
    # 工作目录 ephemeral：结束后不保留仓库内容
    assert not (worker.WORKSPACE_ROOT / record["job_id"]).exists()


async def test_seed_hit_skips_clone_and_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """种子命中：不做运行时 git clone，直接用本地快照执行；首条 clone 步被
    替换为保留 cd 语义的空操作。"""
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    repo = tmp_path / "seedrepo"
    repo.mkdir()
    (repo / "LICENSE").write_text("MIT License")
    (repo / "train.py").write_text("print('training on cpu')\n")
    subprocess_tar = seeds / "nanogpt.tar.gz"
    import tarfile
    with tarfile.open(subprocess_tar, "w:gz") as tar:
        tar.add(repo, arcname="nanoGPT")

    monkeypatch.setattr(worker, "SEEDS_DIR", seeds)

    clone_calls = {"n": 0}
    original = worker._run_step

    async def spy_run_step(command: str, cwd: Path) -> dict:
        if command.startswith("git clone"):
            clone_calls["n"] += 1
        return await original(command, cwd)

    worker._run_step = spy_run_step
    try:
        with respx.mock:
            respx.get("https://api.github.com/repos/karpathy/nanoGPT/license").mock(
                return_value=httpx.Response(200, json={"license": {"spdx_id": "MIT"}})
            )
            async with _client() as client:
                response = await client.post("/jobs", json={
                    "preset_id": "nanogpt", "repo_url": "https://github.com/karpathy/nanoGPT",
                    "repo_license": "MIT",
                "steps": [
                    "git clone https://github.com/karpathy/nanoGPT && cd nanoGPT",
                    "cat train.py",
                ],
                })
                assert response.status_code == 200
                record = await _wait_done(response.json()["job_id"])
    finally:
        worker._run_step = original

    assert record["status"] == "succeeded", record
    assert record["seed_used"] is True
    assert clone_calls["n"] == 0, "seed 命中时不得发生运行时 git clone"
    assert record["steps_result"][0]["log_tail"] == ""  # true && cd nanoGPT
    assert "training on cpu" in record["steps_result"][1]["log_tail"]

async def test_rejects_repo_hiding_gpl_in_root_copying(tmp_path: Path):
    """红线回归（2026-09-03）：git/git 式仓库——根 COPYING 为 GPL-2.0、子目录
    有 vendored 的宽松 LICENSE.txt。递归先命中子目录会绕过 GPL 判定，必须
    根目录优先 + GPL 一票否决。"""
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "COPYING").write_text(
        "Note that the only valid version of the GPL as far as this project\n"
        "is concerned is _this_ particular version of the license (ie v2).\n\n"
        "This program is free software; you can redistribute it and/or modify\n"
        "it under the terms of the GNU General Public License as published by\n"
        "the Free Software Foundation."
    )
    vendored = seed / "vendor"
    vendored.mkdir()
    (vendored / "LICENSE.txt").write_text("MIT License\n\nCopyright (c) somebody")

    original = worker._run_step
    worker._run_step = _stub_clone(seed)
    try:
        with respx.mock:
            respx.get("https://api.github.com/repos/a/gplroot").mock(
                return_value=httpx.Response(200, json={"license": None})
            )
            async with _client() as client:
                response = await client.post("/jobs", json={
                    "preset_id": "x", "repo_url": "https://github.com/a/gplroot",
                    "repo_license": "MIT", "steps": ["echo hi"],
                })
                record = await _wait_done(response.json()["job_id"])
    finally:
        worker._run_step = original

    assert record["status"] == "rejected"
    assert record["code"] == "LICENSE_VIOLATION"
    assert "GPL" in json.dumps(record["license_checks"])


async def test_step_failure_fails_job_with_log_tail(tmp_path: Path):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "LICENSE").write_text("MIT License")

    original = worker._run_step
    worker._run_step = _stub_clone(seed)
    try:
        with respx.mock:
            respx.get("https://api.github.com/repos/a/mit").mock(
                return_value=httpx.Response(200, json={"license": {"spdx_id": "MIT"}})
            )
            async with _client() as client:
                response = await client.post("/jobs", json={
                    "preset_id": "x", "repo_url": "https://github.com/a/mit",
                    "repo_license": "MIT", "steps": ["false"],
                })
                record = await _wait_done(response.json()["job_id"])
    finally:
        worker._run_step = original

    assert record["status"] == "failed"
    assert record["code"] == "REPRO_FAILED"
    assert record["steps_result"][0]["exit_code"] == 1


async def test_token_required_when_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker, "API_TOKEN", "secret-worker-token")
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "LICENSE").write_text("MIT License")

    original = worker._run_step
    worker._run_step = _stub_clone(seed)
    try:
        with respx.mock:
            respx.get("https://api.github.com/repos/a/b/license").mock(
                return_value=httpx.Response(200, json={"license": {"spdx_id": "MIT"}})
            )
            async with _client() as client:
                unauthorized = await client.post("/jobs", json={
                    "preset_id": "x", "repo_url": "https://github.com/a/b",
                    "repo_license": "MIT", "steps": ["echo hi"],
                })
                assert unauthorized.status_code == 401

                authorized = await client.post(
                    "/jobs",
                    json={"preset_id": "x", "repo_url": "https://github.com/a/b",
                          "repo_license": "MIT", "steps": ["echo hi"]},
                    headers={"Authorization": "Bearer secret-worker-token"},
                )
                assert authorized.status_code == 200
                record = await _wait_done(
                    authorized.json()["job_id"], token="secret-worker-token"
                )
    finally:
        worker._run_step = original
    assert record["status"] == "succeeded"
