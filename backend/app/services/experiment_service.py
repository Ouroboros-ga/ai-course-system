"""阶段6 服务层：课程实验、Judge0 与 CodingAgent

完成"实验定义 → 版本 → 测试用例 → 尝试 → 运行 → finalize + CodingAgent hints"编排。

关键约束：
- 前端不直接访问 Judge0；主应用不执行学生代码
- 学生只能看自己的尝试，教师只能管理所属课程实验
- 最终评分型结果才产生 LearningEvidence；单次运行日志不直接修改认知状态
- Judge0 不可用时课程学习页可以降级，且保留明确恢复提示
- CodingAgent 只能请求受控执行和分层提示，不能执行任意前端代码
- 跨课程严格隔离：所有查询都按 course_id 过滤
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.core.exceptions import (
    reject_capability_disabled,
    reject_course_access_denied,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import utcnow_aware
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.experiment_model import (
    AttemptStatus,
    CodingHintLevel,
    CodingHintRecord,
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentRun,
    ExperimentRunArtifact,
    ExperimentTestCase,
    ExperimentVersion,
    RunOutcome,
)
from app.services.sandbox_client import (
    ALLOWED_LANGUAGES,
    SandboxResourceLimits,
    SubmissionStatus,
    sandbox_client,
)


logger = logging.getLogger(__name__)

# 提示策略版本号，每次提示策略变更时递增
CODING_HINT_POLICY_VERSION = "coding-hint-v1.0"

# 默认禁止 full_solution 提示，需教师策略显式允许
# TODO(P1-C1): 未来应从课程/版本教师策略（CourseSafetyPolicy 或实验定义）读取
# full_solution 是否被允许；当前无策略查询逻辑，硬编码为 False，
# 且客户端不可覆盖（端点已移除 full_solution_allowed 字段）。
DEFAULT_FULL_SOLUTION_ALLOWED = False


# ---------------------------------------------------------------------------
# 实验定义服务
# ---------------------------------------------------------------------------


class ExperimentDefinitionService:
    """教师管理课程实验定义"""

    def create_definition(
        self,
        session: Session,
        *,
        course_id: int,
        title: str,
        description: str = "",
        language_whitelist: Optional[list[str]] = None,
        knowledge_node_ids: Optional[list[int]] = None,
        max_attempts: int = 3,
        cooldown_minutes: int = 30,
        created_by: int,
    ) -> ExperimentDefinition:
        # 校验语言白名单
        whitelist = list(language_whitelist or [])
        invalid = [lang for lang in whitelist if lang not in ALLOWED_LANGUAGES]
        if invalid:
            reject_validation_failed(f"不支持的语言: {invalid}")

        definition = ExperimentDefinition(
            course_id=course_id,
            title=title,
            description=description,
            language_whitelist=whitelist,
            knowledge_node_ids=list(knowledge_node_ids or []),
            max_attempts=max_attempts,
            cooldown_minutes=cooldown_minutes,
            publish_status=ExperimentPublishStatus.DRAFT,
            created_by=created_by,
        )
        session.add(definition)
        session.flush()
        return definition

    def get_definition(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
    ) -> ExperimentDefinition:
        definition = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == experiment_id,
                ExperimentDefinition.course_id == course_id,
            )
        ).first()
        if definition is None:
            reject_resource_not_found(f"实验 {experiment_id} 不存在")
        return definition

    def list_definitions(
        self,
        session: Session,
        *,
        course_id: int,
        publish_status: Optional[ExperimentPublishStatus] = None,
    ) -> list[ExperimentDefinition]:
        stmt = select(ExperimentDefinition).where(
            ExperimentDefinition.course_id == course_id,
        )
        if publish_status is not None:
            stmt = stmt.where(ExperimentDefinition.publish_status == publish_status)
        stmt = stmt.order_by(ExperimentDefinition.created_at.desc())
        return list(session.exec(stmt).all())

    def update_definition(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        language_whitelist: Optional[list[str]] = None,
        max_attempts: Optional[int] = None,
        cooldown_minutes: Optional[int] = None,
    ) -> ExperimentDefinition:
        definition = self.get_definition(session, course_id=course_id, experiment_id=experiment_id)
        if language_whitelist is not None:
            invalid = [lang for lang in language_whitelist if lang not in ALLOWED_LANGUAGES]
            if invalid:
                reject_validation_failed(f"不支持的语言: {invalid}")
            definition.language_whitelist = list(language_whitelist)
        if title is not None:
            definition.title = title
        if description is not None:
            definition.description = description
        if max_attempts is not None:
            definition.max_attempts = max_attempts
        if cooldown_minutes is not None:
            definition.cooldown_minutes = cooldown_minutes
        definition.updated_at = utcnow_aware()
        session.add(definition)
        session.flush()
        return definition

    def publish_definition(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
    ) -> ExperimentDefinition:
        definition = self.get_definition(session, course_id=course_id, experiment_id=experiment_id)
        if not definition.default_version_id:
            reject_state_conflict("实验缺少激活版本，无法发布")
        definition.publish_status = ExperimentPublishStatus.PUBLISHED
        definition.updated_at = utcnow_aware()
        session.add(definition)
        session.flush()
        return definition

    def archive_definition(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
    ) -> ExperimentDefinition:
        definition = self.get_definition(session, course_id=course_id, experiment_id=experiment_id)
        definition.publish_status = ExperimentPublishStatus.ARCHIVED
        definition.archived_at = utcnow_aware()
        definition.updated_at = utcnow_aware()
        session.add(definition)
        session.flush()
        return definition


# ---------------------------------------------------------------------------
# 实验版本服务
# ---------------------------------------------------------------------------


class ExperimentVersionService:
    """实验版本与测试用例管理"""

    def create_version(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
        label: str = "",
        cpu_time_limit: int = 5,
        memory_limit: int = 128_000,
        wall_time_limit: int = 10,
        max_processes: int = 30,
        max_file_size: int = 1024,
        passing_score: float = 0.6,
        writes_formal_evidence: bool = True,
        created_by: int,
        test_cases: Optional[list[dict]] = None,
        activate: bool = True,
    ) -> ExperimentVersion:
        # 验证实验存在
        definition_service.get_definition(
            session, course_id=course_id, experiment_id=experiment_id,
        )

        # 计算版本号
        max_version = session.exec(
            select(func.max(ExperimentVersion.version_number)).where(
                ExperimentVersion.experiment_id == experiment_id,
            )
        ).one() or 0
        version_number = int(max_version) + 1

        version = ExperimentVersion(
            experiment_id=experiment_id,
            course_id=course_id,
            version_number=version_number,
            label=label or f"v{version_number}",
            cpu_time_limit=cpu_time_limit,
            memory_limit=memory_limit,
            wall_time_limit=wall_time_limit,
            max_processes=max_processes,
            max_file_size=max_file_size,
            enable_network=False,  # 始终关闭
            passing_score=passing_score,
            writes_formal_evidence=writes_formal_evidence,
            is_active=False,
            created_by=created_by,
        )
        session.add(version)
        session.flush()

        # 写入测试用例
        for case_data in (test_cases or []):
            case = ExperimentTestCase(
                version_id=version.version_id,
                course_id=course_id,
                case_name=case_data.get("case_name", ""),
                stdin=case_data.get("stdin", ""),
                expected_stdout=case_data.get("expected_stdout", ""),
                is_hidden=bool(case_data.get("is_hidden", False)),
                weight=float(case_data.get("weight", 1.0)),
                time_limit_override=case_data.get("time_limit_override"),
            )
            session.add(case)

        if activate:
            self._activate_version(session, course_id=course_id, version_id=version.version_id)

        session.flush()
        return version

    def get_version(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
    ) -> ExperimentVersion:
        version = session.exec(
            select(ExperimentVersion).where(
                ExperimentVersion.version_id == version_id,
                ExperimentVersion.course_id == course_id,
            )
        ).first()
        if version is None:
            reject_resource_not_found(f"实验版本 {version_id} 不存在")
        return version

    def list_versions(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
    ) -> list[ExperimentVersion]:
        return list(session.exec(
            select(ExperimentVersion).where(
                ExperimentVersion.experiment_id == experiment_id,
                ExperimentVersion.course_id == course_id,
            ).order_by(ExperimentVersion.version_number.desc())
        ).all())

    def list_test_cases(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
        include_hidden: bool = True,
    ) -> list[ExperimentTestCase]:
        stmt = select(ExperimentTestCase).where(
            ExperimentTestCase.version_id == version_id,
            ExperimentTestCase.course_id == course_id,
        )
        if not include_hidden:
            stmt = stmt.where(ExperimentTestCase.is_hidden == False)  # noqa: E712
        return list(session.exec(stmt).all())

    def activate_version(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
    ) -> ExperimentVersion:
        return self._activate_version(session, course_id=course_id, version_id=version_id)

    def _activate_version(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
    ) -> ExperimentVersion:
        version = self.get_version(session, course_id=course_id, version_id=version_id)

        # 失活同实验其他版本
        other_versions = session.exec(
            select(ExperimentVersion).where(
                ExperimentVersion.experiment_id == version.experiment_id,
                ExperimentVersion.course_id == course_id,
                ExperimentVersion.is_active == True,  # noqa: E712
                ExperimentVersion.version_id != version_id,
            )
        ).all()
        for other in other_versions:
            other.is_active = False
            session.add(other)

        version.is_active = True
        session.add(version)

        # 更新实验定义的 default_version_id
        definition = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == version.experiment_id,
                ExperimentDefinition.course_id == course_id,
            )
        ).first()
        if definition is not None:
            definition.default_version_id = version.version_id
            definition.updated_at = utcnow_aware()
            session.add(definition)

        session.flush()
        return version

    def lock_version(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
        locked: bool = True,
    ) -> ExperimentVersion:
        version = self.get_version(session, course_id=course_id, version_id=version_id)
        version.is_locked = locked
        session.add(version)
        session.flush()
        return version


# ---------------------------------------------------------------------------
# 实验尝试服务
# ---------------------------------------------------------------------------


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
    ) -> ExperimentAttempt:
        definition = definition_service.get_definition(
            session, course_id=course_id, experiment_id=experiment_id,
        )
        if definition.publish_status != ExperimentPublishStatus.PUBLISHED:
            reject_state_conflict("实验未发布，无法创建尝试")
        if not definition.default_version_id:
            reject_state_conflict("实验缺少激活版本")

        # 检查尝试次数限制：统计所有非 CANCELLED 尝试（含已终结化），
        # 防止学生通过"创建→提交→终结化→创建"循环绕过 max_attempts 总次数限制。
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
            if utcnow_aware() - latest_attempt.created_at < cooldown:
                reject_state_conflict("尝试冷却中，请稍后再试")

        attempt = ExperimentAttempt(
            experiment_id=experiment_id,
            version_id=definition.default_version_id,
            course_id=course_id,
            student_id=student_id,
            status=AttemptStatus.IN_PROGRESS,
            return_anchor=return_anchor or {},
        )
        session.add(attempt)
        session.flush()
        return attempt

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


# ---------------------------------------------------------------------------
# 实验运行服务
# ---------------------------------------------------------------------------


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
        execute: bool = True,
    ) -> ExperimentRun:
        """创建代码运行记录。

        - execute=True（默认）：同步执行沙箱（兼容现有测试）
        - execute=False：仅创建 PENDING 记录，由调用方异步触发 _execute_run
        """
        attempt = attempt_service.get_attempt(
            session, course_id=course_id, attempt_id=attempt_id, student_id=student_id,
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

        run = self._create_run_record(
            session,
            course_id=course_id,
            attempt_id=attempt_id,
            language=language,
            source_code=source_code,
            student_id=student_id,
        )

        if execute:
            # 同步执行沙箱（测试场景）；生产应通过任务中心异步执行
            await self._execute_run(session, run=run, attempt=attempt, version=version)
            self._ensure_coding_diagnosis(session, run)
        return run

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
    ) -> ExperimentRun:
        """仅创建 ExperimentRun 记录（PENDING），不执行沙箱。

        异步路径（async_run=true）调用此方法创建记录，随后由 worker
        通过 _execute_run 异步执行。
        """
        run = ExperimentRun(
            attempt_id=attempt_id,
            course_id=course_id,
            student_id=student_id,
            language=language,
            source_code=source_code,
            outcome=RunOutcome.PENDING,
        )
        session.add(run)
        session.flush()
        return run

    async def _execute_run(
        self,
        session: Session,
        *,
        run: ExperimentRun,
        attempt: ExperimentAttempt,
        version: ExperimentVersion,
    ) -> None:
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

                # 检查编译错误（只记录一次）
                if result.status == SubmissionStatus.COMPILATION_ERROR:
                    compile_ok = False
                    compile_message = result.compile_output or "编译失败"
                    test_summary.append({
                        "case_name": case.case_name,
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
                run.outcome = RunOutcome.INTERNAL_ERROR
                run.error_code = "INTERNAL_ERROR"
                run.error_message = str(exc)
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

        # 计算分数（按权重）
        total_weight = sum(c.weight for c in cases) or 1.0
        passed_weight = sum(
            c.weight for c, t in zip(cases, test_summary) if t["passed"]
        )
        run.score = passed_weight / total_weight if total_weight > 0 else 0.0
        run.finished_at = utcnow_aware()
        session.add(run)
        session.flush()

    def _outcome_to_reason(self, status: SubmissionStatus) -> str:
        return {
            SubmissionStatus.ACCEPTED: "passed",
            SubmissionStatus.WRONG_ANSWER: "wrong_answer",
            SubmissionStatus.TIME_LIMIT_EXCEEDED: "time_limit_exceeded",
            SubmissionStatus.MEMORY_LIMIT_EXCEEDED: "memory_limit_exceeded",
            SubmissionStatus.RUNTIME_ERROR: "runtime_error",
            SubmissionStatus.COMPILATION_ERROR: "compilation_error",
            SubmissionStatus.INTERNAL_ERROR: "internal_error",
            SubmissionStatus.IN_QUEUE: "pending",
            SubmissionStatus.PROCESSING: "pending",
            SubmissionStatus.SANDBOX_UNAVAILABLE: "sandbox_unavailable",
        }.get(status, "unknown")

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


# ---------------------------------------------------------------------------
# 实验终结化服务（finalize）
# ---------------------------------------------------------------------------


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

        if attempt.status not in (AttemptStatus.SUBMITTED, AttemptStatus.FAILED):
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
        score = latest_run.score or 0.0
        passed = score >= version.passing_score and latest_run.outcome == RunOutcome.ACCEPTED

        attempt.final_score = score
        attempt.passed = passed
        attempt.finalized_at = utcnow_aware()
        attempt.status = AttemptStatus.FINALIZED if passed else AttemptStatus.FAILED
        attempt.updated_at = utcnow_aware()

        # 只有评分策略允许且通过时才写入正式 LearningEvidence
        if version.writes_formal_evidence and passed:
            evidence = self._write_formal_evidence(
                session,
                course_id=course_id,
                student_id=attempt.student_id,
                attempt=attempt,
                run=latest_run,
                version=version,
            )
            attempt.evidence_id = evidence.evidence_id

        session.add(attempt)
        session.flush()
        return attempt

    def _write_formal_evidence(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        attempt: ExperimentAttempt,
        run: ExperimentRun,
        version: ExperimentVersion,
    ) -> LearningEvidenceRecord:
        """写入正式评分型 LearningEvidence（复用 cognitive_state_model）"""
        # Stable evidence_id derived from attempt to ensure idempotency
        stable_key = f"experiment_attempt|{attempt.attempt_id}|experiment_scored"
        evidence_id = "ev_" + uuid.uuid5(uuid.NAMESPACE_URL, stable_key).hex

        existing = session.exec(
            select(LearningEvidenceRecord).where(
                LearningEvidenceRecord.evidence_id == evidence_id,
            )
        ).first()
        if existing is not None:
            return existing

        evidence = LearningEvidenceRecord(
            evidence_id=evidence_id,
            student_id=student_id,
            course_id=course_id,
            node_id=None,
            evidence_type="experiment_completion",
            value=run.score,
            confidence=1.0,
            label="实验完成" if attempt.passed else "实验未通过",
            description=f"实验 {attempt.experiment_id} 尝试 {attempt.attempt_id} 评分 {run.score:.2f}",
            source="experiment_finalize_service",
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_refs=[attempt.attempt_id, run.run_id],
            policy_version=CODING_HINT_POLICY_VERSION,
        )
        session.add(evidence)
        session.flush()
        return evidence


# ---------------------------------------------------------------------------
# CodingAgent 分层提示服务
# ---------------------------------------------------------------------------


class CodingHintService:
    """CodingAgent 分层提示

    - 只能请求受控执行和分层提示，不能执行任意前端代码
    - full_solution 需教师策略显式允许；默认禁止
    - 每次提示携带 hint_level、reason_codes、policy_version
    """

    def request_hint(
        self,
        session: Session,
        *,
        course_id: int,
        attempt_id: str,
        student_id: int,
        hint_level: CodingHintLevel,
        reason_codes: Optional[list[str]] = None,
        full_solution_allowed: bool = DEFAULT_FULL_SOLUTION_ALLOWED,
        hint_text: str = "",
        hint_metadata: Optional[dict] = None,
    ) -> CodingHintRecord:
        # 验证尝试存在且属于该学生
        attempt_service.get_attempt(
            session, course_id=course_id, attempt_id=attempt_id, student_id=student_id,
        )

        # full_solution 默认禁止
        if hint_level == CodingHintLevel.FULL_SOLUTION and not full_solution_allowed:
            reject_course_access_denied("教师策略未允许 full_solution 提示")

        hint = CodingHintRecord(
            attempt_id=attempt_id,
            course_id=course_id,
            student_id=student_id,
            hint_level=hint_level,
            reason_codes=list(reason_codes or []),
            policy_version=CODING_HINT_POLICY_VERSION,
            hint_text=hint_text,
            hint_metadata=hint_metadata or {},
        )
        session.add(hint)
        session.flush()
        return hint

    def list_hints(
        self,
        session: Session,
        *,
        course_id: int,
        attempt_id: Optional[str] = None,
        student_id: Optional[int] = None,
    ) -> list[CodingHintRecord]:
        stmt = select(CodingHintRecord).where(CodingHintRecord.course_id == course_id)
        if attempt_id is not None:
            stmt = stmt.where(CodingHintRecord.attempt_id == attempt_id)
        if student_id is not None:
            stmt = stmt.where(CodingHintRecord.student_id == student_id)
        stmt = stmt.order_by(CodingHintRecord.requested_at.desc())
        return list(session.exec(stmt).all())

    def review_hint(
        self,
        session: Session,
        *,
        course_id: int,
        hint_id: str,
        decision: str,
        reviewer_id: int,
        note: str = "",
    ) -> CodingHintRecord:
        if decision not in ("approved", "rejected"):
            reject_validation_failed("审核决定必须是 approved 或 rejected")
        hint = session.exec(
            select(CodingHintRecord).where(
                CodingHintRecord.hint_id == hint_id,
                CodingHintRecord.course_id == course_id,
            )
        ).first()
        if hint is None:
            reject_resource_not_found(f"提示 {hint_id} 不存在")
        hint.teacher_reviewed = True
        hint.teacher_decision = decision
        hint.teacher_note = note
        hint.reviewed_by = reviewer_id
        hint.reviewed_at = utcnow_aware()
        session.add(hint)
        session.flush()
        return hint


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------


definition_service = ExperimentDefinitionService()
version_service = ExperimentVersionService()
attempt_service = ExperimentAttemptService()
run_service = ExperimentRunService()
finalize_service = ExperimentFinalizeService()
coding_hint_service = CodingHintService()
