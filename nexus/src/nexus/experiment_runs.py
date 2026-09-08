"""T2 自主实验 run 记录：授权（scope_hash）与实际尝试（attempt）分离。

- run_id 即 approval_id（一批准一运行，与 preset linkage 语义一致）；
- run 行持久化 scope_hash＋approval 引用；实际命令、安装版本变化只追加
  attempt 行内记录，不回写授权 hash，不消耗新批准；
- operation_id 由 run_id＋attempt_no 确定性派生，重试不重随机（任务书 §2）；
- 已核销重试（retry_start）只读 run 存储返回原 run，不查审批展示 TTL——
  审批过期不打断正在运行的任务；
- 存储：PG ``nexus_checkpoints.nexus_experiment_runs``＋内存降级（与
  approvals/proposals 同失败语义）。图状态与沙箱句柄属 T5，本模块只记
  “启动了哪次授权＋试过哪些命令”。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("nexus.experiment_runs")

_memory_runs: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.time()


class RunError(Exception):
    """run 域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


RUNS_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};
CREATE TABLE IF NOT EXISTS {schema}.nexus_experiment_runs (
    run_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    proposal_id TEXT NOT NULL DEFAULT '',
    proposal_version INTEGER NOT NULL DEFAULT 0,
    scope_hash TEXT NOT NULL DEFAULT '',
    approval_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    attempt_no INTEGER NOT NULL DEFAULT 0,
    attempts JSONB NOT NULL DEFAULT '[]',
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nexus_experiment_runs_owner
    ON {schema}.nexus_experiment_runs (owner, updated_at DESC);
"""


def _pg_settings() -> tuple[str, str] | None:
    from nexus.config import get_settings

    settings = get_settings()
    dsn = settings.postgres_dsn.strip()
    if not dsn:
        return None
    return dsn, settings.postgres_schema


def ensure_runs_table(dsn: str, schema: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(RUNS_DDL.format(schema=schema))


_RUN_SELECT = (
    "run_id, owner, session_id, proposal_id, proposal_version, scope_hash, "
    "approval_id, status, attempt_no, attempts, created_at, updated_at"
)

_RUN_KEYS = ("run_id", "owner", "session_id", "proposal_id", "proposal_version",
             "scope_hash", "approval_id", "status", "attempt_no", "attempts",
             "created_at", "updated_at")


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    attempts = row.get("attempts", [])
    if isinstance(attempts, str):
        try:
            attempts = json.loads(attempts)
        except ValueError:
            attempts = []
    return {
        "run_id": row["run_id"],
        "owner": row.get("owner", ""),
        "session_id": row.get("session_id", ""),
        "proposal_id": row.get("proposal_id", ""),
        "proposal_version": int(row.get("proposal_version", 0) or 0),
        "scope_hash": row.get("scope_hash", "") or "",
        "approval_id": row.get("approval_id", "") or "",
        "status": row.get("status", "running") or "running",
        "attempt_no": int(row.get("attempt_no", 0) or 0),
        "attempts": attempts if isinstance(attempts, list) else [],
        "created_at": row.get("created_at", 0),
        "updated_at": row.get("updated_at", 0),
    }


def _row_from_pg(found: Any) -> dict[str, Any]:
    row = dict(zip(_RUN_KEYS, found))
    return _row_to_dict(row)


def _insert_row(row: dict[str, Any]) -> None:
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            ensure_runs_table(dsn, schema)
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {schema}.nexus_experiment_runs "
                        "(run_id, owner, session_id, proposal_id, proposal_version, "
                        "scope_hash, approval_id, status, attempt_no, attempts, "
                        "created_at, updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (run_id) DO NOTHING",
                        (
                            row["run_id"], row["owner"], row["session_id"],
                            row["proposal_id"], row["proposal_version"],
                            row["scope_hash"], row["approval_id"], row["status"],
                            row["attempt_no"],
                            json.dumps(row["attempts"], ensure_ascii=False),
                            row["created_at"], row["updated_at"],
                        ),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("experiment run pg insert failed, memory fallback: %s", error)
    _memory_runs[row["run_id"]] = dict(row)


def _update_row(row: dict[str, Any]) -> None:
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {schema}.nexus_experiment_runs SET status=%s, "
                        f"attempt_no=%s, attempts=%s, updated_at=%s "
                        f"WHERE run_id=%s",
                        (
                            row["status"], row["attempt_no"],
                            json.dumps(row["attempts"], ensure_ascii=False),
                            row["updated_at"], row["run_id"],
                        ),
                    )
            return
        except Exception as error:  # noqa: BLE001
            logger.warning("experiment run pg update failed: %s", error)
    if row["run_id"] in _memory_runs:
        _memory_runs[row["run_id"]] = dict(row)


def get_run(run_id: str) -> dict[str, Any] | None:
    """读 run（归属由调用方校验；此处不做 user 过滤）。"""
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT {_RUN_SELECT} "
                        f"FROM {schema}.nexus_experiment_runs WHERE run_id = %s",
                        (run_id,),
                    )
                    found = cur.fetchone()
            if found is not None:
                return _row_from_pg(found)
        except Exception as error:  # noqa: BLE001
            logger.warning("experiment run pg read failed: %s", error)
    stored = _memory_runs.get(run_id)
    return _row_to_dict(dict(stored)) if stored is not None else None


def create_or_get_run(
    *, run_id: str, owner: str, session_id: str, proposal_id: str,
    proposal_version: int, scope_hash: str, approval_id: str,
) -> dict[str, Any]:
    """核销后登记 run（幂等：同 run_id 重复返回原行，不建新运行）。

    跨用户/跨会话复用同 run_id → RunError（RUN_FORBIDDEN/RUN_SESSION_MISMATCH），
    不泄露归属以外的任何信息。
    """
    existing = get_run(run_id)
    if existing is not None:
        if (owner or "") != existing["owner"]:
            raise RunError("RUN_FORBIDDEN", "无权操作他人的运行")
        if (session_id or "") != existing["session_id"]:
            raise RunError("RUN_SESSION_MISMATCH", "运行与当前会话不一致")
        return existing
    now = _now()
    row = {
        "run_id": run_id,
        "owner": owner or "",
        "session_id": session_id or "",
        "proposal_id": proposal_id,
        "proposal_version": int(proposal_version or 0),
        "scope_hash": scope_hash,
        "approval_id": approval_id,
        "status": "running",
        "attempt_no": 0,
        "attempts": [],
        "created_at": now,
        "updated_at": now,
    }
    _insert_row(row)
    # 并发竞争：对方先落盘则读回对方行（同归属已在上方校验）。
    stored = get_run(run_id)
    return stored if stored is not None else _row_to_dict(row)


def record_attempt(
    run_id: str, *, actual_command: str,
    config_changes: dict[str, Any] | None = None,
    exit_code: int | None = None, log_ref: str = "",
) -> dict[str, Any]:
    """追加一次实际尝试（安装/修依赖/重跑命令皆属 attempt，不消耗新批准）。

    operation_id 确定性派生（run-op-NNNN），同 run 重放同号，不重随机。
    终态 run（cancelled/completed/failed）拒绝追加（RUN_TERMINAL）。
    返回追加的 attempt 记录。
    """
    run = get_run(run_id)
    if run is None:
        raise RunError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if run["status"] not in ("running",):
        raise RunError("RUN_TERMINAL", f"运行已终态（{run['status']}），不可追加尝试")
    command = (actual_command or "").strip()
    if not command:
        raise RunError("ATTEMPT_COMMAND_EMPTY", "实际命令不能为空")
    attempt_no = int(run["attempt_no"]) + 1
    attempt = {
        "operation_id": f"{run_id}-op-{attempt_no:04d}",
        "attempt_no": attempt_no,
        "actual_command": command[:2000],
        "config_changes": dict(config_changes or {}),
        "started_at": _now(),
        "finished_at": None,
        "exit_code": exit_code,
        "log_ref": (log_ref or "")[:500],
        "artifact_refs": [],
    }
    attempts = list(run["attempts"]) + [attempt]
    updated = dict(run)
    updated.update({"attempt_no": attempt_no, "attempts": attempts,
                    "updated_at": _now()})
    _update_row(updated)
    _memory_runs[run_id] = dict(updated)
    return attempt


async def retry_start(run_id: str, *, user_id: str, session_id: str) -> dict[str, Any]:
    """已核销重试：返回原 run（不建新运行、不重核销、不查审批 TTL）。

    语义：审批展示过期≠运行终止；恢复/重试走 run 存储唯一真相源。
    """
    run = get_run(run_id)
    if run is None:
        raise RunError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if (user_id or "") != run["owner"]:
        raise RunError("RUN_FORBIDDEN", "无权操作他人的运行")
    if (session_id or "") != run["session_id"]:
        raise RunError("RUN_SESSION_MISMATCH", "运行与当前会话不一致")
    return run


def clear_memory_store() -> None:
    """测试隔离：清空内存 run（PG 行不受影响，测试不用真实 PG）。"""
    _memory_runs.clear()
