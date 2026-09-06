"""NX-E1 run 注册表：owner/session/turn/run/job 关联与恢复查询。

数据域：``nexus_checkpoints.nexus_runs``（Nexus 域，可移植 DDL——恢复语义
必须本地可测，见附件服务注释）。一行 = 一次"批准→执行"（run_id 即票据
approval_id，一批准一运行，天然幂等键）。

写入点（执行前归属已由审批记录承担；本表是执行后 linkage + 状态快照）：
- Runtime ``execute_approved_reproduction`` 提交 Worker 成功后，经内部端点
  登记 linkage（含 session/preset/plan_hash/job）；
- Backend 手工执行代理（/repro/execute）经同一内部端点补登记（上游已返回 job）。

恢复语义（验收）：
- 刷新/换设备：GET /nexus/runs?session_id= 列出我的 runs（含 Worker 实时
  状态合并，无响应则回落快照并标 stale），前端对未终态 job 恢复轮询，
  **绝不重新提交**；
- 跨用户：归属过滤，他人 runs 不可见（404/空列表，不区分）；
- job 缺失（Worker 重启丢内存）：实时态 unknown + honest note，不伪造终态。
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

_SCHEMA = "nexus_checkpoints"
_TABLE = f"{_SCHEMA}.nexus_runs"

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    run_id VARCHAR(64) PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL DEFAULT '',
    preset_id TEXT NOT NULL DEFAULT '',
    plan_hash TEXT NOT NULL DEFAULT '',
    approval_id TEXT NOT NULL DEFAULT '',
    job_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'submitted',
    detail TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
)
"""

TERMINAL_RUN_STATUSES = ("succeeded", "failed", "rejected")

_table_ready = False


def ensure_table(session: Session) -> None:
    global _table_ready
    if _table_ready:
        return
    bind = session.connection()
    if bind.dialect.name != "sqlite":
        bind.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
    bind.execute(text(_TABLE_DDL.format(table=_TABLE if bind.dialect.name != "sqlite" else "nexus_runs")))
    session.commit()
    _table_ready = True


def _table(session: Session) -> str:
    return _TABLE if session.connection().dialect.name != "sqlite" else "nexus_runs"


def _now() -> float:
    return time.time()


_COLUMNS = ("run_id, user_id, session_id, tool, preset_id, plan_hash,"
            " approval_id, job_id, status, detail, created_at, updated_at")


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "run_id": row[0], "user_id": row[1], "session_id": row[2],
        "tool": row[3], "preset_id": row[4], "plan_hash": row[5],
        "approval_id": row[6], "job_id": row[7], "status": row[8],
        "detail": row[9], "created_at": row[10], "updated_at": row[11],
    }


def record_run(
    session: Session, *, run_id: str, user_id: str, session_id: str,
    tool: str = "run_reproduction", preset_id: str = "", plan_hash: str = "",
    approval_id: str = "", job_id: str = "", status: str = "submitted",
    detail: str = "",
) -> dict[str, Any] | None:
    """登记 run linkage（幂等：同 run_id 同 owner 更新 job/状态）。

    冲突行属他人时**不更新、不返回**（返回 None，调用方按 409 处理）：
    run_id 全局唯一（正常即 approval_id），跨 owner 复用即篡改信号。
    """
    ensure_table(session)
    now = _now()
    session.connection().execute(
        text(f"INSERT INTO {_table(session)} ({_COLUMNS}) VALUES ("
             ":rid,:uid,:sid,:tool,:preset,:phash,:apv,:job,:status,:detail,:now,:now) "
             "ON CONFLICT (run_id) DO UPDATE SET job_id=excluded.job_id,"
             " status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at"
             f" WHERE {_table(session)}.user_id=:uid"),
        {"rid": run_id[:64], "uid": user_id, "sid": session_id[:128], "tool": tool[:64],
         "preset": preset_id[:64], "phash": plan_hash[:64], "apv": approval_id[:64],
         "job": job_id[:64], "status": status[:32], "detail": detail[:300],
         "now": now},
    )
    # SQLite 与 PG 均支持 ON CONFLICT（含 WHERE 版 DO UPDATE）。
    session.commit()
    return get_owned_run(session, user_id=user_id, run_id=run_id)


def update_run_status(
    session: Session, *, user_id: str, run_id: str, status: str, detail: str = ""
) -> dict[str, Any] | None:
    """更新 run 状态快照（owner 限定；轮询侧 best-effort 回写）。"""
    ensure_table(session)
    session.connection().execute(
        text(f"UPDATE {_table(session)} SET status=:status, detail=:detail,"
             " updated_at=:now WHERE run_id=:rid AND user_id=:uid"),
        {"status": status[:32], "detail": detail[:300], "now": _now(),
         "rid": run_id, "uid": user_id},
    )
    session.commit()
    return get_owned_run(session, user_id=user_id, run_id=run_id)


def get_owned_run(session: Session, *, user_id: str, run_id: str) -> dict[str, Any] | None:
    ensure_table(session)
    row = session.connection().execute(
        text(f"SELECT {_COLUMNS} FROM {_table(session)} WHERE run_id=:rid AND user_id=:uid"),
        {"rid": run_id, "uid": user_id},
    ).first()
    return _row_to_dict(row) if row is not None else None


def list_session_runs(
    session: Session, *, user_id: str, session_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    """某会话我的 runs（创建时间倒序；恢复查询入口）。"""
    ensure_table(session)
    rows = session.connection().execute(
        text(f"SELECT {_COLUMNS} FROM {_table(session)} "
             "WHERE user_id=:uid AND session_id=:sid "
             "ORDER BY created_at DESC LIMIT :limit"),
        {"uid": user_id, "sid": session_id[:128], "limit": max(1, min(int(limit), 100))},
    ).all()
    return [_row_to_dict(r) for r in rows]
