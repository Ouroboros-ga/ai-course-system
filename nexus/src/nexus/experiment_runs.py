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
    graph_thread_id TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    clean_status TEXT NOT NULL DEFAULT '',
    clean_note TEXT NOT NULL DEFAULT '',
    clean_checked_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    clean_rule TEXT NOT NULL DEFAULT '',
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
    """幂等建表＋T4 列补齐（老表逐列 ADD COLUMN IF NOT EXISTS，可重入）。"""
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(RUNS_DDL.format(schema=schema))
            for column, ddl in (
                ("graph_thread_id", "TEXT NOT NULL DEFAULT ''"),
                ("cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
                ("detail", "TEXT NOT NULL DEFAULT ''"),
                # SR6 干净B结论列（老表补齐，可重入；旧行读作未验证）。
                ("clean_status", "TEXT NOT NULL DEFAULT ''"),
                ("clean_note", "TEXT NOT NULL DEFAULT ''"),
                ("clean_checked_at", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
                ("clean_rule", "TEXT NOT NULL DEFAULT ''"),
            ):
                cur.execute(
                    f"ALTER TABLE {schema}.nexus_experiment_runs "
                    f"ADD COLUMN IF NOT EXISTS {column} {ddl}"
                )


_RUN_SELECT = (
    "run_id, owner, session_id, proposal_id, proposal_version, scope_hash, "
    "approval_id, status, attempt_no, attempts, graph_thread_id, "
    "cancel_requested, detail, clean_status, clean_note, clean_checked_at, "
    "clean_rule, created_at, updated_at"
)

_RUN_KEYS = ("run_id", "owner", "session_id", "proposal_id", "proposal_version",
             "scope_hash", "approval_id", "status", "attempt_no", "attempts",
             "graph_thread_id", "cancel_requested", "detail",
             "clean_status", "clean_note", "clean_checked_at", "clean_rule",
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
        "graph_thread_id": row.get("graph_thread_id", "") or "",
        "cancel_requested": bool(int(row.get("cancel_requested", 0) or 0)),
        "detail": row.get("detail", "") or "",
        # SR6 干净B结论（空=未验证；passed/failed 由重放落盘）。
        "clean_status": row.get("clean_status", "") or "",
        "clean_note": row.get("clean_note", "") or "",
        "clean_checked_at": row.get("clean_checked_at", 0) or 0,
        "clean_rule": row.get("clean_rule", "") or "",
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
                        "graph_thread_id, cancel_requested, detail, "
                        "clean_status, clean_note, clean_checked_at, "
                        "clean_rule, created_at, updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (run_id) DO NOTHING",
                        (
                            row["run_id"], row["owner"], row["session_id"],
                            row["proposal_id"], row["proposal_version"],
                            row["scope_hash"], row["approval_id"], row["status"],
                            row["attempt_no"],
                            json.dumps(row["attempts"], ensure_ascii=False),
                            row.get("graph_thread_id", ""),
                            1 if row.get("cancel_requested") else 0,
                            row.get("detail", ""),
                            row.get("clean_status", ""),
                            row.get("clean_note", ""),
                            row.get("clean_checked_at", 0) or 0,
                            row.get("clean_rule", ""),
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
                        f"attempt_no=%s, attempts=%s, graph_thread_id=%s, "
                        f"cancel_requested=%s, detail=%s, updated_at=%s, "
                        f"clean_status=%s, clean_note=%s, clean_checked_at=%s, "
                        f"clean_rule=%s "
                        f"WHERE run_id=%s",
                        (
                            row["status"], row["attempt_no"],
                            json.dumps(row["attempts"], ensure_ascii=False),
                            row.get("graph_thread_id", ""),
                            1 if row.get("cancel_requested") else 0,
                            row.get("detail", ""),
                            row["updated_at"],
                            row.get("clean_status", ""),
                            row.get("clean_note", ""),
                            row.get("clean_checked_at", 0) or 0,
                            row.get("clean_rule", ""),
                            row["run_id"],
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
        return {**existing, "deduped": True}
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
        "graph_thread_id": "",
        "cancel_requested": False,
        "detail": "",
        "clean_status": "",
        "clean_note": "",
        "clean_checked_at": 0,
        "clean_rule": "",
        "created_at": now,
        "updated_at": now,
    }
    _insert_row(row)
    # 并发竞争：对方先落盘则读回对方行（同归属已在上方校验）。
    stored = get_run(run_id)
    result = _row_to_dict(dict(stored) if stored is not None else row)
    result["deduped"] = existing is not None
    return result


def record_attempt(
    run_id: str, *, actual_command: str,
    config_changes: dict[str, Any] | None = None,
    exit_code: int | None = None, log_ref: str = "",
    operation_id: str = "",
) -> dict[str, Any]:
    """追加一次实际尝试（安装/修依赖/重跑命令皆属 attempt，不消耗新批准）。

    operation_id 默认确定性派生（run-op-NNNN），同 run 重放同号，不重随机；
    控制服务返回的真实 operation_id（如 run-id-op-NNNN）可显式传入，用于
    重启后按 id 续查对账（T5 恢复语义）。
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
        "operation_id": (operation_id or "").strip()[:128] or f"{run_id}-op-{attempt_no:04d}",
        "attempt_no": attempt_no,
        "actual_command": command[:2000],
        "config_changes": dict(config_changes or {}),
        "started_at": _now(),
        # 生产语义：attempt 在 operation 完成后才追加，故完成时间即落盘时间；
        # exit_code 为空（合成/在途行）时如实留空，时长显示为空。
        "finished_at": _now() if exit_code is not None else None,
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


def set_status(run_id: str, status: str, detail: str = "") -> dict[str, Any] | None:
    """设置 run 终态/状态（succeeded/failed/cancelled/running），附原因。"""
    run = get_run(run_id)
    if run is None:
        return None
    updated = dict(run)
    updated.update({"status": status, "detail": (detail or "")[:2000],
                    "updated_at": _now()})
    _update_row(updated)
    _memory_runs[run_id] = dict(updated)
    return _row_to_dict(updated)


def set_clean_verdict(run_id: str, status: str, note: str = "",
                      rule: str = "") -> dict[str, Any] | None:
    """SR6 干净B结论落盘（passed/failed/verifying/""；调用方已做重放比对，
    此处只持久化；rule 为结论规则版本，口径变化时旧结论视为过期）。

    结论一旦落盘即稳定（attempt 终态后不可追加）；重复落盘覆盖并刷新时间。
    """
    run = get_run(run_id)
    if run is None:
        return None
    updated = dict(run)
    updated.update({"clean_status": (status or "")[:16],
                    "clean_note": (note or "")[:2000],
                    "clean_checked_at": _now(),
                    "clean_rule": (rule or "")[:32],
                    "updated_at": _now()})
    _update_row(updated)
    _memory_runs[run_id] = dict(updated)
    return _row_to_dict(updated)


def reset_verifying_to_idle() -> int:
    """复位残留 verifying（lifespan 启动时调用）。

    后台重放任务随进程消失；残留 verifying 无执行者，复位为空以便重试。
    返回复位行数（内存路径全表扫描；PG 单条 UPDATE）。
    """
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            ensure_runs_table(dsn, schema)
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {schema}.nexus_experiment_runs "
                        f"SET clean_status='', clean_note='服务重启，干净验证未完成，可重试。', "
                        f"clean_checked_at=%s, updated_at=%s "
                        f"WHERE clean_status='verifying'",
                        (_now(), _now()),
                    )
                    return int(cur.rowcount or 0)
        except Exception as error:  # noqa: BLE001
            logger.warning("reset verifying pg failed: %s", error)
    count = 0
    for run_id, row in list(_memory_runs.items()):
        if row.get("clean_status") == "verifying":
            updated = dict(row)
            updated.update({"clean_status": "",
                            "clean_note": "服务重启，干净验证未完成，可重试。",
                            "clean_checked_at": _now(), "updated_at": _now()})
            _memory_runs[run_id] = updated
            count += 1
    return count


def set_graph_thread(run_id: str, thread_id: str) -> None:
    """登记图执行线程（恢复/对账用；best-effort）。"""
    run = get_run(run_id)
    if run is None:
        return
    updated = dict(run)
    updated.update({"graph_thread_id": (thread_id or "")[:128],
                    "updated_at": _now()})
    _update_row(updated)
    _memory_runs[run_id] = dict(updated)


def request_cancel(run_id: str, user_id: str) -> dict[str, Any]:
    """用户取消 run（置旗；执行者在下一个检查点诚实化为 cancelled）。

    T5 接 Console 取消链时调用；控制服务侧操作取消由 T5 完成。
    """
    run = get_run(run_id)
    if run is None:
        raise RunError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if (user_id or "") != run["owner"]:
        raise RunError("RUN_FORBIDDEN", "无权操作他人的运行")
    updated = dict(run)
    updated.update({"cancel_requested": True, "updated_at": _now()})
    _update_row(updated)
    _memory_runs[run_id] = dict(updated)
    return _row_to_dict(updated)


def is_cancel_requested(run_id: str) -> bool:
    """取消旗查询（执行者检查点用；存储不可读按未取消处理并记日志）。"""
    try:
        run = get_run(run_id)
    except Exception as error:  # noqa: BLE001
        logger.warning("cancel flag read failed: %s", error)
        return False
    return bool((run or {}).get("cancel_requested"))


def clear_memory_store() -> None:
    """测试隔离：清空内存 run（PG 行不受影响，测试不用真实 PG）。"""
    _memory_runs.clear()
