"""OJ 题库的**筛选 / 排序 / 编号**语义（纯领域逻辑）。

与 `metadata.py` 同一约束：**不 import `app.models` / `app.services`、不接收 session**。
本模块定义「什么算命中、按什么顺序排、题号是几」，持久化与 SQL 留在服务层。

## 为什么把这几件事从服务层搬出来

`ExperimentStudentService.list_problem_bank` 原本自己写筛选循环与排序判断。
题库一多就会同时长出「列表页一套规则、详情页另一套规则」的分裂：
详情页也要算题号，教师页也要排序，口径一散就会出现
「列表显示 #007、点进去显示 #009」这种谁也说不清哪个对的 bug。

这里把三条规则钉成**单点可测**的纯函数：

1. **命中判定**（关键词 / 标签 / 难度区间）—— ``matches_search`` / ``matches_tags`` /
   ``resolve_difficulty_bounds``；
2. **排序**（五列 + 升降序）—— ``compare_records``，含「无数据永远沉底」的显式约定；
3. **题号**（课程内序号）—— ``build_problem_no_index`` / ``format_problem_no``。

## 题号口径（**前后端必须一致**）

`experiment_definitions` 没有题号列，题号按**课程目录顺序**派生：
以 ``experiment_id`` 的 **code-point 升序** 排序后取 1-based 下标。

为什么是 ``experiment_id`` 而不是 ``created_at``：

- `created_at` 会被回填、会被时区归一改动，历史行之间的相对顺序不可靠；
- `experiment_id` 是主键，一旦生成永不变更 —— 题号不会因为「教师改了标题」
  或「某个字段被回填」而整套平移。

为什么强调 **code-point** 而不是本地化排序：
前端 `pages/oj/ojTheme.js` 用 `<`/`>` 比较（code-point），Python 的 ``sorted`` 默认也是
code-point。若前端改用 ``localeCompare``，``exp_a0`` 与 ``exp_a-`` 之类就会排出不同顺序，
同一批题在两端的题号会不一致。``test_oj_problem_catalog.py`` 用同一组输入把这条钉住。

⚠️ 服务端给出 ``problem_no`` 即为权威；前端的派生只作为**降级路径**
（接口未部署 / 离线演示时仍能显示连续题号）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import cmp_to_key
from typing import Iterable, Mapping, Optional, Sequence

from app.domain.oj.problems.metadata import (
    ProblemDifficulty,
    normalize_difficulty,
)

__all__ = [
    "CLEAR_SOURCE",
    "CLEAR_YEAR",
    "DEFAULT_SORT_BY",
    "DEFAULT_SORT_ORDER",
    "MAX_SOURCE_LENGTH",
    "MAX_YEAR",
    "MIN_YEAR",
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
    "normalize_search_in",
    "normalize_sort_by",
    "normalize_sort_order",
    "normalize_source",
    "normalize_tag_mode",
    "normalize_year",
    "problem_no_for",
    "resolve_difficulty_bounds",
    "sort_records_with",
]


# ---------------------------------------------------------------------------
# 来源 / 年份
# ---------------------------------------------------------------------------

#: 来源（题库）列宽。与 `ExperimentDefinition.source` 的 ``max_length`` 必须一致 ——
#: 由 `test_oj_problem_catalog.py` 的字面量断言守住。
MAX_SOURCE_LENGTH = 64

#: 「清空来源」的显式取值。`None` 在 PATCH 语义里表示「别动」，
#: 因此需要一个**空值**来表达「清掉」—— 与 `tags` 用 ``[]`` 清空同一套约定。
CLEAR_SOURCE = ""

MIN_YEAR = 1970
MAX_YEAR = 2100

#: 「清空年份」的显式取值。理由同上：``None`` 已被「别动」占用。
CLEAR_YEAR = 0


def normalize_source(value: object) -> Optional[str]:
    """规范化来源：去空白；空串归 ``None``（= 清空）；超长抛 ``ValueError``。

    **不做大小写归并** —— 与 `metadata.normalize_tags` 同一取向：``ICPC`` / ``Codeforces``
    是专名，强行转小写会破坏展示。筛选比较由调用方按 ``casefold`` 处理。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > MAX_SOURCE_LENGTH:
        raise ValueError(
            f"来源过长（{len(text)} 字符 > {MAX_SOURCE_LENGTH}）：{text[:MAX_SOURCE_LENGTH]}…"
        )
    return text


def normalize_year(value: object) -> Optional[int]:
    """规范化年份：接受 int / 纯数字字符串；``None``/空串 归 ``None``。

    ``CLEAR_YEAR``（0）也归 ``None`` —— 让「清空」与「没填」在存储层同义，
    服务层不必区分。越界（<1970 / >2100）**抛错不兜底**：年份是教师显式填写的
    事实，静默截断到边界会造出一个「看起来对但不是我填的」值。
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool 是 int 的子类，得先拦掉
        raise ValueError(f"年份取值非法：{value!r}")
    if isinstance(value, int):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if not text.lstrip("-").isdigit():
            raise ValueError(f"年份取值非法：{value!r}")
        parsed = int(text)
    if parsed == CLEAR_YEAR:
        return None
    if parsed < MIN_YEAR or parsed > MAX_YEAR:
        raise ValueError(f"年份超出范围（{MIN_YEAR}–{MAX_YEAR}）：{parsed}")
    return parsed


# ---------------------------------------------------------------------------
# 筛选口径
# ---------------------------------------------------------------------------


class TagMatchMode(str, Enum):
    """多标签匹配模式。

    ``AND`` 是现行语义（收窄结果）；``OR`` 用于「我想练动态规划**或**贪心」
    这类发散浏览 —— 参考截图的「已选择」区就是按 OR 组的。
    """

    AND = "and"
    OR = "or"


class SearchScope(str, Enum):
    """关键词匹配范围。``STATEMENT`` 对应参考截图的「搜索题面」勾选框。"""

    TITLE = "title"
    STATEMENT = "statement"
    BOTH = "both"


DEFAULT_TAG_MATCH_MODE = TagMatchMode.AND.value
DEFAULT_SEARCH_SCOPE = SearchScope.TITLE.value


def normalize_tag_mode(value: object) -> str:
    if value is None:
        return DEFAULT_TAG_MATCH_MODE
    text = str(getattr(value, "value", value)).strip().lower()
    if not text:
        return DEFAULT_TAG_MATCH_MODE
    if text not in {m.value for m in TagMatchMode}:
        raise ValueError(f"标签匹配模式非法：{value!r}；允许 and, or")
    return text


def normalize_search_in(value: object) -> str:
    if value is None:
        return DEFAULT_SEARCH_SCOPE
    text = str(getattr(value, "value", value)).strip().lower()
    if not text:
        return DEFAULT_SEARCH_SCOPE
    if text not in {s.value for s in SearchScope}:
        raise ValueError(f"搜索范围非法：{value!r}；允许 title, statement, both")
    return text


def matches_search(
    *,
    title: str,
    description: str,
    keyword: Optional[str],
    scope: str = DEFAULT_SEARCH_SCOPE,
) -> bool:
    """关键词命中判定：大小写不敏感的子串匹配。

    关键词为 ``None``/空 → 恒真（「没填 = 不过滤」）。``scope`` 决定匹配哪一段：
    ``title`` 只搜标题，``statement`` 只搜题面，``both`` 任一命中即可。

    ``statement`` 单独存在是有意义的：搜「dijkstra」时教师题面里写了算法名词但
    标题是中文的情况很常见，只搜标题会漏掉。
    """
    if keyword is None:
        return True
    needle = str(keyword).strip().casefold()
    if not needle:
        return True
    title_text = str(title or "").casefold()
    body_text = str(description or "").casefold()
    if scope == SearchScope.TITLE.value:
        return needle in title_text
    if scope == SearchScope.STATEMENT.value:
        return needle in body_text
    return needle in title_text or needle in body_text


def matches_tags(
    problem_tags: Iterable[object] | None,
    wanted: Optional[Sequence[str]],
    mode: str = DEFAULT_TAG_MATCH_MODE,
) -> bool:
    """标签命中判定。``wanted`` 为空 → 恒真。

    比较按 ``casefold``，但**不回写** —— 教师填的 ``DP`` 会与筛选用的 ``dp`` 命中，
    展示仍是 ``DP``（与 `normalize_tags` 保序去重但不归并的取向一致）。
    """
    if not wanted:
        return True
    pool = {str(tag).strip().casefold() for tag in (problem_tags or []) if str(tag).strip()}
    wanted_set = {str(tag).strip().casefold() for tag in wanted if str(tag).strip()}
    if not wanted_set:
        return True
    if mode == TagMatchMode.OR.value:
        return bool(pool & wanted_set)
    return wanted_set <= pool


def difficulty_rank(value: object) -> int:
    """难度的可排序权重：easy=1 < medium=2 < hard=3。

    ⚠️ **空值/未知名不构成第四档**：`normalize_difficulty` 已经把「没填」归为
    `DEFAULT_DIFFICULTY`（medium），所以 ``difficulty_rank(None) == 2``。
    这是刻意的 —— 存储层（NOT NULL + server_default=medium）根本产生不出
    「未标注」难度，域层再造一个 rank 0 的幽灵档位只会让排序结果无法解释。

    前端 `ojTheme.difficultyMeta` 保留了 `order: 0` 的兜底，那是给
    「接口异常/离线演示时拿到 null」用的展示兜底，不是本函数的对端语义。
    """
    text = normalize_difficulty(value)
    return {ProblemDifficulty.EASY.value: 1,
            ProblemDifficulty.MEDIUM.value: 2,
            ProblemDifficulty.HARD.value: 3}[text]


def resolve_difficulty_bounds(
    minimum: Optional[str],
    maximum: Optional[str],
) -> Optional[frozenset[str]]:
    """把难度区间解析成**允许取值的集合**；两端都为空则返回 ``None``（= 不过滤）。

    区间是**闭区间**，按 `ProblemDifficulty` 的档位顺序（easy < medium < hard）取中间档。
    单端给出时另一端自动取边界，因此调用方可以只传 ``minimum`` 表达「提高及以上」。

    端点写反（``min=hard, max=easy``）时返回**空集合**而不是抛错 —— 空集合的语义是
    「没有任何题满足」，这正是用户要的结果；抛 422 反而会让前端得为「拖反了滑块」
    单独写一处错误处理。区间取值本身非法（如 ``minimum="impossible"``）仍走
    `normalize_difficulty` 抛错。
    """
    low = normalize_difficulty(minimum)
    high = normalize_difficulty(maximum)
    if minimum is None and maximum is None:
        return None
    # normalize_difficulty 把 None 归 medium —— 单端缺失时不能用它的返回值，
    # 得回到「不设限」的边界档位。
    low_rank = difficulty_rank(low) if minimum is not None else 1
    high_rank = difficulty_rank(high) if maximum is not None else 3
    return frozenset(
        value
        for value, rank in (
            (ProblemDifficulty.EASY.value, 1),
            (ProblemDifficulty.MEDIUM.value, 2),
            (ProblemDifficulty.HARD.value, 3),
        )
        if low_rank <= rank <= high_rank
    )


# ---------------------------------------------------------------------------
# 排序
# ---------------------------------------------------------------------------


class ProblemSortKey(str, Enum):
    """可排序列。与前端 `ojTheme.OJ_SORTABLE_KEYS` 一一对应。"""

    DEFAULT = "default"
    NO = "no"
    TITLE = "title"
    DIFFICULTY = "difficulty"
    PASS_RATE = "pass_rate"
    ATTEMPT_TOTAL = "attempt_total"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


DEFAULT_SORT_BY = ProblemSortKey.DEFAULT.value
DEFAULT_SORT_ORDER = SortOrder.ASC.value


def normalize_sort_by(value: object) -> str:
    if value is None:
        return DEFAULT_SORT_BY
    text = str(getattr(value, "value", value)).strip().lower()
    if not text:
        return DEFAULT_SORT_BY
    if text not in {k.value for k in ProblemSortKey}:
        allowed = ", ".join(k.value for k in ProblemSortKey)
        raise ValueError(f"排序字段非法：{value!r}；允许 {allowed}")
    return text


def normalize_sort_order(value: object) -> str:
    if value is None:
        return DEFAULT_SORT_ORDER
    text = str(getattr(value, "value", value)).strip().lower()
    if not text:
        return DEFAULT_SORT_ORDER
    if text not in {o.value for o in SortOrder}:
        raise ValueError(f"排序方向非法：{value!r}；允许 asc, desc")
    return text


@dataclass(frozen=True)
class ProblemSortRecord:
    """排序所需的**最小投影**。服务层从 ORM 行构造，本模块只认这几个值。"""

    problem_no: int
    title: str
    difficulty: str
    #: 全班通过率（0–1）。``None`` = 还没有任何终结化尝试 —— 不是 0%。
    pass_rate: Optional[float]
    attempt_total: int


_MISSING = object()


def _sort_value(record: ProblemSortRecord, key: str) -> object:
    if key in (ProblemSortKey.DEFAULT.value, ProblemSortKey.NO.value):
        return record.problem_no
    if key == ProblemSortKey.TITLE.value:
        return str(record.title or "")
    if key == ProblemSortKey.DIFFICULTY.value:
        return difficulty_rank(record.difficulty)
    if key == ProblemSortKey.PASS_RATE.value:
        return _MISSING if record.pass_rate is None else float(record.pass_rate)
    if key == ProblemSortKey.ATTEMPT_TOTAL.value:
        return int(record.attempt_total or 0)
    return record.problem_no  # normalize_sort_by 已挡掉未知值，这里是兜底


def compare_records(
    left: ProblemSortRecord,
    right: ProblemSortRecord,
    *,
    sort_by: str = DEFAULT_SORT_BY,
    sort_order: str = DEFAULT_SORT_ORDER,
) -> int:
    """比较两条记录，返回 -1 / 0 / 1。

    **无数据永远沉底**，不随升降序翻转：``pass_rate=None`` 表示「还没人交过」，
    若按降序把它当成最小值排到最后、按升序排到最前，用户会看到一片「—」占据榜首，
    误以为那是表现最好或最差的一批。这条约定与前端 `ojTheme.sortProblems` 必须一致。
    """
    a = _sort_value(left, sort_by)
    b = _sort_value(right, sort_by)
    if a is _MISSING and b is _MISSING:
        return 0
    if a is _MISSING:
        return 1
    if b is _MISSING:
        return -1
    if a == b:
        return 0
    result = -1 if a < b else 1
    return result if sort_order != SortOrder.DESC.value else -result


def sort_records_with(
    records: Sequence[ProblemSortRecord],
    *,
    sort_by: str = DEFAULT_SORT_BY,
    sort_order: str = DEFAULT_SORT_ORDER,
) -> list[ProblemSortRecord]:
    """按口径排序（返回新列表，不改入参）。

    ``TITLE`` 走 code-point 比较（Python ``str`` 默认）而非 ``locale.strcoll``：
    中文标题的本地化排序依赖系统 locale，同一份数据在不同机器上顺序会漂，
    而排序结果会被翻页固化到用户眼前。确定性优先于「拼音序」。

    调用方若还要带上自己的负载，用 ``compare_records`` 配 ``cmp_to_key`` ——
    本函数只排记录本身，不认任何额外字段。
    """
    return list(
        sorted(
            records,
            key=cmp_to_key(
                lambda left, right: compare_records(
                    left, right, sort_by=sort_by, sort_order=sort_order
                )
            ),
        )
    )


# ---------------------------------------------------------------------------
# 题号
# ---------------------------------------------------------------------------


def format_problem_no(sequence: int) -> str:
    """课程内题号：``1`` → ``#001``。

    非法序号返回 ``—`` 而不是抛错：调用方可能在补数阶段拿到 0 / None，
    为了一个展示串把整个列表接口打 500 不划算。
    """
    try:
        number = int(sequence)
    except (TypeError, ValueError):
        return "—"
    if number <= 0:
        return "—"
    return f"#{number:03d}"


def build_problem_no_index(experiment_ids: Iterable[object]) -> dict[str, int]:
    """课程目录 → ``{experiment_id: 1-based 序号}``。

    ⚠️ 输入必须是**未筛选的全量课程目录**。拿筛选后的结果编号，一筛选整列题号
    就会平移（前端 `ojTheme.test.js` 有专门的反向验证用例钉住这点）。

    去重后按 code-point 升序 —— 与前端 `buildProblemNoIndex` 同一规则，见模块 docstring。
    """
    unique = sorted({str(item) for item in (experiment_ids or []) if str(item)})
    return {experiment_id: position for position, experiment_id in enumerate(unique, start=1)}


def problem_no_for(index: Mapping[str, int], experiment_id: str) -> str:
    """从索引取题号串；不在索引内返回 ``—``（题不在课程目录里，例如未发布）。"""
    return format_problem_no(index.get(str(experiment_id), 0))
