"""OJ 学情聚合服务（PR-14 缩范围版）：只用现有数据源可确定计算的指标。

**刻意不做**（数据源不存在，做即造假）：知识掌握雷达、题目质量反馈、
活跃率（无登录/学习时长采集）、签到与热力图、班级对比（单班部署常态）。

口径（与 scoreboard / 正式证据一致）：
- 提交次数 = `ExperimentRun` 全量（含测试运行）；
- 通过率 = finalized attempts 的 passed 比例；
- 高频错题 = 非通过运行数最多的题目（按 finalized 之外的全部 run 计）；
- 需要关注的学生 = 交过卷但通过题数为 0（finalized>0 且 passed==0），
  或最近 7 天无终结记录的在册学生。从未作答的在册学生不进名单
  （那是点名册问题不是学情问题；ever_submitted 照常返回供前端区分）。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlmodel import Session as OrmSession, select

from app.core.time_utils import to_aware, utcnow_aware
from app.models.course_model import StudentEnrollment
from app.models.coding_diagnosis_model import CodingDiagnosisRecord
from app.models.experiment_activity_model import ExperimentActivityProblem
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentRun,
)


class ExperimentAnalyticsService:
    """OJ 学情看板聚合（教师侧）。"""

    def get_course_summary(
        self,
        session: OrmSession,
        *,
        course_id: int,
        trend_days: int = 30,
    ) -> dict:
        now = utcnow_aware()
        trend_since = now - timedelta(days=trend_days)

        student_count = int(
            session.exec(
                select(func.count(StudentEnrollment.id)).where(
                    StudentEnrollment.course_id == course_id,
                    StudentEnrollment.is_active == True,  # noqa: E712
                )
            ).one()
        )

        run_rows = list(
            session.exec(
                select(ExperimentRun).where(ExperimentRun.course_id == course_id)
            ).all()
        )
        submission_count = len(run_rows)

        attempt_rows = list(
            session.exec(
                select(ExperimentAttempt).where(
                    ExperimentAttempt.course_id == course_id,
                    ExperimentAttempt.status == "finalized",  # type: ignore[arg-type]
                )
            ).all()
        )
        finalized_total = len(attempt_rows)
        finalized_passed = sum(1 for a in attempt_rows if a.passed)
        pass_rate = (
            round(finalized_passed / finalized_total, 4) if finalized_total else None
        )

        # 提交趋势：按日（近 N 天，含 0 的天也输出，前端画图不断线）
        trend: list[dict] = []
        by_day: dict[str, dict[str, int]] = {}
        for run in run_rows:
            # ⚠️ PG 的 DateTime 列返回 naive（PR-01 同款坑）——与 aware 的
            # trend_since 比较前必须归一到 aware，否则 TypeError → 500。
            if run.submitted_at is None:
                continue
            submitted = to_aware(run.submitted_at)
            if submitted < trend_since:
                continue
            day = submitted.date().isoformat()
            bucket = by_day.setdefault(day, {"submissions": 0, "accepted": 0})
            bucket["submissions"] += 1
            outcome_value = str(getattr(run.outcome, "value", run.outcome) or "").lower()
            if outcome_value == "accepted":
                bucket["accepted"] += 1
        for offset in range(trend_days - 1, -1, -1):
            day = (now - timedelta(days=offset)).date().isoformat()
            bucket = by_day.get(day, {"submissions": 0, "accepted": 0})
            trend.append({"date": day, **bucket})

        # 高频错题：非通过（且已判定的）运行数降序，取前 5。
        # run 不直接挂 experiment —— 经 attempt 关联解析（与教师流水同一方式）。
        # 注意：ExperimentRun 没有 experiment_id 列，直接读会 AttributeError
        # 把整端点打成 500（有任一 WA/TLE… 运行即炸）。
        attempt_ids = {run.attempt_id for run in run_rows}
        exp_by_attempt: dict[str, str] = {}
        if attempt_ids:
            for attempt in session.exec(
                select(ExperimentAttempt).where(
                    ExperimentAttempt.attempt_id.in_(attempt_ids)  # type: ignore[attr-defined]
                )
            ).all():
                exp_by_attempt[attempt.attempt_id] = attempt.experiment_id
        wrong_by_problem: dict[str, int] = {}
        for run in run_rows:
            outcome_value = str(getattr(run.outcome, "value", run.outcome) or "").lower()
            if outcome_value in ("accepted", "pending"):
                continue
            experiment_id = exp_by_attempt.get(run.attempt_id)
            if not experiment_id:
                continue
            wrong_by_problem[experiment_id] = wrong_by_problem.get(experiment_id, 0) + 1

        # 诊断记录的 error_class 分布（有 diagnosis 数据才有；没有如实给空）
        diagnosis_rows = list(
            session.exec(
                select(CodingDiagnosisRecord).where(
                    CodingDiagnosisRecord.course_id == course_id
                )
            ).all()
        )
        error_class_counts: dict[str, int] = {}
        for record in diagnosis_rows:
            key = record.error_class or "unknown"
            error_class_counts[key] = error_class_counts.get(key, 0) + 1

        top_wrong = sorted(wrong_by_problem.items(), key=lambda kv: -kv[1])[:5]
        problem_titles = {
            d.experiment_id: d.title
            for d in session.exec(
                select(ExperimentDefinition).where(
                    ExperimentDefinition.course_id == course_id
                )
            ).all()
        }
        high_frequency_wrong = [
            {
                "experiment_id": experiment_id,
                "title": problem_titles.get(experiment_id, experiment_id),
                "wrong_count": count,
            }
            for experiment_id, count in top_wrong
        ]

        # 需要关注的学生：在册学生 × 其终结情况
        per_student: dict[int, dict] = {}
        for attempt in attempt_rows:
            item = per_student.setdefault(
                attempt.student_id, {"finalized": 0, "passed": 0, "last_finalized": None}
            )
            item["finalized"] += 1
            if attempt.passed:
                item["passed"] += 1
            stamp = attempt.finalized_at or attempt.submitted_at
            if stamp is None:
                continue
            stamp = to_aware(stamp)
            if item["last_finalized"] is None or stamp > item["last_finalized"]:
                item["last_finalized"] = stamp

        run_students = {run.student_id for run in run_rows}
        enrolled = set(
            session.exec(
                select(StudentEnrollment.student_id).where(
                    StudentEnrollment.course_id == course_id,
                    StudentEnrollment.is_active == True,  # noqa: E712
                )
            ).all()
        )
        attention: list[dict] = []
        for student_id in sorted(enrolled):
            item = per_student.get(student_id)
            last = item["last_finalized"] if item else None
            idle_days = (
                int((to_aware(now) - to_aware(last)).days) if last else None
            )
            finalized_count = item["finalized"] if item else 0
            passed_count = item["passed"] if item else 0
            # passed==0 必须以"交过卷"为前提，否则全班未作答新生全进名单成噪音。
            needs = (finalized_count > 0 and passed_count == 0) or (
                idle_days is not None and idle_days >= 7
            )
            if not needs:
                continue
            attention.append({
                "student_id": student_id,
                "finalized_count": finalized_count,
                "passed_count": passed_count,
                "idle_days": idle_days,
                "ever_submitted": student_id in run_students,
            })

        # ── 难度分布（设计稿⑥「难度分布正确率」缩水版）：按已发布题的难度
        # 聚合 finalized 尝试数与通过数。仅覆盖**已发布**题（草稿题没有教学意义）。
        published_defs = list(
            session.exec(
                select(ExperimentDefinition).where(
                    ExperimentDefinition.course_id == course_id,
                )
            ).all()
        )
        attempt_by_exp: dict[str, dict[str, int]] = {}
        for attempt in attempt_rows:
            item = attempt_by_exp.setdefault(
                attempt.experiment_id, {"attempts": 0, "passed": 0}
            )
            item["attempts"] += 1
            if attempt.passed:
                item["passed"] += 1

        difficulty_distribution: dict[str, dict[str, Any]] = {}
        for definition in published_defs:
            if definition.publish_status != "published":
                continue
            bucket = difficulty_distribution.setdefault(
                definition.difficulty or "unknown",
                {"problems": 0, "attempt_total": 0, "passed_total": 0},
            )
            bucket["problems"] += 1
            stats = attempt_by_exp.get(definition.experiment_id) or {}
            bucket["attempt_total"] += stats.get("attempts", 0)
            bucket["passed_total"] += stats.get("passed", 0)

        # ── 逐题统计（教师题目管理「使用次数」列 + 看板通过率列用） ──
        problem_stats = [
            {
                "experiment_id": definition.experiment_id,
                "title": definition.title,
                "difficulty": definition.difficulty,
                "publish_status": definition.publish_status,
                "attempt_total": (attempt_by_exp.get(definition.experiment_id) or {}).get("attempts", 0),
                "passed_total": (attempt_by_exp.get(definition.experiment_id) or {}).get("passed", 0),
            }
            for definition in published_defs
        ]

        return {
            "course_id": course_id,
            "student_count": student_count,
            "submission_count": submission_count,
            "finalized_total": finalized_total,
            "finalized_passed": finalized_passed,
            "pass_rate": pass_rate,
            "trend": trend,
            "high_frequency_wrong": high_frequency_wrong,
            "error_class_counts": error_class_counts,
            "students_needing_attention": attention,
            "difficulty_distribution": difficulty_distribution,
            "problem_stats": problem_stats,
            "generated_at": now.isoformat(),
        }

    def get_activity_problem_counts(
        self, session: OrmSession, *, activity_ids: list[str]
    ) -> dict[str, int]:
        """活动 -> 挂题数（看板活动概览用）。"""
        if not activity_ids:
            return {}
        rows = session.exec(
            select(
                ExperimentActivityProblem.activity_id,
                func.count(ExperimentActivityProblem.id),
            ).where(
                ExperimentActivityProblem.activity_id.in_(activity_ids)  # type: ignore[attr-defined]
            ).group_by(ExperimentActivityProblem.activity_id)
        ).all()
        return {activity_id: int(count) for activity_id, count in rows}
