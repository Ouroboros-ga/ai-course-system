from __future__ import annotations

import unittest

from cognition.shadow_pipeline import run_read_only_shadow


class ReadOnlyShadowPipelineTests(unittest.TestCase):
    def _graph_nodes(self) -> list[dict[str, object]]:
        return [
            {"node_id": "pre", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-node-pre"]},
            {"node_id": "target", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-node-target"]},
            {"node_id": "task-pre", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-task-pre"]},
            {"node_id": "task-target", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-task-target"]},
        ]

    def _graph_relations(self) -> list[dict[str, object]]:
        return [
            {"relation_id": "r-pre", "source_id": "pre", "target_id": "target", "relation_type": "prerequisite_of", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-r-pre"]},
            {"relation_id": "r-q-pre", "source_id": "task-pre", "target_id": "pre", "relation_type": "tests", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-r-q-pre"]},
            {"relation_id": "r-q-target", "source_id": "task-target", "target_id": "target", "relation_type": "tests", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-r-q-target"]},
        ]

    def _reviews(self) -> list[dict[str, object]]:
        return [
            {"decision_id": f"review-{relation_id}", "target_id": relation_id, "target_type": "relation", "decision": "accepted", "evidence_bundle_id": f"bundle-{relation_id}"}
            for relation_id in ("r-pre", "r-q-pre", "r-q-target")
        ]

    def _event(self, event_id: str, task_id: str, score: float, sequence: int) -> dict[str, object]:
        return {
            "event_id": event_id, "event_type": "quiz_answered", "student_id": 1, "course_id": 2,
            "sequence_number": sequence, "timestamp": f"2026-07-23T10:0{sequence}:00+00:00",
            "metadata": {"quiz_id": task_id, "observed_score": score, "attempt_group_key": event_id},
        }

    def _run(self, events: list[dict[str, object]]):
        return run_read_only_shadow(
            course_key="course-a", graph_snapshot_id="approved-release-v1", graph_nodes=self._graph_nodes(),
            graph_relations=self._graph_relations(), review_decisions=self._reviews(), source_student_id=1,
            source_course_id=2, student_key="student-pseudonym-1", data_version="protected-export-v1",
            learning_events=events,
        )

    def test_governed_graph_and_events_run_end_to_end_without_writes(self) -> None:
        result = self._run([
            self._event("pre-1", "task-pre", 0.0, 1), self._event("pre-2", "task-pre", 0.0, 2),
            self._event("target-1", "task-target", 1.0, 3), self._event("target-2", "task-target", 1.0, 4),
        ])
        self.assertEqual(result.status, "ok")
        self.assertEqual(set(result.states), {"pre", "target"})
        self.assertLess(result.states["pre"].observed_performance_score, result.states["target"].observed_performance_score)
        self.assertEqual(result.unmapped_event_refs, ())
        self.assertIn("target", result.recommendations)

    def test_invalid_graph_release_returns_no_partial_shadow_output(self) -> None:
        relations = self._graph_relations()
        relations[0]["status"] = "proposed"
        result = run_read_only_shadow(
            course_key="course-a", graph_snapshot_id="bad-release-v1", graph_nodes=self._graph_nodes(),
            graph_relations=relations, review_decisions=self._reviews(), source_student_id=1, source_course_id=2,
            student_key="student-pseudonym-1", data_version="protected-export-v1",
            learning_events=[self._event("pre-1", "task-pre", 0.0, 1)],
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.states, {})
        self.assertEqual(result.error_codes, ("EDUCATION_GRAPH_PREREQUISITE_NOT_ACCEPTED",))


if __name__ == "__main__":
    unittest.main()
