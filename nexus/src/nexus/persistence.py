"""P1-C 会话持久化：PostgresSaver 装配 + 线程归属 + TTL 清理。

设计约束（见 docs/phase1/CodeNexus转型落地计划.md §6.2 与转型实施决策 §3）：
- checkpoints 进独立 schema（默认 ``nexus_checkpoints``），不混入业务表；
- 不持久化完整 LLM trace/prompt，只保留结构化 checkpoint（LangGraph 原生语义）；
- 本地 DSN 为空时回退 InMemorySaver，不在本地启动 PG；
- retention 靠自建 ``nexus_threads`` 表的 updated_at 做 TTL（checkpoint 原生
  表无时间戳列），由服务器 cron 调用 ``cleanup_inactive_threads``。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("nexus.persistence")

_SESSION_RE = re.compile(r"[^A-Za-z0-9\-_]")


def sanitize_session_id(session_id: str) -> str:
    """归一化 session_id：只保留安全字符，超长截断，为空回退 default。"""
    cleaned = _SESSION_RE.sub("", session_id or "")[:128]
    return cleaned or "default"


def sanitize_user_id(user_id: str | None) -> str | None:
    """归一化用户 id：去空格，截断 64，空串视为匿名。"""
    if user_id is None:
        return None
    cleaned = re.sub(r"\s+", "", user_id)[:64]
    return cleaned or None


def thread_for(session_id: str, user_id: str | None = None) -> str:
    """构造 LangGraph thread_id：用户命名空间隔离，不把裸 session_id 当边界。

    - 登录用户：``user-{uid}:nexus-session-{sid}``
    - 匿名/本地：``nexus-session-{sid}``（兼容 P0 行为）
    """
    sid = sanitize_session_id(session_id)
    uid = sanitize_user_id(user_id)
    if uid is None:
        return f"nexus-session-{sid}"
    return f"user-{uid}:nexus-session-{sid}"


def dsn_with_schema(dsn: str, schema: str) -> str:
    """给连接串注入 search_path，令 checkpoint 表落在独立 schema。"""
    if not dsn:
        return dsn
    if "options=" in dsn:
        return dsn
    sep = "&" if "?" in dsn else "?"
    # 空格需编码为 %20 以兼容 libpq URI 解析。
    return f"{dsn}{sep}options=-csearch_path%3D{schema}%2Cpublic"


THREADS_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};
CREATE TABLE IF NOT EXISTS {schema}.nexus_threads (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE {schema}.nexus_threads ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '';
"""


def ensure_threads_table_sync(conn_string: str, schema: str) -> None:
    """同步建表（供 lifespan/清理脚本复用，失败抛异常由调用方处理）。"""
    import psycopg

    ddl = THREADS_DDL.format(schema=schema)
    with psycopg.connect(conn_string, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)


async def ensure_threads_table_async(conn_string: str, schema: str) -> None:
    """异步建表：lifespan 内调用，不阻塞事件循环太久（单次 DDL）。"""
    import psycopg

    ddl = THREADS_DDL.format(schema=schema)
    # psycopg3 异步连接：按需导入，避免无 PG 环境 import 失败。
    from psycopg import AsyncConnection

    async with await AsyncConnection.connect(conn_string, autocommit=True) as conn:
        async with conn.cursor() as cur:
            await cur.execute(ddl)


def touch_thread_sync(
    conn_string: str,
    schema: str,
    thread_id: str,
    user_id: str | None,
    session_id: str,
    title: str | None = None,
) -> None:
    """upsert 线程活跃时间（best-effort，失败只记日志不抛）。

    ``title`` 只在首次插入时落库（会话标题 = 首条用户消息截断），后续续聊
    不覆盖——保持会话在列表中的稳定标识。
    """
    import psycopg

    try:
        with psycopg.connect(conn_string, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {schema}.nexus_threads (thread_id, user_id, session_id, title, updated_at) "
                    "VALUES (%s, %s, %s, %s, now()) "
                    "ON CONFLICT (thread_id) DO UPDATE SET updated_at = now()",
                    (thread_id, user_id or "", session_id, title or ""),
                )
    except Exception as error:  # noqa: BLE001 - 审计失败绝不阻断对话
        logger.warning("touch_thread failed: %s", error)


def list_user_threads_sync(
    conn_string: str, schema: str, user_id: str | None, limit: int = 50
) -> list[dict[str, str]]:
    """按活跃时间倒序列出用户的会话（C2 会话列表数据源）。

    返回 ``[{"session_id", "title", "updated_at"}]``；``updated_at`` 为 ISO 字符串。
    """
    import psycopg

    rows: list[dict[str, str]] = []
    with psycopg.connect(conn_string, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT session_id, title, updated_at FROM {schema}.nexus_threads "
                "WHERE user_id = %s ORDER BY updated_at DESC LIMIT %s",
                (user_id or "", max(1, min(int(limit), 200))),
            )
            for session_id, title, updated_at in cur.fetchall():
                rows.append(
                    {
                        "session_id": session_id,
                        "title": title or "",
                        "updated_at": updated_at.isoformat(),
                    }
                )
    return rows


def cleanup_inactive_threads(conn_string: str, schema: str, retention_days: int) -> dict[str, int]:
    """删除超 TTL 未活跃线程的 checkpoints + 线程行（服务器 cron 调用）。

    返回 ``{"threads": n, "checkpoints": m}``。checkpoint 明细删除经
    saver.delete_thread 逐线程执行，保证三表一致。
    """
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    with psycopg.connect(conn_string, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT thread_id FROM {schema}.nexus_threads "
                "WHERE updated_at < now() - make_interval(days => %s)",
                (retention_days,),
            )
            stale = [row[0] for row in cur.fetchall()]

    removed_checkpoints = 0
    # 逐线程删：复用 saver 的三表删除语义，避免手写 SQL 遗漏 blobs/writes。
    with PostgresSaver.from_conn_string(dsn_with_schema(conn_string, schema)) as saver:
        for thread_id in stale:
            try:
                # delete_thread 无返回值，按 1 计线程数即可。
                saver.delete_thread(thread_id)
            except Exception as error:  # noqa: BLE001
                logger.warning("delete_thread %s failed: %s", thread_id, error)
                continue
            removed_checkpoints += 1

    if stale:
        with psycopg.connect(conn_string, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {schema}.nexus_threads "
                    "WHERE updated_at < now() - make_interval(days => %s)",
                    (retention_days,),
                )
                threads = cur.rowcount if cur.rowcount >= 0 else len(stale)
    else:
        threads = 0
    return {"threads": threads, "checkpoints": removed_checkpoints}
