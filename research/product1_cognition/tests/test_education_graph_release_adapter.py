from __future__ import annotations

import unittest

from cognition.education_graph_release_adapter import adapt_education_graph_release


class EducationGraphReleaseAdapterTests(unittest.TestCase):
    def _nodes(self) -> list[dict[str, object]]:
        return [
            {"node_id": "loop-invariant", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-node-1"]},
            {"node_id": "binary-search-boundary", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-node-2"]},
        ]

    def _relation(self) -> dict[str, object]:
        return {
            "relation_id": "rel-01", "source_id": "loop-invariant", "target_id": "binary-search-boundary",
            "relation_type": "PREREQUISITE_OF", "course_id": "course-a", "status": "accepted",
            "evidence_ids": ["ev-relation-1"],
        }

    def _review(self) -> dict[str, object]:
        return {
            "decision_id": "review-01", "target_id": "rel-01", "target_type": "relation",
            "decision": "accepted", "evidence_bundle_id": "bundle-01",
        }

    def _tests_relation(self) -> dict[str, object]:
        return {
            "relation_id": "rel-tests-01", "source_id": "exercise-boundary-01", "target_id": "binary-search-boundary",
            "relation_type": "tests", "course_id": "course-a", "status": "accepted",
            "evidence_ids": ["ev-tests-1"], "properties": {"task_discrimination": 0.85},
        }

    def test_accepted_domain_export_adapts_to_kg_mest_snapshot(self) -> None:
        result = adapt_education_graph_release(
            course_key="course-a", snapshot_id="edu-graph-snapshot-01",
            nodes=self._nodes(), relations=[self._relation()], review_decisions=[self._review()],
        )
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.error_codes, ())
        self.assertEqual(result.graph.snapshot.prerequisites, {"binary-search-boundary": ("loop-invariant",)})

    def test_domain_enum_value_spelling_is_accepted(self) -> None:
        relation = self._relation()
        relation["relation_type"] = "prerequisite_of"
        result = adapt_education_graph_release(
            course_key="course-a", snapshot_id="edu-graph-snapshot-01",
            nodes=self._nodes(), relations=[relation], review_decisions=[self._review()],
        )
        self.assertEqual(result.status, "accepted")

    def test_accepted_tests_relation_becomes_q_matrix_mapping(self) -> None:
        nodes = self._nodes() + [{
            "node_id": "exercise-boundary-01", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-node-exercise"],
        }]
        result = adapt_education_graph_release(
            course_key="course-a", snapshot_id="edu-graph-snapshot-01", nodes=nodes,
            relations=[self._relation(), self._tests_relation()],
            review_decisions=[self._review(), {
                "decision_id": "review-tests-01", "target_id": "rel-tests-01", "target_type": "relation",
                "decision": "accepted", "evidence_bundle_id": "bundle-tests-01",
            }],
        )
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.graph.snapshot.task_q_matrix, {"exercise-boundary-01": ("binary-search-boundary",)})
        self.assertEqual(result.graph.snapshot.task_discrimination, {"exercise-boundary-01": 0.85})

    def test_unreviewed_tests_relation_rejects_whole_release(self) -> None:
        nodes = self._nodes() + [{
            "node_id": "exercise-boundary-01", "course_id": "course-a", "status": "accepted", "evidence_ids": ["ev-node-exercise"],
        }]
        result = adapt_education_graph_release(
            course_key="course-a", snapshot_id="edu-graph-snapshot-01", nodes=nodes,
            relations=[self._relation(), self._tests_relation()], review_decisions=[self._review()],
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_codes, ("EDUCATION_GRAPH_Q_MATRIX_REVIEW_MISSING",))

    def test_missing_review_rejects_whole_release(self) -> None:
        result = adapt_education_graph_release(
            course_key="course-a", snapshot_id="edu-graph-snapshot-01",
            nodes=self._nodes(), relations=[self._relation()], review_decisions=[],
        )
        self.assertEqual(result.status, "rejected")
        self.assertIsNone(result.graph)
        self.assertEqual(result.error_codes, ("EDUCATION_GRAPH_PREREQUISITE_REVIEW_MISSING",))

    def test_unaccepted_endpoint_or_foreign_course_rejects_whole_release(self) -> None:
        nodes = self._nodes()
        nodes[0] = {"node_id": "loop-invariant", "course_id": "course-a", "status": "proposed", "evidence_ids": ["ev-node-1"]}
        relation = self._relation()
        relation["course_id"] = "course-b"
        result = adapt_education_graph_release(
            course_key="course-a", snapshot_id="edu-graph-snapshot-01",
            nodes=nodes, relations=[relation], review_decisions=[self._review()],
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.error_codes,
            ("EDUCATION_GRAPH_PREREQUISITE_COURSE_SCOPE_MISMATCH", "EDUCATION_GRAPH_PREREQUISITE_NODE_NOT_ACCEPTED"),
        )


if __name__ == "__main__":
    unittest.main()
