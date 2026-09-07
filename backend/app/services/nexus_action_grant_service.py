"""NX-LB4 受限动作授权（one-time action grant）。

取消运行是破坏性停止动作：模型识别"用户想取消"不构成授权证明。授权
只能由用户在服务端登录态下显式签发（浮窗确认/取消按钮 → POST
``/nexus/runs/{run_id}/cancel-grant``），绑定为
``(user_id, run_id, action)``＋会话＋有效期，**一次性核销**。

Runtime 侧取消工具经内部端点消费授权；无有效授权时返回
``CANCEL_CONFIRMATION_REQUIRED``，由模型引导用户去确认，模型参数无法
伪造授权（grant_id 不进模型上下文，核销只认 user/run/action 三元组）。

存储：``nexus_checkpoints.nexus_action_grants``（Nexus 域；与 runs 同
建表/迁移模式，SQLite 仅本地测试）。授权是短生命周期凭证：过期与已
核销行保留作审计，不自动清理。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

_SCHEMA = "nexus_checkpoints"
_TABLE = f"{_SCHEMA}.nexus_action_grants"

_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    grant_id VARCHAR(32) PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    run_id VARCHAR(64) NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL DEFAULT 0,
    consumed_at REAL
)
"""

DEFAULT_TTL_S = 300
_table_ready = False


def _is_sqlite(session: Session) -> bool:
    return session.connection().dialect.name == "sqlite"


def _table(session: Session) -> str:
    return "nexus_action_grants" if _is_sqlite(session) else _TABLE


def ensure_table(session: Session) -> None:
    global _table_ready
    if _table_ready:
        return
    bind = session.connection()
    if bind.dialect.name != "sqlite":
        bind.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
    bind.execute(text(_DDL.format(table=_table(session))))
    session.commit()
    _table_ready = True


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "grant_id": row[0], "session_id": row[1], "run_id": row[2],
        "action": row[3], "created_at": row[4], "expires_at": row[5],
        "consumed": row[6] is not None,
    }


_COLUMNS = ("grant_id, session_id, run_id, action, created_at, expires_at, consumed_at")


def create_grant(
    session: Session, *, user_id: str, session_id: str, run_id: str,
    action: str = "cancel_run", ttl_s: int = DEFAULT_TTL_S,
) -> dict[str, Any]:
    """签发一次性授权（同一 (user, run, action) 可重复签发，各自单次有效）。"""
    ensure_table(session)
    now = time.time()
    grant_id = f"gr_{uuid.uuid4().hex[:12]}"
    session.connection().execute(
        text(f"INSERT INTO {_table(session)} "
             "(grant_id, user_id, session_id, run_id, action, created_at, expires_at) "
             "VALUES (:gid,:uid,:sid,:rid,:action,:now,:exp)"),
        {"gid": grant_id, "uid": user_id, "sid": (session_id or "")[:128],
         "rid": run_id[:64], "action": action[:32], "now": now,
         "exp": now + max(30, int(ttl_s))},
    )
    session.commit()
    row = session.connection().execute(
        text(f"SELECT {_COLUMNS} FROM {_table(session)} WHERE grant_id=:gid"),
        {"gid": grant_id},
    ).first()
    return _row_to_dict(row)


def consume_grant(
    session: Session, *, user_id: str, run_id: str, action: str = "cancel_run",
) -> dict[str, Any] | None:
    """核销本人该 run 最新一条未消费且未过期的授权；无有效授权返回 None。

    核销用条件 UPDATE（consumed_at IS NULL）保证并发下只有一个调用方
    拿到授权；过期授权不核销（保留原状，便于审计差异）。
    """
    ensure_table(session)
    now = time.time()
    row = session.connection().execute(
        text(f"SELECT grant_id FROM {_table(session)} "
             "WHERE user_id=:uid AND run_id=:rid AND action=:action "
             "AND consumed_at IS NULL AND expires_at > :now "
             "ORDER BY created_at DESC LIMIT 1"),
        {"uid": user_id, "rid": run_id[:64], "action": action[:32], "now": now},
    ).first()
    if row is None:
        return None
    grant_id = str(row[0])
    result = session.connection().execute(
        text(f"UPDATE {_table(session)} SET consumed_at=:now "
             "WHERE grant_id=:gid AND consumed_at IS NULL"),
        {"now": now, "gid": grant_id},
    )
    session.commit()
    if result.rowcount != 1:
        return None
    updated = session.connection().execute(
        text(f"SELECT {_COLUMNS} FROM {_table(session)} WHERE grant_id=:gid"),
        {"gid": grant_id},
    ).first()
    return _row_to_dict(updated) if updated is not None else None
