"""OJ 计分板服务：把一个活动的全班作答聚合成作业榜（PR-11）。

数据聚合职责在这里（谁答了哪题、每题最好分），组装与排序交给
`domain/oj/scoreboard/`。**不读缓存**：与 `compute_student_score` 同源重算，
保证「score 可重算且 deterministic」的 DoD 在榜层面同样成立。

为什么独立成文件：与 activity / problem / attempt 服务同构 —— 一个 bounded
context 一个文件；scoreboard 的读者是教师页（PR-12）与学生 Activity 页，
与作答编排无关。
"""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session as OrmSession, select

from app.domain.oj.scoreboard import (
    assert_scoreboard_supported,
    build_homework_board,
)
from app.models.experiment_activity_model import ExperimentActivity
from app.models.experiment_model import ExperimentAttempt
from app.services.experiment_activity_service import ExperimentActivityService


class ExperimentScoreboardService:
    """作业榜：按活动聚合全班成绩。"""

    def __init__(self, activity_service: Optional[ExperimentActivityService] = None):
        self._activity_service = activity_service or ExperimentActivityService()

    def get_homework_board(
        self,
        session: OrmSession,
        *,
        course_id: int,
        activity_id: str,
    ) -> dict:
        """构建一张作业榜（`ranking_mode="none"`）。

        - 榜的**口径 = finalized attempts**：进行中/未终结的尝试不进榜
          （学生自己能看到尝试，但榜只认终值 —— 与 LearningEvidence 同口径）；
        - draft / archived 活动也允许出榜：教师发布前想预览全班的正式成绩、
          归档后回看，都是合理诉求；**作答闸门**（assert_submission_open）
          与**展示闸门**是两回事；
        - 每行成绩与 `compute_student_score`（单生视图）**同源同式**，
          两个入口重算必然一致。
        """
        activity = self._activity_service.get_activity(
            session, course_id=course_id, activity_id=activity_id
        )
        assert_scoreboard_supported(
            ranking_mode=activity.ranking_mode, scoring_mode=activity.scoring_mode
        )

        problems = self._activity_service.list_problems(
            session, activity_id=activity.activity_id
        )
        scores = self._aggregate_student_scores(
            session, activity=activity, problems=problems
        )
        return build_homework_board(scores, ranking_mode=activity.ranking_mode)

    def _aggregate_student_scores(
        self,
        session: OrmSession,
        *,
        activity: ExperimentActivity,
        problems,
    ) -> list[tuple[int, dict]]:
        """全部参与学生的逐题最好分 → 逐生算分（复用活动域的确定性算分）。

        查询一次拉全活动 finalized attempts，在内存里按 (student, problem)
        分组取最好 —— 学生数 × 题数的查询会随班级规模放大，一次性拉取
        是作业场景（几十人 × 几题）下的正确取舍。
        """
        attempts = list(
            session.exec(
                select(ExperimentAttempt).where(
                    ExperimentAttempt.activity_id == activity.activity_id,  # type: ignore[attr-defined]
                    ExperimentAttempt.status == "finalized",  # type: ignore[arg-type]
                )
            ).all()
        )

        # (student_id, definition_id) -> best final_score
        best: dict[tuple[int, str], float] = {}
        for attempt in attempts:
            if attempt.final_score is None:
                continue
            key = (attempt.student_id, attempt.experiment_id)
            prev = best.get(key)
            if prev is None or attempt.final_score > prev:
                best[key] = attempt.final_score

        # 参与者 = 至少有一条 finalized attempt 的学生（未作答的学生不占行；
        # 「零分也上榜」是 ICPC 语义，作业榜只展示有作答记录的人）。
        student_ids = sorted({sid for sid, _ in best})
        per_problem_ref = {p.problem_definition_id: (p.ordinal, p.max_score) for p in problems}

        scores: list[tuple[int, dict]] = []
        from app.domain.oj.activity import compute_homework_score

        for student_id in student_ids:
            entries = []
            for problem in problems:
                best_score = best.get((student_id, problem.problem_definition_id), 0.0)
                entries.append(
                    (
                        problem.ordinal,
                        problem.problem_definition_id,
                        best_score,
                        problem.max_score,
                    )
                )
            scores.append((student_id, compute_homework_score(entries)))
        _ = per_problem_ref  # 预留：后续按 ordinal 输出列头时使用
        return scores
