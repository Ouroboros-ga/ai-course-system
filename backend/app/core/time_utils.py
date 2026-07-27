"""统一 UTC 时间语义工具。

设计原则（Fix6 完成）：
- 约束："All datetime fields must use timezone-aware UTC; utcnow_naive() must be
  replaced with timezone-aware alternatives"
- 历史背景：数据库列类型原为 ``sa.DateTime()``（无 timezone），在 SQLite 上以 TEXT 存储。
  naive UTC（``"2026-07-27 10:00:00.000000"``）与 tz-aware UTC
  （``"2026-07-27 10:00:00.000000+00:00"``）的字符串排序结果不同，混用会破坏
  范围查询、ORDER BY 和唯一性约束。
- 迁移策略（已完成）：
  1. 所有应用代码统一使用 ``utcnow_aware``（tz-aware UTC）。
  2. Alembic 迁移 0008 将所有 ``datetime`` 列升级为 ``sa.DateTime(timezone=True)``。
  3. ``utcnow_naive`` 保留为 ``utcnow_aware`` 的向后兼容别名（不再发弃用警告），
     仅供尚未迁移的外部调用方使用；新代码必须使用 ``utcnow_aware``。

使用方式：
    # 新代码：使用 timezone-aware
    from app.core.time_utils import utcnow_aware
    now = utcnow_aware()  # datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)

    # 转换辅助
    from app.core.time_utils import to_aware, to_naive
    aware = to_aware(naive_dt)   # 假定 naive 为 UTC
    naive = to_naive(aware_dt)   # 剥离 tzinfo，用于 DB 写入
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow_aware() -> datetime:
    """返回 timezone-aware UTC datetime。

    约束："All datetime fields must use timezone-aware UTC"

    所有应用代码必须使用此函数而非 ``datetime.utcnow()``。返回值带
    ``tzinfo=timezone.utc``，可直接用于：
    - DB 列写入（DateTime(timezone=True) 列）
    - JWT exp / 签名时间戳
    - 内存 dataclass 字段
    - ISO 8601 字符串格式化（含 ``+00:00`` 后缀）
    - 与 ``datetime`` 比较时不会因 tz 混用抛 TypeError
    """
    return datetime.now(timezone.utc)


def utcnow_naive() -> datetime:
    """返回 timezone-aware UTC datetime（向后兼容别名）。

    历史原因：本函数原返回 naive UTC datetime。Fix6 完成后，所有调用已迁移到
    ``utcnow_aware``，DB schema 已升级为 ``DateTime(timezone=True)``。本函数
    保留为 ``utcnow_aware`` 的别名，仅供尚未迁移的外部调用方使用，不再发弃用
    警告，但新代码应直接使用 ``utcnow_aware``。
    """
    return utcnow_aware()


def to_aware(dt: datetime) -> datetime:
    """将 naive datetime 转为 tz-aware UTC datetime。

    假定 naive datetime 为 UTC（与 ``utcnow_naive`` 历史语义一致）。
    已 tz-aware 的 datetime 原样返回（如果 tz 不是 UTC，转换为 UTC）。
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_naive(dt: datetime) -> datetime:
    """将 tz-aware datetime 转为 naive UTC datetime（剥离 tzinfo）。

    用于将 tz-aware 值写入不支持 tz 的外部系统（如某些 API 响应）。
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
