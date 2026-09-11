"""判题语义子域。

- ``verdicts.py`` —— 状态 / 判定分离（PR-01）
- ``providers/judge0.py`` —— **Judge0 的唯一 HTTP 出口**（PR-02 自
  ``services/sandbox_client.py`` 迁入；旧路径留纯再导出 shim）

PR-05 已把「判定 → ``test_summary[].reason``」的映射表从
``services/experiment_service.py`` 搬进 ``verdicts.py::REASON_BY_STATUS``，
业务服务改为委托。
"""

from __future__ import annotations

__all__ = ["providers", "verdicts"]
