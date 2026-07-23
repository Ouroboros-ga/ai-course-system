from __future__ import annotations

import unittest

from cognition.graph_adapter import adapt_cognition_graph


class GraphAdapterTests(unittest.TestCase):
    def test_accepted_course_prerequisite_dag_is_adapted(self) -> None:
        result = adapt_cognition_graph(
            course_key="course-a", graph_version="accepted-v1",
            nodes=[{"node_id": "pre"}, {"node_id": "target"}],
            edges=[{
                "subject_node_id": "pre", "object_node_id": "target", "predicate": "PREREQUISITE_OF",
                "course_id": "course-a", "status": "accepted", "review_record_id": "review-01",
                "evidence_refs": ("curriculum:unit-01",),
            }],
        )
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.snapshot.prerequisites, {"target": ("pre",)})

    def test_structural_retrieval_graph_is_not_reinterpreted_as_prerequisites(self) -> None:
        result = adapt_cognition_graph(
            course_key="course-a", graph_version="retrieval-only-v1",
            nodes=[{"node_id": "chapter"}, {"node_id": "concept"}],
            edges=[{"subject_node_id": "chapter", "object_node_id": "concept", "predicate": "CONTAINS", "course_id": "course-a", "status": "accepted"}],
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_codes, ("PREREQUISITE_RELATIONS_UNAVAILABLE",))

    def test_cross_course_or_cycle_is_rejected(self) -> None:
        result = adapt_cognition_graph(
            course_key="course-a", graph_version="bad-v1",
            nodes=[{"node_id": "a"}, {"node_id": "b"}],
            edges=[
                {"subject_node_id": "a", "object_node_id": "b", "predicate": "PREREQUISITE_OF", "course_id": "course-a", "status": "accepted", "review_record_id": "review-01", "evidence_refs": ("curriculum:01",)},
                {"subject_node_id": "b", "object_node_id": "a", "predicate": "PREREQUISITE_OF", "course_id": "course-a", "status": "accepted", "review_record_id": "review-02", "evidence_refs": ("curriculum:02",)},
                {"subject_node_id": "a", "object_node_id": "b", "predicate": "PREREQUISITE_OF", "course_id": "course-b", "status": "accepted", "review_record_id": "review-03", "evidence_refs": ("curriculum:03",)},
            ],
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_codes, ("PREREQUISITE_CYCLE_REJECTED", "PREREQUISITE_EDGE_COURSE_SCOPE_MISSING_OR_MISMATCH"))

    def test_accepted_status_without_evidence_and_review_is_rejected(self) -> None:
        result = adapt_cognition_graph(
            course_key="course-a", graph_version="unsafe-v1",
            nodes=[{"node_id": "pre"}, {"node_id": "target"}],
            edges=[{"subject_node_id": "pre", "object_node_id": "target", "predicate": "PREREQUISITE_OF", "course_id": "course-a", "status": "accepted"}],
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_codes, ("PREREQUISITE_ACCEPTANCE_METADATA_MISSING", "PREREQUISITE_RELATIONS_UNAVAILABLE"))


if __name__ == "__main__":
    unittest.main()
