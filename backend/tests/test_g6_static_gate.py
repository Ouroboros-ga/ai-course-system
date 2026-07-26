"""G6 静态门禁：OpenAPI operation ID 唯一性 + datetime.utcnow() 零残留。

两道门禁：
1. operation_id 唯一性：启动 FastAPI app 后，遍历 OpenAPI schema 的 paths，
   断言所有 operation_id 全局唯一。防止新增端点时函数名冲突破坏客户端代码生成。
2. datetime.utcnow() 零残留：扫描 app/ 目录下所有 .py 文件，
   断言源码中不再出现 `datetime.utcnow()` 调用（允许出现在注释/文档字符串中
   的文本描述，但不允许实际调用）。已由 `utcnow_naive()` 替代。

豁免清单（不写数据库 datetime 列的场景，允许保留 datetime.now(timezone.utc)）：
- 字符串格式化（strftime/isoformat 用于 HTTP 头、文件名、日志）
- JWT 过期时间计算
- 内存 dataclass 默认值
这些场景不经过 sa.DateTime() 列存储，naive 与 aware 的字符串排序差异不影响。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 门禁 1：OpenAPI operation ID 唯一性
# ---------------------------------------------------------------------------


def test_openapi_operation_ids_are_unique():
    """所有端点的 operation_id 必须全局唯一。"""
    from app.main import app

    schema = app.openapi()
    operation_ids: list[str] = []
    duplicates: list[str] = []

    for path, methods in schema.get("paths", {}).items():
        for method, spec in methods.items():
            if not isinstance(spec, dict):
                continue
            op_id = spec.get("operationId")
            if op_id is None:
                continue
            operation_ids.append(op_id)
            if operation_ids.count(op_id) > 1 and op_id not in duplicates:
                duplicates.append(op_id)

    assert not duplicates, (
        f"OpenAPI operation_id 冲突（共 {len(duplicates)} 个）: {duplicates[:10]}。"
        f"请检查端点函数名是否重复，或确认 generate_unique_id_function 已配置。"
    )


# ---------------------------------------------------------------------------
# 门禁 2：datetime.utcnow() 零残留（仅扫描 app/，不扫 tests/）
# ---------------------------------------------------------------------------

# 豁免文件：这些文件中的 datetime.utcnow() 出现在文档字符串或注释中，
# 不是实际调用，允许保留。
_EXEMPT_FILES: set[str] = {
    "app/core/time_utils.py",  # helper 自身的文档说明
}

# 匹配实际调用（非注释/文档字符串行）。Python 注释以 # 开头。
_UTCNOW_CALL_PATTERN = re.compile(r"datetime\.utcnow\(\)")


def test_no_datetime_utcnow_calls_in_app():
    """app/ 目录下不允许出现 datetime.utcnow() 实际调用。"""
    backend_root = Path(__file__).resolve().parent.parent
    app_root = backend_root / "app"
    violations: list[str] = []

    for py_file in app_root.rglob("*.py"):
        rel_path = py_file.relative_to(backend_root).as_posix()
        if rel_path in _EXEMPT_FILES:
            continue
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            # 跳过注释行
            if stripped.startswith("#"):
                continue
            # 跳过文档字符串内的行（简单启发式：以 """ 或 ''' 包围）
            # 这种启发式不完美，但足以捕获实际调用
            if '"""' in stripped or "'''" in stripped:
                continue
            if _UTCNOW_CALL_PATTERN.search(line):
                violations.append(f"{rel_path}:{lineno}: {stripped}")

    assert not violations, (
        f"发现 {len(violations)} 处 datetime.utcnow() 调用，请替换为 utcnow_naive()：\n"
        + "\n".join(violations[:20])
    )
