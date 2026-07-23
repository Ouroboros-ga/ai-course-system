"""Offline contract tests for the LangGraph TeachingAgent workflow."""

from __future__ import annotations

import asyncio
import importlib.util
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.platform.agents.contracts import TeachingTools
from app.platform.agents.composition import build_teaching_runtime
from app.platform.agents.runtime import TeachingAgentRuntime
from app.platform.agents.tools.kg_mest_shadow import KGMetShadowReportStudentModelingPort
from app.platform.agents.tools.fakes import (
    FakeEvents,
    FakeGraph,
    FakeLLM,
    FakeRecommendation,
    FakeRetrieval,
    FakeSandbox,
    FakeScope,
    FakeStudentModeling,
)


_ENDPOINT = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "endpoints" / "teaching_agent.py"
_SPEC = importlib.util.spec_from_file_location("teaching_agent_endpoint_test", _ENDPOINT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
router = _MODULE.router


def build_runtime(*, learner=None, weak=None, retrieval=None, scope=None, llm=None):
    events = FakeEvents()
    tools = TeachingTools(
        scope=scope or FakeScope(), knowledge_graph=FakeGraph(), retrieval=retrieval or FakeRetrieval(),
        student_modeling=learner or FakeStudentModeling(), recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(), learning_events=events, llm=llm or FakeLLM(),
    )
    return TeachingAgentRuntime(tools), events


def run(runtime, **overrides):
    payload = {"student_id": "s-1", "course_id": "c-1", "session_id": "session-1", "message": "为什么二分查找需要更新边界？"}
    payload.update(overrides)
    return asyncio.run(runtime.respond(**payload))


def test_normal_question_uses_evidence_citations_and_records_trace():
    runtime, events = build_runtime()
    state = run(runtime)
    assert state["teaching_action"] == "normal_answer"
    assert state["citations"] == [{"evidence_id": "ev-1", "resource_id": "ppt-1", "page_start": 12, "page_end": 13}]
    assert len(events.events) == len(events.traces) == 1
    assert state["trace_id"] == events.events[0]["trace_id"]
    assert events.traces[0]["final_answer"] == state["final_answer"]
    assert events.traces[0]["retrieved_evidence"][0]["evidence_id"] == "ev-1"


def test_confirmed_weak_prerequisite_selects_prerequisite_review():
    learner = FakeStudentModeling(weak=[{"concept_id": "ordered-array"}])
    runtime, _ = build_runtime(learner=learner)
    assert run(runtime)["teaching_action"] == "prerequisite_review"


def test_repeated_error_selects_misconception_repair():
    learner = FakeStudentModeling(state={"mastery_score": 0.6, "confidence": 0.8, "repeated_error_risk": 0.9, "hint_dependency": 0.1, "transfer_score": 0.6})
    runtime, _ = build_runtime(learner=learner)
    assert run(runtime)["teaching_action"] == "misconception_repair"


def test_insufficient_student_state_selects_diagnostic_without_long_term_conclusion():
    learner = FakeStudentModeling(state={"confidence": 0.2})
    runtime, _ = build_runtime(learner=learner)
    state = run(runtime)
    assert state["teaching_action"] == "diagnostic_question"
    assert state["teaching_action_reason"] == "student_state_insufficient"


def test_unknown_observed_performance_selects_diagnostic_without_treating_missing_values_as_low():
    learner = FakeStudentModeling(state={"mastery_score": None, "confidence": 0.8, "repeated_error_risk": None, "hint_dependency": None, "transfer_score": None})
    runtime, _ = build_runtime(learner=learner)
    state = run(runtime)
    assert state["teaching_action"] == "diagnostic_question"
    assert state["teaching_action_reason"] == "observed_performance_unknown"


def test_code_context_calls_sandbox_and_selects_code_debugging():
    runtime, _ = build_runtime()
    state = run(runtime, code_submission_id="submission-1")
    assert state["teaching_action"] == "code_debugging"
    assert state["sandbox_result"] == {"status": "not_run"}


def test_retrieval_failure_degrades_without_unsupported_citation():
    class BrokenRetrieval:
        async def retrieve_course_evidence(self, **_): raise TimeoutError("offline fake")

    runtime, _ = build_runtime(retrieval=BrokenRetrieval())
    state = run(runtime)
    assert "retrieval" in state["degraded_services"]
    assert state["citations"] == []
    assert "NO_COURSE_EVIDENCE_AVAILABLE" in state["warnings"]


def test_scope_rejection_is_whole_workflow_rejection():
    runtime, events = build_runtime(scope=FakeScope(allowed=False))
    state = run(runtime)
    assert state["status"] == "rejected"
    assert state["errors"] == ["TEACHING_SCOPE_REJECTED"]
    assert len(events.events) == 1


def test_llm_unavailable_returns_explicit_status_without_fabricated_answer():
    runtime, _ = build_runtime(llm=FakeLLM(fail=True))
    state = run(runtime)
    assert state["status"] == "llm_unavailable"
    assert state["errors"] == ["TEACHING_LLM_UNAVAILABLE"]
    assert state.get("final_answer") is None


def test_api_is_disabled_without_explicit_runtime_injection():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/teaching-agent")
    response = TestClient(app).post("/api/v1/teaching-agent/respond", json={"student_id": "s", "course_id": "c", "session_id": "x", "message": "问题"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "TEACHING_AGENT_NOT_CONFIGURED"


def test_api_response_exposes_trace_citations_and_recommendations_when_runtime_injected():
    app = FastAPI(); app.include_router(router, prefix="/api/v1/teaching-agent")
    runtime, _ = build_runtime(); app.state.teaching_agent_runtime = runtime
    response = TestClient(app).post("/api/v1/teaching-agent/respond", json={"student_id": "s", "course_id": "c", "session_id": "x", "message": "问题"})
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] and body["citations"][0]["evidence_id"] == "ev-1"
    assert body["recommended_resources"] == [{"resource_id": "resource-1"}]


def test_explicit_composition_root_requires_every_domain_port():
    runtime = build_teaching_runtime(
        scope=FakeScope(), knowledge_graph=FakeGraph(), retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(), recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(), learning_events=FakeEvents(), llm=FakeLLM(),
    )
    assert run(runtime)["teaching_action"] == "normal_answer"


def _shadow_report() -> dict:
    return {
        "status": "ok", "course_key": "c-1", "data_version": "protected-shadow-v1",
        "states": {
            "binary-search": {
                "status": "ok", "values": {"recurring_error_risk": 0.1, "hint_dependency": 0.2, "transfer": 0.7},
                "observed_performance_score": 0.8, "confidence": "medium", "evidence_refs": ["ev-target"],
                "reason_codes": ["SCORED_EXPLICIT_PERFORMANCE"], "policy_versions": {"scoring": "observed-performance/1.0"},
                "data_version": "protected-shadow-v1",
            },
        },
        "recommendations": {
            "binary-search": [{"concept_id": "ordered-array", "action_type": "review_confirmed_weak_prerequisite", "evidence_refs": ["ev-pre"], "reason_codes": ["CONFIRMED_WEAK_PREREQUISITE"], "policy_version": "graph-path/1.0"}],
        },
    }


def test_kg_mest_shadow_port_drives_existing_prerequisite_action_without_writes():
    learner = KGMetShadowReportStudentModelingPort.from_report(expected_student_id="s-1", expected_course_id="c-1", report=_shadow_report())
    runtime, _ = build_runtime(learner=learner)
    state = run(runtime)
    assert state["teaching_action"] == "prerequisite_review"
    assert state["student_concept_state"]["mastery_score"] == 0.8
    assert state["student_concept_state"]["evidence_refs"] == ("ev-target",)


def test_kg_mest_shadow_port_scope_mismatch_returns_unknown_not_another_student_state():
    learner = KGMetShadowReportStudentModelingPort.from_report(expected_student_id="s-1", expected_course_id="c-1", report=_shadow_report())
    runtime, _ = build_runtime(learner=learner)
    state = run(runtime, student_id="s-2")
    assert state["teaching_action"] == "diagnostic_question"
    assert state["teaching_action_reason"] == "student_state_insufficient"
    assert state["student_concept_state"]["mastery_score"] is None


class TeachingAgentWorkflowTests(unittest.TestCase):
    """Expose the same offline checks through the repository's stdlib test entry."""

    def test_normal_question(self): test_normal_question_uses_evidence_citations_and_records_trace()
    def test_weak_prerequisite(self): test_confirmed_weak_prerequisite_selects_prerequisite_review()
    def test_repeated_error(self): test_repeated_error_selects_misconception_repair()
    def test_insufficient_state(self): test_insufficient_student_state_selects_diagnostic_without_long_term_conclusion()
    def test_unknown_performance(self): test_unknown_observed_performance_selects_diagnostic_without_treating_missing_values_as_low()
    def test_code_context(self): test_code_context_calls_sandbox_and_selects_code_debugging()
    def test_retrieval_failure(self): test_retrieval_failure_degrades_without_unsupported_citation()
    def test_scope_rejection(self): test_scope_rejection_is_whole_workflow_rejection()
    def test_llm_failure(self): test_llm_unavailable_returns_explicit_status_without_fabricated_answer()
    def test_default_api_disabled(self): test_api_is_disabled_without_explicit_runtime_injection()
    def test_injected_api(self): test_api_response_exposes_trace_citations_and_recommendations_when_runtime_injected()
    def test_explicit_composition(self): test_explicit_composition_root_requires_every_domain_port()
    def test_kg_mest_shadow_port(self): test_kg_mest_shadow_port_drives_existing_prerequisite_action_without_writes()
    def test_kg_mest_scope_mismatch(self): test_kg_mest_shadow_port_scope_mismatch_returns_unknown_not_another_student_state()
