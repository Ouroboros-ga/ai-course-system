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

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import case, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from app.core.exceptions import (
    reject_capability_disabled,
    reject_course_access_denied,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import to_aware, to_naive, utcnow_aware
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
)
from app.models.agent_governance_model import AgentActionProposal
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.graph_production_model import CourseKnowledgeNode
from app.models.experiment_model import (
    AttemptStatus,
    CodingHintLevel,
    CodingHintRecord,
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentRun,
    ExperimentRunArtifact,
    ExperimentLabProjection,
    ExperimentRecommendation,
    ExperimentTestCase,
    ExperimentVersion,
    FreeSandboxQuotaWindow,
    RunOutcome,
    SandboxExecutionLease,
)
from app.models.resource_model import LabRecord
from app.services.sandbox_client import (
    ALLOWED_LANGUAGES,
    SandboxResourceLimits,
    SubmissionStatus,
    sandbox_client,
)
from app.services.learning_evidence_context_service import upsert_learning_evidence_context
from app.domain.learning.evidence import EvidenceType


logger = logging.getLogger(__name__)

# 提示策略版本号，每次提示策略变更时递增
CODING_HINT_POLICY_VERSION = "coding-hint-v1.0"

# 默认禁止 full_solution 提示，需教师策略显式允许
# TODO(P1-C1): 未来应从课程/版本教师策略（CourseSafetyPolicy 或实验定义）读取
# full_solution 是否被允许；当前无策略查询逻辑，硬编码为 False，
# 且客户端不可覆盖（端点已移除 full_solution_allowed 字段）。
DEFAULT_FULL_SOLUTION_ALLOWED = False
FORMAL_LEASE_KEY = "formal_judge0"
FORMAL_LEASE_SECONDS = 90
FREE_SANDBOX_WINDOW_SECONDS = 10 * 60
FREE_SANDBOX_MAX_RUNS = 10


def _require_formal_experiment_capabilities(session: Session, *, course_id: int) -> None:
    """Keep publication, attempts, previews, and runs behind both switches."""
    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    if capability is None or not capability.experiment or not capability.coding_sandbox:
        reject_capability_disabled("The course has not enabled formal code experiments.")


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
        ExperimentPublishValidator().validate_existing(session, definition=definition)
        if not definition.default_version_id:
            reject_state_conflict("实验缺少激活版本，无法发布")
        definition.publish_status = ExperimentPublishStatus.PUBLISHED
        definition.updated_at = utcnow_aware()
        session.add(definition)
        session.flush()
        ExperimentLabProjectionService().ensure_projection(
            session,
            course_id=definition.course_id,
            experiment_id=definition.experiment_id,
        )
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
        passing_score: float = 1.0,
        writes_formal_evidence: bool = True,
        created_by: int,
        test_cases: Optional[list[dict]] = None,
        activate: bool = True,
    ) -> ExperimentVersion:
        if passing_score != 1.0:
            reject_validation_failed("Formal programming experiments require passing_score=1.0")
        if not test_cases:
            reject_validation_failed("An experiment version requires at least one test case")
        total_weight = sum(float(case.get("weight", 1.0)) for case in test_cases)
        if abs(total_weight - 1.0) > 1e-9:
            reject_validation_failed("Experiment test case weights must total 1.0")
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
        if not version.is_locked or version.reference_preview_verified_at is None:
            reject_state_conflict("Only a locked version with a verified reference preview may become active")

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
        if locked and version.reference_preview_verified_at is None:
            reject_state_conflict("Reference solution preview has not verified all test cases")
        version.is_locked = locked
        session.add(version)
        session.flush()
        if locked:
            # Locking is the deliberate handoff from the editable test set to
            # the version students may receive.  Creation itself never changes
            # a published experiment's default version.
            return self._activate_version(session, course_id=course_id, version_id=version_id)
        return version

    def preview_reference_solution(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
        language: str,
        source_code: str,
    ) -> dict[str, Any]:
        """Verify a transient teacher reference solution against every case.

        The source stays in request memory only.  No run/artifact/agent record
        is created because those stores are student-product data and must not
        receive teacher answers or hidden inputs.
        """
        _require_formal_experiment_capabilities(session, course_id=course_id)
        version = self.get_version(session, course_id=course_id, version_id=version_id)
        definition = definition_service.get_definition(
            session, course_id=course_id, experiment_id=version.experiment_id,
        )
        if language not in definition.language_whitelist:
            reject_validation_failed("参考解语言不在实验白名单中")
        if not sandbox_client.health_check():
            reject_state_conflict("Judge0 健康检查未通过，无法预览参考解")
        cases = self.list_test_cases(session, course_id=course_id, version_id=version_id)
        if not cases:
            reject_validation_failed("参考解预览需要至少一个测试用例")
        limits = SandboxResourceLimits(
            cpu_time_limit=version.cpu_time_limit,
            memory_limit=version.memory_limit,
            wall_time_limit=version.wall_time_limit,
            max_processes=version.max_processes,
            max_file_size=version.max_file_size,
            enable_network=False,
        )
        passed_count = 0
        for case in cases:
            result = sandbox_client.submit_code(
                source_code=source_code,
                language=language,
                stdin=case.stdin,
                expected_output=case.expected_stdout,
                limits=limits,
            )
            if result.status == SubmissionStatus.ACCEPTED:
                passed_count += 1
        accepted = passed_count == len(cases)
        if accepted:
            version.reference_preview_verified_at = utcnow_aware()
            session.add(version)
            session.flush()
        return {
            "version_id": version.version_id,
            "accepted": accepted,
            "passed_count": passed_count,
            "total_count": len(cases),
        }


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
        _require_formal_experiment_capabilities(session, course_id=course_id)
        if definition.publish_status != ExperimentPublishStatus.PUBLISHED:
            reject_state_conflict("实验未发布，无法创建尝试")
        if not definition.default_version_id:
            reject_state_conflict("实验缺少激活版本")

        # 检查尝试次数限制：统计所有非 CANCELLED 尝试（含已终结化），
        # 防止学生通过"创建→提交→终结化→创建"循环绕过 max_attempts 总次数限制。
        version = version_service.get_version(
            session, course_id=course_id, version_id=definition.default_version_id,
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
    ) -> ExperimentRun:
        """Create a pending formal run record without executing student code.

        The assessed-execution endpoint always enqueues this record for the
        durable worker; it has no synchronous Judge0 mode.
        """
        run = ExperimentRun(
            attempt_id=attempt_id,
            course_id=course_id,
            student_id=student_id,
            language=language,
            source_code=source_code,
            idempotency_key=idempotency_key,
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


class ExperimentRecommendationDispatchError(ValueError):
    """A governed TeachingAgent recommendation could not be materialized."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ExperimentRecommendationService:
    """Turn an approved proposal into a recommendation, never execution state."""

    _FORBIDDEN_ACTION_FIELDS = frozenset({
        "source_code", "code", "language", "stdin", "expected_stdout",
        "test_cases", "resource_limits", "run_id", "attempt_id",
    })

    @classmethod
    def _contains_execution_payload(cls, action: dict[str, Any]) -> bool:
        return any(field in action for field in cls._FORBIDDEN_ACTION_FIELDS)

    def create_from_approved_proposal(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        proposal_id: str,
        proposed_action: dict[str, Any],
    ) -> tuple[ExperimentRecommendation, bool]:
        experiment_id = str(proposed_action.get("experiment_id") or "").strip()
        if not experiment_id:
            raise ExperimentRecommendationDispatchError("missing_experiment_id")
        if not proposal_id:
            raise ExperimentRecommendationDispatchError("missing_proposal_id")
        if self._contains_execution_payload(proposed_action):
            raise ExperimentRecommendationDispatchError("invalid_trigger_payload")

        proposal = session.exec(
            select(AgentActionProposal).where(
                AgentActionProposal.proposal_id == proposal_id,
                AgentActionProposal.course_id == course_id,
            )
        ).first()
        if proposal is None:
            raise ExperimentRecommendationDispatchError("proposal_not_found")
        if proposal.proposal_type != "trigger_experiment":
            raise ExperimentRecommendationDispatchError("proposal_type_mismatch")
        if proposal.status != "approved":
            raise ExperimentRecommendationDispatchError("proposal_not_approved")
        if proposal.student_id != student_id:
            raise ExperimentRecommendationDispatchError("proposal_student_mismatch")

        try:
            persisted_action = json.loads(proposal.proposed_action or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ExperimentRecommendationDispatchError("invalid_stored_proposal") from exc
        if not isinstance(persisted_action, dict):
            raise ExperimentRecommendationDispatchError("invalid_stored_proposal")
        if self._contains_execution_payload(persisted_action):
            raise ExperimentRecommendationDispatchError("invalid_trigger_payload")
        if str(persisted_action.get("experiment_id") or "").strip() != experiment_id:
            raise ExperimentRecommendationDispatchError("proposal_experiment_mismatch")

        requested_node_id = proposed_action.get("outline_node_id")
        stored_node_id = persisted_action.get("outline_node_id")
        if requested_node_id is not None and str(requested_node_id) != str(stored_node_id):
            raise ExperimentRecommendationDispatchError("proposal_outline_node_mismatch")
        outline_node_id = str(stored_node_id) if stored_node_id is not None else None

        capability = session.exec(
            select(CourseCapability).where(CourseCapability.course_id == course_id)
        ).first()
        if capability is None or not capability.experiment or not capability.coding_sandbox:
            raise ExperimentRecommendationDispatchError("experiment_capability_disabled")
        membership = session.exec(
            select(CourseMembership).where(
                CourseMembership.course_id == course_id,
                CourseMembership.user_id == student_id,
            )
        ).first()
        if (
            membership is None
            or membership.status != MembershipStatus.ACTIVE
            or membership.role != CourseRole.STUDENT
        ):
            raise ExperimentRecommendationDispatchError("student_membership_invalid")

        definition = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.course_id == course_id,
                ExperimentDefinition.experiment_id == experiment_id,
            )
        ).first()
        if definition is None or definition.publish_status != ExperimentPublishStatus.PUBLISHED:
            raise ExperimentRecommendationDispatchError("experiment_not_published")
        if not definition.default_version_id:
            raise ExperimentRecommendationDispatchError("default_version_missing")
        version = session.exec(
            select(ExperimentVersion).where(
                ExperimentVersion.course_id == course_id,
                ExperimentVersion.experiment_id == experiment_id,
                ExperimentVersion.version_id == definition.default_version_id,
            )
        ).first()
        if version is None or not version.is_active or not version.is_locked:
            raise ExperimentRecommendationDispatchError("default_version_not_recommendable")
        if outline_node_id is not None and outline_node_id not in {
            str(node_id) for node_id in (definition.knowledge_node_ids or [])
        }:
            raise ExperimentRecommendationDispatchError("outline_node_not_in_experiment")

        existing = session.exec(
            select(ExperimentRecommendation).where(
                ExperimentRecommendation.course_id == course_id,
                ExperimentRecommendation.student_id == student_id,
                ExperimentRecommendation.experiment_id == experiment_id,
            )
        ).first()
        if existing is not None:
            return existing, False

        recommendation = ExperimentRecommendation(
            course_id=course_id,
            student_id=student_id,
            experiment_id=experiment_id,
            version_id=version.version_id,
            outline_node_id=outline_node_id,
            proposal_id=proposal.proposal_id,
        )
        session.add(recommendation)
        session.flush()
        return recommendation, True


class ExperimentLabReadService:
    """Read-only laboratory views backed by course experiments.

    ``LabCatalogEntry`` and ``LabEnrollment`` remain migration-only legacy
    storage.  Student product pages read this projection instead so an
    independently-written row can never look like a formal experiment or a
    trusted result.
    """

    @staticmethod
    def _projection_by_experiment(
        session: Session, *, course_id: int,
    ) -> dict[str, ExperimentLabProjection]:
        projections = session.exec(
            select(ExperimentLabProjection).where(
                ExperimentLabProjection.course_id == course_id,
            )
        ).all()
        return {item.experiment_id: item for item in projections}

    @staticmethod
    def _serialize_experiment(
        definition: ExperimentDefinition,
        projection: ExperimentLabProjection | None,
    ) -> dict[str, Any]:
        return {
            # ``lab_id`` is retained only as a view identifier for current
            # clients.  Navigation must use course_id + experiment_id.
            "lab_id": projection.projection_id if projection else None,
            "projection_id": projection.projection_id if projection else None,
            "course_id": definition.course_id,
            "experiment_id": definition.experiment_id,
            "title": definition.title,
            "description": definition.description,
            "statement_object_key": definition.statement_object_key,
            "language_whitelist": list(definition.language_whitelist or []),
            "default_version_id": definition.default_version_id,
            "publish_status": definition.publish_status.value,
            "knowledge_node_ids": list(definition.knowledge_node_ids or []),
            "entry_kind": "course_experiment_projection",
        }

    def list_catalog(
        self,
        session: Session,
        *,
        course_id: int | None = None,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> dict[str, Any]:
        stmt = select(ExperimentDefinition).where(
            ExperimentDefinition.publish_status == ExperimentPublishStatus.PUBLISHED,
        )
        if course_id is not None:
            stmt = stmt.where(ExperimentDefinition.course_id == course_id)
        definitions = list(session.exec(
            stmt.order_by(ExperimentDefinition.created_at.desc())
        ).all())
        projections_by_course = {
            definition.course_id: self._projection_by_experiment(
                session, course_id=definition.course_id,
            )
            for definition in definitions
        }
        if cursor:
            cursor_index = next(
                (index for index, definition in enumerate(definitions)
                 if definition.experiment_id == cursor),
                len(definitions),
            )
            definitions = definitions[cursor_index + 1:]
        page = definitions[:page_size]
        return {
            "items": [
                self._serialize_experiment(
                    definition,
                    projections_by_course[definition.course_id].get(definition.experiment_id),
                )
                for definition in page
            ],
            "next_cursor": page[-1].experiment_id if len(definitions) > page_size and page else None,
            "total": len(definitions),
        }

    def list_course_tasks(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int | None = None,
    ) -> list[dict[str, Any]]:
        definitions = definition_service.list_definitions(
            session,
            course_id=course_id,
            publish_status=ExperimentPublishStatus.PUBLISHED,
        )
        projections = self._projection_by_experiment(session, course_id=course_id)
        recommendations: dict[str, ExperimentRecommendation] = {}
        attempts: dict[str, ExperimentAttempt] = {}
        records: dict[str, LabRecord] = {}
        if student_id is not None:
            recommendations = {
                item.experiment_id: item
                for item in session.exec(
                    select(ExperimentRecommendation).where(
                        ExperimentRecommendation.course_id == course_id,
                        ExperimentRecommendation.student_id == student_id,
                    )
                ).all()
            }
            for attempt in session.exec(
                select(ExperimentAttempt).where(
                    ExperimentAttempt.course_id == course_id,
                    ExperimentAttempt.student_id == student_id,
                ).order_by(ExperimentAttempt.created_at.desc())
            ).all():
                attempts.setdefault(attempt.experiment_id, attempt)
            for record in session.exec(
                select(LabRecord).where(
                    LabRecord.course_id == course_id,
                    LabRecord.student_id == student_id,
                    LabRecord.trusted_source == True,  # noqa: E712
                    LabRecord.source_kind == "experiment_attempt_terminated",
                ).order_by(LabRecord.created_at.desc())
            ).all():
                if record.experiment_id:
                    records.setdefault(record.experiment_id, record)

        items: list[dict[str, Any]] = []
        for definition in definitions:
            attempt = attempts.get(definition.experiment_id)
            record = records.get(definition.experiment_id)
            recommendation = recommendations.get(definition.experiment_id)
            item = self._serialize_experiment(
                definition, projections.get(definition.experiment_id),
            )
            item.update({
                "recommended": recommendation is not None,
                "recommendation_id": recommendation.recommendation_id if recommendation else None,
                "last_attempt_id": attempt.attempt_id if attempt else None,
                "last_attempt_status": attempt.status.value if attempt else None,
                "best_score": record.final_score if record else None,
                "passed": record.passed if record else None,
            })
            items.append(item)
        return items

    def list_my_experiments(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Show only a student's recommendations and server-owned attempts."""
        recommendations = session.exec(
            select(ExperimentRecommendation).where(
                ExperimentRecommendation.course_id == course_id,
                ExperimentRecommendation.student_id == student_id,
            ).order_by(ExperimentRecommendation.updated_at.desc())
        ).all()
        attempts = session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.course_id == course_id,
                ExperimentAttempt.student_id == student_id,
            ).order_by(ExperimentAttempt.updated_at.desc())
        ).all()
        sources: dict[tuple[int, str], dict[str, Any]] = {}
        for recommendation in recommendations:
            sources[(recommendation.course_id, recommendation.experiment_id)] = {
                "recommended": True,
                "recommendation_id": recommendation.recommendation_id,
                "last_attempt_id": None,
                "last_attempt_status": None,
                "updated_at": recommendation.updated_at,
            }
        for attempt in attempts:
            key = (attempt.course_id, attempt.experiment_id)
            current = sources.setdefault(key, {
                "recommended": False,
                "recommendation_id": None,
                "last_attempt_id": None,
                "last_attempt_status": None,
                "updated_at": attempt.updated_at,
            })
            if current["last_attempt_id"] is None:
                current["last_attempt_id"] = attempt.attempt_id
                current["last_attempt_status"] = attempt.status.value
            current["updated_at"] = max(current["updated_at"], attempt.updated_at)

        result: list[dict[str, Any]] = []
        for (course_id, experiment_id), metadata in sources.items():
            definition = session.exec(
                select(ExperimentDefinition).where(
                    ExperimentDefinition.course_id == course_id,
                    ExperimentDefinition.experiment_id == experiment_id,
                )
            ).first()
            if definition is None:
                continue
            if active_only and definition.publish_status != ExperimentPublishStatus.PUBLISHED:
                continue
            projection = self._projection_by_experiment(
                session, course_id=course_id,
            ).get(experiment_id)
            item = self._serialize_experiment(definition, projection)
            item.update({key: value for key, value in metadata.items() if key != "updated_at"})
            item["updated_at"] = metadata["updated_at"].isoformat() if metadata["updated_at"] else None
            result.append(item)
        return sorted(result, key=lambda item: item.get("updated_at") or "", reverse=True)

    def list_records(
        self,
        session: Session,
        *,
        student_id: int,
        course_id: int | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(LabRecord).where(
            LabRecord.student_id == student_id,
            LabRecord.trusted_source == True,  # noqa: E712
            LabRecord.source_kind == "experiment_attempt_terminated",
        )
        if course_id is not None:
            stmt = stmt.where(LabRecord.course_id == course_id)
        records = session.exec(stmt.order_by(LabRecord.created_at.desc())).all()
        result: list[dict[str, Any]] = []
        for record in records:
            if record.course_id is None or not record.experiment_id or not record.attempt_id:
                continue
            attempt = session.exec(
                select(ExperimentAttempt).where(
                    ExperimentAttempt.attempt_id == record.attempt_id,
                    ExperimentAttempt.course_id == record.course_id,
                    ExperimentAttempt.student_id == student_id,
                    ExperimentAttempt.status == AttemptStatus.FINALIZED,
                )
            ).first()
            definition = session.exec(
                select(ExperimentDefinition).where(
                    ExperimentDefinition.course_id == record.course_id,
                    ExperimentDefinition.experiment_id == record.experiment_id,
                )
            ).first()
            if attempt is None or definition is None or attempt.experiment_id != record.experiment_id:
                continue
            result.append({
                "record_id": record.record_id,
                "projection_id": record.projection_id,
                "course_id": record.course_id,
                "experiment_id": record.experiment_id,
                "lab_id": record.lab_id,
                "lab_title": definition.title,
                "attempt_id": record.attempt_id,
                "final_score": record.final_score,
                "passed": record.passed,
                "evidence_id": record.evidence_id,
                "return_anchor": dict(record.return_anchor or {}),
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            })
        return result


class ExperimentPublishValidator:
    """Single server authority for all formal experiment publish preconditions."""

    def validate(
        self, session: Session, *, course_id: int, experiment_id: str,
    ) -> ExperimentDefinition:
        definition = definition_service.get_definition(
            session, course_id=course_id, experiment_id=experiment_id,
        )
        self.validate_existing(session, definition=definition)
        return definition

    def validate_existing(self, session: Session, *, definition: ExperimentDefinition) -> None:
        _require_formal_experiment_capabilities(session, course_id=definition.course_id)
        if not definition.language_whitelist or any(lang not in ALLOWED_LANGUAGES for lang in definition.language_whitelist):
            reject_validation_failed("实验语言白名单为空或包含不支持的语言")
        if not definition.default_version_id:
            reject_state_conflict("实验缺少活动默认版本，无法发布")
        version = version_service.get_version(
            session, course_id=definition.course_id, version_id=definition.default_version_id,
        )
        if version.experiment_id != definition.experiment_id or not version.is_active:
            reject_state_conflict("默认版本不是该实验的活动版本")
        if not version.is_locked:
            reject_state_conflict("活动默认版本必须先锁定")
        if version.reference_preview_verified_at is None:
            reject_state_conflict("参考解预览尚未全量通过")
        if version.passing_score != 1.0:
            reject_validation_failed("正式实验必须使用 ACM/ICPC 通过阈值 1.0")
        if not (1 <= version.cpu_time_limit <= 30 and 16_000 <= version.memory_limit <= 512_000 and 1 <= version.wall_time_limit <= 60):
            reject_validation_failed("实验资源限制超出安全边界")
        cases = version_service.list_test_cases(
            session, course_id=definition.course_id, version_id=version.version_id,
        )
        if not cases:
            reject_validation_failed("实验至少需要一个测试用例")
        if abs(sum(case.weight for case in cases) - 1.0) > 1e-9:
            reject_validation_failed("测试用例权重总和必须为 1")
        if not sandbox_client.health_check():
            reject_state_conflict("Judge0 健康检查未通过，无法发布")


class SandboxExecutionLeaseService:
    """Lease one formal Judge0 slot across every Uvicorn process."""

    def acquire(self, session: Session, *, task_id: str, now: Optional[datetime] = None) -> bool:
        now = now or utcnow_aware()
        expires_at = now + timedelta(seconds=FORMAL_LEASE_SECONDS)
        # Revision 0055 uses ``DateTime()`` columns. SQLite returns those
        # values without tzinfo, so SQL predicates must bind comparable UTC
        # values even though service time is always timezone-aware UTC.
        db_now = to_naive(now)
        db_expires_at = to_naive(expires_at)
        row = session.exec(
            select(SandboxExecutionLease).where(SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY)
        ).first()
        if row is None:
            row = SandboxExecutionLease(
                lease_key=FORMAL_LEASE_KEY,
                holder_task_id=task_id,
                acquired_at=db_now,
                renewed_at=db_now,
                lease_expires_at=db_expires_at,
            )
            try:
                # A unique-key collision means a peer claimed the absent slot first.
                # Keep the caller's outer transaction usable so the worker can wait.
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError:
                return False
            return True

        # Re-check eligibility in SQL. A process may have renewed or reclaimed the
        # row after the read above, so mutating the loaded object would be racy.
        result = session.exec(
            update(SandboxExecutionLease)
            .where(
                SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY,
                or_(
                    SandboxExecutionLease.holder_task_id == task_id,
                    SandboxExecutionLease.lease_expires_at.is_(None),
                    SandboxExecutionLease.lease_expires_at <= db_now,
                ),
            )
            .values(
                holder_task_id=task_id,
                acquired_at=case(
                    (
                        SandboxExecutionLease.holder_task_id == task_id,
                        func.coalesce(SandboxExecutionLease.acquired_at, db_now),
                    ),
                    else_=db_now,
                ),
                renewed_at=db_now,
                lease_expires_at=db_expires_at,
            )
        )
        return result.rowcount == 1

    def renew(self, session: Session, *, task_id: str) -> bool:
        now = utcnow_aware()
        db_now = to_naive(now)
        result = session.exec(
            update(SandboxExecutionLease)
            .where(
                SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY,
                SandboxExecutionLease.holder_task_id == task_id,
                SandboxExecutionLease.lease_expires_at > db_now,
            )
            .values(
                renewed_at=db_now,
                lease_expires_at=to_naive(now + timedelta(seconds=FORMAL_LEASE_SECONDS)),
            )
        )
        return result.rowcount == 1

    def release(self, session: Session, *, task_id: str) -> None:
        row = session.exec(
            select(SandboxExecutionLease).where(SandboxExecutionLease.lease_key == FORMAL_LEASE_KEY)
        ).first()
        if row is not None and row.holder_task_id == task_id:
            row.holder_task_id = ""
            row.lease_expires_at = to_naive(utcnow_aware())
            session.add(row)
            session.flush()


class FreeSandboxQuotaService:
    def consume(self, session: Session, *, student_id: int, course_id: int) -> int:
        now = utcnow_aware()
        epoch = int(now.timestamp())
        window_started_at = datetime.fromtimestamp(
            epoch - (epoch % FREE_SANDBOX_WINDOW_SECONDS), tz=now.tzinfo,
        )
        increment = (
            update(FreeSandboxQuotaWindow)
            .where(
                FreeSandboxQuotaWindow.student_id == student_id,
                FreeSandboxQuotaWindow.course_id == course_id,
                FreeSandboxQuotaWindow.window_started_at == window_started_at,
                FreeSandboxQuotaWindow.run_count < FREE_SANDBOX_MAX_RUNS,
            )
            .values(
                run_count=FreeSandboxQuotaWindow.run_count + 1,
                updated_at=now,
            )
        )
        if session.exec(increment).rowcount == 1:
            return 0
        try:
            with session.begin_nested():
                session.add(FreeSandboxQuotaWindow(
                    student_id=student_id,
                    course_id=course_id,
                    window_started_at=window_started_at,
                    run_count=1,
                    updated_at=now,
                ))
                session.flush()
                return 0
        except IntegrityError:
            if session.exec(increment).rowcount == 1:
                return 0
        return max(1, FREE_SANDBOX_WINDOW_SECONDS - (epoch % FREE_SANDBOX_WINDOW_SECONDS))


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
sandbox_execution_lease_service = SandboxExecutionLeaseService()
free_sandbox_quota_service = FreeSandboxQuotaService()
coding_hint_service = CodingHintService()
recommendation_service = ExperimentRecommendationService()
experiment_lab_read_service = ExperimentLabReadService()
