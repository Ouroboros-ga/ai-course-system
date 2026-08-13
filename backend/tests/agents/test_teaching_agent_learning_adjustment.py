"""Learning-adjustment workflow contracts without database or network I/O."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.platform.agents.contracts import TeachingTools
from app.platform.agents.edu.runtime import TeachingAgentRuntime
from app.platform.agents.providers.fakes import (
    FakeEvents,
    FakeGraph,
    FakeLLM,
    FakeRecommendation,
    FakeRetrieval,
    FakeSandbox,
    FakeScope,
    FakeStudentModeling,
)
from app.schemas.learning_adjustment import (
    LearningAdjustmentProposal,
    LearningAdjustmentStatus,
    QuestionObservation,
    ReviewTarget,
)


def _observation() -> QuestionObservation:
    return QuestionObservation(
        course_release_id="cr_test",
        media_release_id="mrel_test",
        media_release_item_id="mrit_current",
        outline_node_id="on_current",
        local_time_ms=8_200,
        page=4,
    )


@dataclass
class RecordingAdjustmentPort:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def propose(self, **kwargs: Any) -> LearningAdjustmentProposal | None:
        self.calls.append(kwargs)
        observation = kwargs["observation"]
        return LearningAdjustmentProposal(
            adjustment_id="lad_testproposal",
            status=LearningAdjustmentStatus.PROPOSED,
            question_observation=observation,
            review_target=ReviewTarget(
                course_release_id="cr_test",
                media_release_id="mrel_test",
                media_release_item_id="mrit_prerequisite",
                outline_node_id="on_prerequisite",
                local_time_ms=48_200,
                page=6,
            ),
            teaching_action=kwargs["teaching_action"],
            reason_codes=("CONFIRMED_WEAK_PREREQUISITE",),
            recommended_playback_rate=0.85,
            requires_confirmation=True,
        )


class FailingAdjustmentPort:
    async def propose(self, **_: Any) -> None:
        raise RuntimeError("isolated adjustment failure")


def _runtime(port: Any) -> TeachingAgentRuntime:
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(weak=[{"concept_id": "ordered-array"}]),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=FakeLLM(),
        learning_adjustment=port,
    )
    return TeachingAgentRuntime(tools)


def _respond(runtime: TeachingAgentRuntime) -> Mapping[str, Any]:
    return asyncio.run(
        runtime.respond(
            student_id="7",
            course_id="2",
            session_id="learning-adjustment-test",
            message="Why is the prerequisite needed?",
            question_observation=_observation(),
        )
    )


def test_validated_answer_attaches_deterministic_learning_adjustment() -> None:
    port = RecordingAdjustmentPort()

    state = _respond(_runtime(port))

    assert state["final_answer"]
    assert state["learning_adjustment"]["adjustment_id"] == "lad_testproposal"
    assert state["learning_adjustment"]["return_anchor"] is None
    assert port.calls[0]["teaching_action"] == "prerequisite_review"
    assert port.calls[0]["observation"].local_time_ms == 8_200
    assert port.calls[0]["source_trace_id"] == state["trace_id"]
    assert "user_message" not in port.calls[0]
    assert "final_answer" not in port.calls[0]


def test_adjustment_failure_keeps_validated_teaching_answer_available() -> None:
    state = _respond(_runtime(FailingAdjustmentPort()))

    assert state["final_answer"]
    assert state.get("learning_adjustment") is None
    assert "LEARNING_ADJUSTMENT_UNAVAILABLE" in state["warnings"]
    assert "learning_adjustment" in state["degraded_services"]
