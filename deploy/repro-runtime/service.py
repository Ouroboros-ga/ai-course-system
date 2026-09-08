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

TERMINAL_RUN = ("done", "failed", "cancelled", "unknown")
TERMINAL_OP = ("succeeded", "failed", "cancelled")


def _now() -> float:
    return time.time()


def _service_token() -> str:
    return (os.environ.get("REPRO_RUNTIME_TOKEN") or "").strip()


def _task_image() -> str:
    return (os.environ.get("REPRO_TASK_IMAGE") or "python:3.12-slim").strip()


def _task_docker_args() -> list[str]:
    raw = (os.environ.get("REPRO_TASK_DOCKER_ARGS") or "").strip()
    if not raw:
        return ["--memory=2g", "--cpus=2", "--pids-limit=512"]
    try:
        parsed = json.loads(raw)
    except ValueError:
        return ["--memory=2g", "--cpus=2", "--pids-limit=512"]
    return [str(a) for a in parsed if isinstance(a, str)][:32]


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
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        raise HTTPException(status_code=422, detail="INVALID_PATH")
    segments = [seg for seg in path.split("/") if seg not in ("", ".")]
    if ".." in segments:
        raise HTTPException(status_code=422, detail="PATH_TRAVERSAL_REJECTED")
    return path


def _tail(text: str) -> tuple[str, bool]:
    if len(text) <= OUTPUT_TAIL_MAX:
        return text, False
    return text[-OUTPUT_TAIL_MAX:], True


class OperationCreate(BaseModel):
    operation_id: str = Field(min_length=1, max_length=128)
    command: str = Field(min_length=1)
    timeout_s: float | None = None


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
                    "docker_args": list(run.get("docker_args") or []),
                    "status": run.get("status", "unknown"),
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
                "docker_args": list(row.get("docker_args") or []),
                "status": "unknown",
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
        "container_name": run.get("container_name", ""),
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
async def ensure_sandbox(run_id: str, _: None = Depends(require_token)):
    """ensure（同 run 幂等；重启后未知 run 须换新 id，409 明示）。"""
    run_id = _check_run_id(run_id)
    async with store.lock_for(run_id):
        existing = store.runs.get(run_id)
        if existing is not None:
            if existing.get("status") == "unknown" and run_id not in store.adapters:
                raise HTTPException(
                    status_code=409,
                    detail="RUN_UNKNOWN_STATE:服务重启后该 run 状态未知（不重放、不复用），请换新 run_id",
                )
            return {**_public_run(existing), "deduped": True}
        adapter = SwerexDockerAdapter(
            run_id=run_id, image=_task_image(),
            docker_args=_task_docker_args())
        try:
            container_name = await adapter.start()
        except DockerBackendUnavailableError as error:
            raise HTTPException(status_code=502, detail=f"{error.code}:{error}") from error
        run = {
            "run_id": run_id,
            "sandbox_id": f"sb-{run_id}",
            "container_name": container_name,
            "image": adapter.image,
            "docker_args": list(adapter.docker_args),
            "status": "ready",
            "note": "",
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
        operations = run.setdefault("operations", {})
        if operation_id in operations:
            return {**_public_operation(run_id, operations[operation_id]),
                    "deduped": True}
        op = {
            "operation_id": operation_id,
            "command": body.command,
            "timeout_s": timeout_s,
            "status": "running",
            "exit_code": None,
            "output_tail": "",
            "output_truncated": False,
            "started_at": _now(),
            "finished_at": 0,
        }
        operations[operation_id] = op
        run["status"] = "running"
        run["active_operation_id"] = operation_id
        run["updated_at"] = _now()
        task = asyncio.create_task(_run_operation(run_id, operation_id))
        run.setdefault("tasks", {})[operation_id] = task
        store.save_snapshot()
        return {**_public_operation(run_id, op), "deduped": False}


@app.get("/sandboxes/{run_id}/operations/{operation_id}")
async def query_operation(run_id: str, operation_id: str,
                          _: None = Depends(require_token)):
    """查询结果（HTTP 超时不等同进程已停止；未知 id 诚实 unknown）。"""
    run_id = _check_run_id(run_id)
    operation_id = (operation_id or "").strip()[:128]
    run = store.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="UNKNOWN_RUN")
    op = (run.get("operations") or {}).get(operation_id)
    if op is None:
        return {"operation_id": operation_id, "status": "unknown", "exit_code": None,
                "output_tail": "", "output_truncated": False,
                "note": "控制服务无此操作记录（可能重启丢失，不重放）"}
    return _public_operation(run_id, op)


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
    try:
        content = await adapter.read_bytes(safe_path)
    except DockerBackendUnavailableError as error:
        if "missing" in str(error).lower() or "not_found" in str(error).lower():
            raise HTTPException(status_code=404, detail="file_not_found") from error
        raise HTTPException(status_code=502, detail=f"{error.code}:{error}") from error
    if len(content) > FILE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    return Response(content=content, media_type="application/octet-stream",
                    headers={"X-File-Path": safe_path})
