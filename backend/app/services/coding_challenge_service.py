"""Application service for conversation-scoped coding challenge offers.

The service owns the course/student/conversation predicates.  API handlers must
not assemble offers from experiments directly because doing so makes it too
easy to restore another learner's private AI challenge after a page refresh.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlmodel import Session, select

from app.core.exceptions import reject_resource_not_found, reject_state_conflict
from app.core.time_utils import to_aware, utcnow_aware
from app.domain.learning.evidence import EvidenceType
from app.models.access_control_model import CourseCapability
from app.models.coding_diagnosis_model import CodingDiagnosisRecord
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_outline_model import CourseOutlineNode
from app.models.experiment_model import (
    AttemptStatus,
    CodingChallengeOffer,
    CodingEvidenceEpisode,
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentRun,
    ExperimentTestCase,
    ExperimentVersion,
    RunOutcome,
)
from app.models.graph_production_model import CourseKnowledgeNode
from app.platform.agents.edu.coding import build_teaching_feedback
from app.services.learning_evidence_context_service import (
    upsert_learning_evidence_context,
)

logger = logging.getLogger(__name__)
_RESTORABLE_OFFER_STATUSES = ("preparing", "ready", "started")
_AI_CHALLENGE_LANGUAGES = frozenset({"python3", "javascript", "cpp", "c", "java"})
_SESSION_OFFER_WINDOW = timedelta(minutes=30)
_VALID_EVIDENCE_OUTCOMES = {
    RunOutcome.ACCEPTED,
    RunOutcome.WRONG_ANSWER,
    RunOutcome.TIME_LIMIT_EXCEEDED,
    RunOutcome.MEMORY_LIMIT_EXCEEDED,
    RunOutcome.RUNTIME_ERROR,
    RunOutcome.COMPILATION_ERROR,
}


class CodingChallengeService:
    """Create and restore low-noise conversational challenge offers."""

    @staticmethod
    def serialize_offer(offer: CodingChallengeOffer) -> dict[str, Any]:
        return {
            "offer_id": offer.offer_id,
            "status": offer.status,
            "source": offer.source,
            "title": offer.title,
            "why_now": offer.why_now,
            "concept_id": offer.concept_id,
            "difficulty": offer.difficulty,
            "estimated_minutes": offer.estimated_minutes,
            "languages": list(offer.languages or []),
            "task_id": offer.task_id,
            "actions": {
                "can_start": offer.status == "ready",
                "can_replace": (
                    offer.status in ("preparing", "ready", "failed")
                    and offer.replacement_count < 2
                ),
                "can_dismiss": offer.status in ("preparing", "ready"),
            },
            "reason_code": offer.reason_code,
        }

    @staticmethod
    def serialize_session(
        attempt: ExperimentAttempt,
        version: ExperimentVersion,
        languages: list[str],
        definition: ExperimentDefinition | None = None,
        public_tests: list[ExperimentTestCase] | None = None,
    ) -> dict[str, Any]:
        selected_language = languages[0] if languages else "python3"
        return {
            "session_id": attempt.attempt_id,
            "status": attempt.status.value,
            "interaction_mode": attempt.interaction_mode,
            "language": selected_language,
            "languages": list(languages),
            "starter_code": str((version.starter_code or {}).get(selected_language, "")),
            "return_anchor": dict(attempt.return_anchor or {}),
            "last_activity_at": attempt.last_activity_at.isoformat(),
            "problem": {
                "title": definition.title if definition is not None else "",
                "description": definition.description if definition is not None else "",
                "public_examples": [
                    {
                        "case_name": item.case_name,
                        "stdin": item.stdin,
                        "expected_stdout": item.expected_stdout,
                    }
                    for item in (public_tests or [])
                    if not item.is_hidden
                ],
            },
        }

    @staticmethod
    def _preferred_ai_language(
        session: Session,
        *,
        course_id: int,
        student_id: int,
    ) -> str:
        recent = session.exec(
            select(ExperimentRun)
            .where(
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
                ExperimentRun.language.in_(_AI_CHALLENGE_LANGUAGES),
            )
            .order_by(ExperimentRun.submitted_at.desc())
        ).first()
        return recent.language if recent is not None else "python3"

    @staticmethod
    def _recent_session_offer_count(
        session: Session,
        *,
        course_id: int,
        student_id: int,
        conversation_session_id: str,
        now=None,
    ) -> int:
        """Count proactive offers in the current bounded learning window.

        Browser conversation identifiers intentionally survive refreshes and
        can outlive a real study session.  Counting their full history would
        permanently exhaust the learner's suggestion budget.  Replacement
        records are continuations of an existing offer, not new suggestions.
        """
        reference_time = now or utcnow_aware()
        offers = session.exec(select(CodingChallengeOffer.offer_id).where(
            CodingChallengeOffer.course_id == course_id,
            CodingChallengeOffer.student_id == student_id,
            CodingChallengeOffer.conversation_session_id == conversation_session_id,
            CodingChallengeOffer.replacement_count == 0,
            CodingChallengeOffer.created_at >= reference_time - _SESSION_OFFER_WINDOW,
        )).all()
        return len(offers)

    @staticmethod
    def _public_tests(
        session: Session,
        *,
        course_id: int,
        version_id: str,
    ) -> list[ExperimentTestCase]:
        return list(session.exec(select(ExperimentTestCase).where(
            ExperimentTestCase.course_id == course_id,
            ExperimentTestCase.version_id == version_id,
            ExperimentTestCase.is_hidden.is_(False),
        )).all())

    @staticmethod
    def _owned_offer(
        session: Session,
        *,
        offer_id: str,
        course_id: int,
        student_id: int,
    ) -> CodingChallengeOffer:
        offer = session.exec(
            select(CodingChallengeOffer).where(
                CodingChallengeOffer.offer_id == offer_id,
                CodingChallengeOffer.course_id == course_id,
                CodingChallengeOffer.student_id == student_id,
            )
        ).first()
        if offer is None:
            reject_resource_not_found("Coding challenge offer not found")
        return offer

    def create_ready_offer(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        conversation_session_id: str,
        trace_id: str,
        concept_id: str | None,
        title: str,
        why_now: str,
        difficulty: str,
        estimated_minutes: int,
        languages: list[str],
        experiment_id: str,
        version_id: str,
        source_release_id: str | None,
        outline_node_id: str | None,
        reason_codes: list[str] | None = None,
    ) -> CodingChallengeOffer:
        now = utcnow_aware()
        offer = CodingChallengeOffer(
            course_id=course_id,
            student_id=student_id,
            conversation_session_id=conversation_session_id,
            trace_id=trace_id,
            concept_id=concept_id,
            status="ready",
            source="existing",
            title=title,
            why_now=why_now,
            difficulty=difficulty,
            estimated_minutes=estimated_minutes,
            languages=list(languages),
            reason_codes=list(reason_codes or []),
            experiment_id=experiment_id,
            version_id=version_id,
            source_release_id=source_release_id,
            outline_node_id=outline_node_id,
            expires_at=now + timedelta(hours=24),
            created_at=now,
            updated_at=now,
        )
        session.add(offer)
        session.flush()
        return offer

    def create_preparing_offer(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        conversation_session_id: str,
        trace_id: str,
        concept_id: str,
        why_now: str,
        difficulty: str,
        languages: list[str],
        source_release_id: str,
        outline_node_id: str,
        reason_codes: list[str],
        replacement_count: int = 0,
    ) -> CodingChallengeOffer:
        now = utcnow_aware()
        offer = CodingChallengeOffer(
            course_id=course_id,
            student_id=student_id,
            conversation_session_id=conversation_session_id,
            trace_id=trace_id,
            concept_id=concept_id,
            status="preparing",
            source="ai",
            title="正在准备代码挑战",
            why_now=why_now,
            difficulty=difficulty,
            estimated_minutes=10,
            languages=list(languages or ["python3"]),
            reason_codes=list(reason_codes),
            source_release_id=source_release_id,
            outline_node_id=outline_node_id,
            replacement_count=replacement_count,
            expires_at=now + timedelta(hours=24),
            created_at=now,
            updated_at=now,
        )
        session.add(offer)
        session.flush()
        return offer

    async def maybe_create_offer(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        conversation_session_id: str,
        trace_id: str,
        message: str,
        concept_id: str | None,
        teaching_action: str | None,
        sandbox_available: bool | None = None,
    ) -> dict[str, Any] | None:
        """Apply decision plus server gates, preferring a verified course task."""
        from app.platform.agents.edu.coding import coding_challenge_decision_policy
        from app.services.agent_governance_service import agent_governance_service

        capability = session.exec(select(CourseCapability).where(
            CourseCapability.course_id == course_id,
        )).first()
        if capability is None or not capability.experiment or not capability.coding_sandbox:
            return None
        # ``None`` preserves direct service/test compatibility. The public
        # TeachingAgent route passes the cached Judge0 port health explicitly,
        # so checking availability never adds a synchronous network call to a
        # normal teaching response.
        if sandbox_available is False:
            return None
        if not agent_governance_service.is_tool_enabled(
            session, course_id=course_id, tool_name="coding_challenge",
        ):
            return None
        active = session.exec(
            select(CodingChallengeOffer).where(
                CodingChallengeOffer.course_id == course_id,
                CodingChallengeOffer.student_id == student_id,
                CodingChallengeOffer.status.in_(_RESTORABLE_OFFER_STATUSES),
            ).order_by(CodingChallengeOffer.created_at.desc())
        ).first()
        if active is not None:
            if to_aware(active.expires_at) <= utcnow_aware():
                active.status = "expired"
                active.updated_at = utcnow_aware()
                session.add(active)
                session.flush()
            elif active.conversation_session_id == conversation_session_id:
                return self.serialize_offer(active)
            else:
                return None

        decision = await coding_challenge_decision_policy.decide(
            message=message,
            concept_id=concept_id,
            teaching_action=teaching_action,
            trace_id=trace_id,
            course_id=course_id,
        )
        if (
            not decision.code_practice_fit
            or decision.pedagogical_timing != "now"
            or not concept_id
            or decision.target_concept_id not in (None, concept_id)
        ):
            return None
        if self._recent_session_offer_count(
            session,
            course_id=course_id,
            student_id=student_id,
            conversation_session_id=conversation_session_id,
        ) >= 3:
            return None
        explicit = coding_challenge_decision_policy.is_explicit_request(message)
        if not explicit:
            recent_same = session.exec(select(CodingChallengeOffer.offer_id).where(
                CodingChallengeOffer.course_id == course_id,
                CodingChallengeOffer.student_id == student_id,
                CodingChallengeOffer.concept_id == concept_id,
                CodingChallengeOffer.created_at >= utcnow_aware() - timedelta(minutes=10),
            )).first()
            if recent_same is not None:
                return None

        release = session.exec(select(CourseRelease).where(
            CourseRelease.course_id == course_id,
            CourseRelease.status == ReleaseStatus.PUBLISHED,
            CourseRelease.is_active == True,
        )).first()
        outline_node = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == course_id,
            CourseOutlineNode.outline_version_id == (release.outline_version_id if release else None),
            CourseOutlineNode.knowledge_graph_node_id == concept_id,
        )).first()
        knowledge_node = session.exec(select(CourseKnowledgeNode).where(
            CourseKnowledgeNode.course_id == course_id,
            CourseKnowledgeNode.node_key == concept_id,
        )).first()
        if release is None or outline_node is None or knowledge_node is None:
            return None

        why_now = self._why_now(list(decision.reason_codes or []))
        preferred_language = self._preferred_ai_language(
            session,
            course_id=course_id,
            student_id=student_id,
        )
        candidate = self._select_existing_definition(
            session,
            course_id=course_id,
            student_id=student_id,
            knowledge_node_id=int(knowledge_node.id),
            language=preferred_language,
        )
        if candidate is not None:
            definition, version = candidate
            offer = self.create_ready_offer(
                session,
                course_id=course_id,
                student_id=student_id,
                conversation_session_id=conversation_session_id,
                trace_id=trace_id,
                concept_id=concept_id,
                title=definition.title,
                why_now=why_now,
                difficulty=decision.difficulty,
                estimated_minutes=10,
                languages=list(definition.language_whitelist or ["python3"]),
                experiment_id=definition.experiment_id,
                version_id=version.version_id,
                source_release_id=release.release_id,
                outline_node_id=outline_node.outline_node_id,
                reason_codes=list(decision.reason_codes or []),
            )
            session.commit()
            return self.serialize_offer(offer)

        offer = self.create_preparing_offer(
            session,
            course_id=course_id,
            student_id=student_id,
            conversation_session_id=conversation_session_id,
            trace_id=trace_id,
            concept_id=concept_id,
            why_now=why_now,
            difficulty=decision.difficulty,
            languages=[preferred_language],
            source_release_id=release.release_id,
            outline_node_id=outline_node.outline_node_id,
            reason_codes=list(decision.reason_codes or []),
        )
        self._enqueue_prepare_task(session, offer)
        return self.serialize_offer(offer)

    @staticmethod
    def _why_now(reason_codes: list[str]) -> str:
        if "EXPLICIT_PRACTICE_REQUEST" in reason_codes:
            return "你刚刚提出想练习，可以用一道短题把当前概念落实到代码。"
        if "REPEATED_CONFUSION" in reason_codes:
            return "用一次可运行的小练习检验当前理解，并据结果继续讲解。"
        return "把刚讨论的编程概念落实到一次可运行的小练习。"

    @staticmethod
    def _select_existing_definition(
        session: Session,
        *,
        course_id: int,
        student_id: int,
        knowledge_node_id: int,
        language: str,
    ) -> tuple[ExperimentDefinition, ExperimentVersion] | None:
        definitions = session.exec(select(ExperimentDefinition).where(
            ExperimentDefinition.course_id == course_id,
            ExperimentDefinition.publish_status == ExperimentPublishStatus.PUBLISHED,
            ExperimentDefinition.visibility == "course_catalog",
        ).order_by(ExperimentDefinition.updated_at.desc())).all()
        recent_cutoff = utcnow_aware() - timedelta(days=7)
        for definition in definitions:
            if knowledge_node_id not in (definition.knowledge_node_ids or []):
                continue
            if language not in (definition.language_whitelist or []):
                continue
            recent = session.exec(select(ExperimentAttempt.id).where(
                ExperimentAttempt.course_id == course_id,
                ExperimentAttempt.student_id == student_id,
                ExperimentAttempt.experiment_id == definition.experiment_id,
                ExperimentAttempt.created_at >= recent_cutoff,
            )).first()
            if recent is not None or not definition.default_version_id:
                continue
            version = session.exec(select(ExperimentVersion).where(
                ExperimentVersion.course_id == course_id,
                ExperimentVersion.version_id == definition.default_version_id,
                ExperimentVersion.experiment_id == definition.experiment_id,
                ExperimentVersion.is_locked == True,
                ExperimentVersion.reference_preview_verified_at.is_not(None),
            )).first()
            if version is not None:
                return definition, version
        return None

    @staticmethod
    def _enqueue_prepare_task(session: Session, offer: CodingChallengeOffer) -> None:
        from app.services.task_service import TaskCreateRequest, task_service

        task = task_service.create_task(session, TaskCreateRequest(
            task_type="coding_challenge_prepare",
            owner_user_id=offer.student_id,
            course_id=offer.course_id,
            input_summary=f"课程 {offer.course_id} 对话代码挑战准备",
            input_payload={
                "course_id": offer.course_id,
                "student_id": offer.student_id,
                "offer_id": offer.offer_id,
            },
            idempotency_key=f"coding-challenge-prepare:{offer.offer_id}",
            resource_links=[
                {"resource_kind": "course", "resource_id": str(offer.course_id), "relation": "input"},
                {"resource_kind": "coding_challenge_offer", "resource_id": offer.offer_id, "relation": "output"},
            ],
        ), commit=False)
        offer.task_id = task.task_id
        offer.updated_at = utcnow_aware()
        session.add(offer)
        session.commit()
        try:
            from app.models.database import session_factory
            from app.platform.tasks.worker import local_task_worker

            if local_task_worker.has_handler("coding_challenge_prepare"):
                local_task_worker.submit(
                    session_factory,
                    task.task_id,
                    {
                        "course_id": offer.course_id,
                        "student_id": offer.student_id,
                        "offer_id": offer.offer_id,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - durable task remains recoverable
            logger.info(
                "Deferred coding challenge task submission for offer=%s type=%s",
                offer.offer_id,
                type(exc).__name__,
            )

    def get_active_state(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        conversation_session_id: str,
    ) -> dict[str, Any]:
        offer = session.exec(
            select(CodingChallengeOffer)
            .where(
                CodingChallengeOffer.course_id == course_id,
                CodingChallengeOffer.student_id == student_id,
                CodingChallengeOffer.conversation_session_id == conversation_session_id,
                CodingChallengeOffer.status.in_(_RESTORABLE_OFFER_STATUSES),
            )
            .order_by(CodingChallengeOffer.created_at.desc())
        ).first()
        if offer is None:
            return {"offer": None, "session": None}

        if to_aware(offer.expires_at) <= utcnow_aware():
            offer.status = "expired"
            offer.updated_at = utcnow_aware()
            session.add(offer)
            session.commit()
            return {"offer": None, "session": None}

        attempt = None
        version = None
        definition = None
        if offer.attempt_id:
            attempt = session.exec(
                select(ExperimentAttempt).where(
                    ExperimentAttempt.attempt_id == offer.attempt_id,
                    ExperimentAttempt.course_id == course_id,
                    ExperimentAttempt.student_id == student_id,
                )
            ).first()
            if attempt is not None:
                version = session.exec(
                    select(ExperimentVersion).where(
                        ExperimentVersion.version_id == attempt.version_id,
                        ExperimentVersion.course_id == course_id,
                    )
                ).first()
                definition = session.exec(select(ExperimentDefinition).where(
                    ExperimentDefinition.experiment_id == attempt.experiment_id,
                    ExperimentDefinition.course_id == course_id,
                )).first()
        if offer.status == "started" and (
            attempt is None or attempt.status != AttemptStatus.IN_PROGRESS
        ):
            offer.status = "closed"
            offer.reason_code = "SESSION_NOT_ACTIVE"
            offer.updated_at = utcnow_aware()
            session.add(offer)
            session.commit()
            return {"offer": None, "session": None}
        if (
            attempt is not None
            and attempt.status == AttemptStatus.IN_PROGRESS
            and utcnow_aware() - to_aware(attempt.last_activity_at) >= timedelta(minutes=45)
        ):
            self.close_session(
                session,
                attempt_id=attempt.attempt_id,
                course_id=course_id,
                student_id=student_id,
                reason="inactive_timeout",
            )
            return {"offer": None, "session": None}
        session_view = (
            self.serialize_session(
                attempt,
                version,
                list(offer.languages or []),
                definition,
                self._public_tests(
                    session, course_id=course_id, version_id=version.version_id,
                ),
            )
            if attempt is not None and version is not None
            else None
        )
        if session_view is not None:
            latest_run = session.exec(
                select(ExperimentRun)
                .where(
                    ExperimentRun.attempt_id == attempt.attempt_id,
                    ExperimentRun.course_id == course_id,
                    ExperimentRun.student_id == student_id,
                )
                .order_by(ExperimentRun.submitted_at.desc())
            ).first()
            if latest_run is not None:
                session_view["latest_run"] = self.get_run_view(
                    session,
                    run_id=latest_run.run_id,
                    course_id=course_id,
                    student_id=student_id,
                )
        return {
            "offer": self.serialize_offer(offer),
            "session": session_view,
        }

    def recover_inactive_sessions(
        self,
        session: Session,
        *,
        inactive_after: timedelta = timedelta(minutes=45),
        limit: int = 200,
    ) -> int:
        """Close bounded stale guided sessions during startup recovery."""
        cutoff = utcnow_aware() - inactive_after
        attempts = session.exec(
            select(ExperimentAttempt)
            .where(
                ExperimentAttempt.interaction_mode == "guided_practice",
                ExperimentAttempt.status == AttemptStatus.IN_PROGRESS,
                ExperimentAttempt.last_activity_at <= cutoff,
            )
            .order_by(ExperimentAttempt.last_activity_at.asc())
            .limit(max(1, min(int(limit), 1_000)))
        ).all()
        recovered = 0
        for attempt in attempts:
            try:
                self.close_session(
                    session,
                    attempt_id=attempt.attempt_id,
                    course_id=attempt.course_id,
                    student_id=attempt.student_id,
                    reason="inactive_timeout",
                )
                recovered += 1
            except Exception as exc:  # noqa: BLE001 - one corrupt row cannot block startup
                session.rollback()
                logger.warning(
                    "Inactive coding challenge recovery failed for attempt=%s type=%s",
                    attempt.attempt_id,
                    type(exc).__name__,
                )
        return recovered

    def get_offer_view(
        self,
        session: Session,
        *,
        offer_id: str,
        course_id: int,
        student_id: int,
    ) -> dict[str, Any]:
        offer = self._owned_offer(
            session, offer_id=offer_id, course_id=course_id, student_id=student_id,
        )
        if offer.status in _RESTORABLE_OFFER_STATUSES and to_aware(offer.expires_at) <= utcnow_aware():
            offer.status = "expired"
            offer.updated_at = utcnow_aware()
            session.add(offer)
            session.commit()
        return self.serialize_offer(offer)

    def dismiss_offer(
        self,
        session: Session,
        *,
        offer_id: str,
        course_id: int,
        student_id: int,
    ) -> dict[str, Any]:
        offer = self._owned_offer(
            session, offer_id=offer_id, course_id=course_id, student_id=student_id,
        )
        if offer.status == "dismissed":
            return self.serialize_offer(offer)
        if offer.status not in {"preparing", "ready"}:
            reject_state_conflict("Only an unstarted coding challenge can be dismissed")
        offer.status = "dismissed"
        offer.updated_at = utcnow_aware()
        session.add(offer)
        session.commit()
        return self.serialize_offer(offer)

    def replace_offer(
        self,
        session: Session,
        *,
        offer_id: str,
        course_id: int,
        student_id: int,
    ) -> dict[str, Any]:
        current = self._owned_offer(
            session, offer_id=offer_id, course_id=course_id, student_id=student_id,
        )
        if current.status not in {"preparing", "ready", "failed"}:
            reject_state_conflict("Coding challenge cannot be replaced in its current state")
        if current.replacement_count >= 2:
            reject_state_conflict("Coding challenge replacement limit reached")
        if not current.source_release_id or not current.outline_node_id or not current.concept_id:
            reject_state_conflict("Coding challenge identity is incomplete")
        current.status = "replaced"
        current.updated_at = utcnow_aware()
        session.add(current)
        replacement = self.create_preparing_offer(
            session,
            course_id=course_id,
            student_id=student_id,
            conversation_session_id=current.conversation_session_id,
            trace_id=current.trace_id,
            concept_id=current.concept_id,
            why_now=current.why_now,
            difficulty=current.difficulty,
            languages=list(current.languages or ["python3"]),
            source_release_id=current.source_release_id,
            outline_node_id=current.outline_node_id,
            reason_codes=list(current.reason_codes or []),
            replacement_count=current.replacement_count + 1,
        )
        self._enqueue_prepare_task(session, replacement)
        return self.serialize_offer(replacement)

    def start_offer(
        self,
        session: Session,
        *,
        offer_id: str,
        course_id: int,
        student_id: int,
        return_anchor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Pin the verified version and create exactly one guided episode."""
        offer = self._owned_offer(
            session, offer_id=offer_id, course_id=course_id, student_id=student_id,
        )
        if to_aware(offer.expires_at) <= utcnow_aware():
            offer.status = "expired"
            session.add(offer)
            session.commit()
            reject_state_conflict("Coding challenge offer has expired")

        if offer.attempt_id:
            attempt = session.exec(
                select(ExperimentAttempt).where(
                    ExperimentAttempt.attempt_id == offer.attempt_id,
                    ExperimentAttempt.course_id == course_id,
                    ExperimentAttempt.student_id == student_id,
                )
            ).first()
            version = session.exec(
                select(ExperimentVersion).where(
                    ExperimentVersion.version_id == offer.version_id,
                    ExperimentVersion.course_id == course_id,
                )
            ).first()
            if attempt is None or version is None:
                reject_state_conflict("Pinned coding challenge session is inconsistent")
            definition = session.exec(select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == attempt.experiment_id,
                ExperimentDefinition.course_id == course_id,
            )).first()
            return {
                "offer": self.serialize_offer(offer),
                "session": self.serialize_session(
                    attempt,
                    version,
                    list(offer.languages or []),
                    definition,
                    self._public_tests(
                        session, course_id=course_id, version_id=version.version_id,
                    ),
                ),
            }

        if offer.status != "ready" or not offer.experiment_id or not offer.version_id:
            reject_state_conflict("Coding challenge is not ready to start")

        definition = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == offer.experiment_id,
                ExperimentDefinition.course_id == course_id,
            )
        ).first()
        version = session.exec(
            select(ExperimentVersion).where(
                ExperimentVersion.version_id == offer.version_id,
                ExperimentVersion.course_id == course_id,
            )
        ).first()
        if definition is None or version is None:
            reject_state_conflict("Pinned challenge definition or version no longer exists")
        if (
            definition.publish_status != ExperimentPublishStatus.PUBLISHED
            or version.experiment_id != definition.experiment_id
            or not version.is_locked
            or version.reference_preview_verified_at is None
        ):
            reject_state_conflict("Coding challenge version is not verified and locked")
        if definition.visibility == "student_private" and definition.owner_student_id != student_id:
            reject_resource_not_found("Coding challenge offer not found")
        if definition.expires_at and to_aware(definition.expires_at) <= utcnow_aware():
            reject_state_conflict("Private coding challenge has expired")

        now = utcnow_aware()
        attempt = ExperimentAttempt(
            experiment_id=definition.experiment_id,
            version_id=version.version_id,
            course_id=course_id,
            student_id=student_id,
            status=AttemptStatus.IN_PROGRESS,
            interaction_mode="guided_practice",
            source_release_id=offer.source_release_id,
            outline_node_id=offer.outline_node_id,
            return_anchor=dict(return_anchor or {}),
            last_activity_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(attempt)
        session.flush()
        session.add(CodingEvidenceEpisode(
            attempt_id=attempt.attempt_id,
            course_id=course_id,
            student_id=student_id,
            status="open",
            created_at=now,
            updated_at=now,
        ))
        offer.attempt_id = attempt.attempt_id
        offer.status = "started"
        offer.updated_at = now
        session.add(offer)
        session.commit()
        session.refresh(attempt)
        session.refresh(offer)
        return {
            "offer": self.serialize_offer(offer),
            "session": self.serialize_session(
                attempt,
                version,
                list(offer.languages or []),
                definition,
                self._public_tests(
                    session, course_id=course_id, version_id=version.version_id,
                ),
            ),
        }

    @staticmethod
    def require_open_guided_session(
        session: Session,
        *,
        attempt_id: str,
        course_id: int,
        student_id: int,
    ) -> ExperimentAttempt:
        attempt = session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.attempt_id == attempt_id,
                ExperimentAttempt.course_id == course_id,
                ExperimentAttempt.student_id == student_id,
            ).with_for_update()
        ).first()
        if attempt is None:
            reject_resource_not_found("Coding challenge session not found")
        if attempt.interaction_mode != "guided_practice" or attempt.status != AttemptStatus.IN_PROGRESS:
            reject_state_conflict("Coding challenge session is no longer open")
        episode = session.exec(
            select(CodingEvidenceEpisode).where(
                CodingEvidenceEpisode.attempt_id == attempt_id,
                CodingEvidenceEpisode.course_id == course_id,
                CodingEvidenceEpisode.student_id == student_id,
                CodingEvidenceEpisode.status == "open",
            )
        ).first()
        if episode is None:
            reject_state_conflict("Coding evidence episode is missing or closed")
        return attempt

    def touch_session(
        self,
        session: Session,
        *,
        attempt_id: str,
        course_id: int,
        student_id: int,
    ) -> ExperimentAttempt:
        attempt = self.require_open_guided_session(
            session,
            attempt_id=attempt_id,
            course_id=course_id,
            student_id=student_id,
        )
        attempt.last_activity_at = utcnow_aware()
        attempt.updated_at = attempt.last_activity_at
        session.add(attempt)
        return attempt

    @staticmethod
    def _server_score(run: ExperimentRun) -> float:
        if run.outcome == RunOutcome.ACCEPTED:
            return 1.0
        if run.total_count > 0:
            return max(0.0, min(1.0, run.passed_count / run.total_count))
        return max(0.0, min(1.0, float(run.score or 0.0)))

    def close_session(
        self,
        session: Session,
        *,
        attempt_id: str,
        course_id: int,
        student_id: int,
        reason: str,
    ) -> dict[str, Any]:
        """Close one guided episode and write at most one evidence per node."""
        attempt = session.exec(
            select(ExperimentAttempt).where(
                ExperimentAttempt.attempt_id == attempt_id,
                ExperimentAttempt.course_id == course_id,
                ExperimentAttempt.student_id == student_id,
            ).with_for_update()
        ).first()
        if attempt is None or attempt.interaction_mode != "guided_practice":
            reject_resource_not_found("Coding challenge session not found")
        episode = session.exec(
            select(CodingEvidenceEpisode).where(
                CodingEvidenceEpisode.attempt_id == attempt_id,
                CodingEvidenceEpisode.course_id == course_id,
                CodingEvidenceEpisode.student_id == student_id,
            )
        ).first()
        if episode is None:
            reject_state_conflict("Coding evidence episode is missing")
        if episode.status == "closed":
            return {"episode": dict(episode.summary or {}), "evidence_id": episode.evidence_id}

        runs = list(session.exec(
            select(ExperimentRun)
            .where(
                ExperimentRun.attempt_id == attempt_id,
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
            )
            .order_by(ExperimentRun.submitted_at.asc())
        ).all())
        if any(run.outcome == RunOutcome.PENDING for run in runs):
            reject_state_conflict("Coding challenge run is still in progress")
        valid_runs = [run for run in runs if run.outcome in _VALID_EVIDENCE_OUTCOMES]
        effective_runs = [
            run for run in valid_runs
            if bool((run.evidence_quality or {}).get("is_effective_revision", True))
        ]
        best_score = max((self._server_score(run) for run in valid_runs), default=0.0)
        final_outcome = valid_runs[-1].outcome.value if valid_runs else "no_valid_run"
        summary = {
            "episode_id": episode.episode_id,
            "status": "closed",
            "close_reason": reason,
            "run_count": len(runs),
            "valid_run_count": len(valid_runs),
            "effective_revision_count": len(effective_runs),
            "best_score": round(best_score, 6),
            "final_outcome": final_outcome,
            "passed": any(run.outcome == RunOutcome.ACCEPTED for run in valid_runs),
            "hint_used": any(
                bool((run.evidence_quality or {}).get("hint_used"))
                for run in valid_runs
            ),
        }

        evidence_records: list[LearningEvidenceRecord] = []
        identity_complete = bool(attempt.source_release_id and attempt.outline_node_id)
        if valid_runs and identity_complete:
            evidence_records = self._write_episode_evidence(
                session,
                attempt=attempt,
                episode=episode,
                summary=summary,
            )
            summary["evidence_status"] = "written" if evidence_records else "not_configured"
        elif valid_runs:
            # Guided evidence must stay bound to the offer's immutable release
            # identity. Unlike legacy formal experiments, this path never
            # guesses the currently active release after the fact.
            summary["evidence_status"] = "identity_incomplete"
            summary["reason_codes"] = ["EVIDENCE_IDENTITY_INCOMPLETE"]
        if valid_runs:
            attempt.status = AttemptStatus.FINALIZED
            attempt.final_score = best_score
            attempt.passed = bool(summary["passed"])
            attempt.finalized_at = utcnow_aware()
            attempt.evidence_id = evidence_records[0].evidence_id if evidence_records else None
        else:
            # No code result exists from which a score can be derived.  The
            # session is auditable but deliberately not a scored attempt.
            attempt.status = AttemptStatus.CANCELLED

        now = utcnow_aware()
        attempt.updated_at = now
        attempt.last_activity_at = now
        episode.status = "closed"
        episode.close_reason = reason
        episode.summary = summary
        episode.evidence_id = evidence_records[0].evidence_id if evidence_records else None
        episode.updated_at = now
        episode.closed_at = now
        session.add(attempt)
        session.add(episode)
        offers = session.exec(select(CodingChallengeOffer).where(
            CodingChallengeOffer.attempt_id == attempt_id,
            CodingChallengeOffer.course_id == course_id,
            CodingChallengeOffer.student_id == student_id,
        )).all()
        for offer in offers:
            offer.status = "completed" if valid_runs else "closed"
            offer.updated_at = now
            session.add(offer)
        session.commit()
        return {"episode": summary, "evidence_id": episode.evidence_id}

    @staticmethod
    def _write_episode_evidence(
        session: Session,
        *,
        attempt: ExperimentAttempt,
        episode: CodingEvidenceEpisode,
        summary: dict[str, Any],
    ) -> list[LearningEvidenceRecord]:
        definition = session.exec(select(ExperimentDefinition).where(
            ExperimentDefinition.experiment_id == attempt.experiment_id,
            ExperimentDefinition.course_id == attempt.course_id,
        )).first()
        version = session.exec(select(ExperimentVersion).where(
            ExperimentVersion.version_id == attempt.version_id,
            ExperimentVersion.course_id == attempt.course_id,
        )).first()
        if definition is None or version is None or not version.writes_formal_evidence:
            return []
        configured_node_ids = {
            value for value in (definition.knowledge_node_ids or [])
            if isinstance(value, int) and not isinstance(value, bool)
        }
        if not configured_node_ids:
            return []

        release = session.exec(select(CourseRelease).where(
            CourseRelease.release_id == attempt.source_release_id,
            CourseRelease.course_id == attempt.course_id,
            CourseRelease.status == ReleaseStatus.PUBLISHED,
        )).first()
        if release is None:
            return []
        outline_node = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.outline_node_id == attempt.outline_node_id,
            CourseOutlineNode.course_id == attempt.course_id,
            CourseOutlineNode.outline_version_id == release.outline_version_id,
        )).first()
        if outline_node is None or not outline_node.knowledge_graph_node_id:
            return []
        knowledge_node = session.exec(select(CourseKnowledgeNode).where(
            CourseKnowledgeNode.course_id == attempt.course_id,
            CourseKnowledgeNode.node_key == outline_node.knowledge_graph_node_id,
        )).first()
        if knowledge_node is None or knowledge_node.id not in configured_node_ids:
            return []

        node_id = int(knowledge_node.id)
        stable_key = f"coding_episode|{episode.episode_id}|{node_id}"
        evidence_id = "ev_" + uuid.uuid5(uuid.NAMESPACE_URL, stable_key).hex
        existing = session.exec(select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.evidence_id == evidence_id,
        )).first()
        if existing is not None:
            return [existing]
        evidence = LearningEvidenceRecord(
            evidence_id=evidence_id,
            student_id=attempt.student_id,
            course_id=attempt.course_id,
            node_id=node_id,
            evidence_type=EvidenceType.CODING_EXECUTION.value,
            value=float(summary["best_score"]),
            confidence=1.0,
            label=(
                "Guided code challenge passed"
                if summary["passed"]
                else "Guided code challenge incomplete"
            ),
            description="Server-scored guided-practice episode aggregate.",
            source="coding_episode_finalize_service",
            timestamp=utcnow_aware().isoformat(),
            event_refs=[episode.episode_id, attempt.attempt_id],
            policy_version="coding-episode-v1",
        )
        session.add(evidence)
        session.flush()
        upsert_learning_evidence_context(
            session,
            evidence,
            source_release_id=attempt.source_release_id,
            outline_node_id=attempt.outline_node_id,
        )
        return [evidence]

    @staticmethod
    def get_evidence_node_ids(
        session: Session,
        *,
        attempt_id: str,
        course_id: int,
        student_id: int,
    ) -> list[int]:
        records = session.exec(select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.student_id == student_id,
            LearningEvidenceRecord.course_id == course_id,
            LearningEvidenceRecord.source == "coding_episode_finalize_service",
        )).all()
        return sorted({
            int(record.node_id)
            for record in records
            if record.node_id is not None and attempt_id in (record.event_refs or [])
        })

    def get_run_view(
        self,
        session: Session,
        *,
        run_id: str,
        course_id: int,
        student_id: int,
    ) -> dict[str, Any]:
        run = session.exec(select(ExperimentRun).where(
            ExperimentRun.run_id == run_id,
            ExperimentRun.course_id == course_id,
            ExperimentRun.student_id == student_id,
        )).first()
        if run is None:
            reject_resource_not_found("Coding challenge run not found")
        attempt = session.exec(select(ExperimentAttempt).where(
            ExperimentAttempt.attempt_id == run.attempt_id,
            ExperimentAttempt.course_id == course_id,
            ExperimentAttempt.student_id == student_id,
            ExperimentAttempt.interaction_mode == "guided_practice",
        )).first()
        if attempt is None:
            reject_resource_not_found("Coding challenge run not found")
        episode = session.exec(select(CodingEvidenceEpisode).where(
            CodingEvidenceEpisode.attempt_id == attempt.attempt_id,
            CodingEvidenceEpisode.course_id == course_id,
            CodingEvidenceEpisode.student_id == student_id,
        )).first()
        diagnosis = session.exec(select(CodingDiagnosisRecord).where(
            CodingDiagnosisRecord.run_id == run_id,
            CodingDiagnosisRecord.course_id == course_id,
            CodingDiagnosisRecord.student_id == student_id,
        )).first()

        safe_tests: list[dict[str, Any]] = []
        for case in list((run.test_summary or {}).get("cases", [])):
            if not isinstance(case, dict):
                continue
            if case.get("hidden"):
                safe_tests.append({
                    "case_name": str(case.get("case_name") or "hidden"),
                    "passed": bool(case.get("passed")),
                    "reason": str(case.get("reason") or ""),
                    "hidden": True,
                })
            else:
                safe_tests.append({
                    key: case.get(key)
                    for key in (
                        "case_name", "passed", "reason", "hidden",
                        "stdin", "expected", "actual",
                    )
                    if key in case
                })
        result = {
            "run_id": run.run_id,
            "session_id": run.attempt_id,
            "task_id": run.task_id,
            "status": run.outcome.value,
            "outcome": run.outcome.value,
            "passed_count": run.passed_count,
            "total_count": run.total_count,
            "score": self._server_score(run) if run.outcome in _VALID_EVIDENCE_OUTCOMES else None,
            "compile_ok": run.compile_ok,
            "tests": safe_tests,
            "error_code": run.error_code,
            "cpu_time_ms": run.cpu_time_ms,
            "wall_time_ms": run.wall_time_ms,
            "memory_kb": run.memory_kb,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }
        episode_view = dict(episode.summary or {}) if episode else None
        if episode is not None and not episode_view:
            episode_runs = session.exec(select(ExperimentRun).where(
                ExperimentRun.attempt_id == attempt.attempt_id,
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
            )).all()
            valid = [item for item in episode_runs if item.outcome in _VALID_EVIDENCE_OUTCOMES]
            episode_view = {
                "episode_id": episode.episode_id,
                "status": episode.status,
                "run_count": len(episode_runs),
                "valid_run_count": len(valid),
                "effective_revision_count": sum(
                    bool((item.evidence_quality or {}).get("is_effective_revision", True))
                    for item in valid
                ),
                "best_score": max((self._server_score(item) for item in valid), default=0.0),
            }
        feedback = build_teaching_feedback(diagnosis) if diagnosis else None
        optional_hint_available = bool(
            feedback
            and feedback.get("optional_hint")
            and episode is not None
            and episode.status == "open"
        )
        if feedback is not None and not bool((run.evidence_quality or {}).get("hint_used")):
            feedback = {**feedback, "optional_hint": None}
        return {
            "result": result,
            "diagnosis_status": diagnosis.status if diagnosis else "preparing",
            "teaching_feedback": feedback,
            "optional_hint_available": optional_hint_available,
            "episode": episode_view,
        }

    def reveal_run_hint(
        self,
        session: Session,
        *,
        run_id: str,
        course_id: int,
        student_id: int,
    ) -> dict[str, Any]:
        """Reveal an optional hint and persist the server-owned usage signal."""
        run = session.exec(
            select(ExperimentRun).where(
                ExperimentRun.run_id == run_id,
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
            ).with_for_update()
        ).first()
        if run is None:
            reject_resource_not_found("Coding challenge run not found")
        attempt = session.exec(select(ExperimentAttempt).where(
            ExperimentAttempt.attempt_id == run.attempt_id,
            ExperimentAttempt.course_id == course_id,
            ExperimentAttempt.student_id == student_id,
            ExperimentAttempt.interaction_mode == "guided_practice",
        )).first()
        if attempt is None:
            reject_resource_not_found("Coding challenge run not found")
        episode = session.exec(select(CodingEvidenceEpisode).where(
            CodingEvidenceEpisode.attempt_id == attempt.attempt_id,
            CodingEvidenceEpisode.course_id == course_id,
            CodingEvidenceEpisode.student_id == student_id,
            CodingEvidenceEpisode.status == "open",
        )).first()
        if episode is None:
            reject_state_conflict("Coding challenge session is no longer open")
        diagnosis = session.exec(select(CodingDiagnosisRecord).where(
            CodingDiagnosisRecord.run_id == run_id,
            CodingDiagnosisRecord.course_id == course_id,
            CodingDiagnosisRecord.student_id == student_id,
        )).first()
        feedback = build_teaching_feedback(diagnosis) if diagnosis else None
        if not feedback or not feedback.get("optional_hint"):
            reject_state_conflict("Optional hint is not available for this run")
        run.evidence_quality = {**(run.evidence_quality or {}), "hint_used": True}
        session.add(run)
        session.commit()
        return self.get_run_view(
            session,
            run_id=run_id,
            course_id=course_id,
            student_id=student_id,
        )


coding_challenge_service = CodingChallengeService()
