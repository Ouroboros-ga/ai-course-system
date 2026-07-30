"""Prep Agent 枚举类型。

定义 Prep Agent 的三个 Workflow 标识，由 AgentGateway 根据
``extras["graph_kind"]`` 路由到对应 Runtime Definition。
"""

from __future__ import annotations

from enum import StrEnum


class PrepGraphKind(StrEnum):
    """Prep Agent 的三种 Workflow 类型。

    - INITIAL: 首次课程生成（场景 1）
    - INCREMENTAL: 增量草稿修改（场景 2-5）
    - PPT_MAPPING: PPT 映射优化（场景 6）
    """

    INITIAL = "initial"
    INCREMENTAL = "incremental"
    PPT_MAPPING = "ppt_mapping"


__all__ = ["PrepGraphKind"]
