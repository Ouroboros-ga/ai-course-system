from __future__ import annotations

import unittest

from cognition.graph_adapter import adapt_cognition_graph
from cognition.legacy_prerequisite_candidates import build_legacy_prerequisite_candidates


class LegacyPrerequisiteCandidateTests(unittest.TestCase):
    def _points(self) -> list[dict[str, object]]:
        return [
            {"id": 11, "point_id": "loop-invariant", "course_id": "course-a"},
            {"id": 12, "point_id": "binary-search-boundary", "course_id": "course-a"},
        ]

    def test_legacy_relation_becomes_candidate_not_accepted_graph_edge(self) -> None:
        result = build_legacy_prerequisite_candidates(
            course_key="course-a",
            source_snapshot_version="legacy-export-v1",
            knowledge_points=self._points(),
            relations=[{"id": 77, "source_id": 11, "target_id": 12, "relation_type": "prerequisite", "course_id": "course-a"}],
        )
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.error_codes, ())
        edge = result.candidates[0].as_graph_edge()
        self.assertEqual(edge["status"], "candidate")
        self.assertTrue(edge["requires_human_review"])
        self.assertEqual(edge["evidence_refs"], ("legacy_knowledge_relation:77",))

        graph_result = adapt_cognition_graph(
            course_key="course-a",
            graph_version="candidate-only-v1",
            nodes=[{"node_id": "loop-invariant"}, {"node_id": "binary-search-boundary"}],
            edges=[edge],
        )
        self.assertEqual(graph_result.status, "rejected")
        self.assertEqual(graph_result.error_codes, ("PREREQUISITE_RELATIONS_UNAVAILABLE",))

    def test_unscoped_or_cross_course_legacy_records_reject_whole_batch(self) -> None:
        result = build_legacy_prerequisite_candidates(
            course_key="course-a",
            source_snapshot_version="legacy-export-v1",
            knowledge_points=self._points(),
            relations=[
                {"id": 77, "source_id": 11, "target_id": 12, "relation_type": "prerequisite", "course_id": "course-a"},
                {"id": 78, "source_id": 11, "target_id": 12, "relation_type": "prerequisite", "course_id": "course-b"},
            ],
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.error_codes, ("LEGACY_PREREQUISITE_COURSE_SCOPE_MISMATCH",))

    def test_free_text_prerequisites_are_not_an_input_channel(self) -> None:
        result = build_legacy_prerequisite_candidates(
            course_key="course-a",
            source_snapshot_version="legacy-export-v1",
            knowledge_points=self._points(),
            relations=[],
        )
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.candidates, ())


if __name__ == "__main__":
    unittest.main()
