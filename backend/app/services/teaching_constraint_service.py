"""Persistence and ownership checks for teacher-governed agent constraints."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from pydantic import ValidationError
from sqlmodel import Session, func, select

from app.core.exceptions import (
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.models.access_control_model import (
    CourseMembership,
    CourseRole,
    MembershipStatus,
)
from app.models.course_lifecycle_model import CourseGroup, CourseGroupMember
from app.models.graph_production_model import GraphSnapshotRecord
from app.models.knowledge_bundle_model import CourseKnowledgeBundle, CourseKnowledgeHead
from app.models.teaching_constraint_model import (
    TeachingConstraintEvaluation,
    TeachingConstraintPolicyVersion,
)
from app.platform.agents.edu.constraints import (
    ALL_SCOPES,
    ConstraintSubject,
    canonicalize_snapshot,
    resolve_effective_constraint,
)
from app.schemas.teaching_constraint import (
    TeachingConstraintEnvelope,
    TeachingConstraintSnapshot,
)


DEFAULT_POLICY = {
    "level": "balanced",
    "scopes": ALL_SCOPES,
    "rules": [],
}


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_list(values: Iterable[str], *, limit: int = 50) -> str:
    sanitized = [str(value)[:128] for value in values][:limit]
    return _compact_json(sanitized)


class TeachingConstraintService:
    """Own the independent hardness policy lifecycle and safe evaluation audit."""

    def get_current(
        self, session: Session, *, course_id: int
    ) -> TeachingConstraintPolicyVersion | None:
        return session.exec(
            select(TeachingConstraintPolicyVersion)
            .where(
                TeachingConstraintPolicyVersion.course_id == course_id,
                TeachingConstraintPolicyVersion.is_active == True,  # noqa: E712
            )
            .order_by(TeachingConstraintPolicyVersion.version.desc())
        ).first()

    def get_version(
        self, session: Session, *, course_id: int, version: int
    ) -> TeachingConstraintPolicyVersion | None:
        return session.exec(
            select(TeachingConstraintPolicyVersion).where(
                TeachingConstraintPolicyVersion.course_id == course_id,
                TeachingConstraintPolicyVersion.version == version,
            )
        ).first()

    def list_versions(
        self, session: Session, *, course_id: int, limit: int = 50
    ) -> list[TeachingConstraintPolicyVersion]:
        return list(
            session.exec(
                select(TeachingConstraintPolicyVersion)
                .where(TeachingConstraintPolicyVersion.course_id == course_id)
                .order_by(TeachingConstraintPolicyVersion.version.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
        )

    def list_evaluations(
        self, session: Session, *, course_id: int, limit: int = 100
    ) -> list[TeachingConstraintEvaluation]:
        return list(
            session.exec(
                select(TeachingConstraintEvaluation)
                .where(TeachingConstraintEvaluation.course_id == course_id)
                .order_by(TeachingConstraintEvaluation.created_at.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
        )

    @staticmethod
    def parse_snapshot(
        version: TeachingConstraintPolicyVersion | None,
    ) -> TeachingConstraintSnapshot:
        if version is None:
            return canonicalize_snapshot(DEFAULT_POLICY)
        try:
            payload = json.loads(version.policy_snapshot)
        except (TypeError, ValueError) as exc:
            raise ValueError("stored teaching constraint snapshot is invalid") from exc
        return canonicalize_snapshot(payload)

    def _validate_unique_selectors(self, snapshot: TeachingConstraintSnapshot) -> None:
        seen: set[tuple[Any, ...]] = set()
        for rule in snapshot.rules:
            key = (
                rule.priority,
                rule.target_type,
                rule.target_id,
                rule.intent,
                rule.concept_id,
            )
            if key in seen:
                reject_validation_failed(
                    "相同优先级下存在重复的约束选择器",
                    details={"reason_code": "DUPLICATE_CONSTRAINT_SELECTOR"},
                )
            seen.add(key)

    @staticmethod
    def _active_snapshot_nodes(session: Session, *, course_id: int) -> set[str]:
        head = session.exec(
            select(CourseKnowledgeHead).where(CourseKnowledgeHead.course_id == course_id)
        ).first()
        if head is None or not head.active_bundle_id:
            return set()
        bundle = session.exec(
            select(CourseKnowledgeBundle).where(
                CourseKnowledgeBundle.course_id == course_id,
                CourseKnowledgeBundle.bundle_id == head.active_bundle_id,
            )
        ).first()
        if bundle is None:
            return set()
        snapshot = session.exec(
            select(GraphSnapshotRecord).where(
                GraphSnapshotRecord.course_id == course_id,
                GraphSnapshotRecord.snapshot_id == bundle.graph_snapshot_id,
            )
        ).first()
        if snapshot is None:
            return set()
        node_ids: set[str] = set()
        for node in snapshot.nodes or []:
            if not isinstance(node, Mapping):
                continue
            for key in ("node_key", "id", "node_id"):
                value = node.get(key)
                if value is not None and str(value):
                    node_ids.add(str(value))
        return node_ids

    def validate_targets(
        self,
        session: Session,
        *,
        course_id: int,
        snapshot: TeachingConstraintSnapshot,
    ) -> None:
        """Fail the whole write if any selector escapes the current course."""

        self._validate_unique_selectors(snapshot)
        concept_ids = {rule.concept_id for rule in snapshot.rules if rule.concept_id}
        active_concepts = (
            self._active_snapshot_nodes(session, course_id=course_id)
            if concept_ids
            else set()
        )

        for rule in snapshot.rules:
            if rule.target_type == "group":
                group = session.exec(
                    select(CourseGroup).where(
                        CourseGroup.course_id == course_id,
                        CourseGroup.group_id == rule.target_id,
                    )
                ).first()
                if group is None:
                    reject_validation_failed(
                        "约束分组不属于当前课程",
                        details={
                            "reason_code": "CONSTRAINT_GROUP_OUT_OF_SCOPE",
                            "rule_id": rule.rule_id,
                        },
                    )
            else:
                try:
                    user_id = int(rule.target_id)
                except ValueError:
                    reject_validation_failed(
                        "学生目标必须使用课程成员 ID",
                        details={
                            "reason_code": "CONSTRAINT_STUDENT_INVALID",
                            "rule_id": rule.rule_id,
                        },
                    )
                membership = session.exec(
                    select(CourseMembership).where(
                        CourseMembership.course_id == course_id,
                        CourseMembership.user_id == user_id,
                        CourseMembership.role == CourseRole.STUDENT,
                        CourseMembership.status == MembershipStatus.ACTIVE,
                    )
                ).first()
                if membership is None:
                    reject_validation_failed(
                        "约束学生不是当前课程的活跃学习者",
                        details={
                            "reason_code": "CONSTRAINT_STUDENT_OUT_OF_SCOPE",
                            "rule_id": rule.rule_id,
                        },
                    )
            if rule.concept_id and rule.concept_id not in active_concepts:
                reject_validation_failed(
                    "约束知识点不属于当前课程 Active Bundle",
                    details={
                        "reason_code": "CONSTRAINT_CONCEPT_OUT_OF_SCOPE",
                        "rule_id": rule.rule_id,
                    },
                )

    def _append_version(
        self,
        session: Session,
        *,
        course_id: int,
        snapshot: TeachingConstraintSnapshot,
        actor_user_id: int,
        change_reason: str,
    ) -> TeachingConstraintPolicyVersion:
        current = self.get_current(session, course_id=course_id)
        if current is not None:
            current.is_active = False
            session.add(current)
            # The partial unique active-course index requires the superseding
            # UPDATE to be visible before the new active row is inserted.
            session.flush()
        max_version = session.exec(
            select(func.max(TeachingConstraintPolicyVersion.version)).where(
                TeachingConstraintPolicyVersion.course_id == course_id
            )
        ).one() or 0
        serialized = _compact_json(snapshot.model_dump(mode="json"))
        row = TeachingConstraintPolicyVersion(
            course_id=course_id,
            version=int(max_version) + 1,
            policy_snapshot=serialized,
            policy_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            is_active=True,
            change_reason=change_reason.strip()[:256],
            created_by=actor_user_id,
        )
        session.add(row)
        session.flush()
        return row

    def save(
        self,
        session: Session,
        *,
        course_id: int,
        expected_version: int,
        actor_user_id: int,
        change_reason: str,
        payload: TeachingConstraintSnapshot | Mapping[str, Any],
    ) -> TeachingConstraintPolicyVersion:
        current = self.get_current(session, course_id=course_id)
        current_version = current.version if current else 0
        if expected_version != current_version:
            reject_state_conflict(
                "教学约束策略版本冲突",
                details={
                    "reason_code": "CONSTRAINT_VERSION_CONFLICT",
                    "expected_version": expected_version,
                    "current_version": current_version,
                },
            )
        if len(change_reason.strip()) < 3:
            reject_validation_failed(
                "变更原因至少需要 3 个字符",
                details={"reason_code": "CONSTRAINT_CHANGE_REASON_REQUIRED"},
            )
        try:
            canonical = canonicalize_snapshot(payload)
        except ValidationError as exc:
            reject_validation_failed(
                "教学约束策略不符合契约",
                details={
                    "reason_code": "CONSTRAINT_POLICY_INVALID",
                    "errors": exc.errors(include_url=False, include_input=False),
                },
            )
        self.validate_targets(session, course_id=course_id, snapshot=canonical)
        return self._append_version(
            session,
            course_id=course_id,
            snapshot=canonical,
            actor_user_id=actor_user_id,
            change_reason=change_reason,
        )

    def rollback(
        self,
        session: Session,
        *,
        course_id: int,
        target_version: int,
        expected_version: int,
        actor_user_id: int,
        change_reason: str,
    ) -> TeachingConstraintPolicyVersion:
        current = self.get_current(session, course_id=course_id)
        current_version = current.version if current else 0
        if expected_version != current_version:
            reject_state_conflict(
                "教学约束策略版本冲突",
                details={
                    "reason_code": "CONSTRAINT_VERSION_CONFLICT",
                    "expected_version": expected_version,
                    "current_version": current_version,
                },
            )
        target = self.get_version(session, course_id=course_id, version=target_version)
        if target is None:
            reject_resource_not_found("教学约束策略版本不存在")
        snapshot = self.parse_snapshot(target)
        self.validate_targets(session, course_id=course_id, snapshot=snapshot)
        return self._append_version(
            session,
            course_id=course_id,
            snapshot=snapshot,
            actor_user_id=actor_user_id,
            change_reason=change_reason,
        )

    def resolve(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        intent: str | None = None,
        concept_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[TeachingConstraintPolicyVersion | None, TeachingConstraintEnvelope]:
        version = self.get_current(session, course_id=course_id)
        snapshot = self.parse_snapshot(version)
        envelope = self.preview(
            session,
            course_id=course_id,
            student_id=student_id,
            snapshot=snapshot,
            intent=intent,
            concept_id=concept_id,
            now=now,
        )
        return version, envelope

    def preview(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        snapshot: TeachingConstraintSnapshot | Mapping[str, Any] | None = None,
        intent: str | None = None,
        concept_id: str | None = None,
        now: datetime | None = None,
    ) -> TeachingConstraintEnvelope:
        membership = session.exec(
            select(CourseMembership).where(
                CourseMembership.course_id == course_id,
                CourseMembership.user_id == student_id,
                CourseMembership.role == CourseRole.STUDENT,
                CourseMembership.status == MembershipStatus.ACTIVE,
            )
        ).first()
        if membership is None:
            reject_validation_failed(
                "预览对象不是当前课程的活跃学习者",
                details={"reason_code": "CONSTRAINT_STUDENT_OUT_OF_SCOPE"},
            )
        resolved_snapshot = (
            canonicalize_snapshot(snapshot)
            if snapshot is not None
            else self.parse_snapshot(self.get_current(session, course_id=course_id))
        )
        self.validate_targets(
            session, course_id=course_id, snapshot=resolved_snapshot
        )
        group_ids = tuple(
            session.exec(
                select(CourseGroupMember.group_id).where(
                    CourseGroupMember.course_id == course_id,
                    CourseGroupMember.user_id == student_id,
                )
            ).all()
        )
        envelope = resolve_effective_constraint(
            snapshot=resolved_snapshot,
            subject=ConstraintSubject(
                student_id=str(student_id),
                group_ids=tuple(str(value) for value in group_ids),
                intent=intent,
                concept_id=concept_id,
            ),
            now=now,
        )
        return envelope

    def record_evaluation(
        self,
        session: Session,
        *,
        trace_id: str,
        course_id: int,
        student_id: int,
        policy_version_id: int,
        effective_level: str,
        matched_rule_ids: Sequence[str],
        applied_scopes: Sequence[str],
        decision_codes: Sequence[str],
        context_input_chars: int,
        context_output_chars: int,
        valid_citation_count: int,
        enforcement_status: str,
    ) -> TeachingConstraintEvaluation:
        record = TeachingConstraintEvaluation(
            trace_id=trace_id[:128],
            course_id=course_id,
            student_id=student_id,
            policy_version_id=policy_version_id,
            effective_level=effective_level[:16],
            matched_rule_ids=_json_list(matched_rule_ids),
            applied_scopes=_json_list(applied_scopes),
            decision_codes=_json_list(decision_codes),
            context_input_chars=max(0, int(context_input_chars)),
            context_output_chars=max(0, int(context_output_chars)),
            valid_citation_count=max(0, int(valid_citation_count)),
            enforcement_status=enforcement_status[:32],
        )
        session.add(record)
        session.flush()
        return record


teaching_constraint_service = TeachingConstraintService()
