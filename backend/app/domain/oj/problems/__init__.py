"""OJ 题目子域（`problems`）。

承载题目本身的属性与规则：难度、标签，以及筛选 / 排序 / 编号语义。

**与既有表的关系**：`experiment_definitions` 就是 OJ 的 Problem
（ADR-0001 决定 1），本子域定义「题目的属性规则是什么」，
持久化与查询留在 `services/experiment_service.py`。

设计约束与 `domain/oj/intelligence/` 一致：**不 import `app.models` /
`app.services`、不接收 session**。

模块划分：

- `metadata.py`：难度与标签的**取值规范**（PR-09）；
- `catalog.py`：题库的**检索与呈现规则** —— 命中判定、排序、题号派生（B1/B2）。
"""

from app.domain.oj.problems.catalog import (
    CLEAR_SOURCE,
    CLEAR_YEAR,
    DEFAULT_SORT_BY,
    DEFAULT_SORT_ORDER,
    MAX_SOURCE_LENGTH,
    MAX_YEAR,
    MIN_YEAR,
    ProblemSortKey,
    ProblemSortRecord,
    SearchScope,
    SortOrder,
    TagMatchMode,
    build_problem_no_index,
    compare_records,
    difficulty_rank,
    format_problem_no,
    matches_search,
    matches_tags,
    normalize_search_in,
    normalize_sort_by,
    normalize_sort_order,
    normalize_source,
    normalize_tag_mode,
    normalize_year,
    problem_no_for,
    resolve_difficulty_bounds,
    sort_records_with,
)
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
    "CLEAR_SOURCE",
    "CLEAR_YEAR",
    "DEFAULT_DIFFICULTY",
    "DEFAULT_SORT_BY",
    "DEFAULT_SORT_ORDER",
    "MAX_SOURCE_LENGTH",
    "MAX_TAG_LENGTH",
    "MAX_TAGS",
    "MAX_YEAR",
    "MIN_YEAR",
    "ProblemDifficulty",
    "ProblemSortKey",
    "ProblemSortRecord",
    "SearchScope",
    "SortOrder",
    "TagMatchMode",
    "build_problem_no_index",
    "compare_records",
    "difficulty_rank",
    "format_problem_no",
    "matches_search",
    "matches_tags",
    "normalize_difficulty",
    "normalize_search_in",
    "normalize_sort_by",
    "normalize_sort_order",
    "normalize_source",
    "normalize_tag_mode",
    "normalize_tags",
    "normalize_year",
    "problem_no_for",
    "resolve_difficulty_bounds",
    "sort_records_with",
    "valid_difficulty_values",
]
