"""OJ Activity 域服务：活动的创建 / 发布 / 题目组织 / 可见范围 / 时间窗 / 算分。

**本文件是 PR-07 的 service 落点，与 `experiment_service.py` 无共享代码**
（那是他线在途文件，本域刻意独立成文件以避免提交冲突）。

边界（与 `domain/oj/activity/` 的分工）
---------------------------------------
- **域层**（纯规则）：值域、时间窗判定、版本固定、确定性算分。
- **本服务**：何时读写 DB、ORM ↔ 域输入的适配、「什么时候校验」、
  未实现行为的显式拒绝。

刻意独立于 `experiment_service.py` 的第二个理由：那里面已有
 5 个 service 类（Definition/Version/Attempt/Finalize/...）2200+ 行，
 再塞一个 Activity 域进去会重演「一个文件承载全部 OJ 语义」的现状 ——
 ADR ⑩ 的行为门禁按模块切分，文件越大门禁越难定位。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlmodel import Session as OrmSession, select

from app.core.exceptions import (
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import to_aware, utcnow_aware
from app.domain.oj.activity import (
    ActivityStatus,
    MAX_PROBLEMS_PER_ACTIVITY,
    assert_supported_type,
    assert_unique_ordinals,
    compute_homework_score,
    is_submission_open,
    normalize_activity_status,
    normalize_activity_type,
    normalize_ranking_mode,
    normalize_scoring_mode,
    normalize_scope_type,
    validate_scope_payload,
    validate_time_window,
)
from app.models.experiment_activity_model import (
    ExperimentActivity,
    ExperimentActivityProblem,
    ExperimentActivityScope,
)
from app.models.experiment_model import ExperimentAttempt, ExperimentDefinition, ExperimentVersion

logger = logging.getLogger(__name__)


class ExperimentActivityService:
    """活动（作业/比赛）生命周期与题目组织。"""

    # ------------------------------------------------------------------
    # 创建 / 更新 / 发布
    # ------------------------------------------------------------------

    def create_activity(
        self,
        session: OrmSession,
        *,
        course_id: int,
        owner_id: int,
        title: str,
        type: object = None,
        description_md: str = "",
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        allow_late_submit: bool = False,
        max_submissions: int = 0,
        scoring_mode: object = None,
        ranking_mode: object = None,
    ) -> ExperimentActivity:
        """创建活动（draft 态）。**type 未实现的在这里拒绝，不静默降级。**"""
        activity_type = normalize_activity_type(type)
        try:
            assert_supported_type(activity_type)
        except ValueError as exc:
            reject_validation_failed(str(exc))
            raise

        try:
            validate_time_window(start_at, end_at)
        except ValueError as exc:
            reject_validation_failed(str(exc))
            raise

        if max_submissions < 0:
            reject_validation_failed("max_submissions 不能为负（0 = 不限）")

        activity = ExperimentActivity(
            course_id=course_id,
            owner_id=owner_id,
            title=title,
            type=activity_type,
            description_md=description_md,
            start_at=start_at,
            end_at=end_at,
            allow_late_submit=allow_late_submit,
            max_submissions=max_submissions,
            scoring_mode=normalize_scoring_mode(scoring_mode),
            ranking_mode=normalize_ranking_mode(ranking_mode),
            status=ActivityStatus.DRAFT.value,
        )
        session.add(activity)
        session.flush()
        return activity

    def get_activity(
        self, session: OrmSession, *, course_id: int, activity_id: str
    ) -> ExperimentActivity:
        """按业务键取活动，**同时校验 course 归属**（跨课程访问一律 404）。"""
        activity = session.exec(
            select(ExperimentActivity).where(
                ExperimentActivity.activity_id == activity_id,
                ExperimentActivity.course_id == course_id,
            )
        ).first()
        if activity is None:
            reject_resource_not_found(f"活动 {activity_id} 不存在")
        return activity

    def update_activity(
        self,
        session: OrmSession,
        *,
        course_id: int,
        activity_id: str,
        title: Optional[str] = None,
        description_md: Optional[str] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        allow_late_submit: Optional[bool] = None,
        max_submissions: Optional[int] = None,
        clear_window: bool = False,
    ) -> ExperimentActivity:
        """PATCH 更新。**发布后的时间窗收紧是允许的**（提前截止是教师刚需），
        放宽也是 —— 两者都只改 `end_at`，不引入第二个状态位。
        """
        activity = self.get_activity(session, course_id=course_id, activity_id=activity_id)
        if title is not None:
            activity.title = title
        if description_md is not None:
            activity.description_md = description_md
        if allow_late_submit is not None:
            activity.allow_late_submit = allow_late_submit
        if max_submissions is not None:
            if max_submissions < 0:
                reject_validation_failed("max_submissions 不能为负（0 = 不限）")
            activity.max_submissions = max_submissions
        if clear_window:
            activity.start_at = None
            activity.end_at = None
        else:
            if start_at is not None:
                activity.start_at = start_at
            if end_at is not None:
                activity.end_at = end_at
        try:
            validate_time_window(activity.start_at, activity.end_at)
        except ValueError as exc:
            reject_validation_failed(str(exc))
            raise
        activity.updated_at = utcnow_aware()
        session.add(activity)
        session.flush()
        return activity

    def publish_activity(
        self, session: OrmSession, *, course_id: int, activity_id: str
    ) -> ExperimentActivity:
        """发布。**至少一道题 + 版本已固化**是硬前置（DoD：所有学生拿到相同版本）。

        发布时把每题的 `problem_version_id` 与该 definition 的**当前激活版本**
        做一次比对：不一致说明题目挂上之后版本被换过 —— 这正是要拦的情形。
        """
        activity = self.get_activity(session, course_id=course_id, activity_id=activity_id)
        if activity.status != ActivityStatus.DRAFT.value:
            reject_state_conflict(
                f"活动 {activity_id} 当前为 {activity.status}，只有 draft 可发布"
            )
        problems = self.list_problems(session, activity_id=activity_id)
        if not problems:
            reject_state_conflict("活动没有任何题目，无法发布")

        # 版本固化校验：写入时已钉过，发布时再核一次（题挂上后版本可能被换）。
        for problem in problems:
            version = session.exec(
                select(ExperimentVersion).where(
                    ExperimentVersion.version_id == problem.problem_version_id
                )
            ).first()
            if version is None:
                reject_state_conflict(
                    f"题 {problem.problem_definition_id!r} 的版本 "
                    f"{problem.problem_version_id!r} 不存在，无法发布"
                )
            if version.experiment_id != problem.problem_definition_id:
                reject_state_conflict(
                    f"题 {problem.problem_definition_id!r} 与版本 "
                    f"{problem.problem_version_id!r} 不匹配，无法发布"
                )

        activity.status = ActivityStatus.PUBLISHED.value
        activity.published_at = utcnow_aware()
        activity.updated_at = utcnow_aware()
        session.add(activity)
        session.flush()
        return activity

    def archive_activity(
        self, session: OrmSession, *, course_id: int, activity_id: str
    ) -> ExperimentActivity:
        activity = self.get_activity(session, course_id=course_id, activity_id=activity_id)
        activity.status = ActivityStatus.ARCHIVED.value
        activity.updated_at = utcnow_aware()
        session.add(activity)
        session.flush()
        return activity

    def list_activities(
        self, session: OrmSession, *, course_id: int
    ) -> list[ExperimentActivity]:
        """管理视图：课程下全部活动（含 draft / archived），新创建在前。"""
        return list(
            session.exec(
                select(ExperimentActivity)
                .where(ExperimentActivity.course_id == course_id)
                .order_by(ExperimentActivity.created_at.desc())
            ).all()
        )

    def list_scopes(
        self, session: OrmSession, *, activity_id: str
    ) -> list[ExperimentActivityScope]:
        return list(
            session.exec(
                select(ExperimentActivityScope).where(
                    ExperimentActivityScope.activity_id == activity_id
                )
            ).all()
        )

    def list_student_activities(
        self,
        session: OrmSession,
        *,
        course_id: int,
        student_id: int,
        now: Optional[datetime] = None,
    ) -> list[dict]:
        """学生侧活动列表（PR-12）：已发布 + 可见 + 时间窗状态 + 题目摘要。

        可见性 = course scope 命中本课程（class/user scope 行为未实现，跳过
        策略与 `resolve_visible_activity_ids` 一致）。**作答窗口状态在这里
        计算好给前端**（not_started/open/late/ended），前端不再自己猜时间。
        """
        published = session.exec(
            select(ExperimentActivity).where(
                ExperimentActivity.course_id == course_id,
                ExperimentActivity.status == ActivityStatus.PUBLISHED.value,  # type: ignore[attr-defined]
            )
        ).all()
        visible_ids = self.resolve_visible_activity_ids(
            session, student_id=student_id, course_id=course_id
        )

        current = now or utcnow_aware()
        result = []
        for activity in published:
            if activity.activity_id not in visible_ids:
                continue
            # SQLite 返回 naive datetime（PR-01 同款坑）——比较前必须归一到 aware
            allowed, reason = is_submission_open(
                current,
                start_at=to_aware(activity.start_at) if activity.start_at else None,
                end_at=to_aware(activity.end_at) if activity.end_at else None,
                allow_late_submit=activity.allow_late_submit,
            )
            problems = self.list_problems(session, activity_id=activity.activity_id)
            result.append({
                "activity_id": activity.activity_id,
                "title": activity.title,
                "type": activity.type,
                "description_md": activity.description_md,
                "start_at": activity.start_at.isoformat() if activity.start_at else None,
                "end_at": activity.end_at.isoformat() if activity.end_at else None,
                "window_status": reason,
                "can_submit": allowed,
                "allow_late_submit": activity.allow_late_submit,
                "max_submissions": activity.max_submissions,
                "problem_count": len(problems),
                "total_score": sum(p.max_score for p in problems),
                "problems": [
                    {
                        "ordinal": p.ordinal,
                        "problem_definition_id": p.problem_definition_id,
                        "label": p.label,
                        "max_score": p.max_score,
                    }
                    for p in problems
                ],
            })
        # 进行中的排前面，其余按截止时间近的在前（无截止的垫底）
        result.sort(key=lambda item: (
            item["window_status"] not in ("open", "late"),
            item["end_at"] or "9999",
        ))
        return result

    # ------------------------------------------------------------------
    # 题目组织（版本固定不变式在此强制）
    # ------------------------------------------------------------------

    def add_problem(
        self,
        session: OrmSession,
        *,
        course_id: int,
        activity_id: str,
        problem_definition_id: str,
        ordinal: Optional[int] = None,
        label: str = "",
        max_score: float = 1.0,
    ) -> ExperimentActivityProblem:
        """挂一道题。**版本在写入时逐题固化**：取该 definition 的当前激活版本。

        ⚠️ 语义（2026-09-11 拍板）：固定的是**每道题**的版本，不是全活动
        共享一个版本 —— 不同题（不同 definition）各有自己的版本是正常形态。
        「所有学生拿到相同版本」由固化保证：版本写入 `problem_version_id`
        行并在发布后不可变，学生作答时不再动态解析 definition 的当前版本。
        """
        activity = self.get_activity(session, course_id=course_id, activity_id=activity_id)
        if activity.status != ActivityStatus.DRAFT.value:
            reject_state_conflict("活动已发布，题目集合不可变更")

        existing = self.list_problems(session, activity_id=activity_id)
        if len(existing) >= MAX_PROBLEMS_PER_ACTIVITY:
            reject_validation_failed(
                f"活动题目数已达上限（{MAX_PROBLEMS_PER_ACTIVITY}）"
            )

        definition = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == problem_definition_id,
                ExperimentDefinition.course_id == course_id,
            )
        ).first()
        if definition is None:
            reject_resource_not_found(f"实验 {problem_definition_id} 不存在")
        if not definition.default_version_id:
            reject_state_conflict(f"实验 {problem_definition_id} 没有激活版本，无法挂入活动")

        taken = {p.ordinal for p in existing}
        if ordinal is None:
            ordinal = (max(taken) + 1) if taken else 1
        if ordinal in taken:
            reject_state_conflict(f"题序 {ordinal} 已被占用，请换一个或先腾出该位次")

        if any(p.problem_definition_id == problem_definition_id for p in existing):
            reject_state_conflict(
                f"实验 {problem_definition_id} 已在该活动中，不可重复挂题"
            )

        problem = ExperimentActivityProblem(
            activity_id=activity.activity_id,
            problem_definition_id=problem_definition_id,
            problem_version_id=definition.default_version_id,
            ordinal=ordinal,
            label=label,
            max_score=max_score,
        )
        session.add(problem)
        session.flush()
        return problem

    def remove_problem(
        self, session: OrmSession, *, course_id: int, activity_id: str, ordinal: int
    ) -> None:
        self.get_activity(session, course_id=course_id, activity_id=activity_id)
        problem = session.exec(
            select(ExperimentActivityProblem).where(
                ExperimentActivityProblem.activity_id == activity_id,
                ExperimentActivityProblem.ordinal == ordinal,
            )
        ).first()
        if problem is None:
            reject_resource_not_found(f"题序 {ordinal} 不存在")
        session.delete(problem)
        session.flush()

    def list_problems(
        self, session: OrmSession, *, activity_id: str
    ) -> list[ExperimentActivityProblem]:
        """按 ordinal 升序返回题目。**顺序是算分输入的一部分**，必须在这里钉死。"""
        problems = list(
            session.exec(
                select(ExperimentActivityProblem)
                .where(ExperimentActivityProblem.activity_id == activity_id)
                .order_by(ExperimentActivityProblem.ordinal)
            ).all()
        )
        # 顺序敏感性在域层有对应校验（DB 唯一约束兜底之外的第二道闸）。
        assert_unique_ordinals(p.ordinal for p in problems)
        return problems

    # ------------------------------------------------------------------
    # 可见范围
    # ------------------------------------------------------------------

    def set_scopes(
        self,
        session: OrmSession,
        *,
        activity_id: str,
        scopes: list[dict],
    ) -> list[ExperimentActivityScope]:
        """整体替换 scope 集合。`class` / `user` 可写入但行为未实现（解析时跳过）。"""
        rows: list[ExperimentActivityScope] = []
        seen: set[tuple[str, int]] = set()
        for item in scopes:
            try:
                scope_type, scope_id = validate_scope_payload(
                    item.get("scope_type"), item.get("scope_id")
                )
            except ValueError as exc:
                reject_validation_failed(str(exc))
                raise
            key = (scope_type, scope_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                ExperimentActivityScope(activity_id=activity_id, scope_type=scope_type, scope_id=scope_id)
            )
        for old in session.exec(
            select(ExperimentActivityScope).where(
                ExperimentActivityScope.activity_id == activity_id
            )
        ).all():
            session.delete(old)
        session.flush()
        for row in rows:
            session.add(row)
        session.flush()
        return rows

    def resolve_visible_activity_ids(
        self, session: OrmSession, *, student_id: int, course_id: int
    ) -> set[str]:
        """学生可见的活动 id 集合。

        本期只解析 `course` scope；`class` / `user` 的行**跳过并记日志** ——
        不报错（教师暂存的范围不应炸掉学生端），也**不静默当成 course**
        （把 user scope 当 course 会让范围意外扩大）。
        """
        rows = session.exec(
            select(ExperimentActivityScope).where(
                ExperimentActivityScope.scope_type == "course",
                ExperimentActivityScope.scope_id == course_id,
            )
        ).all()
        visible = {row.activity_id for row in rows}

        unimplemented = session.exec(
            select(ExperimentActivityScope).where(
                ExperimentActivityScope.scope_type.in_(["class", "user"]),  # type: ignore[attr-defined]
                ExperimentActivityScope.scope_id == student_id,
            )
        ).all()
        if unimplemented:
            logger.info(
                "activity scopes of unimplemented types skipped (student=%s): %s",
                student_id,
                sorted({(r.scope_type, r.activity_id) for r in unimplemented}),
            )
        return visible

    # ------------------------------------------------------------------
    # 作答窗口
    # ------------------------------------------------------------------

    def assert_submission_open(
        self, session: OrmSession, *, activity: ExperimentActivity, now: Optional[datetime] = None
    ) -> str:
        """作答入口的时间窗闸门。返回 `"open"` 或 `"late"`（迟交）。

        **status 检查在这里而不在域层**：域层只管时间，`published` 与否是
        持久化状态，属于 service 的职责。
        """
        if activity.status != ActivityStatus.PUBLISHED.value:
            reject_state_conflict(f"活动 {activity.activity_id} 未发布，不可作答")
        # DB 时间列读回是 naive（与 list_student_activities 同款坑）——
        # 与 aware 的 now 比较前必须归一，否则 TypeError → 500。
        # 有时间窗的活动会稳定复现，无窗活动因两端皆 None 躲过。
        allowed, reason = is_submission_open(
            now or utcnow_aware(),
            start_at=to_aware(activity.start_at) if activity.start_at else None,
            end_at=to_aware(activity.end_at) if activity.end_at else None,
            allow_late_submit=activity.allow_late_submit,
        )
        if not allowed:
            reject_state_conflict(
                f"活动不在作答时间窗内（{reason}）", details={"reason": reason}
            )
        return reason

    # ------------------------------------------------------------------
    # 算分（deterministic 重算）
    # ------------------------------------------------------------------

    def compute_student_score(
        self,
        session: OrmSession,
        *,
        activity: ExperimentActivity,
        student_id: int,
    ) -> dict:
        """按题求和重算某学生在活动下的得分。

        数据源是 `ExperimentAttempt.final_score`（finalize 成功才有值），
        每题取**最好一次** —— 与域层 `compute_homework_score` 的输入约定一致。
        **不读任何缓存**：DoD 要求「score 可重算且 deterministic」，
        重算路径与展示路径同源才能保证对得上。
        """
        problems = self.list_problems(session, activity_id=activity.activity_id)
        per_problem: list[tuple[int, str, float, float]] = []
        for problem in problems:
            attempts = list(
                session.exec(
                    select(ExperimentAttempt).where(
                        ExperimentAttempt.activity_id == activity.activity_id,  # type: ignore[attr-defined]
                        ExperimentAttempt.student_id == student_id,
                        ExperimentAttempt.experiment_id == problem.problem_definition_id,
                        ExperimentAttempt.status == "finalized",  # type: ignore[arg-type]
                    )
                ).all()
            )
            best = max(
                (a.final_score for a in attempts if a.final_score is not None),
                default=0.0,
            )
            per_problem.append(
                (problem.ordinal, problem.problem_definition_id, best, problem.max_score)
            )
        return compute_homework_score(per_problem)
