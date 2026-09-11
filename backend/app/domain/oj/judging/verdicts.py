"""Run 的状态与判定语义（状态/判定分离）。

背景
----
``models/experiment_model.py`` 的 ``RunOutcome`` 把两种概念塞进同一个枚举：

- ``PENDING`` —— **运行状态**（还没判完）
- ``ACCEPTED`` / ``WRONG_ANSWER`` / … —— **判定结果**（判完了，是什么结论）

这在只有「一次 run 一个结论」时能凑合，但 Activity / Scoreboard 一上来就会卡住：
ICPC 要按判定算罚时、Homework 要按分数求和，两者都需要表达
「这次 run 还在跑」**且**「已经跑出某个结论」——单一枚举无法同时表达。

本模块是 PR-01 的落点：**拆出状态与判定，同时不破坏既有语义**。

兼容策略
--------
- ``RunOutcome`` 成员一个不改，继续作为**聚合结果**枚举供既有读取方使用；
- 新增 ``RunState`` / ``RunVerdict``；
- 提供 ``state_for_outcome()`` / ``verdict_for_outcome()`` 做映射；
- **算分链路只读 ``RunVerdict``。**

本模块**不 import ``app.models``**：入参按值归一化（``getattr(value, "value", value)``），
避免 domain → models 的反向依赖，也避免把 2261 行 service 的导入链拖进来。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

__all__ = [
    "SYSTEM_VERDICTS",
    "TERMINAL_STATES",
    "RunState",
    "RunVerdict",
    "is_system_verdict",
    "is_terminal_state",
    "normalize",
    "state_for_outcome",
    "verdict_for_outcome",
]


class RunState(str, Enum):
    """运行状态：这次运行**走到哪一步了**。

    与判定（``RunVerdict``）正交。一次运行可以是
    「已结束（finished）但没有任何有效判定（system_error 场景下的 internal_error）」。

    注意：``RunOutcome`` 里没有 ``cancelled`` 成员，取消目前由
    ``ExperimentRun.cancel_requested_at`` 表达，映射时据此推导。
    """

    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    SYSTEM_ERROR = "system_error"


class RunVerdict(str, Enum):
    """判定结果：这次运行的**结论是什么**。

    取值与 ``RunOutcome`` 去掉 ``PENDING`` 后的 8 个成员逐一对应，
    保证迁移期映射无损、且不产生第二套判定词汇。
    """

    ACCEPTED = "accepted"
    WRONG_ANSWER = "wrong_answer"
    TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    RUNTIME_ERROR = "runtime_error"
    COMPILATION_ERROR = "compilation_error"
    INTERNAL_ERROR = "internal_error"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"


#: 不可再变化的状态。聚合与排名只看这些状态的行。
TERMINAL_STATES: frozenset[RunState] = frozenset(
    {RunState.FINISHED, RunState.CANCELLED, RunState.SYSTEM_ERROR}
)

#: 系统侧判定（非学生代码结论）。用于把「沙箱挂了」与「代码判错」区分开，
#: 排名与掌握度都不应把这类 run 当作学生的作答结果。
SYSTEM_VERDICTS: frozenset[RunVerdict] = frozenset(
    {RunVerdict.INTERNAL_ERROR, RunVerdict.SANDBOX_UNAVAILABLE}
)

#: 旧 ``RunOutcome`` 中代表「尚未判定」的取值。
_PENDING = "pending"

#: 判定为系统侧故障的旧取值。
_SYSTEM_OUTCOMES = frozenset({"internal_error", "sandbox_unavailable"})


def normalize(value: Any) -> str | None:
    """把 str / Enum / None 归一化为字符串值。"""
    if value is None:
        return None
    raw = getattr(value, "value", value)
    return str(raw)


def _coerce(enum_cls: type, value: Any):
    """把值归一到指定枚举，兼顾 ``.value``（小写）与成员名（大写）。

    见 ``verdict_for_outcome`` 的说明：库里存的是大写成员名，只认小写会静默失配。
    """
    raw = normalize(value)
    if raw is None:
        return None
    try:
        return enum_cls(raw)
    except ValueError:
        pass
    try:
        return enum_cls[raw.upper()]
    except KeyError:
        return None


def verdict_for_outcome(outcome: Any) -> RunVerdict | None:
    """把旧的单一 ``RunOutcome`` 映射为 ``RunVerdict``。

    ``pending``（尚无结论）返回 ``None``；其余取值逐一对应，因此是无损映射。

    **同时接受两种字符串表示**：``.value``（小写，API 与业务层用）与
    **成员名**（大写，PG 原生 enum ``runoutcome`` 在库里的实际存储形式）。
    只认小写是个脚枪——拿到库里的 ``"ACCEPTED"`` 会静默返回 ``None``，
    被读成「还没判完」，进而把已完成的 run 排进待判队列。
    ``RunVerdict`` 的值全小写、成员名全大写，故 ``raw.upper()`` 可统一覆盖两种。

    无法识别的取值同样返回 ``None``（不抛异常，避免历史脏数据阻断读取路径）。
    """
    raw = normalize(outcome)
    if raw is None or raw.lower() == _PENDING:
        return None
    return _coerce(RunVerdict, outcome)


def state_for_outcome(
    outcome: Any,
    *,
    cancel_requested_at: Any = None,
) -> RunState:
    """把旧的单一 ``RunOutcome``（+ 取消时间戳）映射为 ``RunState``。

    判定顺序（先到先得）：

    1. 尚无结论（``pending``）→ 已请求取消则 ``CANCELLED``，否则 ``QUEUED``；
    2. 结论属于系统侧故障（``internal_error`` / ``sandbox_unavailable``）
       → ``SYSTEM_ERROR``；
    3. 其余有结论的取值 → ``FINISHED``。

    这是**回填与兼容期**的映射：迁移里用它把 2 万余行既有 run 一次算好，
    运行时路径由后续 PR 直接写状态。
    """
    raw = normalize(outcome)
    verdict = verdict_for_outcome(outcome)

    if verdict is None:
        if cancel_requested_at is not None:
            return RunState.CANCELLED
        return RunState.QUEUED

    if raw is not None and raw.lower() in _SYSTEM_OUTCOMES:
        return RunState.SYSTEM_ERROR

    return RunState.FINISHED


def is_terminal_state(state: Any) -> bool:
    """该状态是否已不可再变化。"""
    parsed = _coerce(RunState, state)
    return parsed in TERMINAL_STATES if parsed is not None else False


def is_system_verdict(verdict: Any) -> bool:
    """该判定是否属于系统侧故障（非学生代码结论）。"""
    parsed = _coerce(RunVerdict, verdict)
    return parsed in SYSTEM_VERDICTS if parsed is not None else False


# ---------------------------------------------------------------------------
# 判定 → 测试摘要里的 reason 词汇
# ---------------------------------------------------------------------------
#
# 背景：这段映射原先手写在 ``services/experiment_service.py`` 的
# ``_outcome_to_reason()`` 里（10 条分支）。它是一张**判定词汇表**，
# 属于判题域而不是某个业务服务 —— 所以搬到这里，由域统一维护、可单独测试。
#
# ⚠️ 注意 ``ACCEPTED`` 对应的 reason 是 ``"passed"`` 而不是 ``"accepted"``：
# reason 是给 ``ExperimentRun.test_summary[].reason`` 用的**学生可读词汇**，
# 与 ``RunVerdict`` 的值域**不是同一套**，不要"顺手统一"——那会改掉 API 输出。
REASON_BY_STATUS: dict[str, str] = {
    "accepted": "passed",
    "wrong_answer": "wrong_answer",
    "time_limit_exceeded": "time_limit_exceeded",
    "memory_limit_exceeded": "memory_limit_exceeded",
    "runtime_error": "runtime_error",
    "compilation_error": "compilation_error",
    "internal_error": "internal_error",
    "in_queue": "pending",
    "processing": "pending",
    "sandbox_unavailable": "sandbox_unavailable",
}

#: 认不出的判定统一落到这个 reason（保持与迁移前一致）。
UNKNOWN_REASON = "unknown"


def reason_for_status(status: Any) -> str:
    """判定 → ``test_summary[].reason``。

    入参接受 ``SubmissionStatus`` 枚举或裸字符串（``.value`` 或成员名），
    按值归一化，因此本模块**不需要 import provider**，domain 不反向依赖 providers。

    认不出的取值返回 ``UNKNOWN_REASON``，不抛异常 —— 这条路径在处理脏数据时会被走到。
    """
    raw = normalize(status)
    if raw is None:
        return UNKNOWN_REASON
    return REASON_BY_STATUS.get(raw.lower(), UNKNOWN_REASON)
