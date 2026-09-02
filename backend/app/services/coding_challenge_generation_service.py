"""AI challenge generation with schema and real-sandbox quality gates."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.cognitive_state_model import CognitiveState
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_outline_model import CourseOutlineNode
from app.models.experiment_model import (
    CodingChallengeOffer,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentTestCase,
    ExperimentVersion,
)
from app.models.graph_production_model import CourseKnowledgeNode
from app.platform.agents.contracts.llm import (
    LLMOptions,
    LLMTraceContext,
    StructuredLLMPort,
)
from app.schemas.coding_challenge import CodingChallengeDraft
from app.services.conversation_service import derive_question_inference_signals
from app.services.sandbox_client import (
    SandboxResourceLimits,
    SubmissionStatus,
    sandbox_client,
)

logger = logging.getLogger(__name__)
PROMPT_VERSION = "coding-challenge-generation/v1"


@dataclass(frozen=True)
class ChallengeQualityResult:
    accepted: bool
    reason_code: str


class CodingChallengeGenerationService:
    """Generate a private challenge without persisting raw LLM material."""

    def __init__(self, *, structured_llm: StructuredLLMPort | None = None, sandbox: Any = sandbox_client) -> None:
        self._llm = structured_llm
        self._sandbox = sandbox

    def configure(self, *, structured_llm: StructuredLLMPort | None, sandbox: Any | None = None) -> None:
        self._llm = structured_llm
        if sandbox is not None:
            self._sandbox = sandbox

    @staticmethod
    def _prompt_payload(
        session: Session,
        offer: CodingChallengeOffer,
        *,
        knowledge_node_id: int,
    ) -> dict[str, Any]:
        cognition = session.exec(
            select(CognitiveState)
            .where(
                CognitiveState.student_id == offer.student_id,
                CognitiveState.course_id == offer.course_id,
                CognitiveState.node_id == knowledge_node_id,
                CognitiveState.is_latest.is_(True),
            )
            .order_by(CognitiveState.computed_at.desc())
        ).first()
        question_projection = derive_question_inference_signals(
            session,
            student_id=offer.student_id,
            course_id=offer.course_id,
            concept_id=offer.concept_id,
        )
        concept_signal = next(iter(question_projection.get("signals", [])), {})
        return {
            "release_id": offer.source_release_id,
            "outline_node_id": offer.outline_node_id,
            "concept_id": offer.concept_id,
            "difficulty": offer.difficulty,
            "language": (offer.languages or ["python3"])[0],
            "reason_codes": list(offer.reason_codes or []),
            "cognition_projection": {
                "confusion_risk": cognition.confusion_risk,
                "inquiry_depth": cognition.inquiry_depth,
                "mastery_level": cognition.mastery_level,
                "reason_codes": list(cognition.reason_codes or [])[:8],
            } if cognition is not None else {
                "confusion_risk": None,
                "inquiry_depth": None,
                "mastery_level": "unknown",
                "reason_codes": ["cognition_projection_unavailable"],
            },
            # Deliberately exclude raw questions and trace IDs. The generator
            # receives only the bounded projection used to tune task scope.
            "question_signals": {
                "total_questions": int(question_projection.get("total_questions", 0)),
                "question_count": int(concept_signal.get("question_count", 0)),
                "avg_inquiry_depth": concept_signal.get("avg_inquiry_depth"),
                "inferred_weak": bool(concept_signal.get("inferred_weak", False)),
            },
        }

    async def prepare_offer(
        self,
        session: Session,
        *,
        offer_id: str,
        course_id: int,
        student_id: int,
    ) -> CodingChallengeOffer:
        offer = session.exec(select(CodingChallengeOffer).where(
            CodingChallengeOffer.offer_id == offer_id,
            CodingChallengeOffer.course_id == course_id,
            CodingChallengeOffer.student_id == student_id,
        )).first()
        if offer is None:
            raise ValueError("offer_not_found_or_scope_mismatch")
        if offer.status != "preparing":
            return offer
        if self._llm is None:
            return self._fail(session, offer, "CHALLENGE_LLM_UNAVAILABLE")
        if not offer.source_release_id or not offer.outline_node_id or not offer.concept_id:
            return self._fail(session, offer, "CHALLENGE_IDENTITY_INCOMPLETE")
        release = session.exec(select(CourseRelease).where(
            CourseRelease.release_id == offer.source_release_id,
            CourseRelease.course_id == course_id,
            CourseRelease.status == ReleaseStatus.PUBLISHED,
            CourseRelease.is_active == True,
        )).first()
        outline_node = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.outline_node_id == offer.outline_node_id,
            CourseOutlineNode.course_id == course_id,
            CourseOutlineNode.outline_version_id == (release.outline_version_id if release else None),
            CourseOutlineNode.knowledge_graph_node_id == offer.concept_id,
        )).first()
        knowledge_node = session.exec(select(CourseKnowledgeNode).where(
            CourseKnowledgeNode.course_id == course_id,
            CourseKnowledgeNode.node_key == offer.concept_id,
        )).first()
        if release is None or outline_node is None or knowledge_node is None:
            return self._fail(session, offer, "CHALLENGE_IDENTITY_CONFLICT")

        prompt_payload = self._prompt_payload(
            session,
            offer,
            knowledge_node_id=int(knowledge_node.id),
        )
        prompt_json = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
        last_reason = "CHALLENGE_GENERATION_FAILED"
        for generation_attempt in (1, 2):
            try:
                response = await self._llm.complete(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Generate one concise programming challenge bound to the supplied "
                                "published course identity. Return only the requested JSON. "
                                "The starter must not pass all tests."
                            ),
                        },
                        {"role": "user", "content": prompt_json},
                    ],
                    output_schema=CodingChallengeDraft,
                    options=LLMOptions(
                        temperature=0.2,
                        max_tokens=3_000,
                        timeout_seconds=45,
                        response_format={"type": "json_object"},
                        prompt_version=PROMPT_VERSION,
                    ),
                    trace_context=LLMTraceContext(
                        run_id=offer.offer_id,
                        trace_id=offer.trace_id,
                        agent_type="edu_coding_challenge",
                        node="generate_challenge",
                        purpose="coding_challenge_generation",
                        course_id=str(course_id),
                    ),
                )
                draft = response.parsed
                if not isinstance(draft, CodingChallengeDraft):
                    last_reason = "CHALLENGE_SCHEMA_INVALID"
                    continue
                quality = self._validate_with_sandbox(draft)
                if not quality.accepted:
                    last_reason = quality.reason_code
                    continue
                # The learner may dismiss or replace the card while the LLM
                # and Judge0 checks are running. Re-read and lock the offer at
                # the final write boundary so a stale task cannot resurrect
                # an abandoned card or publish an orphan private definition.
                session.refresh(offer, with_for_update=True)
                if offer.status != "preparing":
                    return offer
                return self._persist_verified_draft(
                    session,
                    offer=offer,
                    draft=draft,
                    model=response.model,
                    repaired=response.repaired,
                    usage=dict(response.usage or {}),
                    prompt_hash=hashlib.sha256(prompt_json.encode("utf-8")).hexdigest(),
                    generation_attempt=generation_attempt,
                    knowledge_node_id=int(knowledge_node.id),
                )
            except Exception as exc:  # noqa: BLE001 - task converts failures to bounded state
                logger.info(
                    "Coding challenge generation attempt failed for offer=%s type=%s",
                    offer.offer_id,
                    type(exc).__name__,
                )
                last_reason = getattr(exc, "reason_code", "") or "CHALLENGE_GENERATION_FAILED"
        session.refresh(offer, with_for_update=True)
        if offer.status != "preparing":
            return offer
        return self._fail(session, offer, last_reason)

    def _validate_with_sandbox(self, draft: CodingChallengeDraft) -> ChallengeQualityResult:
        if not self._sandbox.health_check():
            return ChallengeQualityResult(False, "SANDBOX_UNAVAILABLE")
        limits = SandboxResourceLimits(
            cpu_time_limit=3,
            memory_limit=128_000,
            wall_time_limit=6,
            max_processes=20,
            max_file_size=512,
            enable_network=False,
        )
        cases = [*draft.public_samples, *draft.hidden_tests]
        for case in cases:
            result = self._sandbox.submit_code(
                source_code=draft.reference_solution,
                language=draft.language,
                stdin=case.stdin,
                expected_output=case.expected_stdout,
                limits=limits,
            )
            if result.status == SubmissionStatus.SANDBOX_UNAVAILABLE:
                return ChallengeQualityResult(False, "SANDBOX_UNAVAILABLE")
            if result.status != SubmissionStatus.ACCEPTED:
                return ChallengeQualityResult(False, "REFERENCE_SOLUTION_FAILED")
        starter_passed = 0
        for case in cases:
            result = self._sandbox.submit_code(
                source_code=draft.starter_code,
                language=draft.language,
                stdin=case.stdin,
                expected_output=case.expected_stdout,
                limits=limits,
            )
            if result.status == SubmissionStatus.SANDBOX_UNAVAILABLE:
                return ChallengeQualityResult(False, "SANDBOX_UNAVAILABLE")
            starter_passed += int(result.status == SubmissionStatus.ACCEPTED)
        if starter_passed == len(cases):
            return ChallengeQualityResult(False, "STARTER_CODE_ALREADY_PASSES")
        return ChallengeQualityResult(True, "VERIFIED")

    @staticmethod
    def _persist_verified_draft(
        session: Session,
        *,
        offer: CodingChallengeOffer,
        draft: CodingChallengeDraft,
        model: str,
        repaired: bool,
        usage: dict[str, Any],
        prompt_hash: str,
        generation_attempt: int,
        knowledge_node_id: int,
    ) -> CodingChallengeOffer:
        now = utcnow_aware()
        definition = ExperimentDefinition(
            course_id=offer.course_id,
            title=draft.title,
            description=draft.statement,
            language_whitelist=[draft.language],
            publish_status=ExperimentPublishStatus.PUBLISHED,
            knowledge_node_ids=[knowledge_node_id],
            max_attempts=1,
            cooldown_minutes=0,
            origin="ai_challenge",
            visibility="student_private",
            owner_student_id=offer.student_id,
            expires_at=offer.expires_at,
            created_by=offer.student_id,
        )
        version = ExperimentVersion(
            experiment_id=definition.experiment_id,
            course_id=offer.course_id,
            version_number=1,
            label="AI private challenge",
            starter_code={draft.language: draft.starter_code},
            generation_metadata={
                "prompt_version": PROMPT_VERSION,
                "prompt_hash": prompt_hash,
                "model": model,
                "repaired": bool(repaired),
                "generation_attempt": generation_attempt,
                "validation_reason_codes": ["SCHEMA_VALID", "REFERENCE_VERIFIED", "STARTER_REJECTED"],
                "usage": {
                    key: value for key, value in usage.items()
                    if key in {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"}
                },
            },
            is_locked=True,
            is_active=True,
            reference_preview_verified_at=now,
            created_by=offer.student_id,
        )
        definition.default_version_id = version.version_id
        session.add(definition)
        session.add(version)
        for is_hidden, case in [
            *[(False, item) for item in draft.public_samples],
            *[(True, item) for item in draft.hidden_tests],
        ]:
            session.add(ExperimentTestCase(
                version_id=version.version_id,
                course_id=offer.course_id,
                case_name=case.name,
                stdin=case.stdin,
                expected_stdout=case.expected_stdout,
                is_hidden=is_hidden,
                weight=1.0 / (len(draft.public_samples) + len(draft.hidden_tests)),
            ))
        offer.status = "ready"
        offer.source = "ai"
        offer.title = draft.title
        offer.difficulty = draft.difficulty
        offer.estimated_minutes = draft.estimated_minutes
        offer.languages = [draft.language]
        offer.experiment_id = definition.experiment_id
        offer.version_id = version.version_id
        offer.reason_code = ""
        offer.updated_at = now
        session.add(offer)
        session.commit()
        session.refresh(offer)
        return offer

    @staticmethod
    def _fail(session: Session, offer: CodingChallengeOffer, reason_code: str) -> CodingChallengeOffer:
        offer.status = "failed"
        offer.reason_code = str(reason_code)[:64]
        offer.updated_at = utcnow_aware()
        session.add(offer)
        session.commit()
        return offer


coding_challenge_generation_service = CodingChallengeGenerationService()


__all__ = [
    "ChallengeQualityResult",
    "CodingChallengeGenerationService",
    "coding_challenge_generation_service",
]
