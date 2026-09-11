"""OJ Activity 域：活动类型、时间窗、版本固定与算分的**纯领域规则**。

与 `domain/oj/problems/`、`domain/oj/intelligence/` 同一条边界：
**不 import `app.models` / `app.services`、不接收 session、不做持久化**。
「规则是什么」在这里，「何时读写 DB」在 service。

为什么本期就建 4 种 type 而只实现 homework
------------------------------------------
真缺口是 homework / contest（`docs/architecture/oj-current-state.md` 实测
`homework`/`contest`/`scoreboard` 在 `backend/app` 零命中），但 v2 方案的
取值域里有 4 种（HOMEWORK / CONTEST / EXAM / PRACTICE_SET）。

**取值域一次建全、行为只实现 homework**：type 列用 `String(32)` + 这里的
值域约束（与 `run_state` / `difficulty` 同一取向，不用 PG 原生 enum ——
扩值不需要 `ALTER TYPE`，原生 enum 还不可在事务里回滚）。若只建 homework，
将来加 contest 就得改列约束 + 迁移 + 回归一遍；建全 4 值的成本是零，
收益是「加行为不动表」。

**红线**：未实现的 type 在 service 层显式拒绝（`assert_supported_type`），
**不是**静默当 homework 处理 —— 静默降级会产生「我建的是 contest 怎么按
homework 算分」这类无从排查的问题。这与 `normalize_difficulty` 的
「非法值抛错不兜底」是同一条原则。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Iterable, Sequence

__all__ = [
    "ACTIVITY_STATUSES",
    "ACTIVITY_TYPES",
    "DEFAULT_ACTIVITY_TYPE",
    "MAX_PROBLEMS_PER_ACTIVITY",
    "RANKING_MODES",
    "SCORING_MODES",
    "SCOPE_TYPES",
    "SUPPORTED_ACTIVITY_TYPES",
    "ActivityStatus",
    "ActivityType",
    "assert_immutable_after_publish",
    "assert_pinned_versions",
    "assert_supported_type",
    "assert_unique_ordinals",
    "compute_homework_score",
    "is_submission_open",
    "normalize_activity_status",
    "normalize_activity_type",
    "normalize_ordinal",
    "normalize_ranking_mode",
    "normalize_scoring_mode",
    "normalize_scope_type",
    "validate_time_window",
    "validate_scope_payload",
]


class ActivityType(str, Enum):
    """活动类型 —— **取值域一次建全，行为分批实现**（见模块 docstring）。"""

    HOMEWORK = "homework"
    CONTEST = "contest"
    EXAM = "exam"
    PRACTICE_SET = "practice_set"


class ActivityStatus(str, Enum):
    """活动状态机：draft → published → archived。

    与 `ExperimentPublishStatus` 同一取值集（draft/published/archived）。
    **刻意不引入 "closed" 状态**：活动是否已结束由 `end_at` 时间窗推导，
    存一个可漂移的 closed 位会和时间窗打架（改了 end_at 忘改 status）。
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


#: 全部合法取值（含**尚未实现行为**的类型）。
ACTIVITY_TYPES: frozenset[str] = frozenset(t.value for t in ActivityType)

#: 本期**真正实现了作答行为**的类型。service 层用它拒绝其余类型（不静默降级）。
SUPPORTED_ACTIVITY_TYPES: frozenset[str] = frozenset({"homework"})

#: 新建活动未指定类型时的默认值。作业是本期唯一有行为的类型，默认它最不会出错。
DEFAULT_ACTIVITY_TYPE = ActivityType.HOMEWORK.value

ACTIVITY_STATUSES: frozenset[str] = frozenset(s.value for s in ActivityStatus)

#: 算分模式。本期只实现 `sum`（按题求和，见 `compute_homework_score`）。
SCORING_MODES: frozenset[str] = frozenset({"sum"})

#: 排行模式。`icpc`（罚时/冻结）属 PR-15，本期只接受 `none` —— 列先建好，
#: 值域收窄到已实现的，防止建出来的活动带一个没人实现的排行语义。
RANKING_MODES: frozenset[str] = frozenset({"none", "icpc"})

#: 可见范围类型。`class` / `user` 本期建模不实现行为（scope 行先可写入，
#: 学生侧解析本期只认 `course`，其余在 service 显式跳过并记录）。
SCOPE_TYPES: frozenset[str] = frozenset({"course", "class", "user"})

#: 单个活动的题目上限。与 `MAX_TAGS` 同一取向：超出即拒，不静默截断。
MAX_PROBLEMS_PER_ACTIVITY = 50

#: 算分保留的小数位。**固定精度是 deterministic 的前提** ——
#: 浮点直接相加，输入顺序不同可能差 1 ulp，重算就对不上。
_SCORE_DECIMALS = 6


# ---------------------------------------------------------------------------
# 规范化（与 normalize_difficulty 同一取向：非法值抛错，None/空 → 默认）
# ---------------------------------------------------------------------------


def normalize_activity_type(value: object) -> str:
    return _normalize_choice(value, ACTIVITY_TYPES, "活动类型", DEFAULT_ACTIVITY_TYPE)


def normalize_activity_status(value: object) -> str:
    return _normalize_choice(value, ACTIVITY_STATUSES, "活动状态", ActivityStatus.DRAFT.value)


def normalize_scoring_mode(value: object) -> str:
    return _normalize_choice(value, SCORING_MODES, "算分模式", "sum")


def normalize_ranking_mode(value: object) -> str:
    return _normalize_choice(value, RANKING_MODES, "排行模式", "none")


def normalize_scope_type(value: object) -> str:
    return _normalize_choice(value, SCOPE_TYPES, "可见范围", "course")


def _normalize_choice(value: object, allowed: frozenset[str], label: str, default: str) -> str:
    """枚举 / 字符串双接受，大小写与首尾空白不敏感；空 → 默认，非法 → 抛。"""
    if value is None:
        return default
    raw = getattr(value, "value", value)
    text = str(raw).strip().lower()
    if not text:
        return default
    if text not in allowed:
        raise ValueError(f"{label}取值非法：{value!r}；允许 {', '.join(sorted(allowed))}")
    return text


def assert_supported_type(value: str) -> None:
    """**未实现行为的 type 在此显式拒绝**，绝不静默当 homework 处理。

    与值域校验分开：`normalize_activity_type` 管「是不是合法词」，
    这里管「是不是已实现」。CONTEST / EXAM / PRACTICE_SET 合法但未实现，
    service 在创建/作答入口调用本函数把不住门的挡在门外。
    """
    if value not in SUPPORTED_ACTIVITY_TYPES:
        raise ValueError(
            f"活动类型 {value!r} 尚未实现；当前支持 {', '.join(sorted(SUPPORTED_ACTIVITY_TYPES))}"
        )


# ---------------------------------------------------------------------------
# 时间窗
# ---------------------------------------------------------------------------


def validate_time_window(start_at: datetime | None, end_at: datetime | None) -> None:
    """两端都给时要求 `end_at > start_at`；允许只给一端或都不给（不限时）。

    **不自动补默认窗口**：活动可以永久开放（作业常见），缺省是合法输入，
    与「填错」不同 —— 所以这里只校验显式给出的组合，不兜底。
    """
    if start_at is not None and end_at is not None and end_at <= start_at:
        raise ValueError(f"end_at（{end_at.isoformat()}）必须晚于 start_at（{start_at.isoformat()}）")


def is_submission_open(
    now: datetime,
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    allow_late_submit: bool = False,
) -> tuple[bool, str]:
    """判定 `now` 时刻能否**新建**作答。返回 `(是否允许, 原因码)`。

    - 未开始 → `(False, "not_started")`
    - 已结束且不允许迟交 → `(False, "ended")`
    - 已结束但允许迟交 → `(True, "late")` —— **调用方需要知道这是迟交**，
      只返回 bool 会把"准时"和"迟交"混在一起，报表/防作弊都分不开。
    - 窗口内 → `(True, "open")`
    - 两端都为空 → 永久开放 `(True, "open")`

    注意这里**只管时间窗**；`status == published`、题目是否存在等由 service 叠加。
    领域函数收 `now` 而不自取时钟：可测试性（时间注入）+ 同一请求内判定一致。
    """
    if start_at is not None and now < start_at:
        return False, "not_started"
    if end_at is not None and now > end_at:
        return (True, "late") if allow_late_submit else (False, "ended")
    return True, "open"


# ---------------------------------------------------------------------------
# 版本固定（DoD：所有学生拿到相同版本）
# ---------------------------------------------------------------------------


def assert_pinned_versions(version_ids: Iterable[str]) -> str:
    """**同一道题**在活动内的全部行必须指向同一个 `problem_version_id`，返回它。

    ⚠️ 语义边界（2026-09-11 拍板）：固定的是「**每道题**的版本」，
    **不是**「全活动共享一个版本」——不同题（不同 definition）几乎必然
    各有自己的版本，若强制全活动一个版本，两道题的作业根本建不起来。
    「所有学生拿到相同版本」由**逐题固化**保证：版本在挂题时写入
    `problem_version_id` 行并发布后不可变，而不是在学生作答时动态解析
    definition 的当前激活版本。

    本函数用于同一 definition 在活动内出现多行（如按语言拆行）的场景：
    多行必须同版本，否则"这道题的版本"本身失去意义。
    """
    unique = {str(v) for v in version_ids}
    if not unique:
        raise ValueError("至少需要一个版本")
    if len(unique) > 1:
        raise ValueError(
            f"同一道题在活动内必须固定同一 problem_version_id，"
            f"实际出现 {len(unique)} 个：{sorted(unique)}"
        )
    return next(iter(unique))


def assert_unique_ordinals(ordinals: Iterable[int]) -> list[int]:
    """题序不得重复 —— 位次决定算分顺序，冲突会破坏 deterministic 重算。

    返回排序后的位次列表。DB 侧有 (activity_id, ordinal) 唯一约束兜底，
    这里给出**更早、更可读**的错误（带冲突位次明细，而不是 IntegrityError）。
    """
    values = [int(o) for o in ordinals]
    seen: set[int] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"题序重复：{value}（位次决定算分顺序，必须唯一）")
        seen.add(value)
    return sorted(values)


def assert_immutable_after_publish(status: str, field: str) -> None:
    """发布后禁止变更的字段在此统一把门。

    可变：时间窗（提前截止 / 延期是教师刚需）、说明文案。
    不可变：题目集合、每题版本、每题满分 —— 这些是算分与公平性的根基，
    发布后改动等于「考完试改卷面分值」。
    """
    if status == ActivityStatus.PUBLISHED.value:
        raise ValueError(f"活动已发布，{field} 不可变更（如需调整请归档后另建活动）")


def normalize_ordinal(ordinal: object) -> int:
    """题序必须是正整数；浮点 / 字符串数字接受，非整数拒绝。

    序号直接决定算分顺序与展示顺序，`1.5` 这类值会破坏 deterministic 重算，
    因此**不接受隐式截断**。
    """
    raw = getattr(ordinal, "value", ordinal)
    if isinstance(raw, bool):
        raise ValueError(f"题序必须是正整数，收到布尔值：{raw!r}")
    if isinstance(raw, float) and not raw.is_integer():
        raise ValueError(f"题序必须是正整数，收到小数：{raw!r}")
    try:
        number = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"题序必须是正整数，收到：{raw!r}") from exc
    if number < 1:
        raise ValueError(f"题序必须是正整数，收到：{number}")
    return number


# ---------------------------------------------------------------------------
# 算分（DoD：score 可重算且 deterministic）
# ---------------------------------------------------------------------------


def compute_homework_score(
    per_problem: Sequence[tuple[int, str, float, float]],
) -> dict:
    """按题求和的确定性算分。

    输入每项 `(ordinal, problem_ref, best_score, max_score)`：
    `best_score` 是该生在此题上的最好得分（0..1），`max_score` 是该题满分。

    返回::

        {
          "total": 8.5,        # 实得总分（各题 best × max 之和，固定精度）
          "max_total": 10.0,   # 满分合计
          "per_problem": [{"ordinal": 1, "ref": "...", "score": 1.0, "max": 5.0}, ...]
        }

    Deterministic 的三道保障：
    1. **先按 ordinal 排序再求和** —— 浮点加法不满足交换律，顺序必须钉死；
    2. **每题先 round 再累加，总和再 round** —— 中间值不携带无限精度；
    3. 输入是显式序列而非 dict —— dict 的插入顺序依赖调用方，序列把
       「顺序是输入的一部分」变成类型上的事实。

    `best_score` 超界（<0 或 >1）抛错而不是 clamp：越界说明上游判分坏了，
    静默截断会把坏分伪装成满分。
    """
    if not per_problem:
        return {"total": 0.0, "max_total": 0.0, "per_problem": []}

    ordered = sorted(per_problem, key=lambda item: item[0])
    total = 0.0
    max_total = 0.0
    detail: list[dict] = []
    for ordinal, ref, best_score, max_score in ordered:
        best = round(float(best_score), _SCORE_DECIMALS)
        cap = round(float(max_score), _SCORE_DECIMALS)
        if best < 0.0 or best > 1.0:
            raise ValueError(f"题 {ref!r} 的最好得分越界（0..1）：{best}")
        if cap < 0.0:
            raise ValueError(f"题 {ref!r} 的满分不能为负：{cap}")
        earned = round(best * cap, _SCORE_DECIMALS)
        total = round(total + earned, _SCORE_DECIMALS)
        max_total = round(max_total + cap, _SCORE_DECIMALS)
        detail.append(
            {"ordinal": ordinal, "ref": ref, "score": earned, "max": cap}
        )

    return {"total": total, "max_total": max_total, "per_problem": detail}


# ---------------------------------------------------------------------------
# scope
# ---------------------------------------------------------------------------


def validate_scope_payload(scope_type: str, scope_id: int | None) -> tuple[str, int]:
    """校验一条 scope：类型合法 + id 为正整数，返回规范化后的二元组。

    scope_id 的语义随类型变化（course_id / class_id / user_id），域层不解读，
    只保证「是正整数」—— 0 和负数对所有类型都是坏的。
    """
    normalized = normalize_scope_type(scope_type)
    if scope_id is None:
        raise ValueError(f"scope 类型 {normalized!r} 必须提供 scope_id")
    if isinstance(scope_id, bool) or int(scope_id) != scope_id or int(scope_id) < 1:
        raise ValueError(f"scope_id 必须是正整数，收到：{scope_id!r}")
    return normalized, int(scope_id)
