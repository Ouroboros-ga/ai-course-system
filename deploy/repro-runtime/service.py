"""repro-runtime：自主实验执行控制服务（内网专用，127.0.0.1）。

只做 SWE-ReX Docker 后端的薄 HTTP 封装：实例生命周期、命令执行、
文件传输、取消回收。不做审批、不做指标判定、不存业务——那些归 Nexus 域。

安全要点（部署约束，见 README）：
- 只绑 127.0.0.1；Bearer token 缺失拒绝启动（fail-closed）。
- 实验容器不挂 Docker socket、不读宿主业务卷；容器管理只在本进程。
- 路径服务端校验（绝对＋无 ..）；文件 5MB 上限；输出尾部 256KB 上限。
- 重启不重放：快照只用于对账（unknown），同 run 不静默复用（409）。

运行状态机（run）：creating → ready → running ⇄ ready → done/failed/
cancelled/unknown。operations 独立记录；取消只打断运行中操作并回收实例，
终态幂等。长操作 POST 即返回 running（先登记再执行），调用方按
operation_id 轮询；同 id 重复提交返回原记录，不运行两次。
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import tempfile
import time
from typing import Any
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from swerex_adapter import DockerBackendUnavailableError, SwerexDockerAdapter

logger = logging.getLogger("repro_runtime.service")

OUTPUT_TAIL_MAX = 256 * 1024
FILE_MAX_BYTES = 5 * 1024 * 1024
SNAPSHOT_OPS_KEEP = 50

# F3：会话执行参数（公开原语的薄编排，不自研内核）。
# - 首窗：提交后首个会话窗口（秒），超时即返 running（不阻塞 POST；
#   容器侧 pexpect 在窗内要么回显、要么抛超时，服务循环永不饥饿）。
# - 会话操作输出重定向到任务容器内 /tmp 日志/标记文件（真增量来源）；
#   标记只是"进程自述"，终态采信必须叠加 shell 空闲探针（防伪造成功）。
SESSION_FIRST_WINDOW_S = 15.0
SESSION_PROBE_TIMEOUT_S = 2.0
SESSION_OP_STATE_DIR = "/tmp/.nexus-ops"
SESSION_LOG_MAX_BYTES = 1024 * 1024

# 服务端可用容量上限（超出即 422，不静默截断；部署可经 env 收紧/放宽）。
MAX_MEMORY_MB = int(os.environ.get("REPRO_MAX_MEMORY_MB") or 8192)
MAX_CPUS = float(os.environ.get("REPRO_MAX_CPUS") or 4)
MAX_DISK_MB = int(os.environ.get("REPRO_MAX_DISK_MB") or 51200)
MAX_WALL_TIME_S = int(os.environ.get("REPRO_MAX_WALL_TIME_S") or 7200)

TERMINAL_RUN = ("done", "failed", "cancelled", "unknown")
TERMINAL_OP = ("succeeded", "failed", "cancelled")


def _now() -> float:
    return time.time()


def _service_token() -> str:
    return (os.environ.get("REPRO_RUNTIME_TOKEN") or "").strip()


def _task_image() -> str:
    return (os.environ.get("REPRO_TASK_IMAGE") or "python:3.12-slim").strip()


def _task_pull() -> str:
    """镜像拉取策略：默认 never（缺镜像即失败，不静默联网拉取）。"""
    value = (os.environ.get("REPRO_TASK_PULL") or "never").strip().lower()
    return value if value in ("never", "missing", "always") else "never"


def _env_docker_args() -> list[str]:
    raw = (os.environ.get("REPRO_TASK_DOCKER_ARGS") or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return [str(a) for a in parsed if isinstance(a, str)][:32]


def _task_docker_args(resources: "ResourcesSpec | None" = None) -> list[str]:
    """容器参数：有已确认 resources 时按其派生（内存/CPU/磁盘），否则回退部署默认。

    REPRO_TASK_DOCKER_ARGS 作为管理员附加参数始终追加在后。
    """
    extra = _env_docker_args()
    if resources is None:
        return extra or ["--memory=2g", "--cpus=2", "--pids-limit=512"]
    args: list[str] = []
    if resources.memory_mb:
        args.append(f"--memory={int(resources.memory_mb)}m")
    if resources.cpu:
        args.append(f"--cpus={resources.cpu}")
    if resources.disk_mb:
        # 需要存储驱动支持（overlay2+xfs 等）；不支持时 ensure 会降级并如实记 note。
        args.append(f"--storage-opt=size={int(resources.disk_mb)}m")
    args.append("--pids-limit=512")
    return args + extra


def _workspace_root() -> str:
    return "/" + (os.environ.get("REPRO_WORKSPACE_ROOT") or "workspace").strip("/")


def _snapshot_path() -> str:
    return (os.environ.get("REPRO_SNAPSHOT_PATH") or "./data/sandboxes.json").strip()


async def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = _service_token()
    if not expected:
        raise HTTPException(status_code=503, detail="SERVICE_TOKEN_NOT_CONFIGURED")
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="INVALID_SERVICE_TOKEN")


def _check_run_id(run_id: str) -> str:
    cleaned = (run_id or "").strip()[:64]
    if not cleaned or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
                           for c in cleaned):
        raise HTTPException(status_code=422, detail="INVALID_RUN_ID")
    return cleaned


def _check_path(path: str) -> str:
    """路径校验：绝对路径＋禁 `..`＋限定任务工作区根（任务书 §2）。"""
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        raise HTTPException(status_code=422, detail="INVALID_PATH")
    segments = [seg for seg in path.split("/") if seg not in ("", ".")]
    if ".." in segments:
        raise HTTPException(status_code=422, detail="PATH_TRAVERSAL_REJECTED")
    root = _workspace_root()
    if path != root and not path.startswith(root + "/"):
        raise HTTPException(status_code=422, detail="PATH_OUTSIDE_WORKSPACE")
    return path


async def _assert_no_symlink_escape(adapter: Any, path: str) -> None:
    """symlink 逃逸校验：容器内 readlink -f 解析后必须仍在工作区内。

    父目录不存在时 readlink -f 返回解析后的字面路径（exit 0），不误伤新建文件。
    """
    root = _workspace_root()
    try:
        real = await adapter.resolve_real_path(path)
    except DockerBackendUnavailableError as error:
        raise HTTPException(status_code=502, detail=f"{error.code}:{error}") from error
    if real and real != root and not real.startswith(root + "/"):
        raise HTTPException(status_code=422, detail="PATH_SYMLINK_ESCAPE")


def _tail(text: str) -> tuple[str, bool]:
    if len(text) <= OUTPUT_TAIL_MAX:
        return text, False
    return text[-OUTPUT_TAIL_MAX:], True


class OperationCreate(BaseModel):
    operation_id: str = Field(min_length=1, max_length=128)
    command: str = Field(min_length=1)
    timeout_s: float | None = None
    # F2：请求哈希（Nexus 意图登记的稳定摘要；同 id 不同请求即冲突）。
    # 旧客户端不带时只比 command 文本；都缺失无法比对时沿旧语义返回原记录。
    request_hash: str = Field(default="", max_length=128)
    # F2：执行 fencing token（Nexus 租约持有者的单调令牌）。
    # run 首次提交即锁定；旧 token 的新提交 → 409 FENCING_REJECTED。
    fencing: str = Field(default="", max_length=128)
    # F3：走 run 会话执行（可中断＋增量日志；语义路由由调用方按操作类型
    # 决定：安装/下载/实验执行等关联命令 True，独立探针/文件工具 False）。
    session: bool = False


class FencingRotate(BaseModel):
    """F2：轮换 run 的 fencing（恢复认领后新持有者接管执行权）。"""

    fencing: str = Field(min_length=1, max_length=128)


class ResourcesSpec(BaseModel):
    """已确认的资源声明（§2 Resources 子集；服务端据此派生容器限额）。"""

    cpu: float | None = Field(default=None, gt=0)
    memory_mb: int | None = Field(default=None, gt=0)
    disk_mb: int | None = Field(default=None, gt=0)
    wall_time_s: int | None = Field(default=None, gt=0)


class EnsureRequest(BaseModel):
    """ensure 请求体：授权 scope_hash＋资源声明（缺省兼容旧客户端）。"""

    scope_hash: str = Field(default="", max_length=128)
    resources: ResourcesSpec | None = None
    # F3：网络策略档案名（服务端映射到固定部署网络；未知档案 422）。
    network_profile: str = Field(default="", max_length=64)


def _check_resources_limits(resources: "ResourcesSpec | None") -> None:
    """服务端可用容量核对：超出部署上限即 422，不静默截断。"""
    if resources is None:
        return
    if resources.memory_mb and resources.memory_mb > MAX_MEMORY_MB:
        raise HTTPException(status_code=422, detail="RESOURCE_LIMIT_EXCEEDED:MEMORY")
    if resources.cpu and resources.cpu > MAX_CPUS:
        raise HTTPException(status_code=422, detail="RESOURCE_LIMIT_EXCEEDED:CPU")
    if resources.disk_mb and resources.disk_mb > MAX_DISK_MB:
        raise HTTPException(status_code=422, detail="RESOURCE_LIMIT_EXCEEDED:DISK")
    if resources.wall_time_s and resources.wall_time_s > MAX_WALL_TIME_S:
        raise HTTPException(status_code=422, detail="RESOURCE_LIMIT_EXCEEDED:WALL_TIME")


def _network_map() -> dict[str, str]:
    """F3：profile→docker 网络映射（部署配置，未配置即无映射）。

    例：REPRO_NETWORK_MAP='{"restricted": "nexus-exp-restricted"}'。
    映射只引用已存在的 docker 网络；创建/规则见 scripts/ 与网络隔离文档，
    本服务不自动建网（建网属部署变更）。
    """
    raw = (os.environ.get("REPRO_NETWORK_MAP") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()
            if isinstance(k, str) and isinstance(v, str) and k and v}


def _resolve_network(network_profile: str) -> tuple[str, str, bool]:
    """F3：profile → (docker 网络名, 生效说明, 是否隔离)。

    未声明/无映射 → ("", "默认 bridge（未隔离，如实记录）", False)；
    未知档案 → 422（未知≠默认放行）。
    隔离标准：生效网络 == REPRO_ISOLATED_NETWORK（部署配置的受限网络名）。
    """
    profile = (network_profile or "").strip()[:64]
    isolated_name = (os.environ.get("REPRO_ISOLATED_NETWORK") or "").strip()
    if not profile:
        return "", "默认 bridge（未声明档案，未隔离）", False
    mapped = _network_map().get(profile, "")
    if not mapped:
        raise HTTPException(
            status_code=422,
            detail=f"UNKNOWN_NETWORK_PROFILE:未知网络档案 {profile!r}",
        )
    isolated = bool(isolated_name) and mapped == isolated_name
    note = (f"受限网络 {mapped}（已隔离）" if isolated
            else f"网络 {mapped}（非隔离档案，如实记录）")
    return mapped, note, isolated


def _op_id_safe(operation_id: str) -> str:
    """操作态文件命名清洗（只留安全字符；Shlex 外的第二道底线）。"""
    return "".join(
        c for c in (operation_id or "") if c.isalnum() or c in ("-", "_"))[:96]


def _op_state_paths(operation_id: str) -> dict[str, str]:
    """F3：操作态文件路径（任务容器内 /tmp，不进工作区/配方）。

    script 原命令逐字落文件执行（引号/管道/退出码语义零改写）；
    log 真输出字节；done 完成自述（采信须叠加 shell 空闲探针）。
    """
    safe = _op_id_safe(operation_id) or "op"
    base = f"{SESSION_OP_STATE_DIR}/.{safe}"
    return {"script": f"{base}.sh", "log": f"{base}.log",
            "done": f"{base}.done"}


def _session_name(run_id: str) -> str:
    """F3：run 级会话名（run 隔离，64 上限内）。"""
    return f"sess-{_op_id_safe(run_id)[:56]}"


def _wrap_session_command(script_path: str, log_path: str, done_path: str) -> str:
    """F3：会话包装命令（固定模板＋引用路径；原命令不进字符串）。

    设施退出码 == 脚本退出码（pexpect 提取，权威）；done 文件只是自述。
    关键：末尾用子 shell `(exit $code)` 传递退出码——裸 `exit` 会退出
    REPL 本体，导致会话 pty EOF（线上实证）。
    """
    import shlex

    return (
        f"bash {shlex.quote(script_path)} > {shlex.quote(log_path)} 2>&1; "
        f"code=$?; printf 'EXIT:%s' \"$code\" > {shlex.quote(done_path)}; "
        f"(exit $code)"
    )


def _parse_done_marker(text: str) -> int | None:
    """解析 EXIT 标记；非形即 None（伪造/损坏的标记不采信）。"""
    import re

    match = re.search(r"EXIT:(-?\d+)\s*$", (text or "").strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


class _Store:
    """run/operation 内存状态＋JSON 快照（重启只对账 unknown，不重放）。

    T5 会把本侧车毕业为 PG；快照格式保持简单可迁移（run 行＋近 N 操作）。
    """

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.adapters: dict[str, SwerexDockerAdapter] = {}

    def lock_for(self, run_id: str) -> asyncio.Lock:
        lock = self.locks.get(run_id)
        if lock is None:
            lock = asyncio.Lock()
            self.locks[run_id] = lock
        return lock

    def save_snapshot(self) -> None:
        path = _snapshot_path()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            slim: dict[str, Any] = {}
            for run_id, run in self.runs.items():
                ops = run.get("operations") or {}
                kept = dict(list(ops.items())[-SNAPSHOT_OPS_KEEP:])
                for op in kept.values():
                    tail, _ = _tail(str(op.get("output_tail") or ""))
                    op["output_tail"] = tail
                slim[run_id] = {
                    "run_id": run_id,
                    "sandbox_id": run.get("sandbox_id", ""),
                    "container_name": run.get("container_name", ""),
                    "image": run.get("image", ""),
                    "image_digest": run.get("image_digest", ""),
                    "scope_hash": run.get("scope_hash", ""),
                    "resources": dict(run.get("resources") or {}),
                    "wall_time_s": int(run.get("wall_time_s") or 0),
                    "deadline_at": float(run.get("deadline_at") or 0),
                    "docker_args": list(run.get("docker_args") or []),
                    "status": run.get("status", "unknown"),
                    "fencing": str(run.get("fencing") or ""),
                    "created_at": run.get("created_at", 0),
                    "updated_at": run.get("updated_at", 0),
                    "operations": kept,
                }
            tmp = f"{path}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(slim, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as error:  # noqa: BLE001 - 快照失败记日志，不阻断主流程
            logger.warning("snapshot save failed: %s", error)

    def load_snapshot(self) -> None:
        path = _snapshot_path()
        try:
            with open(path, encoding="utf-8") as handle:
                slim = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(slim, dict):
            return
        now = _now()
        for run_id, row in slim.items():
            if not isinstance(row, dict):
                continue
            operations = row.get("operations") if isinstance(
                row.get("operations"), dict) else {}
            for op in operations.values():
                if isinstance(op, dict) and op.get("status") not in TERMINAL_OP:
                    op["status"] = "unknown"
                    op["note"] = "服务重启，执行状态未知（不重放）"
            self.runs[str(run_id)] = {
                "run_id": str(run_id),
                "sandbox_id": str(row.get("sandbox_id", "")),
                "container_name": str(row.get("container_name", "")),
                "image": str(row.get("image", "")),
                "image_digest": str(row.get("image_digest", "")),
                "scope_hash": str(row.get("scope_hash", "")),
                "resources": dict(row.get("resources") or {}),
                "wall_time_s": int(row.get("wall_time_s") or 0),
                "deadline_at": float(row.get("deadline_at") or 0),
                "docker_args": list(row.get("docker_args") or []),
                "status": "unknown",
                "fencing": str(row.get("fencing") or ""),
                "note": "服务重启，执行状态未知（不重放、不自动恢复）",
                "created_at": float(row.get("created_at", 0) or 0),
                "updated_at": now,
                "operations": operations,
            }


store = _Store()


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run["run_id"],
        "sandbox_id": run.get("sandbox_id", ""),
        "status": run.get("status", "unknown"),
        "note": run.get("note", ""),
        "image": run.get("image", ""),
        "image_digest": run.get("image_digest", ""),
        "scope_hash": run.get("scope_hash", ""),
        "resources": dict(run.get("resources") or {}),
        "wall_time_s": int(run.get("wall_time_s") or 0),
        "deadline_at": float(run.get("deadline_at") or 0),
        "container_name": run.get("container_name", ""),
        # F2：现 fencing（对账可见；非密钥，轮换经专用端点）。
        "fencing": str(run.get("fencing") or ""),
        # F3：网络档案与生效网络（只读投影）。
        "network_profile": str(run.get("network_profile") or ""),
        "effective_network": str(run.get("effective_network") or ""),
        "network_isolated": bool(run.get("network_isolated", False)),
        "network_note": str(run.get("network_note") or ""),
        "created_at": run.get("created_at", 0),
        "updated_at": run.get("updated_at", 0),
        "active_operation_id": run.get("active_operation_id", ""),
    }


def _public_operation(run_id: str, op: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": op.get("operation_id", ""),
        "status": op.get("status", "unknown"),
        "exit_code": op.get("exit_code"),
        "output_tail": op.get("output_tail", ""),
        "output_truncated": bool(op.get("output_truncated")),
        "started_at": op.get("started_at", 0),
        "finished_at": op.get("finished_at", 0),
        # F3：会话/增量只读投影（one-shot 留空；游标语义见 query）。
        "session": bool(op.get("session", False)),
        "log_bytes": int(op.get("log_bytes") or 0),
        "log_capped": bool(op.get("log_capped", False)),
        "declared_exit": op.get("declared_exit"),
        "facility_confirmed": bool(op.get("facility_confirmed", False)),
        "interrupt_note": str(op.get("interrupt_note") or ""),
        "note": str(op.get("note") or ""),
    }


async def _run_operation(run_id: str, operation_id: str) -> None:
    """后台执行单个 operation（先登记后执行；异常转失败记录，不抛）。

    所有写终态处只在操作仍为 running 时落盘——取消端点可能已先行标记
    cancelled，迟到的执行结果不得覆盖取消结论。
    """
    run = store.runs.get(run_id)
    if run is None:
        return
    op = (run.get("operations") or {}).get(operation_id)
    if op is None or op.get("status") != "running":
        return

    def _finish(**fields: object) -> None:
        if op.get("status") == "running":
            op.update(fields)

    adapter = store.adapters.get(run_id)
    if adapter is None:
        _finish(status="failed", finished_at=_now(),
                output_tail="实例不可用（服务重启或已回收）",
                output_truncated=False)
        run["updated_at"] = _now()
        store.save_snapshot()
        return
    try:
        result = await adapter.execute(op["command"], op.get("timeout_s"))
        output = str((result or {}).get("output") or "")
        tail, _ = _tail(output)
        _finish(status="succeeded" if (result or {}).get("exit_code") == 0 else "failed",
                exit_code=(result or {}).get("exit_code"),
                output_tail=tail,
                output_truncated=bool((result or {}).get("truncated")) or len(output) > len(tail),
                finished_at=_now())
    except asyncio.CancelledError:
        _finish(status="cancelled", finished_at=_now(),
                output_tail=str(op.get("output_tail") or "") + "\n[cancelled]",
                output_truncated=bool(op.get("output_truncated")))
        raise
    except DockerBackendUnavailableError as error:
        _finish(status="failed", finished_at=_now(),
                output_tail=f"{error.code}：{error}",
                output_truncated=False)
    finally:
        run["updated_at"] = _now()
        if run.get("active_operation_id") == operation_id:
            run["active_operation_id"] = ""
        store.save_snapshot()


app = FastAPI(title="repro-runtime", version="0.1.0")


@app.on_event("startup")
async def _on_startup() -> None:
    if not _service_token():
        raise RuntimeError("REPRO_RUNTIME_TOKEN 未配置，拒绝启动")
    store.load_snapshot()
    logger.info("repro-runtime ready (snapshot runs=%d)", len(store.runs))


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "version": "0.1.0", "runs": len(store.runs)}


@app.put("/sandboxes/{run_id}")
async def ensure_sandbox(run_id: str, body: EnsureRequest | None = None,
                         _: None = Depends(require_token)):
    """ensure（同 run 同 scope 幂等；异 hash 409；重启后未知 run 须换新 id）。

    请求体携带授权 scope_hash 与已确认 resources：首次落盘，重复 PUT 比对
    scope_hash（不同 → 409 SCOPE_HASH_MISMATCH）；资源超部署上限 → 422。
    """
    run_id = _check_run_id(run_id)
    scope_hash = (body.scope_hash if body else "") or ""
    resources = body.resources if body else None
    _check_resources_limits(resources)
    # F3：网络档案解析（未知档案 422；未声明走默认 bridge，如实记未隔离）。
    network_profile = (body.network_profile if body else "") or ""
    network_name, network_note, network_isolated = _resolve_network(network_profile)
    async with store.lock_for(run_id):
        existing = store.runs.get(run_id)
        if existing is not None:
            if scope_hash and existing.get("scope_hash") and \
                    scope_hash != existing["scope_hash"]:
                raise HTTPException(
                    status_code=409,
                    detail="SCOPE_HASH_MISMATCH:同 run 已按另一 scope 授权，拒绝复用",
                )
            if existing.get("status") == "unknown" and run_id not in store.adapters:
                raise HTTPException(
                    status_code=409,
                    detail="RUN_UNKNOWN_STATE:服务重启后该 run 状态未知（不重放、不复用），请换新 run_id",
                )
            return {**_public_run(existing), "deduped": True}
        docker_args = _task_docker_args(resources)
        if network_name:
            docker_args = [a for a in docker_args
                           if not a.startswith("--network=")]
            docker_args.append(f"--network={network_name}")
        note = ""
        adapter = SwerexDockerAdapter(
            run_id=run_id, image=_task_image(),
            docker_args=docker_args, pull=_task_pull())
        try:
            container_name = await adapter.start()
        except DockerBackendUnavailableError as error:
            # 磁盘配额参数不被存储驱动支持时降级（如实记 note，不假装生效）。
            if any(a.startswith("--storage-opt") for a in docker_args):
                fallback = [a for a in docker_args
                            if not a.startswith("--storage-opt")]
                adapter = SwerexDockerAdapter(
                    run_id=run_id, image=_task_image(),
                    docker_args=fallback, pull=_task_pull())
                try:
                    container_name = await adapter.start()
                except DockerBackendUnavailableError:
                    raise HTTPException(
                        status_code=502, detail=f"{error.code}:{error}") from error
                note = "磁盘配额（--storage-opt）不被存储驱动支持，已降级：未生效。"
            else:
                raise HTTPException(
                    status_code=502, detail=f"{error.code}:{error}") from error
        image_digest = await adapter.image_digest()
        wall_time_s = int(getattr(resources, "wall_time_s", 0) or 0)
        run = {
            "run_id": run_id,
            "sandbox_id": f"sb-{run_id}",
            "container_name": container_name,
            "image": adapter.image,
            "image_digest": image_digest,
            "scope_hash": scope_hash,
            "resources": (resources.model_dump() if resources is not None else {}),
            "wall_time_s": wall_time_s,
            "deadline_at": (_now() + wall_time_s) if wall_time_s else 0,
            "docker_args": list(adapter.docker_args),
            "status": "ready",
            "note": note,
            # F2：执行 fencing（首次提交锁定；轮换经专用端点）。
            "fencing": "",
            # F3：网络档案与生效网络（未部署受限网络前如实记未隔离）。
            "network_profile": (network_profile or "")[:64],
            "effective_network": network_name or "bridge",
            "network_isolated": bool(network_isolated),
            "network_note": network_note,
            # F3：会话/重建位（中断失败回收后置位，下次会话提交重建）。
            "session_name": "",
            "session_ready": False,
            "needs_rebuild": False,
            "created_at": _now(),
            "updated_at": _now(),
            "operations": {},
            "active_operation_id": "",
        }
        store.runs[run_id] = run
        store.adapters[run_id] = adapter
        store.save_snapshot()
        return {**_public_run(run), "deduped": False}


@app.get("/sandboxes/{run_id}")
async def sandbox_status(run_id: str, _: None = Depends(require_token)):
    """生命周期/活跃 operation/资源摘要（对账用）。"""
    run_id = _check_run_id(run_id)
    run = store.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="UNKNOWN_RUN")
    view = _public_run(run)
    view["docker_args"] = list(run.get("docker_args") or [])
    return view


def _tail_text(data: bytes, limit: int = OUTPUT_TAIL_MAX) -> tuple[str, bool]:
    """字节尾转文本（末 limit 字节；超限截断标记）。"""
    raw = bytes(data or b"")
    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace"), False
    return raw[-limit:].decode("utf-8", errors="replace"), True


async def _restart_adapter_for_rebuild(run: dict[str, Any]) -> Any:
    """F3：中断失败后的容器回收重建（needs_rebuild 消费点）。

    杀旧实例（best-effort）→ 按原镜像/限额起新实例（pull=never，镜像必已
    存在）→ 清会话位。失败抛 DockerBackendUnavailableError，调用方 502。
    """
    from swerex_adapter import DockerBackendUnavailableError  # noqa: F401

    run_id = run["run_id"]
    old = store.adapters.pop(run_id, None)
    if old is not None:
        try:
            await old.kill()
        except Exception:  # noqa: BLE001 - 回收失败记日志，继续重建
            logger.warning("run %s rebuild kill failed", run_id)
    adapter = SwerexDockerAdapter(
        run_id=run_id, image=str(run.get("image") or _task_image()),
        docker_args=list(run.get("docker_args") or []), pull="never")
    await adapter.start()
    store.adapters[run_id] = adapter
    run["needs_rebuild"] = False
    run["session_name"] = ""
    run["session_ready"] = False
    return adapter


async def _ensure_session(run: dict[str, Any], adapter: Any) -> str:
    """F3：确保 run 会话就绪（已就绪直接返回；并发建会话容忍已存在）。"""
    from swerex_adapter import DockerBackendUnavailableError

    name = str(run.get("session_name") or "") or _session_name(run["run_id"])
    if run.get("session_ready"):
        return name
    try:
        await adapter.create_session(name)
    except DockerBackendUnavailableError as error:
        if error.code != "SESSION_EXISTS":
            logger.warning("run %s session ensure failed: %s: %.300s",
                           run["run_id"], error.code, error)
            raise
    run["session_name"] = name
    run["session_ready"] = True
    return name


async def _read_op_log(adapter: Any, paths: dict[str, str]) -> tuple[bytes, bool]:
    """读操作日志（上限 SESSION_LOG_MAX_BYTES；超限截断标记）。"""
    try:
        data = await adapter.read_bytes(paths["log"],
                                        max_bytes=SESSION_LOG_MAX_BYTES + 16)
    except Exception:  # noqa: BLE001 - 缺失/失败按空处理，不抛
        return b"", False
    if len(data) > SESSION_LOG_MAX_BYTES:
        return data[-SESSION_LOG_MAX_BYTES:], True
    return data, False


async def _read_done_marker(adapter: Any, paths: dict[str, str]) -> int | None:
    """读完成自述 EXIT 值；缺失/畸形即 None（不采信，由探针裁决）。"""
    try:
        text = await adapter.read_text(paths["done"])
    except Exception:  # noqa: BLE001
        return None
    return _parse_done_marker(text)


async def _finalize_session_op(
    run: dict[str, Any], op: dict[str, Any], adapter: Any, *,
    status: str, exit_code: int | None, note: str = "",
) -> None:
    """F3：会话操作终态落盘（日志尾＋标记交叉注记＋快照）。"""
    paths = _op_state_paths(op["operation_id"])
    log_data, log_capped = await _read_op_log(adapter, paths)
    tail, tail_cut = _tail_text(log_data)
    declared = await _read_done_marker(adapter, paths)
    notes: list[str] = []
    if note:
        notes.append(note)
    if log_capped or tail_cut:
        notes.append("日志超限已截断（上限 1MB/尾部 256KB）。")
    if declared is not None and exit_code is not None and declared != exit_code:
        notes.append(
            f"完成自述 EXIT:{declared} 与设施退出码 {exit_code} 不一致，"
            "以设施为准（自述不可伪造成功）。")
    if declared is None and status in ("succeeded", "failed"):
        notes.append("完成标记缺失；结论来自设施退出码。")
    op.update({
        "status": status, "exit_code": exit_code,
        "output_tail": tail, "output_truncated": bool(tail_cut or log_capped),
        "log_bytes": len(log_data), "log_capped": bool(log_capped),
        "declared_exit": declared, "facility_confirmed": True,
        "finished_at": _now(),
        "note": " ".join(notes)[:500],
    })
    if run.get("active_operation_id") == op["operation_id"]:
        run["active_operation_id"] = ""
    run["updated_at"] = _now()
    store.save_snapshot()


def _session_windows(op: dict[str, Any], run: dict[str, Any]) -> tuple[float, str]:
    """F3：本窗时长与到期原因（op 超时/wall_time/首窗取最小）。

    返回 (window_s, expired_cause)；expired_cause 为空即两时限都未到。
    """
    now = _now()
    op_timeout = op.get("timeout_s") or 3600.0
    try:
        op_deadline = float(op.get("started_at") or now) + max(1.0, float(op_timeout))
    except (TypeError, ValueError):
        op_deadline = now + 3600.0
    wall_deadline = float(run.get("deadline_at") or 0) or float("inf")
    window = min(SESSION_FIRST_WINDOW_S, op_deadline - now, wall_deadline - now)
    if op_deadline <= now:
        return 0.0, "OPERATION_TIMEOUT"
    if wall_deadline <= now:
        return 0.0, "WALL_TIME_EXCEEDED"
    return max(0.5, window), ""


async def _recycle_container(run: dict[str, Any], reason: str) -> None:
    """F3：中断失败的范围内处置——杀容器、下次会话提交重建。

    保留原始原因（run note 追加，不覆盖）；如实标记 needs_rebuild。
    """
    run_id = run["run_id"]
    old = store.adapters.pop(run_id, None)
    if old is not None:
        try:
            await old.kill()
        except Exception:  # noqa: BLE001
            logger.warning("run %s recycle kill failed", run_id)
    run["needs_rebuild"] = True
    run["session_ready"] = False
    run["active_operation_id"] = ""
    previous = str(run.get("note") or "")
    combined = f"{previous} | {reason}" if previous else reason
    run["note"] = combined[:500]
    run["updated_at"] = _now()
    store.save_snapshot()


async def _interrupt_session_op(
    run: dict[str, Any], op: dict[str, Any], adapter: Any,
) -> dict[str, Any]:
    """F3：中断会话操作并确认停止（调用方已持 run 锁）。

    中断→探活→空闲即 cancelled（附尾部输出）；仍忙即 INTERRUPT_UNCONFIRMED
    ＋回收容器（保留原始原因，不伪装成只取消一个命令）。
    """
    from swerex_adapter import DockerBackendUnavailableError

    operation_id = op["operation_id"]
    session = str(run.get("session_name") or "") or _session_name(run["run_id"])
    paths = _op_state_paths(operation_id)
    try:
        interrupt_obs = await adapter.interrupt_session(session)
    except DockerBackendUnavailableError as error:
        await _recycle_container(
            run, f"中断失败（{error.code}），容器已回收待重建；"
            f"原操作 {operation_id} 未确认停止。")
        op.update({"status": "cancelled", "finished_at": _now(),
                   "interrupt_note": f"INTERRUPT_UNCONFIRMED:{error.code}",
                   "note": f"中断未确认停止，已回收容器（{error.code}）。"})
        run["updated_at"] = _now()
        store.save_snapshot()
        return {"operation_id": operation_id, "status": "cancelled",
                "unconfirmed": True, "code": "INTERRUPT_UNCONFIRMED"}
    try:
        free = await adapter.probe_session(session,
                                           timeout_s=SESSION_PROBE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - 探针异常按仍忙处理
        free = False
    log_data, _ = await _read_op_log(adapter, paths)
    tail, _ = _tail_text(log_data)
    tail = ((str(interrupt_obs.get("output") or "") + "\n" + tail)[-OUTPUT_TAIL_MAX:])
    if free:
        op.update({"status": "cancelled", "exit_code": None,
                   "output_tail": tail, "output_truncated": True,
                   "log_bytes": len(log_data),
                   "finished_at": _now(), "interrupt_note": "已确认停止",
                   "note": "操作级中断：已确认进程停止，实验继续。"})
        if run.get("active_operation_id") == operation_id:
            run["active_operation_id"] = ""
        run["updated_at"] = _now()
        store.save_snapshot()
        return {"operation_id": operation_id, "status": "cancelled",
                "unconfirmed": False}
    await _recycle_container(
        run, f"中断未确认停止（{operation_id}），容器已回收待重建。")
    op.update({"status": "cancelled", "finished_at": _now(),
               "output_tail": tail, "output_truncated": True,
               "interrupt_note": "INTERRUPT_UNCONFIRMED",
               "note": "中断未确认停止，已回收容器；原因保留，实验可继续。"})
    run["updated_at"] = _now()
    store.save_snapshot()
    return {"operation_id": operation_id, "status": "cancelled",
            "unconfirmed": True, "code": "INTERRUPT_UNCONFIRMED"}


async def _submit_session_operation(
    run: dict[str, Any], op: dict[str, Any], adapter: Any,
) -> dict[str, Any]:
    """F3：会话提交（首窗内完成即终态，否则 running 即返）。

    原命令逐字落脚本文件执行（语义零改写）；在途时限（op 超时/wall_time）
    到期即中断＋timed_out。调用方已持 run 锁（会话串行）。
    """
    from swerex_adapter import DockerBackendUnavailableError

    operation_id = op["operation_id"]
    paths = _op_state_paths(operation_id)
    session = await _ensure_session(run, adapter)
    op.update({
        "session": True, "session_name": session,
        "script_path": paths["script"], "log_path": paths["log"],
        "done_path": paths["done"], "log_bytes": 0,
        "declared_exit": None, "facility_confirmed": False,
    })
    try:
        await adapter.upload_bytes(
            paths["script"], (str(op.get("command") or "") + "\n").encode("utf-8"))
    except DockerBackendUnavailableError as error:
        op.update({"status": "failed", "finished_at": _now(),
                   "output_tail": f"脚本下发失败（{error.code}）",
                   "note": f"脚本下发失败：{error.code}"})
        run["updated_at"] = _now()
        store.save_snapshot()
        return _public_operation(run["run_id"], op)
    window, expired = _session_windows(op, run)
    wrapper = _wrap_session_command(paths["script"], paths["log"], paths["done"])
    if expired:
        # 提交即到期（op 超时/wall 到期）：中断式收尾，不执行。
        await _finalize_session_op(
            run, op, adapter, status="timed_out", exit_code=None,
            note=f"{expired}：提交时已到期，未执行。")
        return _public_operation(run["run_id"], op)
    try:
        observation = await adapter.run_in_session(
            session, wrapper, timeout_s=window)
    except DockerBackendUnavailableError as error:
        if error.code != "SESSION_TIMEOUT":
            logger.warning("run %s session submit failed: %s: %.300s",
                           run["run_id"], error.code, error)
            op.update({"status": "failed", "finished_at": _now(),
                       "output_tail": f"会话执行失败（{error.code}）",
                       "note": f"会话执行失败：{error.code}"})
            run["updated_at"] = _now()
            store.save_snapshot()
            return _public_operation(run["run_id"], op)
        # 首窗超时：命令仍在跑——在途时限到期即中断＋timed_out，否则 running。
        _, expired_now = _session_windows(op, run)
        if expired_now:
            interrupted = await _interrupt_session_op(run, op, adapter)
            if interrupted.get("unconfirmed"):
                op.update({"status": "timed_out", "finished_at": _now(),
                           "note": f"{expired_now}：到期中断未确认，已回收容器。"})
            else:
                op.update({"status": "timed_out",
                           "note": f"{expired_now}：到期已中断。"})
            op["finished_at"] = _now()
            run["updated_at"] = _now()
            store.save_snapshot()
            return _public_operation(run["run_id"], op)
        run["updated_at"] = _now()
        store.save_snapshot()
        return _public_operation(run["run_id"], op)
    # 首窗内完成：设施退出码权威，标记交叉注记。
    exit_code = observation.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        await _finalize_session_op(
            run, op, adapter, status="failed", exit_code=None,
            note="设施未返回有效退出码（NO_EXIT_CODE），fail-closed。")
    else:
        await _finalize_session_op(
            run, op, adapter,
            status="succeeded" if exit_code == 0 else "failed",
            exit_code=exit_code)
    return _public_operation(run["run_id"], op)


@app.post("/sandboxes/{run_id}/operations")
async def submit_operation(run_id: str, body: OperationCreate,
                           _: None = Depends(require_token)):
    """登记后执行（202 直接返回 running）；同 id 返回原记录，不运行两次。"""
    run_id = _check_run_id(run_id)
    operation_id = (body.operation_id or "").strip()[:128]
    if not operation_id:
        raise HTTPException(status_code=422, detail="INVALID_OPERATION_ID")
    if not isinstance(body.command, str) or not body.command.strip():
        raise HTTPException(status_code=422, detail="EMPTY_COMMAND")
    timeout_s = body.timeout_s
    if timeout_s is not None and (timeout_s <= 0 or timeout_s > 3600):
        raise HTTPException(status_code=422, detail="INVALID_TIMEOUT")
    async with store.lock_for(run_id):
        run = store.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="UNKNOWN_RUN")
        if run.get("status") in TERMINAL_RUN:
            raise HTTPException(
                status_code=409,
                detail=f"RUN_TERMINAL:{run.get('status')}：终态 run 不再接受新操作",
            )
        # F2：fencing 校验（首次提交锁定，旧 token/空 token 新提交拒绝）。
        # 无历史包袱：fencing 随本批引入，不存在发空 token 的旧客户端。
        fencing = (body.fencing or "").strip()[:128]
        locked = str(run.get("fencing") or "")
        if locked and fencing != locked:
            raise HTTPException(
                status_code=409,
                detail="FENCING_REJECTED:提交 token 已过期（执行权已转移）；"
                "旧持有者的新提交被拒绝，先对账再由现持有者提交。",
            )
        deadline = float(run.get("deadline_at") or 0)
        if deadline and _now() > deadline:
            # 已确认的 wall_time 到期：不再接受新操作，已有结果保留（不静默杀）。
            raise HTTPException(
                status_code=409,
                detail="WALL_TIME_EXCEEDED:已达该 run 的授权时限，不再接受新操作",
            )
        operations = run.setdefault("operations", {})
        if operation_id in operations:
            existing = operations[operation_id]
            # F2：同 ID 同请求返回原记录（不运行两次）；同 ID 不同请求即
            # 409 OPERATION_ID_CONFLICT（旧进程无退出证明不得重跑，先对账）。
            # 比对顺序：双方都带哈希即比哈希；否则比 command 文本；旧记录/
            # 旧快照缺命令时无法判定，沿旧语义返回原记录（不误杀）。
            new_hash = (body.request_hash or "").strip()
            old_hash = str(existing.get("request_hash") or "")
            new_command = body.command.strip()
            old_command = str(existing.get("command") or "")
            conflict = False
            if new_hash and old_hash:
                conflict = new_hash != old_hash
            elif old_command:
                conflict = new_command != old_command.strip()
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail="OPERATION_ID_CONFLICT:该 operation_id 已登记不同请求；"
                    "旧进程无退出证明不得重跑，先查询对账。",
                )
            return {**_public_operation(run_id, existing),
                    "deduped": True}
        op = {
            "operation_id": operation_id,
            "command": body.command,
            "request_hash": (body.request_hash or "").strip(),
            "timeout_s": timeout_s,
            "status": "running",
            "exit_code": None,
            "output_tail": "",
            "output_truncated": False,
            # F3：会话操作态（one-shot 留空；快照 whole-dict 持久化）。
            "session": bool(body.session),
            "session_name": "",
            "script_path": "",
            "log_path": "",
            "done_path": "",
            "log_bytes": 0,
            "log_capped": False,
            "declared_exit": None,
            "facility_confirmed": False,
            "interrupt_note": "",
            "note": "",
            "started_at": _now(),
            "finished_at": 0,
        }
        operations[operation_id] = op
        if fencing and not str(run.get("fencing") or ""):
            run["fencing"] = fencing
        run["status"] = "running"
        run["active_operation_id"] = operation_id
        run["updated_at"] = _now()
        if body.session:
            # F3：会话提交（串行：本锁内首窗执行；中断/重建位在此消费）。
            from swerex_adapter import DockerBackendUnavailableError

            adapter = store.adapters.get(run_id)
            if adapter is None or run.get("needs_rebuild"):
                try:
                    if run.get("needs_rebuild"):
                        adapter = await _restart_adapter_for_rebuild(run)
                    else:
                        raise DockerBackendUnavailableError(
                            "NOT_STARTED", "实例不可用")
                except DockerBackendUnavailableError as error:
                    op.update({"status": "failed", "finished_at": _now(),
                               "output_tail": f"实例不可用（{error.code}）",
                               "note": f"实例不可用：{error.code}"})
                    run["updated_at"] = _now()
                    store.save_snapshot()
                    return {**_public_operation(run_id, op), "deduped": False}
                except Exception as error:  # noqa: BLE001 - 重建失败如实 502
                    op.update({"status": "failed", "finished_at": _now(),
                               "output_tail": "实例重建失败",
                               "note": f"实例重建失败：{type(error).__name__}"})
                    run["updated_at"] = _now()
                    store.save_snapshot()
                    return {**_public_operation(run_id, op), "deduped": False}
            try:
                return {**await _submit_session_operation(run, op, adapter),
                        "deduped": False}
            except DockerBackendUnavailableError as error:
                op.update({"status": "failed", "finished_at": _now(),
                           "output_tail": f"会话提交失败（{error.code}）",
                           "note": f"会话提交失败：{error.code}"})
                run["updated_at"] = _now()
                store.save_snapshot()
                return {**_public_operation(run_id, op), "deduped": False}
        task = asyncio.create_task(_run_operation(run_id, operation_id))
        run.setdefault("tasks", {})[operation_id] = task
        store.save_snapshot()
        return {**_public_operation(run_id, op), "deduped": False}


@app.get("/sandboxes/{run_id}/operations/{operation_id}")
async def query_operation(run_id: str, operation_id: str,
                          cursor: int = 0, probe: int = 0,
                          _: None = Depends(require_token)):
    """查询结果（HTTP 超时不等同进程已停止；未知 id 诚实 unknown）。

    F3 增量：`cursor` 为已消费日志字节数，返回该偏移后的增量
    （`increment`/`offset`/`reset`；reset=True 表示流起点变化，调用方应
    替换缓冲后以 offset 为新游标）。`probe=1` 对运行中会话操作做一次
    shell 空闲探针：空闲＋标记齐全即按设施语义采信终态（防伪造成功），
    仍忙则保持 running。终态操作忽略 probe（幂等返回）。
    """
    run_id = _check_run_id(run_id)
    operation_id = (operation_id or "").strip()[:128]
    try:
        cursor = max(0, int(cursor or 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="INVALID_CURSOR")
    run = store.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="UNKNOWN_RUN")
    op = (run.get("operations") or {}).get(operation_id)
    if op is None:
        return {"operation_id": operation_id, "status": "unknown", "exit_code": None,
                "output_tail": "", "output_truncated": False,
                "increment": "", "offset": 0, "reset": True,
                "note": "控制服务无此操作记录（可能重启丢失，不重放）"}
    if op.get("status") in TERMINAL_OP:
        return _operation_increment(run, op, cursor)
    if probe and op.get("session") and op.get("status") == "running":
        async with store.lock_for(run_id):
            # 锁内重读（查询与中断/提交互斥，会话串行）。
            op = (run.get("operations") or {}).get(operation_id) or op
            if op.get("status") == "running" and op.get("session"):
                await _probe_and_adopt(run, op)
    if op.get("status") in TERMINAL_OP:
        return _operation_increment(run, op, cursor)
    # 运行中会话操作：实时日志增量（读失败即空增量＋原因，不抛）。
    view = _operation_increment(run, op, cursor)
    if op.get("session"):
        adapter = store.adapters.get(run_id)
        if adapter is not None:
            try:
                paths = _op_state_paths(operation_id)
                log_data, capped = await _read_op_log(adapter, paths)
                text = log_data.decode("utf-8", errors="replace")
                view["increment"] = text[cursor:] if cursor < len(text) else ""
                view["offset"] = len(text)
                view["reset"] = False
                view["log_bytes"] = len(log_data)
                view["log_capped"] = bool(capped)
                declared = await _read_done_marker(adapter, paths)
                view["declared_exit"] = declared
            except Exception as error:  # noqa: BLE001
                view["note"] = (str(view.get("note") or "")
                                + f" 日志读取失败（{type(error).__name__}）。")[:500]
        else:
            view["note"] = (str(view.get("note") or "")
                            + " 实例不可达，增量未知。")[:500]
    return view


async def _probe_and_adopt(run: dict[str, Any], op: dict[str, Any]) -> str:
    """F3：运行中会话操作的探针采信（调用方已持 run 锁）。

    shell 空闲＋标记齐全 → 按设施序列化语义采信终态；仍忙 → running；
    空闲但标记缺失 → 防御性 failed（MARKER_MISSING）。返回裁决词。
    """
    from swerex_adapter import DockerBackendUnavailableError

    adapter = store.adapters.get(run["run_id"])
    if adapter is None:
        return "no_adapter"
    try:
        session = str(op.get("session_name") or "") or _session_name(run["run_id"])
        free = await adapter.probe_session(session,
                                           timeout_s=SESSION_PROBE_TIMEOUT_S)
    except DockerBackendUnavailableError:
        return "probe_failed"
    if not free:
        return "busy"
    paths = _op_state_paths(op["operation_id"])
    declared = await _read_done_marker(adapter, paths)
    if declared is None:
        await _finalize_session_op(
            run, op, adapter, status="failed", exit_code=None,
            note="空闲但完成标记缺失（MARKER_MISSING），fail-closed。")
        return "adopted_missing"
    await _finalize_session_op(
        run, op, adapter,
        status="succeeded" if declared == 0 else "failed",
        exit_code=declared,
        note="探针确认 shell 空闲后采信（设施序列化证明）。")
    return "adopted"


def _operation_increment(
    run: dict[str, Any], op: dict[str, Any], cursor: int,
) -> dict[str, Any]:
    """F3：操作增量投影（调用方可持锁可不持；只读 run/op 字典）。

    终态：增量取自落盘 output_tail（`reset=True`，调用方替换缓冲）；
    运行中会话操作：增量取自实时日志（`reset=False`，追加即可）。
    """
    view = _public_operation(run["run_id"], op)
    if op.get("status") in TERMINAL_OP or not op.get("session"):
        tail = str(op.get("output_tail") or "")
        view["increment"] = tail[cursor:] if cursor < len(tail) else ""
        view["offset"] = len(tail)
        view["reset"] = True
        return view
    # 运行中：实时日志增量（best-effort；读失败即空增量，不抛）。
    view["increment"] = ""
    view["offset"] = cursor
    view["reset"] = False
    return view


class OperationCancel(BaseModel):
    """F3：操作级取消请求体（fencing 与提交同规则，旧 token 拒绝）。"""

    fencing: str = Field(default="", max_length=128)


@app.post("/sandboxes/{run_id}/operations/{operation_id}/cancel")
async def cancel_operation(run_id: str, operation_id: str,
                           body: OperationCancel | None = None,
                           _: None = Depends(require_token)):
    """F3：只停止卡住的命令（整体取消仍走 run 级 cancel）。

    - 会话运行中操作 → 中断＋确认停止（附尾部输出），实验继续；
    - one-shot 运行中操作 → 409 OPERATION_NOT_INTERRUPTIBLE（其中断语义
      即回收实例，请走 run 级取消，不伪装成单命令取消）；
    - 终态操作 → 幂等返回现态；未知 id → unknown（不重放）。
    中断无法确认停止 → INTERRUPT_UNCONFIRMED＋回收容器（保留原始原因）。
    """
    run_id = _check_run_id(run_id)
    operation_id = (operation_id or "").strip()[:128]
    fencing = ((body.fencing if body else "") or "").strip()[:128]
    async with store.lock_for(run_id):
        run = store.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="UNKNOWN_RUN")
        locked = str(run.get("fencing") or "")
        if locked and fencing != locked:
            raise HTTPException(
                status_code=409,
                detail="FENCING_REJECTED:提交 token 已过期；旧持有者不得中断现持有者的操作。",
            )
        op = (run.get("operations") or {}).get(operation_id)
        if op is None:
            return {"operation_id": operation_id, "status": "unknown",
                    "deduped": True,
                    "note": "控制服务无此操作记录（不重放）。"}
        if op.get("status") in TERMINAL_OP:
            return {**_public_operation(run_id, op), "deduped": True}
        if not op.get("session"):
            raise HTTPException(
                status_code=409,
                detail="OPERATION_NOT_INTERRUPTIBLE:一次性操作无会话级中断语义；"
                "请走 run 级取消（先停操作再回收实例）。",
            )
        adapter = store.adapters.get(run_id)
        if adapter is None:
            raise HTTPException(status_code=409, detail="RUN_UNKNOWN_STATE")
        result = await _interrupt_session_op(run, op, adapter)
        return {**_public_operation(run_id, op), **result, "deduped": False}


@app.put("/sandboxes/{run_id}/fencing")
async def rotate_fencing(run_id: str, body: FencingRotate,
                         _: None = Depends(require_token)):
    """F2：轮换 run 的执行 fencing（恢复认领后新持有者接管）。

    终态 run 拒绝轮换（RUN_TERMINAL）；未知 run 404。旧 token 的新提交
    自此被拒（FENCING_REJECTED），调用方须先对账再轮换。
    """
    run_id = _check_run_id(run_id)
    fencing = (body.fencing or "").strip()[:128]
    if not fencing:
        raise HTTPException(status_code=422, detail="INVALID_FENCING")
    async with store.lock_for(run_id):
        run = store.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="UNKNOWN_RUN")
        if run.get("status") in TERMINAL_RUN:
            raise HTTPException(
                status_code=409,
                detail=f"RUN_TERMINAL:{run.get('status')}：终态 run 不再轮换 fencing",
            )
        run["fencing"] = fencing
        run["updated_at"] = _now()
        store.save_snapshot()
        return {"run_id": run_id, "fencing": fencing}


@app.post("/sandboxes/{run_id}/cancel")
async def cancel_run(run_id: str, _: None = Depends(require_token)):
    """先取消运行中操作，再回收实例；终态幂等；终态 run 直接返回现态。"""
    run_id = _check_run_id(run_id)
    async with store.lock_for(run_id):
        run = store.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="UNKNOWN_RUN")
        if run.get("status") in TERMINAL_RUN:
            return {**_public_run(run), "deduped": True}
        # 取消后台任务（操作记录置 cancelled，不删历史）。
        for op_id, task in list((run.get("tasks") or {}).items()):
            if not task.done():
                task.cancel()
            op = (run.get("operations") or {}).get(op_id)
            if op is not None and op.get("status") == "running":
                op.update({"status": "cancelled", "finished_at": _now(),
                           "output_tail": str(op.get("output_tail") or ""),
                           "output_truncated": bool(op.get("output_truncated"))})
        run["tasks"] = {}
        run["active_operation_id"] = ""
        adapter = store.adapters.pop(run_id, None)
        if adapter is not None:
            # kill-first：容器内服务可能正被长执行占住，优雅 stop 会排队挂起；
            # 先 daemon 面强制回收，再 best-effort 优雅收尾（20s 上限）。
            await adapter.kill()
            try:
                await asyncio.wait_for(adapter.stop(), timeout=20.0)
            except asyncio.TimeoutError:
                logger.warning("run %s graceful stop timed out after kill", run_id)
        run.update({"status": "cancelled", "updated_at": _now(),
                    "note": "用户取消：已停止运行中操作并回收实例"})
        store.save_snapshot()
        return {**_public_run(run), "deduped": False}


@app.put("/sandboxes/{run_id}/files/{path:path}")
async def upload_file(run_id: str, path: str, request: Request,
                      _: None = Depends(require_token)):
    """受限大小文件上传（工作区限定，服务端校验）。"""
    run_id = _check_run_id(run_id)
    safe_path = _check_path("/" + unquote(path).lstrip("/"))
    body = await request.body()
    if len(body) > FILE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="FILE_TOO_LARGE")
    run = store.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="UNKNOWN_RUN")
    if run.get("status") in TERMINAL_RUN:
        raise HTTPException(status_code=409, detail="RUN_TERMINAL")
    adapter = store.adapters.get(run_id)
    if adapter is None:
        raise HTTPException(status_code=409, detail="RUN_UNKNOWN_STATE")
    await _assert_no_symlink_escape(adapter, safe_path)
    try:
        await adapter.upload_bytes(safe_path, bytes(body))
    except DockerBackendUnavailableError as error:
        raise HTTPException(status_code=502, detail=f"{error.code}:{error}") from error
    return {"path": safe_path, "size_bytes": len(body)}


@app.get("/sandboxes/{run_id}/files/{path:path}")
async def download_file(run_id: str, path: str, _: None = Depends(require_token)):
    """下载（缺失 404 file_not_found；超限如实报错，不截断冒充完整）。"""
    run_id = _check_run_id(run_id)
    safe_path = _check_path("/" + unquote(path).lstrip("/"))
    run = store.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="UNKNOWN_RUN")
    adapter = store.adapters.get(run_id)
    if adapter is None:
        raise HTTPException(status_code=409, detail="RUN_UNKNOWN_STATE")
    await _assert_no_symlink_escape(adapter, safe_path)
    try:
        content = await adapter.read_bytes(safe_path, max_bytes=FILE_MAX_BYTES)
    except DockerBackendUnavailableError as error:
        if "missing" in str(error).lower() or "not_found" in str(error).lower():
            raise HTTPException(status_code=404, detail="file_not_found") from error
        raise HTTPException(status_code=502, detail=f"{error.code}:{error}") from error
    if len(content) > FILE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    return Response(content=content, media_type="application/octet-stream",
                    headers={"X-File-Path": safe_path})
