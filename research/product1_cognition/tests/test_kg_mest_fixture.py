from __future__ import annotations

import json
from pathlib import Path
import unittest

from cognition.kg_mest import (
    GraphEvidenceGrounder,
    GraphSnapshot,
    LearningEvent,
    LearningPathRecommender,
    MeasurementRole,
    MultiSourceEvidenceEngine,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "kg_mest_course_v1.json"


class KGMESTFixtureTests(unittest.TestCase):
    def test_versioned_fixture_replays_to_confirmed_weak_prerequisite(self) -> None:
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        graph = GraphSnapshot(course_key=raw["course_key"], **raw["graph"])
        grounder = GraphEvidenceGrounder(graph)
        events = []
        for item in raw["events"]:
            item = dict(item)
            item["measurement_role"] = MeasurementRole(item["measurement_role"])
            grounded = grounder.ground(LearningEvent(**item))
            if grounded is not None:
                events.append(grounded)
        engine = MultiSourceEvidenceEngine()
        explicit, _ = engine.extract(events)
        by_concept = {
            concept: engine.build_state(
                student_key="student-synthetic-01", course_key=raw["course_key"], concept_id=concept,
                explicit_signals=[signal for signal in explicit if signal.concept_id == concept],
                data_version=raw["data_version"],
            )
            for concept in ("loop-invariant", "binary-search-boundary")
        }
        recommendation = LearningPathRecommender(graph).recommend(
            by_concept["binary-search-boundary"], by_concept,
        )
        self.assertEqual(recommendation[0].action_type, "review_confirmed_weak_prerequisite")
        self.assertEqual(recommendation[0].concept_id, "loop-invariant")
        self.assertEqual(by_concept["loop-invariant"].data_version, "synthetic-course-v1")
        self.assertEqual(by_concept["binary-search-boundary"].observed_performance_score, 0.5)


if __name__ == "__main__":
    unittest.main()
