"""Repro Worker：不可信论文仓库的受限执行器（独立容器运行）。

安全边界（AGENTS.md §4.1.10 / 技术决策补丁 §14/§29）：
- 未知 GitHub Repo 一律视为不可信代码，只允许在本 Worker（独立容器、独立
  网络、资源配额）内执行；本进程**不**属于 Nexus Runtime 或旧 Backend 的
  Python 环境，也不共享其任何凭据。
- License 双重校验（W3）：GitHub API 查询 + clone 后本地 LICENSE 文件解析，
  两级都通过才执行；越线仓库拒绝并返回 ``LICENSE_VIOLATION``。
- 资源约束：单任务总时长硬截止（默认 15 分钟）、单步超时、磁盘配额、
  串行执行；超时进程 SIGKILL。
- 回传物最小化：只回传状态、每步日志尾部与 artifact 清单（文件名+大小），
  不回传任意文件；工作目录任务结束后删除。
- 可选 Bearer 认证（``REPRO_WORKER_TOKEN``）：配置后所有 /jobs 请求必须携带。
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 配置（环境变量注入；容器内不落任何生产凭据）
# ---------------------------------------------------------------------------

WORKER_VERSION = "0.1.0"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


WORKSPACE_ROOT = Path(_env("REPRO_WORKER_WORKSPACE_ROOT", "/tmp/repro-jobs"))
TOTAL_TIMEOUT_S = int(_env("REPRO_WORKER_TOTAL_TIMEOUT_S", "900"))      # 15 分钟硬截止
STEP_TIMEOUT_S = int(_env("REPRO_WORKER_STEP_TIMEOUT_S", "300"))
DISK_QUOTA_BYTES = int(_env("REPRO_WORKER_DISK_QUOTA_MB", "2048")) * 1024 * 1024
MAX_CONCURRENT = int(_env("REPRO_WORKER_MAX_CONCURRENT", "1"))
GITHUB_TOKEN = _env("REPRO_WORKER_GITHUB_TOKEN")
API_TOKEN = _env("REPRO_WORKER_TOKEN")
LOG_TAIL_CHARS = 4000
MAX_STEPS = 10

# 允许演示/复现用途的开源 License（SPDX）。越线（GPL/AGPL/CC-BY-NC/无 License）
# 一律拒绝——技术决策补丁 §23 红线。
ALLOWED_LICENSES = {
    spdx.strip()
    for spdx in _env(
        "REPRO_WORKER_ALLOWED_LICENSES",
        "MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,ISC,0BSD,Unlicense,CC0-1.0",
    ).split(",")
    if spdx.strip()
}

# 本地 LICENSE 文件启发式：文件名模式 + 内容关键字（第二道校验）。
_LICENSE_FILE_GLOBS = ("LICENSE*", "LICENCE*", "COPYING*", "NOTICE*")
_LOCAL_LICENSE_HINTS = {
    "MIT": re.compile(r"\bMIT License\b", re.I),
    "Apache-2.0": re.compile(r"Apache License\s+Version 2\.0", re.I),
    "BSD-3-Clause": re.compile(r"BSD 3-Clause", re.I),
    "BSD-2-Clause": re.compile(r"BSD 2-Clause", re.I),
    "ISC": re.compile(r"\bISC License\b", re.I),
}
_GPL_PATTERN = re.compile(
    r"GNU (General Public|Affero General Public|Lesser General Public) License", re.I
)
_GITHUB_REPO_PATTERN = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_ARTIFACT_GLOBS = ("*.log", "*.txt", "*.json", "*.csv", "*.md")
_ARTIFACT_MAX_BYTES = 1_000_000

app = FastAPI(title="CodeNexus Repro Worker", version=WORKER_VERSION)

_jobs: dict[str, dict[str, Any]] = {}
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)


# ---------------------------------------------------------------------------
# 请求模型与鉴权
# ---------------------------------------------------------------------------


class JobRequest(BaseModel):
    preset_id: str = Field(min_length=1, max_length=64)
    repo_url: str = Field(min_length=1, max_length=300)
    repo_license: str = Field(min_length=1, max_length=64)
    steps: list[str] = Field(min_length=1, max_length=MAX_STEPS)


async def _require_token(authorization: str | None = Header(default=None)) -> None:
    if API_TOKEN and authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="INVALID_WORKER_TOKEN")


# ---------------------------------------------------------------------------
# License 校验（W3：GitHub API + 本地文件，双道）
# ---------------------------------------------------------------------------


def _github_repo_slug(repo_url: str) -> str | None:
    match = _GITHUB_REPO_PATTERN.match(repo_url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


async def _github_license_spdx(repo_url: str) -> str | None:
    """查询 GitHub API 的 License SPDX；不可达/无 License 时返回 None。"""
    slug = _github_repo_slug(repo_url)
    if slug is None:
        return None
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.github.com/repos/{slug}/license", headers=headers
            )
            if response.status_code != 200:
                return None
            spdx = (response.json().get("license") or {}).get("spdx_id")
            return spdx if spdx and spdx != "NOASSERTION" else None
    except Exception:  # noqa: BLE001 - GitHub 不可达时交给本地校验兜底
        return None


def _local_license_spdx(workspace: Path) -> tuple[str | None, str]:
    """扫描工作目录中的 LICENSE/COPYING 文件，返回 (spdx, 依据文件名)。"""
    for pattern in _LICENSE_FILE_GLOBS:
        for candidate in workspace.rglob(pattern):
            if not candidate.is_file() or candidate.stat().st_size > 200_000:
                continue
            try:
                head = candidate.read_text(errors="replace")[:20_000]
            except OSError:
                continue
            if _GPL_PATTERN.search(head):
                return "GPL", candidate.name
            for spdx, pattern_re in _LOCAL_LICENSE_HINTS.items():
                if pattern_re.search(head):
                    return spdx, candidate.name
    return None, ""


def _license_decision(
    requested: str,
    github_spdx: str | None,
    local_spdx: str | None,
) -> tuple[bool, str, str]:
    """三源（请求声明/GitHub/本地文件）判断，fail-closed。

    返回 (allowed, 有效 spdx 或空, 拒绝原因)。
    """

    def _allowed(value: str) -> bool:
        return value in ALLOWED_LICENSES

    requested_norm = requested.strip()
    candidates = [v for v in (github_spdx, local_spdx) if v]
    if candidates and not all(_allowed(v) for v in candidates):
        return False, "", f"observed license {candidates} not in allowlist"
    if not candidates:
        # GitHub 与本地都无法识别 License → 视为无 License（默认版权保留）。
        return False, "", "no verifiable license (GitHub + local LICENSE file)"
    effective = candidates[0]
    if not _allowed(requested_norm) and requested_norm not in {"unknown", "none"}:
        return False, effective, f"requested license {requested_norm!r} not in allowlist"
    return True, effective, ""


# ---------------------------------------------------------------------------
# 执行沙箱逻辑
# ---------------------------------------------------------------------------


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
        if total > DISK_QUOTA_BYTES:  # 早停：已超配额无需继续统计
            break
    return total


def _tail(text: str, limit: int = LOG_TAIL_CHARS) -> str:
    return text[-limit:]


_CD_PATTERN = re.compile(r"(?:^|&&)\s*cd\s+(\S+)\s*$")


async def _run_step(command: str, cwd: Path) -> dict[str, Any]:
    """在受限子进程中执行单步：超时 SIGKILL，输出截尾。"""
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", "-lc", command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=STEP_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "command": command, "exit_code": None, "timed_out": True,
                "duration_s": round(time.monotonic() - started, 1),
                "log_tail": _tail(f"TIMEOUT after {STEP_TIMEOUT_S}s (SIGKILL)"),
            }
        except asyncio.CancelledError:
            # 任务被取消（进程重启/停机）时必须杀掉子进程，否则 Proactor 循环
            # 关闭会因存活管道挂死，未知仓库代码也会脱离控制继续运行。
            proc.kill()
            raise
        return {
            "command": command,
            "exit_code": proc.returncode,
            "timed_out": False,
            "duration_s": round(time.monotonic() - started, 1),
            "log_tail": _tail(stdout.decode(errors="replace")),
        }
    except Exception as error:  # noqa: BLE001 - 执行器故障如实上报
        return {
            "command": command, "exit_code": None, "timed_out": False,
            "duration_s": round(time.monotonic() - started, 1),
            "log_tail": _tail(f"worker error: {type(error).__name__}: {error}"),
        }


def _collect_artifacts(workspace: Path) -> list[dict[str, Any]]:
    """artifact 白名单：仅收集限定扩展名的小文件清单（不回传内容）。"""
    artifacts: list[dict[str, Any]] = []
    if not workspace.exists():
        return artifacts
    for pattern in _ARTIFACT_GLOBS:
        for candidate in workspace.rglob(pattern):
            if not candidate.is_file():
                continue
            size = candidate.stat().st_size
            if size > _ARTIFACT_MAX_BYTES:
                continue
            artifacts.append({
                "path": str(candidate.relative_to(workspace)),
                "size_bytes": size,
            })
            if len(artifacts) >= 20:
                return artifacts
    return artifacts


async def _execute_job(job_id: str, request: JobRequest) -> None:
    record = _jobs[job_id]
    workspace = WORKSPACE_ROOT / job_id
    record["status"] = "running"
    record["started_at"] = time.time()
    deadline = time.monotonic() + TOTAL_TIMEOUT_S
    step_results: list[dict[str, Any]] = []
    try:
        WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)

        # 1) 预 clone 到 .license-check/ 做本地 License 第二道校验。
        clone = await _run_step(
            f"git clone --depth 1 {request.repo_url} .license-check", workspace
        )
        if clone["exit_code"] != 0:
            raise RuntimeError(f"git clone failed: {clone['log_tail'][:300]}")
        local_spdx, license_file = _local_license_spdx(workspace / ".license-check")
        github_spdx = record["license_checks"]["github_spdx"]
        allowed, effective, reason = _license_decision(
            request.repo_license, github_spdx, local_spdx
        )
        record["license_checks"].update({
            "local_spdx": local_spdx,
            "local_evidence": license_file,
            "effective": effective,
            "allowed": allowed,
            "reason": reason,
        })
        shutil.rmtree(workspace / ".license-check", ignore_errors=True)
        if not allowed:
            record.update({
                "status": "rejected",
                "code": "LICENSE_VIOLATION",
                "detail": reason,
                "finished_at": time.time(),
            })
            return

        # 2) 逐步执行（bash -lc；维护跨步 cd 语义）。
        current_rel = ""
        for index, command in enumerate(request.steps):
            if time.monotonic() > deadline:
                step_results.append({
                    "command": command, "exit_code": None, "timed_out": True,
                    "duration_s": 0, "log_tail": _tail(
                        f"TOTAL TIMEOUT {TOTAL_TIMEOUT_S}s reached before step {index + 1}"
                    ),
                })
                raise TimeoutError(f"total budget {TOTAL_TIMEOUT_S}s exceeded")
            if _dir_size(workspace) > DISK_QUOTA_BYTES:
                raise RuntimeError("disk quota exceeded")
            step_dir = workspace / current_rel if current_rel else workspace
            # 子进程 cwd 直接设为目标目录（跨步 cd 语义由 current_rel 维护），
            # 不经 shell cd——避免 Windows 反斜杠路径在 bash 内不可用的问题。
            result = await _run_step(command, step_dir)
            step_results.append(result)
            match = _CD_PATTERN.search(command)
            if match and match.group(1) not in (".", ".."):
                current_rel = (
                    f"{current_rel}/{match.group(1)}" if current_rel else match.group(1)
                ).strip("./")
            if result["exit_code"] != 0:
                raise RuntimeError(f"step {index + 1} failed (exit={result['exit_code']})")
            if result["timed_out"]:
                raise TimeoutError(f"step {index + 1} timeout")

        record.update({
            "status": "succeeded",
            "steps_result": step_results,
            "artifacts": _collect_artifacts(workspace),
            "finished_at": time.time(),
        })
    except TimeoutError as error:
        record.update({
            "status": "failed", "code": "REPRO_TIMEOUT", "detail": str(error),
            "steps_result": step_results,
            "finished_at": time.time(),
        })
    except Exception as error:  # noqa: BLE001 - 失败分类如实回传
        record.update({
            "status": "failed", "code": "REPRO_FAILED", "detail": str(error)[:500],
            "steps_result": step_results,
            "finished_at": time.time(),
        })
    finally:
        # 工作目录 ephemeral：结构化结果已入 record，不保留仓库内容。
        shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": WORKER_VERSION,
        "auth_configured": bool(API_TOKEN),
        "github_token_configured": bool(GITHUB_TOKEN),
        "total_timeout_s": TOTAL_TIMEOUT_S,
        "step_timeout_s": STEP_TIMEOUT_S,
        "disk_quota_mb": DISK_QUOTA_BYTES // (1024 * 1024),
        "allowed_licenses": sorted(ALLOWED_LICENSES),
        "active_jobs": sum(1 for job in _jobs.values() if job["status"] == "running"),
    }


@app.post("/jobs", dependencies=[Depends(_require_token)])
async def submit_job(request: JobRequest) -> dict[str, Any]:
    slug = _github_repo_slug(request.repo_url)
    if slug is None:
        raise HTTPException(status_code=422, detail="REPO_URL_MUST_BE_GITHUB")

    job_id = uuid.uuid4().hex[:12]
    github_spdx = await _github_license_spdx(request.repo_url)
    record: dict[str, Any] = {
        "job_id": job_id,
        "status": "queued",
        "preset_id": request.preset_id,
        "repo_url": request.repo_url,
        "requested_license": request.repo_license,
        "license_checks": {"github_spdx": github_spdx},
        "submitted_at": time.time(),
    }
    _jobs[job_id] = record

    # 提交期即可判定的 License 越线直接拒绝（GitHub 明确返回不允许的 License）。
    if github_spdx and github_spdx not in ALLOWED_LICENSES:
        record.update({
            "status": "rejected",
            "code": "LICENSE_VIOLATION",
            "detail": f"github spdx {github_spdx!r} not in allowlist",
            "finished_at": time.time(),
        })
        return {"job_id": job_id, "status": "rejected", "code": "LICENSE_VIOLATION"}

    asyncio.create_task(_guarded_execute(job_id, request))
    return {"job_id": job_id, "status": "queued"}


async def _guarded_execute(job_id: str, request: JobRequest) -> None:
    async with _semaphore:
        try:
            await _execute_job(job_id, request)
        except Exception as error:  # noqa: BLE001 - 执行器兜底，绝不让任务静默消失
            _jobs[job_id].update({
                "status": "failed",
                "code": "WORKER_INTERNAL_ERROR",
                "detail": f"{type(error).__name__}: {error}"[:500],
                "finished_at": time.time(),
            })


@app.get("/jobs/{job_id}", dependencies=[Depends(_require_token)])
async def job_status(job_id: str) -> dict[str, Any]:
    record = _jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    return record


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        app,
        host=_env("REPRO_WORKER_HOST", "0.0.0.0"),
        port=int(_env("REPRO_WORKER_PORT", "8400")),
    )
