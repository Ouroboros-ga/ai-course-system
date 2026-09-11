"""OJ 学生题库 façade（PR-10 后端半部）：学生侧的题库 / 题目详情 / 我的提交。

「façade」的含义：**只聚合既有链路，不开新能力**。题目来自已发布的
`ExperimentDefinition`（course_catalog + PUBLISHED，与教师管理页同一份资产，
不建第二套题库 —— ADR ①）；作答状态来自学生自己的 attempts；提交记录来自
学生自己的 runs。本模块**不做任何判题/写操作**。

安全边界（与既有约束一致，这里单点再钉一遍）：
- 学生只能看到 PUBLISHED 的课程目录题（draft / archived 一律 404，防探测）；
- 提交记录按 token 里的学生过滤，**别人的 run 一律 404**（不透露存在性）；
- 本 façade 不返回任何 testcase（含非隐藏的）—— 用例细节是教师资产；
  评测解读走既有的 diagnosis / explanation 通道。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import case, func
from sqlmodel import Session as OrmSession, select

from app.core.exceptions import reject_resource_not_found
from app.models.experiment_activity_model import ExperimentActivityProblem
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentRun,
    ExperimentVersion,
    ExperimentPublishStatus,
)
from app.services.experiment_problem_service import definition_service, version_service

#: 学生侧题目状态。未尝试 / 尝试过（未通过）/ 已通过（存在通过的正式尝试）。
STUDENT_PROBLEM_STATUSES = ("not_attempted", "attempted", "solved")


class ExperimentStudentService:
    """学生侧题库与提交记录的只读聚合。"""

    # ------------------------------------------------------------------
    # 题库列表
    # ------------------------------------------------------------------

    def list_problem_bank(
        self,
        session: OrmSession,
        *,
        course_id: int,
        student_id: int,
        search: Optional[str] = None,
        difficulty: Optional[str] = None,
        tags: Optional[list[str]] = None,
        status_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """学生题库：已发布题目 + 全班通过率 + 我的作答状态。

        标签筛选在 Python 侧做（JSON 列无法直接索引；课程目录题量级为几十，
        内存过滤是正确取舍）。返回结构与分页元数据一并提供。
        """
        if status_filter is not None and status_filter not in STUDENT_PROBLEM_STATUSES:
            reject_resource_not_found(f"未知状态筛选：{status_filter}")

        definitions = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.course_id == course_id,
                ExperimentDefinition.publish_status == ExperimentPublishStatus.PUBLISHED,  # type: ignore[attr-defined]
                ExperimentDefinition.visibility == "course_catalog",  # type: ignore[attr-defined]
            )
        ).all()

        # 全班通过率：一次聚合，避免 N+1。
        stats = self._course_attempt_stats(session, course_id=course_id)
        mine = self._my_attempt_summary(session, course_id=course_id, student_id=student_id)

        items: list[dict] = []
        for d in definitions:
            if search and search.strip() and search.strip().lower() not in d.title.lower():
                continue
            if difficulty is not None and d.difficulty != difficulty.strip().lower():
                continue
            if tags:
                d_tags = {str(t).strip().lower() for t in (d.tags or [])}
                if not all(str(t).strip().lower() in d_tags for t in tags):
                    continue

            attempt_total, passed_total = stats.get(d.experiment_id, (0, 0))
            my = mine.get(d.experiment_id, {"attempted": False, "solved": False})
            my_status = (
                "solved" if my["solved"]
                else "attempted" if my["attempted"]
                else "not_attempted"
            )
            if status_filter is not None and my_status != status_filter:
                continue

            items.append({
                "experiment_id": d.experiment_id,
                "title": d.title,
                "description": d.description,
                "difficulty": d.difficulty,
                "tags": list(d.tags or []),
                "pass_rate": round(passed_total / attempt_total, 4) if attempt_total else None,
                "attempt_total": attempt_total,
                "my_status": my_status,
                "my_best_score": my.get("best_score"),
            })

        total = len(items)
        start = (page - 1) * page_size
        return {
            "items": items[start:start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # 题目详情（学生视角）
    # ------------------------------------------------------------------

    def get_student_problem(
        self,
        session: OrmSession,
        *,
        course_id: int,
        student_id: int,
        experiment_id: str,
    ) -> dict:
        """学生题目详情：公开面（题面/限制/起始代码）+ 我的作答摘要。

        **不含任何 testcase**（隐藏的不给，非隐藏的也不在此给 —— 用例明细
        属于教师资产；学生侧的评测解读走 diagnosis 通道）。
        """
        definition = definition_service.get_definition(
            session, course_id=course_id, experiment_id=experiment_id
        )
        if (
            definition.publish_status != ExperimentPublishStatus.PUBLISHED  # type: ignore[attr-defined]
            or definition.visibility != "course_catalog"  # type: ignore[attr-defined]
        ):
            # 与题库列表同一可见性 —— draft/archived 对学生即不存在。
            reject_resource_not_found(f"题目 {experiment_id} 不存在")

        version = None
        if definition.default_version_id:
            version = session.exec(
                select(ExperimentVersion).where(
                    ExperimentVersion.version_id == definition.default_version_id
                )
            ).first()

        starter_code: dict = {}
        limits = {"cpu_time_limit": None, "memory_limit": None, "wall_time_limit": None}
        if version is not None:
            raw = getattr(version, "starter_code", None)
            starter_code = dict(raw) if isinstance(raw, dict) else {}
            limits = {
                "cpu_time_limit": version.cpu_time_limit,
                "memory_limit": version.memory_limit,
                "wall_time_limit": version.wall_time_limit,
            }

        my = self._my_attempt_summary(
            session, course_id=course_id, student_id=student_id
        ).get(experiment_id, {"attempted": False, "solved": False, "best_score": None})
        attempt_total, passed_total = self._course_attempt_stats(
            session, course_id=course_id
        ).get(experiment_id, (0, 0))

        return {
            "experiment_id": definition.experiment_id,
            "title": definition.title,
            "description": definition.description,
            "difficulty": definition.difficulty,
            "tags": list(definition.tags or []),
            "language_whitelist": list(definition.language_whitelist or []),
            "limits": limits,
            "starter_code": starter_code,
            "knowledge_node_ids": list(definition.knowledge_node_ids or []),
            "stats": {
                "attempt_total": attempt_total,
                "passed_total": passed_total,
                "pass_rate": (
                    round(passed_total / attempt_total, 4) if attempt_total else None
                ),
            },
            "my_status": (
                "solved" if my["solved"]
                else "attempted" if my["attempted"]
                else "not_attempted"
            ),
            "my_best_score": my.get("best_score"),
        }

    # ------------------------------------------------------------------
    # 我的提交
    # ------------------------------------------------------------------

    def list_my_submissions(
        self,
        session: OrmSession,
        *,
        course_id: int,
        student_id: int,
        experiment_id: Optional[str] = None,
        outcome: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """我的提交记录（只含本人 runs）。结果筛选接受 outcome 值（accepted 等）。"""
        # run 不直接挂 experiment —— 经 attempt 关联（attempt.experiment_id）。
        stmt = select(ExperimentRun).where(
            ExperimentRun.course_id == course_id,
            ExperimentRun.student_id == student_id,
        )
        if experiment_id is not None:
            stmt = stmt.join(  # type: ignore[arg-type]
                ExperimentAttempt,
                ExperimentAttempt.attempt_id == ExperimentRun.attempt_id,
            ).where(ExperimentAttempt.experiment_id == experiment_id)
        rows = list(session.exec(stmt.order_by(  # type: ignore[arg-type]
            ExperimentRun.submitted_at.desc()  # type: ignore[attr-defined]
        )).all())

        # 一次取回相关 attempt，解析每条 run 的题目归属
        attempt_ids = {r.attempt_id for r in rows}
        exp_by_attempt: dict[str, str] = {}
        if attempt_ids:
            for a in session.exec(
                select(ExperimentAttempt).where(
                    ExperimentAttempt.attempt_id.in_(attempt_ids)  # type: ignore[attr-defined]
                )
            ).all():
                exp_by_attempt[a.attempt_id] = a.experiment_id

        items = []
        wanted = outcome.strip().lower() if outcome else None
        for r in rows:
            outcome_value = str(getattr(r.outcome, "value", r.outcome) or "").lower()
            if wanted and outcome_value != wanted:
                continue
            if language is not None and r.language != language:
                continue
            items.append(
                self._serialize_run(
                    r, outcome_value, exp_by_attempt.get(r.attempt_id)
                )
            )
            if len(items) >= max(1, min(limit, 200)):
                break
        return items

    def get_my_submission(
        self,
        session: OrmSession,
        *,
        course_id: int,
        student_id: int,
        run_id: str,
    ) -> dict:
        """单条提交详情。**只认本人 run**：别人的 404，不透露存在性。"""
        run = session.exec(
            select(ExperimentRun).where(
                ExperimentRun.run_id == run_id,
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
            )
        ).first()
        if run is None:
            reject_resource_not_found(f"提交 {run_id} 不存在")
        attempt = session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.attempt_id == run.attempt_id
            )
        ).first()
        outcome_value = str(getattr(run.outcome, "value", run.outcome) or "").lower()
        return self._serialize_run(
            run, outcome_value, attempt.experiment_id if attempt else None
        )

    # ------------------------------------------------------------------
    # 内部聚合
    # ------------------------------------------------------------------

    def _serialize_run(
        self, run: ExperimentRun, outcome_value: str, experiment_id: Optional[str]
    ) -> dict:
        return {
            "run_id": run.run_id,
            "experiment_id": experiment_id,
            "attempt_id": run.attempt_id,
            "activity_id": run.activity_id,
            "language": run.language,
            "outcome": outcome_value,
            "run_state": run.run_state,
            "score": run.score,
            "passed_count": run.passed_count,
            "total_count": run.total_count,
            "cpu_time_ms": run.cpu_time_ms,
            "wall_time_ms": run.wall_time_ms,
            "memory_kb": run.memory_kb,
            "submitted_at": run.submitted_at.isoformat() if run.submitted_at else None,
        }

    def _course_attempt_stats(
        self, session: OrmSession, *, course_id: int
    ) -> dict[str, tuple[int, int]]:
        """全班维度：(experiment_id -> (finalized 总数, 通过数))，一次聚合。"""
        rows = session.exec(
            select(
                ExperimentAttempt.experiment_id,
                func.count(ExperimentAttempt.id),
                func.sum(case((ExperimentAttempt.passed == True, 1), else_=0)),  # noqa: E712
            ).where(
                ExperimentAttempt.course_id == course_id,
                ExperimentAttempt.status == "finalized",  # type: ignore[arg-type]
            ).group_by(ExperimentAttempt.experiment_id)
        ).all()
        return {
            experiment_id: (int(total or 0), int(passed or 0))
            for experiment_id, total, passed in rows
        }

    def _my_attempt_summary(
        self, session: OrmSession, *, course_id: int, student_id: int
    ) -> dict[str, dict]:
        """我的维度：experiment_id -> {attempted, solved, best_score}。"""
        rows = session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.course_id == course_id,
                ExperimentAttempt.student_id == student_id,
            )
        ).all()
        summary: dict[str, dict] = {}
        for a in rows:
            item = summary.setdefault(
                a.experiment_id, {"attempted": False, "solved": False, "best_score": None}
            )
            if a.status == "in_progress":
                item["attempted"] = True
            if a.status == "finalized":
                item["attempted"] = True
                if a.passed:
                    item["solved"] = True
                if a.final_score is not None:
                    if item["best_score"] is None or a.final_score > item["best_score"]:
                        item["best_score"] = a.final_score
        return summary
