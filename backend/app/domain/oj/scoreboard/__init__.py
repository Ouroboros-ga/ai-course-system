"""OJ 计分板子域（`scoreboard`）。

PR-11：作业榜（HomeworkScoreboard）。只放纯规则 —— 榜的组装与排序；
数据聚合（谁答了哪题、最好分）在 `services/experiment_scoreboard_service.py`。

`icpc` 排行（罚时 / 冻结 / 名次）属 PR-15，本包值域已收窄到 `none`。
"""
from app.domain.oj.scoreboard.policy import (
    BoardRow,
    assert_scoreboard_supported,
    build_homework_board,
)

__all__ = [
    "BoardRow",
    "assert_scoreboard_supported",
    "build_homework_board",
]
