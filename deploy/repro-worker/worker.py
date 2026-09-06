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

NX-E2/E3（2026-09-06）：
- Stage 事件：Preparing/Building/Running/Metric/Verifying/Completed 由真实
  执行边界触发（序号单调递增），preset 无独立构建阶段时 Building 如实
  skipped、无干净 B 复验时 Verifying 如实 not_applicable，不伪造阶段。
- 增量日志：每步 stdout 逐行读入有界环形缓冲（末 ``STEP_LOG_MAX_CHARS``
  字符），运行中即可经 ``live_log_tail`` 观察，不必等步骤结束。
- Cancel：``POST /jobs/{job_id}/cancel`` 幂等；子进程 ``start_new_session``
  成组，取消/超时按进程组 SIGKILL；自然完成竞争时保持真实终态（晚到取消
  不把已完成的作业改成 cancelled）。``_jobs`` 仍为内存（持久化对账属 NX-E4）。
"""
from __future__ import annotations

import asyncio
import collections
import os
import re
import shutil
import signal
import tarfile
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

WORKER_VERSION = "0.2.0"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


WORKSPACE_ROOT = Path(_env("REPRO_WORKER_WORKSPACE_ROOT", "/tmp/repro-jobs"))
# 已核验预设的仓库种子（tar.gz，顶层目录 = 仓库名）。命中时跳过运行时 git
# clone——确定性 + 免境内网络干扰；内容冻结快照，本地 LICENSE 校验仍然执行。
SEEDS_DIR = Path(_env("REPRO_SEEDS_DIR", "/seeds"))
TOTAL_TIMEOUT_S = int(_env("REPRO_WORKER_TOTAL_TIMEOUT_S", "900"))      # 15 分钟硬截止
STEP_TIMEOUT_S = int(_env("REPRO_WORKER_STEP_TIMEOUT_S", "300"))
DISK_QUOTA_BYTES = int(_env("REPRO_WORKER_DISK_QUOTA_MB", "2048")) * 1024 * 1024
MAX_CONCURRENT = int(_env("REPRO_WORKER_MAX_CONCURRENT", "1"))
GITHUB_TOKEN = _env("REPRO_WORKER_GITHUB_TOKEN")
API_TOKEN = _env("REPRO_WORKER_TOKEN")
LOG_TAIL_CHARS = 4000
MAX_STEPS = 10
# NX-E2：每步增量日志环形缓冲上限（字符）。终态 log_tail 仍受 LOG_TAIL_CHARS 约束。
STEP_LOG_MAX_CHARS = int(_env("REPRO_WORKER_STEP_LOG_MAX_CHARS", "8000"))

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
    """扫描 LICENSE/COPYING 文件判定 License，返回 (spdx, 依据文件名)。

    **根目录优先**：仓库的整体 License 由根目录声明（如 git/git 的 COPYING）；
    递归兜底仅用于根目录无声明的情况——否则子目录 vendored 的宽松许可
    （如 git/git/sha1dc/LICENSE.txt）会掩盖根目录的 GPL，造成红线绕过。
    GPL 声明在任何层级都具有一票否决权。
    """
    candidates: list[tuple[Path, str]] = []
    for scope in (workspace.glob("*"), workspace.rglob("*")):
        for candidate in scope:
            if candidate.is_file() and candidate.stat().st_size <= 200_000 and \
                    any(candidate.match(pat) for pat in _LICENSE_FILE_GLOBS):
                candidates.append((candidate, candidate.name))
        if candidates:
            break  # 根目录已有命中，不再递归
    if not candidates:
        return None, ""

    # GPL 一票否决：任何候选文件含 GPL 声明即判 GPL。
    for candidate, name in candidates:
        try:
            head = candidate.read_text(errors="replace")[:20_000]
        except OSError:
            continue
        if _GPL_PATTERN.search(head):
            return "GPL", name
    # 根目录的非 GPL 命中按序识别。
    for candidate, name in candidates:
        try:
            head = candidate.read_text(errors="replace")[:20_000]
        except OSError:
            continue
        for spdx, pattern_re in _LOCAL_LICENSE_HINTS.items():
            if pattern_re.search(head):
                return spdx, name
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


def _replace_own_clone_step(step: str, repo_url: str) -> str:
    """种子命中时把首条 git clone 步替换为空操作，保留 cd 语义。"""
    stripped = step.strip()
    if not stripped.startswith(f"git clone {repo_url}"):
        return step
    match = _CD_PATTERN.search(stripped)
    return f"true && cd {match.group(1)}" if match else "true"


class CancelledJobError(Exception):
    """NX-E3：用户取消——终止当前步骤进程组并把作业置为 cancelled。"""


# Stage 名固定为设计板/v1.3 C4 六段；preset 无独立构建阶段、无干净 B 复验时
# 分别如实 skipped / not_applicable，绝不虚构 Building/Verifying 进度。
STAGE_NAMES = ("preparing", "building", "running", "metric", "verifying", "completed")


def _emit_stage(record: dict[str, Any], stage: str, status: str, note: str | None = None) -> None:
    if stage not in STAGE_NAMES:
        raise ValueError(f"unknown stage: {stage}")
    record["stage_seq"] = int(record.get("stage_seq", 0)) + 1
    event: dict[str, Any] = {
        "seq": record["stage_seq"],
        "stage": stage,
        "status": status,
        "time": time.time(),
    }
    if note:
        event["note"] = str(note)[:200]
    record.setdefault("stage_events", []).append(event)


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    """按进程组 SIGKILL（start_new_session 使 pgid=pid）；组不存在则忽略。

    POSIX（生产容器）走 killpg 整组回收；非 POSIX（本地开发/测试）退化为
    直杀主进程——取消语义在两种平台都成立，只是子进程树回收精度不同。
    """
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass


# start_new_session 为 POSIX-only；Windows 开发环境直接省略（_kill_group 已退化）。
_SUBPROCESS_GROUP_KWARGS = {"start_new_session": True} if os.name == "posix" else {}


async def _run_step(
    command: str,
    cwd: Path,
    live_log_slot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """在受限子进程中执行单步：超时按进程组 SIGKILL，输出截尾。

    NX-E2：子进程 ``start_new_session`` 成组，stdout 逐行泵入有界环形缓冲，
    运行中即可经 ``live_log_slot["live_log_tail"]`` 增量观察。取消由
    ``/jobs/{id}/cancel`` 直接对活动进程组 SIGKILL，本函数只负责如实回传
    （被杀步骤 exit=-9/None），取消语义由调用方结合 cancel 标记裁决。
    """
    started = time.monotonic()
    ring: collections.deque[str] = collections.deque()
    ring_chars = 0

    def _append(chunk: str) -> None:
        nonlocal ring_chars
        ring.append(chunk)
        ring_chars += len(chunk)
        while ring_chars > STEP_LOG_MAX_CHARS and ring:
            ring_chars -= len(ring.popleft())

    def _snapshot() -> str:
        return "".join(ring)[-STEP_LOG_MAX_CHARS:]

    if live_log_slot is not None:
        live_log_slot["live_log_tail"] = ""

    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", "-lc", command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **_SUBPROCESS_GROUP_KWARGS,
        )
        if live_log_slot is not None:
            # NX-E3：活动进程句柄挂 record 私有键（下划线前缀，job_status 过滤不外泄），
            # cancel 端点据此对进程组 SIGKILL；步骤结束后残值无害（returncode 非 None）。
            live_log_slot["_proc"] = proc

        async def _pump() -> None:
            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                _append(raw.decode(errors="replace"))
                if live_log_slot is not None:
                    live_log_slot["live_log_tail"] = _snapshot()

        pump = asyncio.create_task(_pump())
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=STEP_TIMEOUT_S)
        except asyncio.TimeoutError:
            timed_out = True
            _kill_group(proc)
            await proc.wait()
        except asyncio.CancelledError:
            # 任务被取消（进程重启/停机）时必须按组杀掉子进程，否则 Proactor
            # 循环关闭会因存活管道挂死，未知仓库代码也会脱离控制继续运行。
            _kill_group(proc)
            pump.cancel()
            raise
        # 进程已退出；给泵一小段时间排干管道尾部（readline 到 EOF 自然返回）。
        try:
            await asyncio.wait_for(pump, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pump.cancel()

        log_text = _snapshot()
        if timed_out:
            return {
                "command": command, "exit_code": None, "timed_out": True,
                "duration_s": round(time.monotonic() - started, 1),
                "log_tail": _tail(f"TIMEOUT after {STEP_TIMEOUT_S}s (SIGKILL)\n{log_text}"),
            }
        return {
            "command": command,
            "exit_code": proc.returncode,
            "timed_out": False,
            "duration_s": round(time.monotonic() - started, 1),
            "log_tail": _tail(log_text),
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


def _finalize_cancelled(record: dict[str, Any]) -> None:
    """NX-E3 终态：用户取消。已完成的步骤结果如实保留。"""
    record.update({
        "status": "cancelled",
        "code": "CANCELLED",
        "detail": "用户取消（当前步骤进程组已回收）",
        "finished_at": time.time(),
    })


async def _execute_job(job_id: str, request: JobRequest) -> None:
    record = _jobs[job_id]
    workspace = WORKSPACE_ROOT / job_id
    if record.get("cancel_requested"):
        # 排队期被取消：尚未领取任何资源，直接落终态。
        _finalize_cancelled(record)
        return
    record["status"] = "running"
    record["started_at"] = time.time()
    deadline = time.monotonic() + TOTAL_TIMEOUT_S
    step_results: list[dict[str, Any]] = []
    _emit_stage(record, "preparing", "started")
    try:
        WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)

        # 1) 取仓库到工作区：优先命中已核验预设的本地种子（确定性快照，
        #    直接解包到工作区根，tar 顶层目录 = 仓库名），否则运行时 git clone
        #    到 .license-check/ 仅做 License 校验（执行步会自行 clone）。
        #    种子是受信任的本地基础设施产物（打包时已核验），用 Python tarfile
        #    解包——GNU tar 会把 Windows 盘符冒号误判为远程主机语法。
        seed = SEEDS_DIR / f"{request.preset_id}.tar.gz"
        if seed.exists():
            record["seed_used"] = True
            with tarfile.open(seed, "r:gz") as tar:
                tar.extractall(workspace)
            check_root = workspace
        else:
            record["seed_used"] = False
            fetch = await _run_step(
                f"git clone --depth 1 {request.repo_url} .license-check", workspace,
                live_log_slot=record,
            )
            check_root = workspace / ".license-check"
            if fetch["exit_code"] != 0:
                raise RuntimeError(f"repo fetch failed: {fetch['log_tail'][:300]}")
        local_spdx, license_file = _local_license_spdx(check_root)
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
            _emit_stage(record, "preparing", "failed", note=reason)
            record.update({
                "status": "rejected",
                "code": "LICENSE_VIOLATION",
                "detail": reason,
                "finished_at": time.time(),
            })
            return
        _emit_stage(record, "preparing", "done")
        # preset 执行器没有独立构建阶段（依赖安装就是普通步骤），如实 skipped。
        _emit_stage(record, "building", "skipped",
                    note="preset 无独立构建阶段，依赖安装随步骤执行")
        _emit_stage(record, "running", "started")

        # 2) 逐步执行（bash -lc；维护跨步 cd 语义）。
        #    种子命中时，首条"git clone <本仓库>"步已由种子替代——替换为
        #    保留其 cd 语义的空操作（seed tar 顶层目录 = 仓库名）。
        steps = list(request.steps)
        if record.get("seed_used"):
            steps = [
                _replace_own_clone_step(step, request.repo_url) for step in steps
            ]
        current_rel = ""
        for index, command in enumerate(steps):
            if record.get("cancel_requested"):
                raise CancelledJobError(f"cancelled before step {index + 1}")
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
            record["current_step"] = index + 1
            result = await _run_step(command, step_dir, live_log_slot=record)
            step_results.append(result)
            record["steps_result"] = step_results
            match = _CD_PATTERN.search(command)
            if match and match.group(1) not in (".", ".."):
                current_rel = (
                    f"{current_rel}/{match.group(1)}" if current_rel else match.group(1)
                ).strip("./")
            if record.get("cancel_requested"):
                if result["exit_code"] != 0 or result["timed_out"]:
                    # 取消落在执行中的步骤上（SIGKILL 生效）→ cancelled。
                    raise CancelledJobError(f"cancelled during step {index + 1}")
                # 步骤自身恰好完成：保留结果，交由下一轮前置检查/收尾裁决。
                continue
            if result["exit_code"] != 0:
                raise RuntimeError(f"step {index + 1} failed (exit={result['exit_code']})")
            if result["timed_out"]:
                raise TimeoutError(f"step {index + 1} timeout")

        if record.get("cancel_requested"):
            # 取消晚到：全部步骤已完成，保持自然终态（真实优先于取消意图），
            # cancel_late 仅供验收取证；Stage 照常收尾——工作确实全部发生了。
            record["cancel_late"] = True
        _emit_stage(record, "running", "done")
        _emit_stage(record, "metric", "started")

        record.update({
            "status": "succeeded",
            "steps_result": step_results,
            "artifacts": _collect_artifacts(workspace),
            "finished_at": time.time(),
        })
        _emit_stage(record, "metric", "done")
        # A/B 干净环境复验属 NX-P2；preset 单环境如实 not_applicable。
        _emit_stage(record, "verifying", "not_applicable",
                    note="单环境 preset 运行，无干净 B 复验（A/B 属 NX-P2）")
        _emit_stage(record, "completed", "done")
    except CancelledJobError as error:
        _emit_stage(record, "running", "failed", note=str(error))
        _finalize_cancelled(record)
        record["steps_result"] = step_results
    except TimeoutError as error:
        record.update({
            "status": "failed", "code": "REPRO_TIMEOUT", "detail": str(error),
            "steps_result": step_results,
            "finished_at": time.time(),
        })
    except Exception as error:  # noqa: BLE001 - 失败分类如实回传
        if record.get("cancel_requested"):
            # 取消引发的连带失败（如取仓库步骤被 SIGKILL）：如实落 cancelled，
            # 不冒充 REPRO_FAILED；Stage 列表停在真实中断处（如 preparing）。
            _finalize_cancelled(record)
            record["steps_result"] = step_results
        else:
            record.update({
                "status": "failed", "code": "REPRO_FAILED", "detail": str(error)[:500],
                "steps_result": step_results,
                "finished_at": time.time(),
            })
    finally:
        record.pop("live_log_tail", None)
        record.pop("current_step", None)
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
        "stage_events_enabled": True,
        "cancel_enabled": True,
        "step_log_max_chars": STEP_LOG_MAX_CHARS,
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
    # 下划线前缀为进程内部状态（如 _proc 句柄），不属于对外契约。
    return {key: value for key, value in record.items() if not key.startswith("_")}


@app.post("/jobs/{job_id}/cancel", dependencies=[Depends(_require_token)])
async def cancel_job(job_id: str) -> dict[str, Any]:
    """NX-E3：取消作业。幂等；与自然完成竞争时保持真实终态。

    - queued/cancelling → 置 cancel_requested，执行器在下一个边界（步骤前置
      检查/入口检查）收尾；正在执行的步骤由本端点直接对进程组 SIGKILL。
    - 已终态（succeeded/failed/rejected/cancelled）→ 幂等返回现有状态，
      不报错、不改动。
    - 回收确认（步骤进程退出、执行器落 cancelled）之前状态为 cancelling，
      前端据此显示"取消中"，不以本端点返回即宣称已取消。
    """
    record = _jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    status_now = record.get("status")
    if status_now in ("succeeded", "failed", "rejected", "cancelled"):
        return {"job_id": job_id, "status": status_now, "already_terminal": True}
    record["cancel_requested"] = True
    record["status"] = "cancelling"
    proc = record.get("_proc")
    if proc is not None and proc.returncode is None:
        _kill_group(proc)
        record["cancel_landed"] = True
    return {"job_id": job_id, "status": "cancelling"}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        app,
        host=_env("REPRO_WORKER_HOST", "0.0.0.0"),
        port=int(_env("REPRO_WORKER_PORT", "8400")),
    )
