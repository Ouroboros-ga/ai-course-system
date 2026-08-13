"""Offline enforcement tests for TeachingAgent constraint envelopes."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

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
from app.platform.agents.edu.constraints import ALL_SCOPES, canonicalize_snapshot
from app.schemas.learning_adjustment import QuestionObservation


@dataclass
class MutableConstraintPort:
    level: str = "balanced"
    scopes: tuple[str, ...] = ALL_SCOPES
    parameters: Mapping[str, Any] = field(default_factory=dict)
    resolve_calls: int = 0
    evaluations: list[dict[str, Any]] = field(default_factory=list)

    async def resolve(self, **_: Any) -> Mapping[str, Any]:
        self.resolve_calls += 1
        from app.platform.agents.edu.constraints import (
            ConstraintSubject,
            resolve_effective_constraint,
        )

        envelope = resolve_effective_constraint(
            snapshot=canonicalize_snapshot(
                {
                    "level": self.level,
                    "scopes": self.scopes,
                    "parameters": self.parameters,
                    "rules": [],
                }
            ),
            subject=ConstraintSubject(student_id="1"),
        )
        return {
            "policy_version": self.resolve_calls,
            "envelope": envelope.model_dump(mode="json"),
        }

    async def record_evaluation(self, **payload: Any) -> None:
        self.evaluations.append(dict(payload))


@dataclass
class FakeConversationHistory:
    turns: Sequence[Mapping[str, Any]] = ()
    calls: int = 0

    async def select_relevant_turns(self, **_: Any) -> Sequence[Mapping[str, Any]]:
        self.calls += 1
        return self.turns


@dataclass
class CountingLearningAdjustment:
    calls: int = 0

    async def propose(self, **_: Any) -> None:
        self.calls += 1
        return None


class LongAnswerLLM(FakeLLM):
    async def generate_teaching_response(self, *, context: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "answer": "第一句。" + ("这是很长的模型回答" * 300),
            "citations": [
                {"evidence_id": item["evidence_id"]}
                for item in context.get("retrieved_evidence", [])
            ],
        }


@dataclass
class FailingConstraintPort:
    async def resolve(self, **_: Any) -> Mapping[str, Any]:
        raise RuntimeError("policy store unavailable")

    async def record_evaluation(self, **_: Any) -> None:
        return None


@dataclass
class MultiEvidenceRetrieval:
    calls: int = 0

    async def retrieve_course_evidence(self, **_: Any) -> list[Mapping[str, Any]]:
        self.calls += 1
        return [
            {"evidence_id": "evidence-1", "content": "first"},
            {"evidence_id": "evidence-2", "content": "second"},
            {"evidence_id": "evidence-3", "content": "third"},
        ]


@dataclass
class CountingWebResearch:
    calls: int = 0

    async def research(self, **_: Any) -> Mapping[str, Any]:
        self.calls += 1
        return {"is_supplementary": True, "items": []}


def _runtime(
    *,
    constraint: MutableConstraintPort | None,
    history: FakeConversationHistory | None = None,
    retrieval: Any | None = None,
    llm: Any | None = None,
    learning_adjustment: Any | None = None,
) -> TeachingAgentRuntime:
    return TeachingAgentRuntime(
        TeachingTools(
            scope=FakeScope(),
            knowledge_graph=FakeGraph(),
            retrieval=retrieval or FakeRetrieval(),
            student_modeling=FakeStudentModeling(),
            recommendation=FakeRecommendation(),
            sandbox=FakeSandbox(),
            learning_events=FakeEvents(),
            llm=llm or FakeLLM(),
            teaching_constraints=constraint,
            conversation_history=history,
            learning_adjustment=learning_adjustment,
        )
    )


def _run(
    runtime: TeachingAgentRuntime,
    *,
    question_observation: QuestionObservation | None = None,
) -> Mapping[str, Any]:
    return asyncio.run(
        runtime.respond(
            student_id="1",
            course_id="2",
            session_id="session-1",
            message="为什么二分查找需要更新边界？",
            question_observation=question_observation,
        )
    )


def test_constraint_node_runs_after_concept_and_before_context_tools():
    constraint = MutableConstraintPort(level="strict")
    history = FakeConversationHistory(
        turns=({"user": "上次的问题", "assistant": "上次的回答", "concept_id": "binary-search"},)
    )

    state = _run(_runtime(constraint=constraint, history=history))
    nodes = [item["node"] for item in state["trace"]]

    assert nodes.index("resolve_teaching_constraints") > nodes.index("resolve_concept")
    assert nodes.index("resolve_teaching_constraints") < nodes.index("load_conversation_history")
    assert nodes.index("load_conversation_history") < nodes.index("load_student_state")
    assert state["constraint_level"] == "strict"
    assert state["conversation_turns"][0]["user"] == "上次的问题"


def test_cached_runtime_reads_constraint_port_on_every_request():
    constraint = MutableConstraintPort(level="balanced")
    runtime = _runtime(constraint=constraint)

    first = _run(runtime)
    constraint.level = "locked"
    second = _run(runtime)

    assert first["constraint_level"] == "balanced"
    assert second["constraint_level"] == "locked"
    assert constraint.resolve_calls == 2


def test_strict_concept_answer_without_course_evidence_uses_safe_fallback():
    class EmptyRetrieval:
        async def retrieve_course_evidence(self, **_: Any) -> list[Mapping[str, Any]]:
            return []

    state = _run(
        _runtime(
            constraint=MutableConstraintPort(level="strict"),
            retrieval=EmptyRetrieval(),
        )
    )

    assert state["final_answer"] == "当前课程证据不足，我不能把这段内容作为已核实的课程事实回答。请联系教师补充材料，或换一种提问方式。"
    assert "COURSE_EVIDENCE_REQUIRED_BY_CONSTRAINT" in state["warnings"]


def test_evidence_constraint_fallback_never_proposes_a_learning_adjustment():
    class EmptyRetrieval:
        async def retrieve_course_evidence(self, **_: Any) -> list[Mapping[str, Any]]:
            return []

    adjustment = CountingLearningAdjustment()
    state = _run(
        _runtime(
            constraint=MutableConstraintPort(level="strict"),
            retrieval=EmptyRetrieval(),
            learning_adjustment=adjustment,
        ),
        question_observation=QuestionObservation(
            course_release_id="cr_test",
            media_release_id="mrel_test",
            media_release_item_id="mrit_test",
            outline_node_id="outline_test",
            local_time_ms=8_200,
            page=4,
        ),
    )

    assert "COURSE_EVIDENCE_REQUIRED_BY_CONSTRAINT" in state["warnings"]
    assert state["learning_adjustment"] is None
    assert adjustment.calls == 0


def test_locked_answer_is_bounded_after_generation():
    state = _run(
        _runtime(
            constraint=MutableConstraintPort(level="locked"),
            llm=LongAnswerLLM(),
        )
    )

    assert len(state["final_answer"]) <= 900
    assert "ANSWER_TRUNCATED_BY_CONSTRAINT" in state["warnings"]


def test_constraint_resolution_failure_uses_locked_envelope():
    """A broken policy provider may not silently relax a teacher's safeguards."""
    state = _run(_runtime(constraint=FailingConstraintPort()))

    assert state["constraint_level"] == "locked"
    assert state["constraint_envelope"]["parameters"]["external_research"] == "disabled"
    assert "CONSTRAINT_POLICY_UNAVAILABLE" in state["warnings"]


def test_evidence_limit_only_applies_when_evidence_scope_is_enabled():
    retrieval = MultiEvidenceRetrieval()
    state = _run(
        _runtime(
            constraint=MutableConstraintPort(
                scopes=("response",),
                parameters={"max_evidence": 1},
            ),
            retrieval=retrieval,
        )
    )

    assert retrieval.calls == 1
    assert [item["evidence_id"] for item in state["retrieved_evidence"]] == [
        "evidence-1", "evidence-2", "evidence-3",
    ]


def test_disabled_external_research_never_calls_web_port():
    web = CountingWebResearch()
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=FakeLLM(),
        teaching_constraints=MutableConstraintPort(
            parameters={"external_research": "disabled"},
        ),
        web_research=web,
    )

    state = _run(TeachingAgentRuntime(tools))

    assert web.calls == 0
    assert "TOOL_BLOCKED_BY_HARDNESS" in state["warnings"]


def test_constraint_audit_receives_only_counts_and_codes():
    constraint = MutableConstraintPort(level="strict")
    state = _run(_runtime(constraint=constraint))

    assert constraint.evaluations
    payload = constraint.evaluations[0]
    serialized = repr(payload)
    assert state["user_message"] not in serialized
    assert state["final_answer"] not in serialized
    assert payload["summary"]["valid_citation_count"] == 1


@dataclass
class DisabledToolGovernance:
    disabled: set[str] = field(default_factory=set)
    always_confirm: set[str] = field(default_factory=set)

    async def is_tool_enabled(self, *, tool_name: str, **_: Any) -> bool:
        return tool_name not in self.disabled

    async def requires_confirmation(self, *, tool_name: str, **_: Any) -> Mapping[str, Any]:
        return {
            "require_confirmation": tool_name in self.always_confirm,
            "threshold": "always" if tool_name in self.always_confirm else "never",
        }

    async def record_invocation(self, **_: Any) -> None:
        return None


@dataclass
class CountingStudentModel(FakeStudentModeling):
    calls: int = 0

    async def get_concept_state(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls += 1
        return await super().get_concept_state(**kwargs)


@dataclass
class CountingRecommendation(FakeRecommendation):
    calls: int = 0

    async def recommend_next_action(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls += 1
        return await super().recommend_next_action(**kwargs)


@dataclass
class CountingHistory:
    calls: int = 0

    async def get_history(self, **_: Any) -> Mapping[str, Any]:
        self.calls += 1
        return {"status": "available"}


def test_disabled_context_student_history_and_recommendation_ports_are_not_called():
    student_model = CountingStudentModel()
    recommendation = CountingRecommendation()
    history = CountingHistory()
    conversation = FakeConversationHistory(
        turns=({"user": "old", "assistant": "answer"},)
    )
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=student_model,
        recommendation=recommendation,
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=FakeLLM(),
        teaching_constraints=MutableConstraintPort(level="balanced"),
        conversation_history=conversation,
        student_history=history,
        tool_governance=DisabledToolGovernance(
            disabled={
                "conversation_context",
                "student_modeling",
                "student_history",
                "recommendation",
            }
        ),
    )

    state = _run(TeachingAgentRuntime(tools))

    assert conversation.calls == 0
    assert student_model.calls == 0
    assert history.calls == 0
    assert recommendation.calls == 0
    assert set(state["governance_skipped_tools"]) >= {
        "conversation_context",
        "student_modeling",
        "student_history",
        "recommendation",
    }


@dataclass
class FakeQuestionGeneration:
    calls: int = 0

    async def generate_question(self, **_: Any) -> Mapping[str, Any]:
        self.calls += 1
        return {"draft_id": "draft-1"}


@dataclass
class FakeSafetyValve:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create_proposal(self, **payload: Any) -> Mapping[str, Any]:
        self.calls.append(dict(payload))
        return {
            "proposal_id": "ap-question",
            "status": "pending",
            "requires_confirmation": True,
            "tool_name": payload["tool_name"],
        }


def test_always_confirmation_reaches_safety_valve_before_question_generation():
    generation = FakeQuestionGeneration()
    valve = FakeSafetyValve()
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=FakeLLM(),
        teaching_constraints=MutableConstraintPort(level="balanced"),
        question_generation=generation,
        tool_governance=DisabledToolGovernance(
            always_confirm={"question_generation"}
        ),
        teacher_safety_valve=valve,
    )

    state = _run(TeachingAgentRuntime(tools))

    assert generation.calls == 0
    assert valve.calls[0]["tool_name"] == "question_generation"
    assert state["pending_proposals"][0]["proposal_id"] == "ap-question"
