"""NX-E1 run 注册表：owner/session/turn/run/job 关联与恢复查询。

数据域：``nexus_checkpoints.nexus_runs``（Nexus 域，可移植 DDL——恢复语义
必须本地可测，见附件服务注释）。一行 = 一次"批准→执行"（run_id 即票据
approval_id，一批准一运行，天然幂等键）。

NX-LB1 扩展：title（用户命名，可空）/run_number（会话内稳定序号）/
version（元数据乐观锁）/parent_run_id/proposal_id+proposal_version/
config_snapshot（冻结配置 JSON）/preset_display_name/paper_title
（记录时冻结的展示投影）。

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

迁移说明（NX-LB1，回退见验收记录）：
- 新库：CREATE TABLE IF NOT EXISTS 已含全部列；
- 旧库：``migrate_nexus_runs`` 检查缺失列后逐列 ADD（SQLite 用 PRAGMA，
  PG 用 information_schema，均可重入），再为 run_number=0 的旧行按
  (user,session,created_at) 回填序号，并建 counters 表播种；
- 回退：旧代码忽略新增列（SELECT 显式列名），直接部署旧版即可；
  如需清退字段可手动 DROP COLUMN（PG）/重建表（SQLite），_coords见验收记录。
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

_SCHEMA = "nexus_checkpoints"
_TABLE = f"{_SCHEMA}.nexus_runs"
_COUNTERS_TABLE = f"{_SCHEMA}.nexus_run_counters"

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
    updated_at REAL NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    run_number INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    parent_run_id TEXT NOT NULL DEFAULT '',
    proposal_id TEXT NOT NULL DEFAULT '',
    proposal_version INTEGER NOT NULL DEFAULT 0,
    config_snapshot TEXT NOT NULL DEFAULT '{{}}',
    preset_display_name TEXT NOT NULL DEFAULT '',
    paper_title TEXT NOT NULL DEFAULT ''
)
"""

_COUNTERS_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    last_number INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, session_id)
)
"""

# NX-LB1 新增列（migrate_nexus_runs 按名补列；与 _TABLE_DDL 保持同构）。
_LB1_COLUMNS: tuple[tuple[str, str], ...] = (
    ("title", "TEXT NOT NULL DEFAULT ''"),
    ("run_number", "INTEGER NOT NULL DEFAULT 0"),
    ("version", "INTEGER NOT NULL DEFAULT 1"),
    ("parent_run_id", "TEXT NOT NULL DEFAULT ''"),
    ("proposal_id", "TEXT NOT NULL DEFAULT ''"),
    ("proposal_version", "INTEGER NOT NULL DEFAULT 0"),
    ("config_snapshot", "TEXT NOT NULL DEFAULT '{}'"),
    ("preset_display_name", "TEXT NOT NULL DEFAULT ''"),
    ("paper_title", "TEXT NOT NULL DEFAULT ''"),
)

TERMINAL_RUN_STATUSES = ("succeeded", "failed", "rejected")

_table_ready = False


def _is_sqlite(session: Session) -> bool:
    return session.connection().dialect.name == "sqlite"


def _table(session: Session) -> str:
    return "nexus_runs" if _is_sqlite(session) else _TABLE


def _counters_table(session: Session) -> str:
    return "nexus_run_counters" if _is_sqlite(session) else _COUNTERS_TABLE


def ensure_table(session: Session) -> None:
    """建表（新库全列）+ 触发一次显式迁移（旧库补列/回填/播种，可重入）。"""
    global _table_ready
    if _table_ready:
        return
    ensure_table_schema_only(session)
    _table_ready = True
    migrate_nexus_runs(session)


def _now() -> float:
    return time.time()


_COLUMNS = ("run_id, user_id, session_id, tool, preset_id, plan_hash,"
            " approval_id, job_id, status, detail, created_at, updated_at,"
            " title, run_number, version, parent_run_id, proposal_id,"
            " proposal_version, config_snapshot, preset_display_name, paper_title")


def _existing_columns(session: Session, table: str) -> set[str]:
    """已存在的列名（SQLite 用 PRAGMA，PG 用 information_schema）。"""
    bind = session.connection()
    if bind.dialect.name == "sqlite":
        rows = bind.execute(text(f"PRAGMA table_info({table})")).all()
        return {str(r[1]) for r in rows}
    short = table.split(".")[-1]
    rows = bind.execute(
        text("SELECT column_name FROM information_schema.columns "
             "WHERE table_schema=:schema AND table_name=:name"),
        {"schema": _SCHEMA, "name": short},
    ).all()
    return {str(r[0]) for r in rows}


def migrate_nexus_runs(session: Session) -> dict[str, Any]:
    """NX-LB1 显式迁移（可重入）：补列 → 旧行回填序号 → counters 播种。

    返回 {"added_columns": [...], "backfilled": n, "counters_seeded": m}。
    回退：旧代码 SELECT 显式列名，忽略新增列（见模块文档）。
    """
    ensure_table_schema_only(session)
    table = _table(session)
    existing = _existing_columns(session, table)
    added: list[str] = []
    for name, ddl in _LB1_COLUMNS:
        if name not in existing:
            session.connection().execute(
                text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            added.append(name)
    session.commit()
    # 旧行（run_number=0）按 (user, session, created_at) 回填稳定序号。
    backfilled = 0
    rows = session.connection().execute(
        text(f"SELECT run_id, user_id, session_id FROM {table} "
             "WHERE run_number = 0 ORDER BY user_id, session_id, created_at, run_id")
    ).all()
    last_key: tuple[str, str] | None = None
    seq = 0
    for run_id, user_id, session_id in rows:
        key = (str(user_id), str(session_id))
        seq = seq + 1 if key == last_key else 1
        last_key = key
        session.connection().execute(
            text(f"UPDATE {table} SET run_number=:n, updated_at=:now WHERE run_id=:rid"),
            {"n": seq, "now": _now(), "rid": run_id},
        )
        backfilled += 1
    if backfilled:
        session.commit()
    # counters 播种： max(run_number)（已有计数器只升不降，不回退）。
    seeded = 0
    pairs = session.connection().execute(
        text(f"SELECT user_id, session_id, MAX(run_number) FROM {table} GROUP BY user_id, session_id")
    ).all()
    for user_id, session_id, max_n in pairs:
        cursor = session.connection().execute(
            text(f"SELECT last_number FROM {_counters_table(session)} "
                 "WHERE user_id=:u AND session_id=:s"),
            {"u": user_id, "s": session_id},
        ).first()
        if cursor is None:
            session.connection().execute(
                text(f"INSERT INTO {_counters_table(session)} (user_id, session_id, last_number)"
                     " VALUES (:u, :s, :n)"),
                {"u": user_id, "s": session_id, "n": int(max_n or 0)},
            )
            seeded += 1
        elif int(cursor[0]) < int(max_n or 0):
            session.connection().execute(
                text(f"UPDATE {_counters_table(session)} SET last_number=:n "
                     "WHERE user_id=:u AND session_id=:s"),
                {"u": user_id, "s": session_id, "n": int(max_n or 0)},
            )
            seeded += 1
    if seeded:
        session.commit()
    return {"added_columns": added, "backfilled": backfilled, "counters_seeded": seeded}


def ensure_table_schema_only(session: Session) -> None:
    """只建表不迁移（migrate 内部使用，避免递归）。"""
    bind = session.connection()
    if bind.dialect.name != "sqlite":
        bind.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
    table = "nexus_runs" if bind.dialect.name == "sqlite" else _TABLE
    counters = "nexus_run_counters" if bind.dialect.name == "sqlite" else _COUNTERS_TABLE
    bind.execute(text(_TABLE_DDL.format(table=table)))
    bind.execute(text(_COUNTERS_DDL.format(table=counters)))
    session.commit()


def _allocate_run_number(session: Session, user_id: str, session_id: str) -> int:
    """分配会话内稳定序号（counters 表原子递增；失败抛异常由调用方处理）。"""
    table = _counters_table(session)
    row = session.connection().execute(
        text(f"INSERT INTO {table} (user_id, session_id, last_number)"
             " VALUES (:u, :s, 1)"
             " ON CONFLICT (user_id, session_id) DO UPDATE"
             f" SET last_number = {table}.last_number + 1"
             " RETURNING last_number"),
        {"u": user_id, "s": session_id[:128]},
    ).first()
    if row is None:  # 极旧方言不支持 RETURNING：回退读。
        row = session.connection().execute(
            text(f"SELECT last_number FROM {table} WHERE user_id=:u AND session_id=:s"),
            {"u": user_id, "s": session_id[:128]},
        ).first()
    return int(row[0]) if row is not None else 1


def _row_to_dict(row: Any) -> dict[str, Any]:
    base = {
        "run_id": row[0], "user_id": row[1], "session_id": row[2],
        "tool": row[3], "preset_id": row[4], "plan_hash": row[5],
        "approval_id": row[6], "job_id": row[7], "status": row[8],
        "detail": row[9], "created_at": row[10], "updated_at": row[11],
        "title": row[12], "run_number": row[13], "version": row[14],
        "parent_run_id": row[15], "proposal_id": row[16],
        "proposal_version": row[17],
        "config_snapshot": json.loads(row[18] or "{}"),
        "preset_display_name": row[19], "paper_title": row[20],
    }
    base["display_title"] = display_title(base)
    return base


def display_title(run: dict[str, Any]) -> str:
    """默认显示名：用户命名优先，否则 preset 展示名 + 会话内序号。

    paper_title 单独投影作论文信息，不强制用长论文名作实验名。
    """
    title = (run.get("title") or "").strip()
    if title:
        return title
    preset = (run.get("preset_display_name") or run.get("preset_id") or "复现").strip()
    number = run.get("run_number") or 0
    return f"{preset} #{number}" if number else preset


def record_run(
    session: Session, *, run_id: str, user_id: str, session_id: str,
    tool: str = "run_reproduction", preset_id: str = "", plan_hash: str = "",
    approval_id: str = "", job_id: str = "", status: str = "submitted",
    detail: str = "", title: str = "", parent_run_id: str = "",
    proposal_id: str = "", proposal_version: int = 0,
    config_snapshot: dict[str, Any] | None = None,
    preset_display_name: str = "", paper_title: str = "",
) -> dict[str, Any] | None:
    """登记 run linkage（幂等：同 run_id 同 owner 更新 job/状态）。

    冲突行属他人时**不更新、不返回**（返回 None，调用方按 409 处理）：
    run_id 全局唯一（正常即 approval_id），跨 owner 复用即篡改信号。
    新行分配会话内稳定序号（counters 原子递增；重登同一 run_id 不重分配）。
    """
    ensure_table(session)
    now = _now()
    existing = get_owned_run(session, user_id=user_id, run_id=run_id)
    number = existing["run_number"] if existing else _allocate_run_number(
        session, user_id, session_id)
    snapshot = json.dumps(config_snapshot or {}, ensure_ascii=False)
    session.connection().execute(
        text(f"INSERT INTO {_table(session)} ({_COLUMNS}) VALUES ("
             ":rid,:uid,:sid,:tool,:preset,:phash,:apv,:job,:status,:detail,:now,:now,"
             ":title,:num,:ver,:parent,:prop,:propver,:snap,:pdisplay,:paper) "
             "ON CONFLICT (run_id) DO UPDATE SET job_id=excluded.job_id,"
             " status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at"
             f" WHERE {_table(session)}.user_id=:uid"),
        {"rid": run_id[:64], "uid": user_id, "sid": session_id[:128], "tool": tool[:64],
         "preset": preset_id[:64], "phash": plan_hash[:64], "apv": approval_id[:64],
         "job": job_id[:64], "status": status[:32], "detail": detail[:300],
         "now": now, "title": (title or "")[:120], "num": number, "ver": 1,
         "parent": (parent_run_id or "")[:64], "prop": (proposal_id or "")[:64],
         "propver": int(proposal_version or 0), "snap": snapshot,
         "pdisplay": (preset_display_name or "")[:120], "paper": (paper_title or "")[:300]},
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


def get_run_by_job(session: Session, *, user_id: str, job_id: str) -> dict[str, Any] | None:
    """按 job 反查本人的 run（报告链取提案/基线上下文用；跨用户不可见）。"""
    ensure_table(session)
    row = session.connection().execute(
        text(f"SELECT {_COLUMNS} FROM {_table(session)} WHERE job_id=:job AND user_id=:uid "
             "ORDER BY updated_at DESC LIMIT 1"),
        {"job": job_id, "uid": user_id},
    ).first()
    return _row_to_dict(row) if row is not None else None


def list_session_runs(
    session: Session, *, user_id: str, session_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    """某会话我的 runs（创建时间倒序；恢复查询入口）。"""
    page = list_session_runs_page(
        session, user_id=user_id, session_id=session_id, limit=limit)
    return page["items"]


def count_session_runs(session: Session, *, user_id: str, session_id: str) -> int:
    """会话运行计数（真实 COUNT；失败抛异常由调用方转 unknown，不返回 0 冒充）。"""
    ensure_table(session)
    row = session.connection().execute(
        text(f"SELECT COUNT(*) FROM {_table(session)} WHERE user_id=:uid AND session_id=:sid"),
        {"uid": user_id, "sid": session_id[:128]},
    ).first()
    return int(row[0]) if row is not None else 0


def list_session_runs_page(
    session: Session, *, user_id: str, session_id: str,
    limit: int = 20, cursor: str = "",
) -> dict[str, Any]:
    """NX-LB1 分页列表：cursor=`created_at:run_id`（上一页末项），返回
    {items, next_cursor, total}。排序 (created_at DESC, run_id DESC) 稳定，
    重命名/删除他行不重排（序号是行属性，不是位置）。
    """
    ensure_table(session)
    limit = max(1, min(int(limit or 20), 100))
    params: dict[str, Any] = {"uid": user_id, "sid": session_id[:128], "limit": limit + 1}
    cursor_clause = ""
    if cursor:
        try:
            created_raw, cursor_id = cursor.rsplit(":", 1)
            created_at = float(created_raw)
            cursor_clause = (" AND (created_at < :cts OR (created_at = :cts AND run_id < :cid))")
            params["cts"] = created_at
            params["cid"] = cursor_id[:64]
        except (ValueError, TypeError):
            pass
    rows = session.connection().execute(
        text(f"SELECT {_COLUMNS} FROM {_table(session)} "
             f"WHERE user_id=:uid AND session_id=:sid{cursor_clause} "
             "ORDER BY created_at DESC, run_id DESC LIMIT :limit"),
        params,
    ).all()
    items = [_row_to_dict(r) for r in rows[:limit]]
    next_cursor = ""
    if len(rows) > limit:
        last = items[-1]
        next_cursor = f"{last['created_at']}:{last['run_id']}"
    return {"items": items, "next_cursor": next_cursor, "total": count_session_runs(
        session, user_id=user_id, session_id=session_id)}


def rename_run(
    session: Session, *, user_id: str, run_id: str,
    title: str | None, expected_version: int,
) -> dict[str, Any] | None:
    """NX-LB1 重命名：title 为 None/空串恢复默认名；expected_version 乐观锁。

    返回更新后行；行不存在/非 owner 返回 None（调用方 404，不区分）；
    版本冲突抛 _VersionConflict（调用方 409）。
    只改命名类元数据：配置/状态/owner 永不经此入口变更。
    """
    ensure_table(session)
    row = get_owned_run(session, user_id=user_id, run_id=run_id)
    if row is None:
        return None
    if int(expected_version) != int(row["version"]):
        raise _VersionConflict(int(row["version"]))
    cleaned = (title or "").strip()[:120]
    session.connection().execute(
        text(f"UPDATE {_table(session)} SET title=:title, version=version+1,"
             " updated_at=:now WHERE run_id=:rid AND user_id=:uid AND version=:ver"),
        {"title": cleaned, "now": _now(), "rid": run_id, "uid": user_id,
         "ver": int(row["version"])},
    )
    session.commit()
    updated = get_owned_run(session, user_id=user_id, run_id=run_id)
    if updated is None or updated["title"] != cleaned:
        # 并发撞锁：读回不符即视为冲突。
        current = get_owned_run(session, user_id=user_id, run_id=run_id)
        raise _VersionConflict(int((current or {}).get("version", 0)))
    return updated


class _VersionConflict(Exception):
    """乐观锁冲突：携带当前版本号（调用方按 409 返回，不泄露他人数据）。"""

    def __init__(self, current_version: int) -> None:
        super().__init__(f"版本冲突，当前版本={current_version}")
        self.current_version = current_version
