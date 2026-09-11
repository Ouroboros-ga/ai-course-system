"""OJ 题目子域（`problems`）。

承载题目本身的属性与规则：难度、标签，以及后续的筛选/排序语义。

**与既有表的关系**：`experiment_definitions` 就是 OJ 的 Problem
（ADR-0001 决定 1），本子域定义「题目的属性规则是什么」，
持久化与查询留在 `services/experiment_service.py`。

设计约束与 `domain/oj/intelligence/` 一致：**不 import `app.models` /
`app.services`、不接收 session**。
"""

from app.domain.oj.problems.metadata import (
    DEFAULT_DIFFICULTY,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    ProblemDifficulty,
    normalize_difficulty,
    normalize_tags,
    valid_difficulty_values,
)

__all__ = [
    "DEFAULT_DIFFICULTY",
    "MAX_TAG_LENGTH",
    "MAX_TAGS",
    "ProblemDifficulty",
    "normalize_difficulty",
    "normalize_tags",
    "valid_difficulty_values",
]
