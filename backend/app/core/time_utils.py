"""统一 UTC 时间语义工具。

设计原则：
- 数据库列类型为 ``sa.DateTime()``（无 timezone），在 SQLite 上以 TEXT 存储、
  用字符串比较排序。naive UTC（``"2026-07-27 10:00:00.000000"``）与
  tz-aware UTC（``"2026-07-27 10:00:00.000000+00:00"``）的字符串排序结果不同，
  混用会破坏范围查询、ORDER BY 和唯一性约束。
- 因此所有写入数据库 datetime 列的时间值必须是 **naive UTC**。
- ``datetime.utcnow()`` 已在 Python 3.12+ 标记弃用；本模块提供基于
  ``datetime.now(timezone.utc)`` 的等价实现，保持 naive 语义不变。

使用方式：
    from app.core.time_utils import utcnow_naive

    created_at: datetime = Field(default_factory=utcnow_naive)
    record.updated_at = utcnow_naive()
    now = utcnow_naive()

非写库路径（JWT exp、字符串格式化、内存 dataclass）可直接使用
``datetime.now(timezone.utc)``，无需经过本模块。
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """返回 naive UTC datetime，与 ``sa.DateTime()`` 列兼容。

    等价于已弃用的 ``datetime.utcnow()``，但基于
    ``datetime.now(timezone.utc).replace(tzinfo=None)``，
    与 ``app/scripts/migration_ops.py`` 的写法一致。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
