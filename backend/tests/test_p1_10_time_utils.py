"""P1-10 验收测试：time_utils.py 替换 utcnow_naive() 为时区感知实现

验证约束：
- utcnow_aware() 返回 timezone-aware UTC datetime（tzinfo=timezone.utc）
- utcnow_naive() 标记为 deprecated，调用时发出 DeprecationWarning
- to_aware() 将 naive datetime 转为 tz-aware（假定 UTC）
- to_naive() 将 tz-aware datetime 转为 naive（剥离 tzinfo）
- now_utc_iso() 返回含 +00:00 后缀的 ISO 8601 字符串
- 新代码（非 DB 写入）必须使用 utcnow_aware() 而非 utcnow_naive()

约束来源：
- Hard Constraints: "All datetime fields must use timezone-aware UTC; utcnow_naive()
  must be replaced with timezone-aware alternatives"
- Lessons Learned: "utcnow_naive() usage leads to timezone-unaware datetime fields;
  replace with timezone-aware functions"
"""
from __future__ import annotations

import warnings
from datetime import datetime, timezone, timedelta

import pytest

from app.core.time_utils import (
    now_utc_iso,
    to_aware,
    to_naive,
    utcnow_aware,
    utcnow_naive,
)


class TestUtcnowAware:
    """测试1: utcnow_aware 返回 tz-aware UTC"""

    def test_returns_timezone_aware_datetime(self) -> None:
        now = utcnow_aware()
        assert now.tzinfo is not None
        assert now.tzinfo == timezone.utc

    def test_close_to_current_time(self) -> None:
        before = datetime.now(timezone.utc)
        result = utcnow_aware()
        after = datetime.now(timezone.utc)
        assert before <= result <= after

    def test_does_not_emit_deprecation_warning(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            utcnow_aware()  # 不应抛 DeprecationWarning


class TestUtcnowNaiveDeprecated:
    """测试2: utcnow_naive 标记为 deprecated"""

    def test_emits_deprecation_warning(self) -> None:
        with pytest.warns(DeprecationWarning, match="deprecated"):
            utcnow_naive()

    def test_returns_naive_datetime(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            now = utcnow_naive()
        assert now.tzinfo is None

    def test_naive_value_equals_aware_value_stripped(self) -> None:
        """naive 与 aware 的 UTC 时刻应一致（剥离 tzinfo 后相等）"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            naive = utcnow_naive()
        aware = utcnow_aware()
        # 两者都基于 datetime.now(timezone.utc)，差异应在毫秒内
        diff = abs((aware.replace(tzinfo=None) - naive).total_seconds())
        assert diff < 1.0


class TestToAware:
    """测试3: to_aware 转换 naive → aware"""

    def test_naive_to_aware_adds_utc_tzinfo(self) -> None:
        naive = datetime(2026, 7, 27, 10, 0, 0)
        aware = to_aware(naive)
        assert aware.tzinfo == timezone.utc
        assert aware.year == 2026
        assert aware.hour == 10

    def test_aware_utc_returns_unchanged(self) -> None:
        aware = datetime(2026, 7, 27, 10, 0, 0, tzinfo=timezone.utc)
        result = to_aware(aware)
        assert result == aware

    def test_aware_non_utc_converted_to_utc(self) -> None:
        # CST = UTC+8，10:00 CST = 02:00 UTC
        from datetime import timedelta
        cst_tz = timezone(timedelta(hours=8))
        cst_dt = datetime(2026, 7, 27, 10, 0, 0, tzinfo=cst_tz)
        utc_dt = to_aware(cst_dt)
        assert utc_dt.tzinfo == timezone.utc
        assert utc_dt.hour == 2  # 10:00 CST → 02:00 UTC


class TestToNaive:
    """测试4: to_naive 转换 aware → naive"""

    def test_aware_utc_strips_tzinfo(self) -> None:
        aware = datetime(2026, 7, 27, 10, 0, 0, tzinfo=timezone.utc)
        naive = to_naive(aware)
        assert naive.tzinfo is None
        assert naive.year == 2026
        assert naive.hour == 10

    def test_aware_non_utc_converted_to_utc_then_stripped(self) -> None:
        # CST = UTC+8，10:00 CST = 02:00 UTC
        cst_tz = timezone(timedelta(hours=8))
        cst_dt = datetime(2026, 7, 27, 10, 0, 0, tzinfo=cst_tz)
        naive = to_naive(cst_dt)
        assert naive.tzinfo is None
        assert naive.hour == 2  # 转为 UTC 后剥离

    def test_naive_returns_unchanged(self) -> None:
        naive = datetime(2026, 7, 27, 10, 0, 0)
        result = to_naive(naive)
        assert result == naive
        assert result.tzinfo is None


class TestNowUtcIso:
    """测试5: now_utc_iso 返回 ISO 8601 字符串"""

    def test_returns_string_with_utc_suffix(self) -> None:
        iso = now_utc_iso()
        assert isinstance(iso, str)
        # ISO 8601 with UTC timezone should contain +00:00
        assert "+00:00" in iso

    def test_parseable_by_datetime_fromisoformat(self) -> None:
        iso = now_utc_iso()
        parsed = datetime.fromisoformat(iso)
        assert parsed.tzinfo == timezone.utc


class TestRoundTripConversion:
    """测试6: 往返转换不丢失信息"""

    def test_naive_to_aware_to_naive_roundtrip(self) -> None:
        original_naive = datetime(2026, 7, 27, 10, 30, 45, 123456)
        aware = to_aware(original_naive)
        back_to_naive = to_naive(aware)
        assert back_to_naive == original_naive

    def test_aware_to_naive_to_aware_roundtrip(self) -> None:
        original_aware = datetime(2026, 7, 27, 10, 30, 45, 123456, tzinfo=timezone.utc)
        naive = to_naive(original_aware)
        back_to_aware = to_aware(naive)
        assert back_to_aware == original_aware


class TestCoreExports:
    """测试7: app.core 包导出新函数"""

    def test_core_exports_timezone_aware_functions(self) -> None:
        from app.core import utcnow_aware, to_aware, to_naive, now_utc_iso
        assert callable(utcnow_aware)
        assert callable(to_aware)
        assert callable(to_naive)
        assert callable(now_utc_iso)

    def test_core_still_exports_utcnow_naive_for_compat(self) -> None:
        """既有代码仍可从 app.core 导入 utcnow_naive"""
        from app.core import utcnow_naive
        assert callable(utcnow_naive)
