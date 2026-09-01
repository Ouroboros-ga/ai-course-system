"""Quality and privacy gates for AI-generated conversational challenges."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta

import pytest
from app.core.time_utils import utcnow_aware
from app.models.cognitive_state_model import CognitiveState
from app.models.conversation_model import ConversationMessage
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
)
from app.models.experiment_model import (
    CodingChallengeOffer,
    ExperimentDefinition,
    ExperimentTestCase,
    ExperimentVersion,
)
from app.models.graph_production_model import (
    CourseKnowledgeNode,
    CourseKnowledgeNodeStatus,
)
from app.platform.agents.contracts.llm import LLMResponse
from app.schemas.coding_challenge import CodingChallengeDraft
from app.services.coding_challenge_generation_service import (
    CodingChallengeGenerationService,
)
from app.services.sandbox_client import SandboxResult, SubmissionStatus
from pydantic import ValidationError
from sqlmodel import select


class _FakeStructuredLLM:
    def __init__(self, draft: CodingChallengeDraft) -> None:
        self.draft = draft
        self.calls = 0
        self.last_kwargs = None

    async def complete(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return LLMResponse(
            content=self.draft.model_dump_json(),
            parsed=self.draft,
            model="fake-structured-model",
            usage={"prompt_tokens": 12, "completion_tokens": 34},
        )


class _FakeSandbox:
    def __init__(self, *, reference_accepted: bool = True, starter_accepted: bool = False) -> None:
        self.reference_accepted = reference_accepted
        self.starter_accepted = starter_accepted

    def health_check(self) -> bool:
        return True

    def submit_code(self, *, source_code: str, **_kwargs) -> SandboxResult:
        if "REFERENCE_SECRET" in source_code:
            accepted = self.reference_accepted
        else:
            accepted = self.starter_accepted
        return SandboxResult(
            status=SubmissionStatus.ACCEPTED if accepted else SubmissionStatus.WRONG_ANSWER,
        )


def _draft() -> CodingChallengeDraft:
    return CodingChallengeDraft(
        title="实现稳定的二分查找",
        statement="实现函数，在升序整数数组中查找目标值，并正确处理空数组与边界位置。",
        language="python3",
        starter_code="def search(nums, target):\n    return -1\n",
        public_samples=[{"name": "found", "stdin": "[1,3,5]\n3", "expected_stdout": "1"}],
        hidden_tests=[{"name": "empty", "stdin": "[]\n2", "expected_stdout": "-1"}],
        reference_solution="REFERENCE_SECRET\ndef search(nums, target):\n    return 1\n",
        difficulty="medium",
        estimated_minutes=12,
    )


def _preparing_offer(session, teacher_user, student_user) -> CodingChallengeOffer:
    course = Course(
        fanya_course_id=f"ai-challenge-{uuid.uuid4().hex[:8]}",
        fanya_course_name="算法课程",
        title="算法课程",
        teacher_id=teacher_user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.flush()
    knowledge = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_ai_binary_search",
        title="二分查找",
        status=CourseKnowledgeNodeStatus.PUBLISHED,
    )
    outline = CourseOutlineVersion(
        course_id=course.id,
        lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
        created_by=teacher_user.id,
    )
    outline_node = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        title="二分查找",
        knowledge_graph_node_id=knowledge.node_key,
    )
    release = CourseRelease(
        course_id=course.id,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        outline_version_id=outline.outline_version_id,
        created_by=teacher_user.id,
    )
    offer = CodingChallengeOffer(
        course_id=course.id,
        student_id=student_user.id,
        conversation_session_id="ai-session",
        trace_id="trace-ai",
        concept_id=knowledge.node_key,
        status="preparing",
        source="ai",
        title="正在准备代码挑战",
        why_now="把刚讨论的搜索边界落实到代码。",
        difficulty="medium",
        estimated_minutes=10,
        languages=["python3"],
        reason_codes=["EXPLICIT_PRACTICE_REQUEST"],
        source_release_id=release.release_id,
        outline_node_id=outline_node.outline_node_id,
        expires_at=utcnow_aware() + timedelta(hours=24),
    )
    session.add(knowledge)
    session.add(outline)
    session.add(outline_node)
    session.add(release)
    session.add(offer)
    session.commit()
    session.refresh(offer)
    return offer


def test_draft_rejects_duplicate_tests_before_sandbox() -> None:
    with pytest.raises(ValidationError, match="duplicate_test_case"):
        CodingChallengeDraft(
            title="重复测试示例",
            statement="这个题目描述足够长，但公开测试和隐藏测试完全重复，因此不应进入沙箱验证。",
            language="python3",
            starter_code="print(0)",
            public_samples=[{"name": "a", "stdin": "1", "expected_stdout": "1"}],
            hidden_tests=[{"name": "b", "stdin": "1", "expected_stdout": "1"}],
            reference_solution="print(input())",
        )


def test_verified_ai_draft_persists_private_problem_without_reference_solution(
    session,
    teacher_user,
    student_user,
):
    offer = _preparing_offer(session, teacher_user, student_user)
    llm = _FakeStructuredLLM(_draft())
    session.add(CognitiveState(
        student_id=student_user.id,
        course_id=offer.course_id,
        node_id=session.exec(select(CourseKnowledgeNode.id).where(
            CourseKnowledgeNode.node_key == offer.concept_id,
        )).one(),
        confusion_risk=0.6,
        inquiry_depth=0.4,
        mastery_level="unknown",
        reason_codes=["insufficient_effective_scored_weight"],
        is_latest=True,
    ))
    session.add(ConversationMessage(
        student_id=student_user.id,
        course_id=offer.course_id,
        session_id=offer.conversation_session_id,
        trace_id="raw-question-trace",
        role="user",
        content="RAW_CONVERSATION_SECRET",
        concept_id=offer.concept_id,
    ))
    session.commit()
    service = CodingChallengeGenerationService(
        structured_llm=llm,
        sandbox=_FakeSandbox(),
    )

    prepared = asyncio.run(service.prepare_offer(
        session,
        offer_id=offer.offer_id,
        course_id=offer.course_id,
        student_id=student_user.id,
    ))

    assert prepared.status == "ready"
    assert prepared.source == "ai"
    definition = session.exec(select(ExperimentDefinition).where(
        ExperimentDefinition.experiment_id == prepared.experiment_id,
    )).one()
    version = session.exec(select(ExperimentVersion).where(
        ExperimentVersion.version_id == prepared.version_id,
    )).one()
    cases = session.exec(select(ExperimentTestCase).where(
        ExperimentTestCase.version_id == version.version_id,
    )).all()
    assert definition.visibility == "student_private"
    assert definition.owner_student_id == student_user.id
    assert definition.expires_at == offer.expires_at
    assert version.is_locked is True
    assert version.reference_preview_verified_at is not None
    assert len(cases) == 2
    persisted = json.dumps({
        "definition": definition.model_dump(mode="json"),
        "version": version.model_dump(mode="json"),
        "offer": prepared.model_dump(mode="json"),
    }, ensure_ascii=False, default=str)
    assert "REFERENCE_SECRET" not in persisted
    assert "reference_solution" not in persisted
    prompt_payload = json.loads(llm.last_kwargs["messages"][1]["content"])
    assert "RAW_CONVERSATION_SECRET" not in llm.last_kwargs["messages"][1]["content"]
    assert prompt_payload["cognition_projection"] == {
        "confusion_risk": 0.6,
        "inquiry_depth": 0.4,
        "mastery_level": "unknown",
        "reason_codes": ["insufficient_effective_scored_weight"],
    }
    assert prompt_payload["question_signals"]["total_questions"] == 1
    assert "trace_ids" not in prompt_payload["question_signals"]


def test_reference_failure_regenerates_once_then_fails_without_problem_rows(
    session,
    teacher_user,
    student_user,
):
    offer = _preparing_offer(session, teacher_user, student_user)
    llm = _FakeStructuredLLM(_draft())
    service = CodingChallengeGenerationService(
        structured_llm=llm,
        sandbox=_FakeSandbox(reference_accepted=False),
    )
    definitions_before = len(session.exec(select(ExperimentDefinition)).all())

    prepared = asyncio.run(service.prepare_offer(
        session,
        offer_id=offer.offer_id,
        course_id=offer.course_id,
        student_id=student_user.id,
    ))

    assert llm.calls == 2
    assert prepared.status == "failed"
    assert prepared.reason_code == "REFERENCE_SOLUTION_FAILED"
    assert len(session.exec(select(ExperimentDefinition)).all()) == definitions_before


def test_generation_does_not_revive_an_offer_dismissed_while_llm_was_running(
    session,
    teacher_user,
    student_user,
):
    offer = _preparing_offer(session, teacher_user, student_user)

    class _DismissDuringGeneration(_FakeStructuredLLM):
        async def complete(self, **kwargs):
            current = session.exec(select(CodingChallengeOffer).where(
                CodingChallengeOffer.offer_id == offer.offer_id,
            )).one()
            current.status = "dismissed"
            session.add(current)
            session.commit()
            return await super().complete(**kwargs)

    definitions_before = len(session.exec(select(ExperimentDefinition)).all())
    service = CodingChallengeGenerationService(
        structured_llm=_DismissDuringGeneration(_draft()),
        sandbox=_FakeSandbox(),
    )

    prepared = asyncio.run(service.prepare_offer(
        session,
        offer_id=offer.offer_id,
        course_id=offer.course_id,
        student_id=student_user.id,
    ))

    assert prepared.status == "dismissed"
    assert len(session.exec(select(ExperimentDefinition)).all()) == definitions_before
