"""OJ 作答侧服务：尝试（Attempt）/ 运行（Run）/ 终结（Finalize）/ 实验室投影。

从 `experiment_service.py` 拆出（OJ 整改 PR-04，承接 PR-03 的 bounded-context
拆分）：本文件只讲「学生作答的一生」—— 创建尝试、提交运行、Judge0 判定、
终结出分、写学习证据、投影实验室视图。

与 PR-03 同一约定（**不留 shim**）：
- 单例 `attempt_service` / `run_service` / `finalize_service` 随类迁到本文件，
  其余调用方**直接从本模块导入**；
- 题目侧单例 `definition_service` / `version_service` 与共享门卫从
  `experiment_problem_service` 导入（依赖方向：作答侧 → 题目侧，单向）；
- `ExperimentLabProjectionService` 随迁 —— 它只服务 attempt/run 的投影，
  迁入后 PR-03 在 `publish_definition` 里的函数级延迟导入随之收口。
"""
from __future__ import annotations

import logging
import json
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from sqlalchemy import (
    case,
    func,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel import (
    Session,
    select,
)
from app.core.exceptions import (
    reject_course_access_denied,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import (
    to_aware,
    utcnow_aware,
)
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.graph_production_model import CourseKnowledgeNode
from app.models.experiment_model import (
    AttemptStatus,
    ExperimentAttempt,
    ExperimentPublishStatus,
    ExperimentRun,
    ExperimentLabProjection,
    ExperimentVersion,
    RunOutcome,
)
from app.models.resource_model import LabRecord
from app.domain.oj.judging.providers.judge0 import (
    SandboxResourceLimits,
    SubmissionStatus,
    sandbox_client,
)
from app.domain.oj.judging.verdicts import RunState, reason_for_status
from app.services.experiment_problem_service import (  # noqa: F401
    _require_formal_experiment_capabilities,
    definition_service,
    version_service,
)
from app.services.experiment_activity_service import ExperimentActivityService
from app.services.learning_evidence_context_service import upsert_learning_evidence_context
from app.domain.learning.evidence import EvidenceType

logger = logging.getLogger(__name__)

# 提示策略版本已归位域层（PR-06b）；此处保留引用给 finalize 附带提示路径。
from app.domain.oj.intelligence import CODING_HINT_POLICY_VERSION  # noqa: F401

class ExperimentAttemptService:
    """学生实验尝试管理"""

    def create_attempt(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
        student_id: int,
        return_anchor: Optional[dict] = None,
        activity_id: Optional[str] = None,
    ) -> ExperimentAttempt:
        definition = definition_service.get_definition(
            session, course_id=course_id, experiment_id=experiment_id,
        )
        _require_formal_experiment_capabilities(session, course_id=course_id)
        if definition.visibility != "course_catalog":
            reject_resource_not_found(f"实验 {experiment_id} 不存在")
        if definition.publish_status != ExperimentPublishStatus.PUBLISHED:
            reject_state_conflict("实验未发布，无法创建尝试")

        # 作答归属（活动作业 vs 自由练习）：活动路径固定挂题时冻结的版本，
        # 不再动态解析 definition 的当前激活版本 —— 同一活动全体学生同卷公平。
        # 自由练习（activity_id=None）沿用既有语义，走当前激活版本。
        pinned_version_id = definition.default_version_id
        if activity_id is not None:
            pinned_version_id = self._resolve_activity_version(
                session,
                course_id=course_id,
                experiment_id=experiment_id,
                student_id=student_id,
                activity_id=activity_id,
            )
        if not pinned_version_id:
            reject_state_conflict("实验缺少激活版本")

        # 检查尝试次数限制：统计所有非 CANCELLED 尝试（含已终结化），
        # 防止学生通过"创建→提交→终结化→创建"循环绕过 max_attempts 总次数限制。
        # 活动作答与自由练习共享同一预算（同题同生同口径），不另设活动内计数 ——
        # 否则"活动内重开 attempt"会成为绕过 max_attempts 的合法通道。
        version = version_service.get_version(
            session, course_id=course_id, version_id=pinned_version_id,
        )
        if (
            version.experiment_id != definition.experiment_id
            or not version.is_active
            or not version.is_locked
            or version.reference_preview_verified_at is None
        ):
            reject_state_conflict("The published experiment has no verified locked active version")

        all_attempts = session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.experiment_id == experiment_id,
                ExperimentAttempt.student_id == student_id,
                ExperimentAttempt.course_id == course_id,
                ExperimentAttempt.status != AttemptStatus.CANCELLED,
            )
        ).all()
        if len(all_attempts) >= definition.max_attempts:
            reject_state_conflict("已达最大尝试次数限制")

        # 检查冷却
        latest_attempt = session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.experiment_id == experiment_id,
                ExperimentAttempt.student_id == student_id,
                ExperimentAttempt.course_id == course_id,
            ).order_by(ExperimentAttempt.created_at.desc())
        ).first()
        if latest_attempt and latest_attempt.created_at:
            cooldown = timedelta(minutes=definition.cooldown_minutes)
            if utcnow_aware() - to_aware(latest_attempt.created_at) < cooldown:
                reject_state_conflict("尝试冷却中，请稍后再试")

        attempt = ExperimentAttempt(
            experiment_id=experiment_id,
            version_id=pinned_version_id,
            course_id=course_id,
            student_id=student_id,
            status=AttemptStatus.IN_PROGRESS,
            activity_id=activity_id,
            return_anchor=return_anchor or {},
        )
        session.add(attempt)
        session.flush()
        return attempt

    @staticmethod
    def _resolve_activity_version(
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
        student_id: int,
        activity_id: str,
    ) -> str:
        """活动作答的三道门 + 冻结版本解析。

        顺序即安全含义：不存在/跨课程 → 404；对该学生不可见 → 404
        （不透露活动存在性）；类型未实现 → 422（绝不静默当 homework）；
        未发布/窗口关闭 → 409；题目不在活动中 → 422。
        返回挂题时逐题固化的 ``problem_version_id``（调用方不再回读
        definition 的当前激活版本）。
        """
        activity_svc = ExperimentActivityService()
        activity = activity_svc.get_activity(
            session, course_id=course_id, activity_id=activity_id,
        )
        visible = activity_svc.resolve_visible_activity_ids(
            session, student_id=student_id, course_id=course_id,
        )
        if activity.activity_id not in visible:
            reject_resource_not_found(f"活动 {activity_id} 不存在")
        if activity.type != "homework":
            reject_validation_failed(
                f"活动类型 {activity.type} 暂不支持作答",
                details={"activity_id": activity_id, "type": activity.type},
            )
        activity_svc.assert_submission_open(session, activity=activity)
        problems = activity_svc.list_problems(session, activity_id=activity.activity_id)
        matched = next(
            (p for p in problems if p.problem_definition_id == experiment_id),
            None,
        )
        if matched is None:
            reject_validation_failed(
                f"实验 {experiment_id} 不在活动 {activity_id} 内",
                details={"activity_id": activity_id, "experiment_id": experiment_id},
            )
        return matched.problem_version_id

    def student_summaries(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
    ) -> dict[str, dict[str, Any]]:
        """学生视角的实验聚合：每个 experiment 一条摘要（列表筛选与进度展示用）。

        只读聚合，不改变任何状态；教师视图不调用。CANCELLED 尝试不计入
        （与 max_attempts 计数口径一致）。无尝试的实验不在返回中出现，
        调用方按"待完成"处理。
        """
        attempts = session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.course_id == course_id,
                ExperimentAttempt.student_id == student_id,
                ExperimentAttempt.status != AttemptStatus.CANCELLED,
            )
        ).all()
        runs = session.exec(
            select(ExperimentRun).where(
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
            ).order_by(ExperimentRun.submitted_at.desc())
        ).all()
        runs_by_attempt: dict[str, list] = {}
        for run in runs:
            runs_by_attempt.setdefault(run.attempt_id, []).append(run)

        by_exp: dict[str, list] = {}
        for attempt in attempts:
            by_exp.setdefault(attempt.experiment_id, []).append(attempt)

        summaries: dict[str, dict[str, Any]] = {}
        for experiment_id, items in by_exp.items():
            ordered = sorted(items, key=lambda a: to_aware(a.started_at), reverse=True)
            finalized = [a for a in items if a.status == AttemptStatus.FINALIZED]
            latest_run = None
            for attempt in ordered:
                attempt_runs = runs_by_attempt.get(attempt.attempt_id)
                if attempt_runs:
                    latest_run = attempt_runs[0]
                    break
            outcome = (
                getattr(latest_run.outcome, "value", latest_run.outcome)
                if latest_run is not None
                else None
            )
            summaries[experiment_id] = {
                "attempts_used": len(items),
                "has_finalized": bool(finalized),
                "bucket": "done" if finalized else "in_progress",
                "latest_outcome": outcome,
                "latest_passed_count": latest_run.passed_count if latest_run else None,
                "latest_total_count": latest_run.total_count if latest_run else None,
            }
        return summaries

    def get_attempt(
        self,
        session: Session,
        *,
        course_id: int,
        attempt_id: str,
        student_id: Optional[int] = None,
    ) -> ExperimentAttempt:
        attempt = session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.attempt_id == attempt_id,
                ExperimentAttempt.course_id == course_id,
            )
        ).first()
        if attempt is None:
            reject_resource_not_found(f"尝试 {attempt_id} 不存在")
        # 学生只能看自己的尝试
        if student_id is not None and attempt.student_id != student_id:
            reject_course_access_denied("无权访问他人尝试")
        return attempt

    def list_attempts(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: Optional[str] = None,
        student_id: Optional[int] = None,
        status: Optional[AttemptStatus] = None,
    ) -> list[ExperimentAttempt]:
        stmt = select(ExperimentAttempt).where(
            ExperimentAttempt.course_id == course_id,
        )
        if experiment_id is not None:
            stmt = stmt.where(ExperimentAttempt.experiment_id == experiment_id)
        if student_id is not None:
            stmt = stmt.where(ExperimentAttempt.student_id == student_id)
        if status is not None:
            stmt = stmt.where(ExperimentAttempt.status == status)
        stmt = stmt.order_by(ExperimentAttempt.created_at.desc())
        return list(session.exec(stmt).all())

    def submit_attempt(
        self,
        session: Session,
        *,
        course_id: int,
        attempt_id: str,
    ) -> ExperimentAttempt:
        attempt = self.get_attempt(session, course_id=course_id, attempt_id=attempt_id)
        if attempt.status != AttemptStatus.IN_PROGRESS:
            reject_state_conflict(f"尝试状态 {attempt.status.value} 不可提交")
        attempt.status = AttemptStatus.SUBMITTED
        attempt.submitted_at = utcnow_aware()
        attempt.updated_at = utcnow_aware()
        session.add(attempt)
        session.flush()
        return attempt

class ExperimentRunService:
    """实验代码运行管理"""

    async def create_run(
        self,
        session: Session,
        *,
        course_id: int,
        attempt_id: str,
        language: str,
        source_code: str,
        student_id: int,
        idempotency_key: Optional[str] = None,
    ) -> ExperimentRun:
        """创建代码运行记录。

        Formal execution is always asynchronous.  This method only reserves a
        pending server-owned run; the task worker is the sole caller of
        ``_execute_run``.
        """
        attempt = attempt_service.get_attempt(
            session, course_id=course_id, attempt_id=attempt_id, student_id=student_id,
        )
        if idempotency_key:
            existing = session.exec(
                select(ExperimentRun).where(
                    ExperimentRun.attempt_id == attempt_id,
                    ExperimentRun.course_id == course_id,
                    ExperimentRun.student_id == student_id,
                    ExperimentRun.idempotency_key == idempotency_key,
                )
            ).first()
            if existing is not None:
                return existing
        if attempt.status != AttemptStatus.IN_PROGRESS:
            reject_state_conflict("The experiment attempt is already submitted or finalized")

        # 活动作答的提交时刻复核：窗口可能在建 attempt 之后关闭，且
        # max_submissions 是"提交次数"预算 —— 语义点在提交不在建尝试。
        # （并发竞态与既有 max_attempts 检查同级，不在此加锁。）
        if attempt.activity_id:
            self._assert_activity_submission_allowed(
                session,
                course_id=course_id,
                student_id=student_id,
                attempt=attempt,
            )

        # 校验语言白名单
        definition = definition_service.get_definition(
            session, course_id=course_id, experiment_id=attempt.experiment_id,
        )
        if language not in definition.language_whitelist:
            reject_validation_failed(f"实验未允许语言: {language}")

        version = version_service.get_version(
            session, course_id=course_id, version_id=attempt.version_id,
        )

        try:
            # The database constraint protects this query-then-insert path
            # across multiple Uvicorn processes.
            with session.begin_nested():
                return self._create_run_record(
                    session,
                    course_id=course_id,
                    attempt_id=attempt_id,
                    language=language,
                    source_code=source_code,
                    student_id=student_id,
                    idempotency_key=idempotency_key,
                    # 活动归属由 attempt 继承（PR-07 设计：attempt 归属创建后不可变，
                    # run 侧冗余拷贝，换取 scoreboard/报表按活动拉 run 免 join）。
                    activity_id=attempt.activity_id,
                )
        except IntegrityError:
            existing = session.exec(
                select(ExperimentRun).where(
                    ExperimentRun.attempt_id == attempt_id,
                    ExperimentRun.course_id == course_id,
                    ExperimentRun.student_id == student_id,
                    ExperimentRun.idempotency_key == idempotency_key,
                )
            ).first()
            if existing is not None:
                return existing
            raise

    @staticmethod
    def _assert_activity_submission_allowed(
        session: Session,
        *,
        course_id: int,
        student_id: int,
        attempt: ExperimentAttempt,
    ) -> None:
        """活动提交复核：窗口重验 + 每生每题提交上限。

        已取消/基础设施失败的 run 不占预算（取消从不是成绩， infra 失败不转嫁学生）。
        判定口径以 ``run_state`` 为准（PR-01：状态是真相源，不读 outcome 猜）。
        """
        activity_svc = ExperimentActivityService()
        activity = activity_svc.get_activity(
            session, course_id=course_id, activity_id=attempt.activity_id,
        )
        activity_svc.assert_submission_open(session, activity=activity)
        max_allowed = int(activity.max_submissions or 0)
        if max_allowed <= 0:
            return
        used = session.exec(
            select(func.count(ExperimentRun.id))
            .join(
                ExperimentAttempt,
                ExperimentAttempt.attempt_id == ExperimentRun.attempt_id,
            )
            .where(
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
                ExperimentAttempt.activity_id == activity.activity_id,
                ExperimentAttempt.experiment_id == attempt.experiment_id,
                ExperimentRun.run_state.notin_([
                    RunState.CANCELLED.value,
                    RunState.SYSTEM_ERROR.value,
                ]),
            )
        ).one()
        if int(used or 0) >= max_allowed:
            reject_state_conflict(
                f"活动本题提交次数已达上限（{max_allowed} 次）",
                details={
                    "activity_id": activity.activity_id,
                    "experiment_id": attempt.experiment_id,
                    "max_submissions": max_allowed,
                },
            )

    @staticmethod
    def _ensure_coding_diagnosis(session: Session, run: ExperimentRun) -> None:
        """Create the bounded CodingEduAgent record for a terminal run.

        Diagnosis is derived from the server-owned ``ExperimentRun`` after
        Judge0 has written its result.  It is deliberately best-effort: a
        diagnosis failure must not roll back an otherwise valid code result or
        turn a sandbox outage into a fabricated success.
        """
        if run.outcome in (RunOutcome.PENDING,):
            return
        try:
            from app.services.coding_eduagent_service import coding_eduagent

            coding_eduagent.diagnose_run(
                session,
                course_id=int(run.course_id),
                student_id=int(run.student_id),
                run_id=str(run.run_id),
            )
        except Exception as exc:  # noqa: BLE001 - diagnosis is optional context
            logger.warning(
                "CodingEduAgent diagnosis failed for run %s: %s: %s",
                run.run_id,
                type(exc).__name__,
                exc,
            )

    def _create_run_record(
        self,
        session: Session,
        *,
        course_id: int,
        attempt_id: str,
        language: str,
        source_code: str,
        student_id: int,
        idempotency_key: Optional[str] = None,
        activity_id: Optional[str] = None,
    ) -> ExperimentRun:
        """Create a pending formal run record without executing student code.

        The assessed-execution endpoint always enqueues this record for the
        durable worker; it has no synchronous Judge0 mode.
        """
        normalized_source = self._normalize_source(source_code)
        source_hash = hashlib.sha256(normalized_source.encode("utf-8")).hexdigest()
        duplicate = session.exec(
            select(ExperimentRun.id).where(
                ExperimentRun.attempt_id == attempt_id,
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
                ExperimentRun.normalized_source_hash == source_hash,
            )
        ).first() is not None
        run = ExperimentRun(
            attempt_id=attempt_id,
            course_id=course_id,
            student_id=student_id,
            language=language,
            source_code=source_code,
            normalized_source_hash=source_hash,
            evidence_quality={
                "is_effective_revision": not duplicate,
                "duplicate_source": duplicate,
            },
            idempotency_key=idempotency_key,
            activity_id=activity_id,
            outcome=RunOutcome.PENDING,
        )
        session.add(run)
        session.flush()
        return run

    @staticmethod
    def _normalize_source(source_code: str) -> str:
        """Remove display-only formatting noise before revision counting.

        The original source remains the immutable Judge0 input.  This derived
        representation is used only for a server-owned SHA-256 identity and is
        never returned as a substitute for the student's code.
        """
        normalized = source_code.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.rstrip() for line in normalized.split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    @staticmethod
    def _terminal_error_signature(run: ExperimentRun) -> str:
        cases = []
        for item in list((run.test_summary or {}).get("cases", [])):
            if not isinstance(item, dict):
                continue
            cases.append({
                "passed": bool(item.get("passed")),
                "reason": str(item.get("reason") or ""),
                "hidden": bool(item.get("hidden")),
            })
        payload = {
            "outcome": run.outcome.value,
            "error_code": run.error_code,
            "compile_ok": bool(run.compile_ok),
            "passed_count": int(run.passed_count),
            "total_count": int(run.total_count),
            "cases": cases,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record_terminal_evidence_quality(
        self,
        session: Session,
        run: ExperimentRun,
    ) -> None:
        """Classify one server-owned terminal run without storing raw errors."""
        if run.outcome == RunOutcome.PENDING:
            return
        infrastructure_failure = run.outcome in {
            RunOutcome.SANDBOX_UNAVAILABLE,
            RunOutcome.INTERNAL_ERROR,
        }
        signature = self._terminal_error_signature(run)
        duplicate_error_signature = False
        if run.outcome != RunOutcome.ACCEPTED and not infrastructure_failure:
            previous = session.exec(
                select(ExperimentRun).where(
                    ExperimentRun.attempt_id == run.attempt_id,
                    ExperimentRun.course_id == run.course_id,
                    ExperimentRun.student_id == run.student_id,
                    ExperimentRun.run_id != run.run_id,
                    ExperimentRun.outcome == run.outcome,
                )
            ).all()
            duplicate_error_signature = any(
                self._terminal_error_signature(item) == signature
                for item in previous
            )
        quality = dict(run.evidence_quality or {})
        quality.update({
            "error_signature": signature,
            "duplicate_error_signature": duplicate_error_signature,
            "infrastructure_failure": infrastructure_failure,
            "is_effective_revision": bool(
                quality.get("is_effective_revision", True)
                and not duplicate_error_signature
                and not infrastructure_failure
            ),
        })
        run.evidence_quality = quality
        session.add(run)

    async def _execute_run(
        self,
        session: Session,
        *,
        run: ExperimentRun,
        attempt: ExperimentAttempt,
        version: ExperimentVersion,
        before_case: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        if run.outcome != RunOutcome.PENDING:
            return
        # 加载测试用例
        cases = version_service.list_test_cases(
            session, course_id=run.course_id, version_id=version.version_id,
        )

        # 构建资源限制（固化在服务端）
        limits = SandboxResourceLimits(
            cpu_time_limit=version.cpu_time_limit,
            memory_limit=version.memory_limit,
            wall_time_limit=version.wall_time_limit,
            max_processes=version.max_processes,
            max_file_size=version.max_file_size,
            enable_network=False,  # 始终关闭
        )

        # 检查沙箱可用性
        sandbox_available = sandbox_client.health_check()
        if not sandbox_available:
            run.outcome = RunOutcome.SANDBOX_UNAVAILABLE
            run.error_code = "SANDBOX_UNAVAILABLE"
            run.error_message = "代码沙箱不可用，请稍后重试"
            run.finished_at = utcnow_aware()
            session.add(run)
            session.flush()
            return

        # 执行每个测试用例
        test_summary: list[dict] = []
        passed_count = 0
        compile_ok = True
        compile_message = ""
        first_runtime_error = ""
        first_wrong_answer = ""

        for case in cases:
            session.refresh(run)
            if run.cancel_requested_at is not None:
                # A cancellation never becomes a grade.  The handler sees the
                # task cancellation and leaves this attempt in submitted state.
                return
            if before_case is not None and not await before_case():
                raise RuntimeError("sandbox_execution_lease_lost")
            try:
                case_limits = limits
                if case.time_limit_override is not None:
                    case_limits = SandboxResourceLimits(
                        cpu_time_limit=case.time_limit_override,
                        memory_limit=limits.memory_limit,
                        wall_time_limit=limits.wall_time_limit,
                        max_processes=limits.max_processes,
                        max_file_size=limits.max_file_size,
                        enable_network=False,
                    )

                result = sandbox_client.submit_code(
                    source_code=run.source_code,
                    language=run.language,
                    stdin=case.stdin,
                    expected_output=case.expected_stdout,
                    limits=case_limits,
                )

                # Infrastructure failures never become a student zero.  Leave
                # the attempt submitted so the task can be retried safely.
                if result.status in (
                    SubmissionStatus.SANDBOX_UNAVAILABLE,
                    SubmissionStatus.INTERNAL_ERROR,
                ):
                    run.outcome = RunOutcome.SANDBOX_UNAVAILABLE
                    run.error_code = "SANDBOX_UNAVAILABLE"
                    run.error_message = "Code sandbox became unavailable during assessment."
                    run.compile_ok = compile_ok
                    run.test_summary = {"cases": test_summary}
                    run.finished_at = utcnow_aware()
                    session.add(run)
                    session.flush()
                    return

                # 检查编译错误（只记录一次）
                if result.status == SubmissionStatus.COMPILATION_ERROR:
                    compile_ok = False
                    compile_message = result.compile_output or "编译失败"
                    test_summary.append({
                        "case_name": case.case_name if not case.is_hidden else f"hidden_{case.case_id[:8]}",
                        "passed": False,
                        "reason": "compilation_error",
                        "hidden": case.is_hidden,
                    })
                    break  # 编译失败，后续 case 跳过

                passed = result.status == SubmissionStatus.ACCEPTED
                if passed:
                    passed_count += 1

                reason = self._outcome_to_reason(result.status)
                if result.status == SubmissionStatus.RUNTIME_ERROR and not first_runtime_error:
                    first_runtime_error = result.stderr or "运行时错误"
                if result.status == SubmissionStatus.WRONG_ANSWER and not first_wrong_answer:
                    first_wrong_answer = "测试未通过"

                # 隐藏测试不向前端泄露详情
                summary_entry: dict = {
                    "case_name": case.case_name if not case.is_hidden else f"hidden_{case.case_id[:8]}",
                    "passed": passed,
                    "reason": reason,
                    "hidden": case.is_hidden,
                }
                if not case.is_hidden:
                    summary_entry["stdin"] = case.stdin
                    summary_entry["expected"] = case.expected_stdout
                    summary_entry["actual"] = result.stdout
                test_summary.append(summary_entry)

                # 更新资源消耗（SandboxResult.time 为秒，memory 为 KB）
                if result.time is not None:
                    run.cpu_time_ms = max(run.cpu_time_ms or 0, int(result.time * 1000))
                if result.time is not None:
                    run.wall_time_ms = max(run.wall_time_ms or 0, int(result.time * 1000))
                if result.memory is not None:
                    run.memory_kb = max(run.memory_kb or 0, result.memory)

            except Exception as exc:
                logger.warning("Experiment run case execution failed: %s", exc)
                run.outcome = RunOutcome.SANDBOX_UNAVAILABLE
                run.error_code = "SANDBOX_UNAVAILABLE"
                run.error_message = "Code sandbox became unavailable during assessment."
                run.finished_at = utcnow_aware()
                run.compile_ok = compile_ok
                run.test_summary = {"cases": test_summary}
                session.add(run)
                session.flush()
                return

        # 汇总结果
        run.total_count = len(cases)
        run.passed_count = passed_count
        run.compile_ok = compile_ok
        run.compile_message = compile_message
        run.runtime_message = first_runtime_error
        run.test_summary = {"cases": test_summary}

        if not compile_ok:
            run.outcome = RunOutcome.COMPILATION_ERROR
        elif passed_count == len(cases) and cases:
            run.outcome = RunOutcome.ACCEPTED
        elif passed_count > 0:
            run.outcome = RunOutcome.WRONG_ANSWER
        else:
            # 区分超时/内存/运行时错误，否则默认 wrong_answer
            if any(t["reason"] == "time_limit_exceeded" for t in test_summary):
                run.outcome = RunOutcome.TIME_LIMIT_EXCEEDED
            elif any(t["reason"] == "memory_limit_exceeded" for t in test_summary):
                run.outcome = RunOutcome.MEMORY_LIMIT_EXCEEDED
            elif any(t["reason"] == "runtime_error" for t in test_summary):
                run.outcome = RunOutcome.RUNTIME_ERROR
            else:
                run.outcome = RunOutcome.WRONG_ANSWER

        # Formal grading is ACM/ICPC: partial case success is diagnostic-only.
        run.score = 1.0 if run.outcome == RunOutcome.ACCEPTED else 0.0
        run.finished_at = utcnow_aware()
        session.add(run)
        session.flush()

    def _outcome_to_reason(self, status: SubmissionStatus) -> str:
        """判定 → ``test_summary[].reason``。

        映射表已搬到判题域（``domain/oj/judging/verdicts.py`` 的
        ``REASON_BY_STATUS``）。这里保留薄封装，让调用点与既有行为不变；
        词汇由域统一维护，可单独测试。
        """
        return reason_for_status(status)

    def get_run(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        student_id: Optional[int] = None,
    ) -> ExperimentRun:
        run = session.exec(
            select(ExperimentRun).where(
                ExperimentRun.run_id == run_id,
                ExperimentRun.course_id == course_id,
            )
        ).first()
        if run is None:
            reject_resource_not_found(f"运行 {run_id} 不存在")
        if student_id is not None and run.student_id != student_id:
            reject_course_access_denied("无权访问他人运行")
        return run

    def list_runs(
        self,
        session: Session,
        *,
        course_id: int,
        attempt_id: Optional[str] = None,
        student_id: Optional[int] = None,
    ) -> list[ExperimentRun]:
        stmt = select(ExperimentRun).where(ExperimentRun.course_id == course_id)
        if attempt_id is not None:
            stmt = stmt.where(ExperimentRun.attempt_id == attempt_id)
        if student_id is not None:
            stmt = stmt.where(ExperimentRun.student_id == student_id)
        stmt = stmt.order_by(ExperimentRun.submitted_at.desc())
        return list(session.exec(stmt).all())

    def request_cancel(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        student_id: int,
    ) -> ExperimentRun:
        # This row lock is shared with the handler's completion transaction.
        # Whoever commits first decides the result: a pending run becomes
        # cancelled, while a terminal run remains the immutable assessment
        # fact and cannot make its task look cancelled afterwards.
        run = session.exec(
            select(ExperimentRun)
            .where(
                ExperimentRun.course_id == course_id,
                ExperimentRun.run_id == run_id,
                ExperimentRun.student_id == student_id,
            )
            .with_for_update()
        ).first()
        if run is None:
            reject_resource_not_found("Experiment run does not exist or is not accessible")
        if run.outcome != RunOutcome.PENDING or run.cancel_requested_at is not None:
            reject_state_conflict("Only a pending formal assessment can be cancelled")

        run.cancel_requested_at = utcnow_aware()
        session.add(run)
        session.flush()
        return run

class ExperimentFinalizeService:
    """实验尝试终结化：通过评分规则后形成正式评分型 Evidence"""

    def finalize_attempt(
        self,
        session: Session,
        *,
        course_id: int,
        attempt_id: str,
        student_id: Optional[int] = None,
    ) -> ExperimentAttempt:
        attempt = attempt_service.get_attempt(
            session, course_id=course_id, attempt_id=attempt_id, student_id=student_id,
        )

        if attempt.status == AttemptStatus.FINALIZED:
            return attempt
        if attempt.status != AttemptStatus.SUBMITTED:
            reject_state_conflict(f"尝试状态 {attempt.status.value} 不可终结化")

        # 获取最后一次运行
        runs = run_service.list_runs(
            session, course_id=course_id, attempt_id=attempt_id,
        )
        if not runs:
            reject_state_conflict("尝试无运行记录，无法终结化")
        latest_run = runs[0]

        version = version_service.get_version(
            session, course_id=course_id, version_id=attempt.version_id,
        )

        # 计算最终分数
        passed = latest_run.outcome == RunOutcome.ACCEPTED and latest_run.passed_count == latest_run.total_count
        score = 1.0 if passed else 0.0

        attempt.final_score = score
        attempt.passed = passed
        attempt.finalized_at = utcnow_aware()
        attempt.status = AttemptStatus.FINALIZED
        attempt.updated_at = utcnow_aware()

        # 只有评分策略允许且通过时才写入正式 LearningEvidence
        if version.writes_formal_evidence and latest_run.outcome in {
            RunOutcome.ACCEPTED,
            RunOutcome.WRONG_ANSWER,
            RunOutcome.TIME_LIMIT_EXCEEDED,
            RunOutcome.MEMORY_LIMIT_EXCEEDED,
            RunOutcome.RUNTIME_ERROR,
            RunOutcome.COMPILATION_ERROR,
        }:
            evidence_records = self._write_formal_evidence(
                session,
                course_id=course_id,
                student_id=attempt.student_id,
                attempt=attempt,
                run=latest_run,
                version=version,
            )
            if evidence_records:
                # Retain the legacy singular reference for LabRecord callers;
                # every mapped node still has its own queryable evidence row.
                attempt.evidence_id = evidence_records[0].evidence_id

        ExperimentLabProjectionService().project_terminated_attempt(
            session, attempt=attempt, run=latest_run,
        )

        # F3-A：通过的实验同步完成态投影。身份按"attempt 自带 → active release +
        # 知识映射"回退解析，都解析不出就跳过（不猜）；幂等键保证终结化重试不
        # 重复计数。未通过的尝试不动 exposure（掌握度仍经证据链渗透），完成率
        # 只反映真正做出的题目。统计投影绝不能阻断评分：异常只记日志。
        if attempt.passed:
            try:
                self._project_completion_on_pass(
                    session, course_id=course_id, attempt=attempt,
                )
            except Exception:
                logger.exception(
                    "Experiment finalize completion projection failed (non-blocking): "
                    "course_id=%s attempt_id=%s",
                    course_id,
                    attempt.attempt_id,
                )

        session.add(attempt)
        session.flush()
        return attempt

    @staticmethod
    def _project_completion_on_pass(session: Session, *, course_id: int, attempt) -> None:
        from app.models.unified_learning_model import LearningEventType
        from app.services.unified_learning_service import record_event, refresh_course_stats

        # 1) 优先使用 attempt 自带身份（对话式挑战链路）；正式实验页没有该身份，
        #    回退到 active release + 知识映射解析（学情统计本来就按 active
        #    release 口径展示）。
        release_id = getattr(attempt, "source_release_id", None)
        outline_node_ids: list[str] = []
        if getattr(attempt, "outline_node_id", None):
            outline_node_ids = [attempt.outline_node_id]
        if not release_id or not outline_node_ids:
            resolved = ExperimentFinalizeService._resolve_active_outlines(
                session, course_id=course_id, attempt=attempt,
            )
            if resolved is None:
                return
            release_id, outline_node_ids = resolved
        wrote = False
        for outline_node_id in outline_node_ids:
            try:
                record_event(
                    session,
                    student_id=attempt.student_id,
                    course_id=course_id,
                    release_id=release_id,
                    outline_node_id=outline_node_id,
                    event_type=LearningEventType.EXPLICIT_COMPLETE,
                    idempotency_key=(
                        f"experiment_finalize|{attempt.attempt_id}|{outline_node_id}"
                    ),
                    payload={
                        "experiment_id": attempt.experiment_id,
                        "final_score": attempt.final_score,
                    },
                    source="experiment_finalize",
                )
            except ValueError:
                # release 不存在 / 节点不在该 release 内：映射不上就跳过，不猜测。
                logger.warning(
                    "Experiment finalize completion skipped (unmapped release/node): "
                    "course_id=%s attempt_id=%s outline_node_id=%s",
                    course_id,
                    attempt.attempt_id,
                    outline_node_id,
                )
                continue
            wrote = True
        if wrote:
            refresh_course_stats(session, course_id=course_id, release_id=release_id)

    @staticmethod
    def _resolve_active_outlines(
        session: Session, *, course_id: int, attempt,
    ):
        """经 active release + 知识映射解析大纲节点。

        返回 (release_id, [outline_node_id])，解析不出返回 None。
        definition 未配知识点 / 无 active release / 知识点在大纲找不到
        对应节点时均为预期内的"配不通"，调用方跳过即可。
        """
        from app.models.course_outline_model import CourseOutlineNode
        from app.models.graph_production_model import CourseKnowledgeNode
        from app.services.unified_learning_service import active_release

        try:
            definition = definition_service.get_definition(
                session, course_id=course_id, experiment_id=attempt.experiment_id,
            )
        except Exception:
            logger.warning(
                "Experiment finalize completion skipped (no definition): "
                "course_id=%s attempt_id=%s",
                course_id,
                attempt.attempt_id,
            )
            return None
        requested = [
            node_id
            for node_id in (definition.knowledge_node_ids or [])
            if isinstance(node_id, int) and not isinstance(node_id, bool)
        ]
        if not requested:
            logger.warning(
                "Experiment finalize completion skipped (no_knowledge_nodes): "
                "course_id=%s attempt_id=%s experiment_id=%s",
                course_id,
                attempt.attempt_id,
                attempt.experiment_id,
            )
            return None
        release = active_release(session, course_id)
        if release is None:
            logger.warning(
                "Experiment finalize completion skipped (no_active_release): "
                "course_id=%s attempt_id=%s",
                course_id,
                attempt.attempt_id,
            )
            return None
        outlines: list[str] = []
        for node_id in requested:
            knowledge = session.exec(select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.id == node_id,
                CourseKnowledgeNode.course_id == course_id,
            )).first()
            if knowledge is None:
                continue
            outline = session.exec(select(CourseOutlineNode).where(
                CourseOutlineNode.course_id == course_id,
                CourseOutlineNode.outline_version_id == release.outline_version_id,
                CourseOutlineNode.knowledge_graph_node_id == knowledge.node_key,
            )).first()
            if outline is not None and outline.outline_node_id not in outlines:
                outlines.append(outline.outline_node_id)
        if not outlines:
            logger.warning(
                "Experiment finalize completion skipped (node_not_mapped): "
                "course_id=%s attempt_id=%s",
                course_id,
                attempt.attempt_id,
            )
            return None
        return release.release_id, outlines

    def _write_formal_evidence(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        attempt: ExperimentAttempt,
        run: ExperimentRun,
        version: ExperimentVersion,
    ) -> list[LearningEvidenceRecord]:
        """Write source-free, node-specific formal code evidence.

        Mapping is fail-closed: an experiment without a valid course-owned
        knowledge node is finalized as a lab result but cannot change
        cognition through a guessed identity.
        """
        definition = definition_service.get_definition(
            session,
            course_id=course_id,
            experiment_id=attempt.experiment_id,
        )
        requested_node_ids = [
            node_id
            for node_id in (definition.knowledge_node_ids or [])
            if isinstance(node_id, int) and not isinstance(node_id, bool)
        ]
        if not requested_node_ids:
            return []
        course_node_ids = set(session.exec(select(CourseKnowledgeNode.id).where(
            CourseKnowledgeNode.course_id == course_id,
            CourseKnowledgeNode.id.in_(requested_node_ids),
        )).all())
        evidence_records: list[LearningEvidenceRecord] = []
        seen_node_ids: set[int] = set()
        for node_id in requested_node_ids:
            if node_id not in course_node_ids or node_id in seen_node_ids:
                continue
            seen_node_ids.add(node_id)
            stable_key = (
                f"experiment_attempt|{attempt.attempt_id}|"
                f"{EvidenceType.CODING_EXECUTION.value}|{node_id}"
            )
            evidence_id = "ev_" + uuid.uuid5(uuid.NAMESPACE_URL, stable_key).hex
            existing = session.exec(select(LearningEvidenceRecord).where(
                LearningEvidenceRecord.evidence_id == evidence_id,
            )).first()
            if existing is not None:
                upsert_learning_evidence_context(session, existing)
                evidence_records.append(existing)
                continue
            score = 1.0 if attempt.passed else 0.0
            evidence = LearningEvidenceRecord(
                evidence_id=evidence_id,
                student_id=student_id,
                course_id=course_id,
                node_id=node_id,
                evidence_type=EvidenceType.CODING_EXECUTION.value,
                value=score,
                confidence=1.0,
                label="Code assessment passed" if attempt.passed else "Code assessment not passed",
                description=(
                    f"Experiment {attempt.experiment_id} attempt {attempt.attempt_id} "
                    f"server-scored code result {score:.2f}"
                ),
                source="experiment_finalize_service",
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_refs=[attempt.attempt_id, run.run_id],
                policy_version=CODING_HINT_POLICY_VERSION,
            )
            session.add(evidence)
            session.flush()
            upsert_learning_evidence_context(session, evidence)
            evidence_records.append(evidence)
        return evidence_records

    def get_cognitive_evidence_node_ids(
        self,
        session: Session,
        *,
        attempt: ExperimentAttempt,
    ) -> list[int]:
        """Return only this attempt's persisted code-evidence node IDs."""
        records = session.exec(select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.student_id == attempt.student_id,
            LearningEvidenceRecord.course_id == attempt.course_id,
            LearningEvidenceRecord.evidence_type == EvidenceType.CODING_EXECUTION.value,
            LearningEvidenceRecord.source == "experiment_finalize_service",
        )).all()
        return sorted({
            int(record.node_id)
            for record in records
            if record.node_id is not None and attempt.attempt_id in (record.event_refs or [])
        })

class ExperimentLabProjectionService:
    """Build trusted laboratory records only from a terminated attempt."""

    @staticmethod
    def ensure_projection(
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
    ) -> ExperimentLabProjection:
        projection = session.exec(
            select(ExperimentLabProjection).where(
                ExperimentLabProjection.course_id == course_id,
                ExperimentLabProjection.experiment_id == experiment_id,
            )
        ).first()
        if projection is None:
            projection = ExperimentLabProjection(
                course_id=course_id,
                experiment_id=experiment_id,
            )
            session.add(projection)
            session.flush()
        return projection

    def project_terminated_attempt(
        self,
        session: Session,
        *,
        attempt: ExperimentAttempt,
        run: ExperimentRun,
    ) -> LabRecord:
        if attempt.status != AttemptStatus.FINALIZED or attempt.final_score not in (0.0, 1.0):
            raise ValueError("attempt_must_be_terminated_by_server")
        if run.attempt_id != attempt.attempt_id or run.course_id != attempt.course_id:
            raise ValueError("run_attempt_scope_mismatch")
        definition = definition_service.get_definition(
            session, course_id=attempt.course_id, experiment_id=attempt.experiment_id,
        )
        if definition.course_id != attempt.course_id:
            raise ValueError("definition_course_scope_mismatch")

        projection = self.ensure_projection(
            session,
            course_id=attempt.course_id,
            experiment_id=attempt.experiment_id,
        )

        existing = session.exec(
            select(LabRecord).where(
                LabRecord.attempt_id == attempt.attempt_id,
                LabRecord.trusted_source == True,  # noqa: E712
            )
        ).first()
        if existing is not None:
            return existing

        record = LabRecord(
            lab_id=projection.projection_id,
            course_id=attempt.course_id,
            experiment_id=attempt.experiment_id,
            projection_id=projection.projection_id,
            student_id=attempt.student_id,
            attempt_id=attempt.attempt_id,
            final_score=attempt.final_score,
            passed=attempt.passed,
            evidence_id=attempt.evidence_id,
            return_anchor=dict(attempt.return_anchor or {}),
            source_kind="experiment_attempt_terminated",
            trusted_source=True,
        )
        session.add(record)
        session.flush()
        return record

attempt_service = ExperimentAttemptService()

run_service = ExperimentRunService()

finalize_service = ExperimentFinalizeService()
