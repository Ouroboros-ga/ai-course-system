from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[3]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.platform.agents.contracts import TeachingTools
from app.platform.agents.runtime import TeachingAgentRuntime
from app.platform.agents.tools.fakes import FakeEvents, FakeLLM, FakeRecommendation, FakeRetrieval, FakeSandbox, FakeScope
from cognition.kg_mest import GraphEvidenceGrounder, GraphSnapshot, LearningEvent, MeasurementRole, MultiSourceEvidenceEngine
from cognition.teaching_adapter import SyntheticKGMetStudentModelingPort, state_to_teaching_view


FIXTURE = Path(__file__).parents[1] / "fixtures" / "kg_mest_course_v1.json"


class FixtureGraph:
    async def resolve_concepts(self, **_):
        return [{"concept_id": "binary-search-boundary", "confidence": 0.9}]

    async def get_context(self, **_):
        return {"graph_version": "synthetic-graph-v1", "prerequisites": [{"concept_id": "loop-invariant"}], "successors": []}


def states_from_fixture():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    graph = GraphSnapshot(course_key=raw["course_key"], **raw["graph"])
    events = []
    for item in raw["events"]:
        item = dict(item)
        item["measurement_role"] = MeasurementRole(item["measurement_role"])
        grounded = GraphEvidenceGrounder(graph).ground(LearningEvent(**item))
        if grounded:
            events.append(grounded)
    engine = MultiSourceEvidenceEngine()
    signals, _ = engine.extract(events)
    return {
        concept: engine.build_state(
            student_key="student-synthetic-01", course_key=raw["course_key"], concept_id=concept,
            explicit_signals=[signal for signal in signals if signal.concept_id == concept], data_version=raw["data_version"],
        )
        for concept in ("binary-search-boundary", "loop-invariant")
    }


class TeachingAdapterTests(unittest.TestCase):
    def test_adapter_preserves_explanation_and_translates_deterministic_fields(self) -> None:
        state = states_from_fixture()["binary-search-boundary"]
        view = state_to_teaching_view(state)
        self.assertEqual(view["mastery_score"], 0.5)
        self.assertEqual(view["confidence"], 0.65)
        self.assertEqual(view["evidence_refs"], state.evidence_refs)
        self.assertIn("scoring", view["policy_versions"])

    def test_real_langgraph_consumes_synthetic_kg_mest_weak_prerequisite(self) -> None:
        states = states_from_fixture()
        runtime = TeachingAgentRuntime(TeachingTools(
            scope=FakeScope(), knowledge_graph=FixtureGraph(), retrieval=FakeRetrieval(),
            student_modeling=SyntheticKGMetStudentModelingPort(states, ("loop-invariant",)),
            recommendation=FakeRecommendation(), sandbox=FakeSandbox(), learning_events=FakeEvents(), llm=FakeLLM(),
        ))
        response = asyncio.run(runtime.respond(
            student_id="student-synthetic-01", course_id="course-algorithms", session_id="session-1",
            message="为什么边界要这样更新？",
        ))
        self.assertEqual(response["teaching_action"], "prerequisite_review")
        self.assertEqual(response["teaching_action_reason"], "confirmed_weak_prerequisite")


if __name__ == "__main__":
    unittest.main()
