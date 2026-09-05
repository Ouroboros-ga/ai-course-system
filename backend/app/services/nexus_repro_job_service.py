"""Nexus 复现作业归属服务（M4-B1）。

数据域（AGENTS.md §4.1.11）：作业归属表落 Nexus 域 schema
（``nexus_checkpoints.nexus_repro_jobs``，PG-only，与 nexus_artifacts 同模式）。
作业本体（状态/日志/产物）在 Repro Worker 进程内存中，Backend 只持久化
"谁发起了哪个作业"，用于 job 查询代理的发起人鉴权（防 job id 枚举）。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session

_SCHEMA = "nexus_checkpoints"
_TABLE = f"{_SCHEMA}.nexus_repro_jobs"

_TABLE_DDL_BODY = """
(
    job_id VARCHAR(16) PRIMARY KEY,
    user_id TEXT NOT NULL,
    preset_id TEXT NOT NULL DEFAULT '',
    repo_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_table_ready = False


def ensure_table(session: Session) -> None:
    """幂等建表（进程内只执行一次；失败如实抛出由调用方处理）。"""
    global _table_ready
    if _table_ready:
        return
    bind = session.connection()
    bind.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
    bind.execute(text(f"CREATE TABLE IF NOT EXISTS {_TABLE} {_TABLE_DDL_BODY}"))
    session.commit()
    _table_ready = True


def record_job(
    session: Session, *, job_id: str, user_id: str, preset_id: str = "", repo_url: str = ""
) -> None:
    """登记作业归属（提交后立即调用；重复提交同 job_id 幂等更新）。"""
    ensure_table(session)
    session.connection().execute(
        text(
            f"INSERT INTO {_TABLE} (job_id, user_id, preset_id, repo_url) "
            "VALUES (:job_id, :user_id, :preset_id, :repo_url) "
            "ON CONFLICT (job_id) DO NOTHING"
        ),
        {"job_id": job_id, "user_id": user_id, "preset_id": preset_id, "repo_url": repo_url},
    )
    session.commit()


def get_owned_job(session: Session, *, job_id: str, user_id: str) -> dict | None:
    """按发起人取作业归属；非发起人与不存在同等返回 None（防枚举）。"""
    ensure_table(session)
    row = session.connection().execute(
        text(
            f"SELECT job_id, user_id, preset_id, repo_url FROM {_TABLE} "
            "WHERE job_id = :job_id AND user_id = :user_id"
        ),
        {"job_id": job_id, "user_id": user_id},
    ).first()
    if row is None:
        return None
    return {"job_id": row[0], "user_id": row[1], "preset_id": row[2], "repo_url": row[3]}
