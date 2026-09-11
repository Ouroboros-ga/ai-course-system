"""OJ 计分板策略：把「每生每题的最好成绩」组装成**确定性**的作业榜。

与 `domain/oj/activity/` 的分工：activity 管「活动是什么、算分公式是什么」，
scoreboard 管「把全班的结果拼成一张可展示、可重算、顺序稳定的榜」。

为什么 ranking_mode="none" 时**不给名次**
------------------------------------------
本期唯一实现的排行模式就是 `none` —— 作业场景里「按学号自然序 + 各人总分」
是教学上正确的形态；名次竞争是 ICPC 的事（PR-15 的 `icpc` 模式，含罚时/
冻结）。**不提前发明名次规则**：作业榜排一个名次出来，教师就会被问
「为什么他 85 排在他 85 前面」—— 没有罚时语义的并列名次是纯负债。

Deterministic 的含义（与 `activity.compute_homework_score` 一脉相承）
--------------------------------------------------------------------
同一组作答数据，**任何时刻、任何调用顺序**重算，整张榜逐字节相同：
- 行序：`ranking_mode="none"` 按学号升序（稳定的自然序，不随插入顺序漂移）；
- 并列：不产生名次（见上），因此无需 tie-break 语义；
- 数值：分数来自域层算分（已固定 6 位精度），这里不再二次 round。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = [
    "BoardRow",
    "assert_scoreboard_supported",
    "build_homework_board",
]


@dataclass(frozen=True)
class BoardRow:
    """榜单一行：一个学生在一张作业榜里的完整成绩。"""

    student_id: int
    total: float
    max_total: float
    per_problem: tuple[dict, ...] = field(default_factory=tuple)
    # 名次。`ranking_mode="none"` 恒为 None（见模块 docstring）。
    rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "student_id": self.student_id,
            "total": self.total,
            "max_total": self.max_total,
            "per_problem": list(self.per_problem),
            "rank": self.rank,
        }


def assert_scoreboard_supported(ranking_mode: str, scoring_mode: str) -> None:
    """未实现的排行/算分模式显式拒绝，与 `activity.assert_supported_type` 同取向。

    `icpc` 是合法词但属 PR-15；`sum` 之外尚无算分模式。静默按作业榜渲染
    会产生「我开的是 icpc 榜怎么没有罚时」这类无从排查的问题。
    """
    if ranking_mode != "none":
        raise ValueError(
            f"排行模式 {ranking_mode!r} 尚未实现（icpc 属 PR-15）；当前仅支持 none"
        )
    if scoring_mode != "sum":
        raise ValueError(f"算分模式 {scoring_mode!r} 尚未实现；当前仅支持 sum")


def build_homework_board(
    scores: Sequence[tuple[int, dict]],
    *,
    ranking_mode: str,
) -> dict[str, Any]:
    """把「(student_id, 该生活动算分结果)」序列组装成作业榜。

    输入的算分结果即 `activity.compute_homework_score` 的返回
    （含 total / max_total / per_problem）。本函数只负责**组装与排序**，
    不碰任何数值。

    - `ranking_mode="none"`：按学号升序，`rank` 全 None；
    - 同一学生出现两行 → 抛错（上游聚合的 bug，静默去重会掩盖）；
    - 空榜合法（还没人作答），返回 `rows: []`。

    返回::

        {"ranking_mode": "none", "rows": [BoardRow.to_dict(), ...], "total_rows": n}
    """
    if ranking_mode != "none":
        # 与 assert_scoreboard_supported 保持同一拒绝面（双保险：直接调 build 也拦）。
        raise ValueError(
            f"排行模式 {ranking_mode!r} 尚未实现（icpc 属 PR-15）；当前仅支持 none"
        )

    seen: set[int] = set()
    for student_id, _score in scores:
        if student_id in seen:
            raise ValueError(f"学生 {student_id} 在榜内出现两行 —— 上游聚合有 bug")
        seen.add(student_id)

    ordered = sorted(scores, key=lambda item: item[0])
    rows = [
        BoardRow(
            student_id=student_id,
            total=score["total"],
            max_total=score["max_total"],
            per_problem=tuple(score["per_problem"]),
            rank=None,
        ).to_dict()
        for student_id, score in ordered
    ]
    return {"ranking_mode": ranking_mode, "rows": rows, "total_rows": len(rows)}
