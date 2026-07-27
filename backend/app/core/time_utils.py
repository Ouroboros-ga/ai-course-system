"""统一 UTC 时间语义工具。

设计原则（P1-10 更新）：
- 约束："All datetime fields must use timezone-aware UTC; utcnow_naive() must be
  replaced with timezone-aware alternatives"
- 历史背景：数据库列类型为 ``sa.DateTime()``（无 timezone），在 SQLite 上以 TEXT 存储。
  naive UTC（``"2026-07-27 10:00:00.000000"``）与 tz-aware UTC
  （``"2026-07-27 10:00:00.000000+00:00"``）的字符串排序结果不同，混用会破坏
  范围查询、ORDER BY 和唯一性约束。
- 迁移策略（两阶段）：
  1. P1-10（本变更）：提供 timezone-aware API（``utcnow_aware``、``to_aware``、
     ``to_naive``），新代码与内存 dataclass / 签名 / JWT 必须使用 ``utcnow_aware``。
     ``utcnow_naive`` 标记为 deprecated，仅保留给既有 DB 列写入兼容。
  2. 后续：通过 Alembic 迁移将 ``sa.DateTime()`` 升级为 ``sa.DateTime(timezone=True)``，
     并将既有 naive 数据 backfill 为 tz-aware，届时可移除 ``utcnow_naive``。

使用方式：
    # 新代码：优先使用 timezone-aware
    from app.core.time_utils import utcnow_aware
    now = utcnow_aware()  # datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)

    # 既有 DB 列写入（naive DateTime 列）：临时兼容
    from app.core.time_utils import utcnow_naive
    record.updated_at = utcnow_naive()  # DeprecatedWarning

    # 转换辅助
    from app.core.time_utils import to_aware, to_naive
    aware = to_aware(naive_dt)   # 假定 naive 为 UTC
    naive = to_naive(aware_dt)   # 剥离 tzinfo，用于 DB 写入
"""
from __future__ import annotations

import warnings
from datetime import datetime, timezone


def utcnow_aware() -> datetime:
    """返回 timezone-aware UTC datetime。

    约束："All datetime fields must use timezone-aware UTC"

    新代码（非 DB 写入路径）必须使用此函数而非 ``utcnow_naive`` 或
    ``datetime.utcnow()``。返回值带 ``tzinfo=timezone.utc``，可直接用于：
    - JWT exp / 签名时间戳
    - 内存 dataclass 字段
    - ISO 8601 字符串格式化（含 ``+00:00`` 后缀）
    - 与 ``datetime`` 比较时不会因 tz 混用抛 TypeError
    """
    return datetime.now(timezone.utc)


def utcnow_naive() -> datetime:
    """返回 naive UTC datetime，与 ``sa.DateTime()`` 列兼容。

    .. deprecated:: P1-10
       新代码应使用 :func:`utcnow_aware`。本函数仅保留给既有 DB 列写入兼容，
       将在 DB schema 迁移到 ``sa.DateTime(timezone=True)`` 后移除。

    等价于已弃用的 ``datetime.utcnow()``，但基于
    ``datetime.now(timezone.utc).replace(tzinfo=None)``。
    """
    warnings.warn(
        "utcnow_naive() is deprecated; use utcnow_aware() for new code. "
        "DB schema migration to sa.DateTime(timezone=True) is pending.",
        DeprecationWarning,
        stacklevel=2,
    )
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_aware(dt: datetime) -> datetime:
    """将 naive datetime 转为 tz-aware UTC datetime。

    假定 naive datetime 为 UTC（与 ``utcnow_naive`` 语义一致）。
    已 tz-aware 的 datetime 原样返回（如果 tz 不是 UTC，转换为 UTC）。
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_naive(dt: datetime) -> datetime:
    """将 tz-aware datetime 转为 naive UTC datetime（剥离 tzinfo）。

    用于将 tz-aware 值写入既有 ``sa.DateTime()`` 列（临时兼容）。
    naive datetime 原样返回。
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def now_utc_iso() -> str:
    """返回 ISO 8601 格式的 tz-aware UTC 时间字符串（含 ``+00:00`` 后缀）。

    用于日志、审计、JSON 序列化等非 DB 路径。
    """
    return utcnow_aware().isoformat()
