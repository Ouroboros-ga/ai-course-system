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

from app.core.exceptions import reject_resource_not_found, reject_validation_failed
from app.models.experiment_activity_model import ExperimentActivityProblem
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentRun,
    ExperimentTestCase,
    ExperimentVersion,
    ExperimentPublishStatus,
)
from app.domain.oj.problems import (
    ProblemSortRecord,
    build_problem_no_index,
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
from app.services.experiment_problem_service import definition_service, version_service

#: 学生侧题目状态。未尝试 / 尝试过（未通过）/ 已通过（存在通过的正式尝试）。
STUDENT_PROBLEM_STATUSES = ("not_attempted", "attempted", "solved")

#: 学生侧题面只有中文一种。B2 把它作为**数据**回给前端（而不是让前端写死
#: 「中文」这两个字），多语言题面落地时只改这里。
STATEMENT_LOCALES = ["zh"]
STATEMENT_DEFAULT_LOCALE = "zh"


def _422_on_error(parser, value):
    """把域层的 ``ValueError`` 翻译成 422。

    域层对非法取值**抛错不兜底**是刻意的（见 `normalize_difficulty` 的 docstring）：
    参数填错必须让调用方知道。这里只负责翻译成 HTTP 语义。
    """
    try:
        return parser(value)
    except ValueError as exc:
        reject_validation_failed(str(exc))
        raise  # 不可达：reject_validation_failed 必定抛 HTTPException。仅为类型收敛。



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
        search_in: Optional[str] = None,
        difficulty: Optional[str] = None,
        difficulty_min: Optional[str] = None,
        difficulty_max: Optional[str] = None,
        tags: Optional[list[str]] = None,
        tag_mode: Optional[str] = None,
        source: Optional[str] = None,
        year: Optional[int] = None,
        status_filter: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """学生题库：已发布题目 + 全班通过率 + 我的作答状态。

        **处理顺序不能调换**：

        ① 拉全量已发布目录 → 建题号索引 → ② 过滤 → ③ 排序 → ④ 分页 → ⑤ 序列化。

        ⚠️ ①必须早于②：题号是「课程内第几题」，拿筛选后的结果编号，一筛选整列
        题号就会平移（域层 `build_problem_no_index` + 前端 `ojTheme.test.js`
        各有一条反向验证用例钉住这点）。
        ⚠️ ③必须早于④：先分页再排序只能排到当前页，跨页排序会给出错误的第一名
        —— 这正是 B1 要修的问题，别再退回服务端只分页、前端排当前页。

        筛选/排序/题号三套规则全部来自 `domain/oj/problems/catalog.py`，
        本方法只负责取数与装配。
        """
        if status_filter is not None and status_filter not in STUDENT_PROBLEM_STATUSES:
            reject_resource_not_found(f"未知状态筛选：{status_filter}")

        scope = _422_on_error(normalize_search_in, search_in)
        match_mode = _422_on_error(normalize_tag_mode, tag_mode)
        order_key = _422_on_error(normalize_sort_by, sort_by)
        order_dir = _422_on_error(normalize_sort_order, sort_order)
        wanted_source = _422_on_error(normalize_source, source)
        wanted_year = _422_on_error(normalize_year, year)

        # `difficulty` 是单值旧参数；min/max 是 B1 的区间参数。两者都接受：
        # 显式给出 min/max 时它们优先，否则单值参数当作「min = max」。
        effective_min = difficulty_min if difficulty_min is not None else difficulty
        effective_max = difficulty_max if difficulty_max is not None else difficulty
        try:
            allowed_difficulty = resolve_difficulty_bounds(effective_min, effective_max)
        except ValueError as exc:
            reject_validation_failed(str(exc))
            raise

        definitions = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.course_id == course_id,
                ExperimentDefinition.publish_status == ExperimentPublishStatus.PUBLISHED,  # type: ignore[attr-defined]
                ExperimentDefinition.visibility == "course_catalog",  # type: ignore[attr-defined]
            )
        ).all()

        # ① 题号索引 —— 必须来自**未过滤**的全量目录。
        no_index = build_problem_no_index(d.experiment_id for d in definitions)

        # 全班通过率：一次聚合，避免 N+1。
        stats = self._course_attempt_stats(session, course_id=course_id)
        mine = self._my_attempt_summary(session, course_id=course_id, student_id=student_id)

        records: list[ProblemSortRecord] = []
        payload_by_no: dict[str, dict] = {}
        for d in definitions:
            if not matches_search(
                title=d.title,
                description=d.description,
                keyword=search,
                scope=scope,
            ):
                continue
            if allowed_difficulty is not None and str(d.difficulty or "") not in allowed_difficulty:
                continue
            if not matches_tags(d.tags, tags, match_mode):
                continue
            if wanted_source is not None and str(d.source or "").casefold() != wanted_source.casefold():
                continue
            if wanted_year is not None and d.year != wanted_year:
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

            sequence = no_index.get(d.experiment_id, 0)
            problem_no = format_problem_no(sequence)
            pass_rate = round(passed_total / attempt_total, 4) if attempt_total else None

            records.append(ProblemSortRecord(
                problem_no=sequence,
                title=d.title,
                difficulty=d.difficulty,
                pass_rate=pass_rate,
                attempt_total=attempt_total,
            ))
            payload_by_no[problem_no] = {
                "experiment_id": d.experiment_id,
                # 题号由服务端给定即为权威；前端仅在同名字段缺失时降级派生。
                "problem_no": problem_no,
                "sort_index": sequence,
                "title": d.title,
                "description": d.description,
                "difficulty": d.difficulty,
                # tags 就是「显示算法标签」列的数据源（不另开 algorithm_tags 列，
                # 理由见迁移 20260913_1200_oj_problem_source.py 的 docstring）。
                "tags": list(d.tags or []),
                "source": d.source,
                "year": d.year,
                "pass_rate": pass_rate,
                "attempt_total": attempt_total,
                "my_status": my_status,
                "my_best_score": my.get("best_score"),
            }

        # ③ 排序在**全量命中集**上做，④ 才分页。
        ordered = sort_records_with(records, sort_by=order_key, sort_order=order_dir)
        items = [payload_by_no[format_problem_no(record.problem_no)] for record in ordered]

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

        **不含隐藏 testcase**（隐藏的不给 —— 用例明细属于教师资产；
        学生侧的评测解读走 diagnosis 通道）。**公开样例给**：
        `is_hidden=False` 的用例即教师标为公开的示例，按原样透出
        输入/输出（OJ 惯例；前端样例区靠它渲染，否则恒空）。

        B2（2026-09-13）补充：题号 / 来源 / 年份 / 题面语言，以及样例的稳定
        `sample_id`（题面「运行」按钮的幂等键）。题号与列表页**同一套派生规则**
        （未过滤的课程目录 + code-point 升序），否则会出现「列表 #007、点进去 #009」。
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
        samples: list[dict] = []
        if version is not None:
            raw = getattr(version, "starter_code", None)
            starter_code = dict(raw) if isinstance(raw, dict) else {}
            limits = {
                "cpu_time_limit": version.cpu_time_limit,
                "memory_limit": version.memory_limit,
                "wall_time_limit": version.wall_time_limit,
            }
            # 公开样例（is_hidden=False）——设计稿②「样例」区：学生靠样例理解
            # 输入输出格式。隐藏用例绝不返回（防作弊红线）。
            # `sample_id` 用 `case_id`：它是稳定主键，样例「运行」要拿它做幂等键；
            # 用列表下标当 id 的话，教师调整用例顺序会让所有样例 id 平移。
            for case in session.exec(
                select(ExperimentTestCase).where(
                    ExperimentTestCase.version_id == version.version_id,
                    ExperimentTestCase.is_hidden == False,  # noqa: E712
                )
            ).all():
                samples.append({
                    "sample_id": case.case_id,
                    "name": case.case_name,
                    "input": case.stdin,
                    "output": case.expected_stdout,
                })

        my = self._my_attempt_summary(
            session, course_id=course_id, student_id=student_id
        ).get(experiment_id, {"attempted": False, "solved": False, "best_score": None})
        attempt_total, passed_total = self._course_attempt_stats(
            session, course_id=course_id
        ).get(experiment_id, (0, 0))

        return {
            "experiment_id": definition.experiment_id,
            "problem_no": self._problem_no_for_course(
                session, course_id=course_id, experiment_id=definition.experiment_id
            ),
            "source": definition.source,
            "year": definition.year,
            "statement_locales": list(STATEMENT_LOCALES),
            "statement_default_locale": STATEMENT_DEFAULT_LOCALE,
            "title": definition.title,
            "description": definition.description,
            "difficulty": definition.difficulty,
            "tags": list(definition.tags or []),
            "language_whitelist": list(definition.language_whitelist or []),
            "limits": limits,
            "starter_code": starter_code,
            "samples": samples,
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
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[dict]]:
        """我的提交记录（只含本人 runs）。结果筛选接受 outcome 值（accepted 等）。

        `date_from` / `date_to`：YYYY-MM-DD（含端点），按提交时间过滤。

        返回 ``(total, items)``：total 是**全部命中数**（分页前），不是截断后的
        条数 —— 前端分页器靠它算总页数，撒谎的 total 会把后页吞掉。
        """
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

        # 时间范围（YYYY-MM-DD 含端点，UTC 口径）。DB 时间可能是 naive ——
        # 用 to_aware 归一后比较，避免 naive/aware TypeError（PR-01 同款坑）。
        from datetime import datetime as dt, timedelta, timezone

        from app.core.time_utils import to_aware

        def _parse_day(value: Optional[str], end: bool = False) -> Optional[dt]:
            if not value:
                return None
            parsed = dt.strptime(value.strip(), "%Y-%m-%d")
            if end:
                parsed += timedelta(days=1) - timedelta(seconds=1)
            return parsed.replace(tzinfo=timezone.utc)

        day_from = _parse_day(date_from)
        day_to = _parse_day(date_to, end=True)

        for r in rows:
            outcome_value = str(getattr(r.outcome, "value", r.outcome) or "").lower()
            if wanted and outcome_value != wanted:
                continue
            if language is not None and r.language != language:
                continue
            if day_from or day_to:
                submitted = to_aware(r.submitted_at) if r.submitted_at else None
                if submitted is None:
                    continue
                if day_from and submitted < day_from:
                    continue
                if day_to and submitted > day_to:
                    continue
            items.append(
                self._serialize_run(
                    r, outcome_value, exp_by_attempt.get(r.attempt_id)
                )
            )
        total = len(items)
        start = max(0, offset)
        return total, items[start:start + max(1, min(limit, 200))]

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

    def _catalog_experiment_ids(self, session: OrmSession, *, course_id: int) -> list[str]:
        """课程内**已发布**目录的 experiment_id 列表 —— 题号派生的唯一顺序源。

        用 `experiment_id` 而不是 `created_at`：后者会被回填、会被时区归一改动，
        历史行之间的相对顺序不可靠；前者是主键，永不变更。
        """
        return [
            str(item)
            for item in session.exec(
                select(ExperimentDefinition.experiment_id).where(
                    ExperimentDefinition.course_id == course_id,
                    ExperimentDefinition.publish_status == ExperimentPublishStatus.PUBLISHED,  # type: ignore[attr-defined]
                    ExperimentDefinition.visibility == "course_catalog",  # type: ignore[attr-defined]
                )
            ).all()
        ]

    def _problem_no_for_course(
        self, session: OrmSession, *, course_id: int, experiment_id: str
    ) -> str:
        """单题题号。

        与列表页共用 `build_problem_no_index` 的同一规则 —— 详情页自己算一套
        「按创建时间排」是这类 bug 的经典来源（列表 #007、点进去 #009）。
        """
        return problem_no_for(
            build_problem_no_index(self._catalog_experiment_ids(session, course_id=course_id)),
            experiment_id,
        )

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
        """我的维度：experiment_id -> {attempted, solved, best_score}。

        attempted = 存在过非 CANCELLED 尝试。CANCELLED 不算碰过
        （与 max_attempts 计数口径一致）；SUBMITTED / FAILED 照算碰过 ——
        交过卷pending终结、判题失败都是"尝试过"，标"未尝试"会骗学生重开一题。
        """
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
            status_value = str(getattr(a.status, "value", a.status) or "")
            if status_value == "cancelled":
                continue
            item["attempted"] = True
            if status_value == "finalized":
                if a.passed:
                    item["solved"] = True
                if a.final_score is not None:
                    if item["best_score"] is None or a.final_score > item["best_score"]:
                        item["best_score"] = a.final_score
        return summary
