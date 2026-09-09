"""Research Ask / Auto 执行模式（任务书 T2＋前端规格 §2.1）。

- 只在 Research 展示；Ask 与 Auto 同样自主研究/规划/检索/多格式输出，
  唯一差别是实验代码沙箱的执行权限；
- 新字段 research_execution_mode=ask|auto：Research 缺失/null 归 Ask，
  未知值拒绝（InvalidExecutionMode，调用方转 400
  INVALID_RESEARCH_EXECUTION_MODE）；General 不传，兼容传入合法值也不
  产生实验授权，未知值仍拒绝——模式不能经模型工具参数修改，只走请求
  上下文；
- 用户明确选择保存到服务端会话偏好（(user, session) 键控），客户端刷新
  后恢复并显式发送；未传字段不从旧 Auto 偏好偷偷升级——恢复只发生在
  “本次未传＋服务端有偏好”时，且新会话无记录默认 Ask；
- 启动新 run 只认本次 effective 值（Research+Auto+本人批准）；已启动 run
  按启动时冻结的授权继续，不因对话切 Ask 暗中取消。

存储：PG ``nexus_checkpoints.nexus_session_prefs``＋内存降级（与审批域
同失败语义；偏好丢失只回落默认 Ask，不阻断对话）。
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("nexus.execution_mode")

ASK = "ask"
AUTO = "auto"

_memory_prefs: dict[str, dict[str, Any]] = {}


class InvalidExecutionMode(ValueError):
    """未知执行模式词形：调用方必须转 HTTP 400 INVALID_RESEARCH_EXECUTION_MODE。"""

    def __init__(self, raw: Any) -> None:
        super().__init__(f"INVALID_RESEARCH_EXECUTION_MODE:{raw!r}")
        self.raw = raw


def normalize_execution_mode(raw: Any | None, mode: str) -> str:
    """归一本次请求的执行模式（不读偏好）。

    - None/缺字段：Research→ask（安全默认）；General→ask（占位，无授权含义）；
    - "ask"/"auto"（去空白/小写）：原样采用（General 兼容传入合法值）；
    - 其他（含空串/未知词/非 str）：InvalidExecutionMode（两模式一致拒绝）。
    """
    if raw is None:
        return ASK
    if not isinstance(raw, str):
        raise InvalidExecutionMode(raw)
    cleaned = raw.strip().lower()
    if cleaned in (ASK, AUTO):
        return cleaned
    raise InvalidExecutionMode(raw)


def _pref_key(user_id: str, session_id: str) -> str:
    return f"{user_id or ''}\u0000{session_id or ''}"


def _pg_settings() -> tuple[str, str] | None:
    from nexus.config import get_settings

    settings = get_settings()
    dsn = settings.postgres_dsn.strip()
    if not dsn:
        return None
    return dsn, settings.postgres_schema


def save_preference(user_id: str, session_id: str, mode_value: str) -> None:
    """保存用户明确选择的执行模式（best-effort：失败只记日志）。"""
    if mode_value not in (ASK, AUTO):
        return
    _memory_prefs[_pref_key(user_id, session_id)] = {
        "mode": mode_value, "updated_at": time.time()}
    pg = _pg_settings()
    if pg is None:
        return
    dsn, schema = pg
    try:
        import psycopg

        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {schema}.nexus_session_prefs "
                    f"(user_id, session_id, research_execution_mode, updated_at) "
                    f"VALUES (%s,%s,%s,%s) "
                    f"ON CONFLICT (user_id, session_id) DO UPDATE SET "
                    f"research_execution_mode = EXCLUDED.research_execution_mode, "
                    f"updated_at = EXCLUDED.updated_at",
                    (user_id or "", session_id or "", mode_value, time.time()),
                )
    except Exception as error:  # noqa: BLE001
        logger.warning("execution mode pref pg save failed: %s", error)


def get_preference(user_id: str, session_id: str) -> str | None:
    """读服务端会话偏好（无记录→None，调用方回落默认 Ask）。"""
    pg = _pg_settings()
    if pg is not None:
        dsn, schema = pg
        try:
            import psycopg

            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT research_execution_mode "
                        f"FROM {schema}.nexus_session_prefs "
                        f"WHERE user_id = %s AND session_id = %s",
                        (user_id or "", session_id or ""),
                    )
                    found = cur.fetchone()
            if found is not None and (found[0] or "") in (ASK, AUTO):
                return found[0]
        except Exception as error:  # noqa: BLE001
            logger.warning("execution mode pref pg read failed: %s", error)
    stored = _memory_prefs.get(_pref_key(user_id, session_id))
    if stored is not None and stored.get("mode") in (ASK, AUTO):
        return stored["mode"]
    return None


def resolve_effective(
    raw: Any | None, mode: str, *, user_id: str = "", session_id: str = "",
) -> tuple[str, bool]:
    """解析本次 effective 执行模式，返回 (effective, explicit)。

    - 本次显式传合法值 → 采用并（有身份时）保存偏好；
    - 本次未传 → 默认 Ask（不从旧 Auto 偏好偷偷升级；刷新恢复走偏好
      查询端点由客户端显式发送）；
    - 本次传未知值 → 抛 InvalidExecutionMode（不读偏好兜底）。
    """
    if raw is None:
        return ASK, False
    # 本次显式传值：严格校验（未知拒绝），合法则保存偏好。
    normalized = normalize_execution_mode(raw, mode)
    if user_id:
        save_preference(user_id, session_id, normalized)
    return normalized, True


def can_execute(mode: str, execution_mode: str | None) -> bool:
    """执行授权判定：仅 Research+Auto 可启动新实验（T2 启动门）。

    General 传入 auto 也不产生授权；Ask/Auto 拼写外的值一律不可执行。
    """
    return mode == "research" and (execution_mode or ASK) == AUTO


def clear_memory_store() -> None:
    """测试隔离：清空内存偏好（PG 行不受影响，测试不用真实 PG）。"""
    _memory_prefs.clear()
