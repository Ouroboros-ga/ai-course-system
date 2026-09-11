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
import hashlib
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
from app.domain.oj.judging.providers.judge0 import (
    ALLOWED_LANGUAGES,
    SandboxResourceLimits,
    SubmissionStatus,
    sandbox_client,
)
from app.domain.oj.judging.verdicts import reason_for_status
from app.domain.oj.problems.metadata import normalize_difficulty, normalize_tags
# PR-03：题目侧服务（定义/版本）已拆至 experiment_problem_service，
# 单例随类迁移 —— 旧导入名在此保留引用以缩小本 PR 触面；新代码请从新模块导入。
# PR-03/04：题目侧服务已拆至 experiment_problem_service，作答侧已拆至
# experiment_attempt_service —— 单例随类迁移；此处保留的是**留守代码的真实依赖**。
from app.services.experiment_problem_service import (  # noqa: F401
    _require_formal_experiment_capabilities,
    definition_service,
    version_service,
)
from app.domain.oj.intelligence import (
    CODING_HINT_POLICY_VERSION,
    assert_full_solution_allowed,
    normalize_review_decision,
)
from app.services.experiment_attempt_service import (  # noqa: F401
    attempt_service,
    finalize_service,
    run_service,
)
from app.services.learning_evidence_context_service import upsert_learning_evidence_context
from app.domain.learning.evidence import EvidenceType


logger = logging.getLogger(__name__)

# 提示策略版本号，每次提示策略变更时递增

# 默认禁止 full_solution 提示，需教师策略显式允许
# TODO(P1-C1): 未来应从课程/版本教师策略（CourseSafetyPolicy 或实验定义）读取
# full_solution 是否被允许；当前无策略查询逻辑，硬编码为 False，
# 且客户端不可覆盖（端点已移除 full_solution_allowed 字段）。
DEFAULT_FULL_SOLUTION_ALLOWED = False
FORMAL_LEASE_KEY = "formal_judge0"
FORMAL_LEASE_SECONDS = 90
FREE_SANDBOX_WINDOW_SECONDS = 10 * 60
FREE_SANDBOX_MAX_RUNS = 10




# ---------------------------------------------------------------------------
# PR-09：题目元数据（难度 / 标签）的服务层适配
# ---------------------------------------------------------------------------
#
# 规则本身在 `domain/oj/problems/metadata.py`（域层：合法取值是什么、怎么规范化）。
# 这里只做两件域层不该管的事：
#
# 1. **把 `ValueError` 翻成 `reject_validation_failed`** —— 域层不 import
#    `app.core.exceptions`（与 `domain/oj` 其余部分的边界一致），所以"抛什么
#    异常"是调用方的责任。翻译放在单点，避免每个调用处各写一份 try。
# 2. **决定"什么时候校验"** —— create 恒校验（没填也会规范化成默认值），
#    update 是 PATCH 语义：`None` 表示"别动这一列"，空 list 表示"清空标签"。
#    这个区分是业务策略，域层看不到，因此留在 service。






# ---------------------------------------------------------------------------
# 实验定义服务
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 实验版本服务
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 实验尝试服务
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 实验运行服务
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 实验终结化服务（finalize）
# ---------------------------------------------------------------------------






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
            ExperimentDefinition.visibility == "course_catalog",
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

        # full_solution 默认禁止 —— 门禁在域层单点（PR-06b 归位），
        # 任何产生提示的路径都必须过同一道门，不允许各端点各写一份。
        try:
            assert_full_solution_allowed(hint_level, full_solution_allowed)
        except ValueError:
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
        try:
            normalize_review_decision(decision)
        except ValueError as exc:
            reject_validation_failed(str(exc))
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


sandbox_execution_lease_service = SandboxExecutionLeaseService()
free_sandbox_quota_service = FreeSandboxQuotaService()
coding_hint_service = CodingHintService()
recommendation_service = ExperimentRecommendationService()
experiment_lab_read_service = ExperimentLabReadService()
