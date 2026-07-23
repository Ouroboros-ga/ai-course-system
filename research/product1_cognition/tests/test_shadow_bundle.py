from __future__ import annotations

import unittest

from cognition.shadow_bundle import BUNDLE_SCHEMA_VERSION, artifact_sha256, run_shadow_bundle


class ShadowBundleTests(unittest.TestCase):
    def _manifest(self, artifacts: dict[str, object], **overrides: object) -> dict[str, object]:
        manifest: dict[str, object] = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "data_classification": "protected_pseudonymized",
            "course_key": "course-a", "graph_snapshot_id": "snapshot-a", "student_key": "pseudo-student-a",
            "data_version": "protected-export-v1", "source_scope": {"student_id": 1, "course_id": 2},
            "artifact_sha256": {name: artifact_sha256(value) for name, value in artifacts.items()},
            "shadow_gate": {
                "research_tests_passed": True, "contract_ablation_passed": True,
                "graph_snapshot_status": "accepted", "graph_course_isolation_verified": True,
                "interaction_gold_status": "approved_protected_gold", "privacy_review_status": "approved",
                "provider_contract_tests_passed": True, "append_only_audit_verified": True,
                "no_production_write_verified": True,
            },
        }
        manifest.update(overrides)
        return manifest

    def _inputs(self):
        nodes = [
            {"node_id": "pre", "course_id": "course-a", "status": "accepted", "evidence_ids": ["n1"]},
            {"node_id": "target", "course_id": "course-a", "status": "accepted", "evidence_ids": ["n2"]},
            {"node_id": "task", "course_id": "course-a", "status": "accepted", "evidence_ids": ["n3"]},
        ]
        relations = [
            {"relation_id": "r1", "source_id": "pre", "target_id": "target", "relation_type": "prerequisite_of", "course_id": "course-a", "status": "accepted", "evidence_ids": ["r1-e"]},
            {"relation_id": "r2", "source_id": "task", "target_id": "target", "relation_type": "tests", "course_id": "course-a", "status": "accepted", "evidence_ids": ["r2-e"]},
        ]
        reviews = [
            {"decision_id": "d1", "target_id": "r1", "target_type": "relation", "decision": "accepted", "evidence_bundle_id": "b1"},
            {"decision_id": "d2", "target_id": "r2", "target_type": "relation", "decision": "accepted", "evidence_bundle_id": "b2"},
        ]
        events = [{
            "event_id": "event-1", "event_type": "quiz_answered", "student_id": 1, "course_id": 2,
            "sequence_number": 1, "timestamp": "2026-07-23T10:00:00+00:00",
            "metadata": {"quiz_id": "task", "is_correct": True},
        }]
        return nodes, relations, reviews, events

    def test_ready_bundle_runs_and_report_hides_raw_source_scope(self) -> None:
        nodes, relations, reviews, events = self._inputs()
        artifacts = {"graph_nodes": nodes, "graph_relations": relations, "review_decisions": reviews, "learning_events": events}
        result = run_shadow_bundle(manifest=self._manifest(artifacts), graph_nodes=nodes, graph_relations=relations, review_decisions=reviews, learning_events=events)
        self.assertEqual(result.status, "ok")
        self.assertNotIn("source_scope", result.report)
        self.assertNotIn("student_id", str(result.report))
        self.assertIn("target", result.report["states"])

    def test_unapproved_bundle_is_not_run(self) -> None:
        nodes, relations, reviews, events = self._inputs()
        artifacts = {"graph_nodes": nodes, "graph_relations": relations, "review_decisions": reviews, "learning_events": events}
        manifest = self._manifest(artifacts)
        manifest["shadow_gate"] = {**manifest["shadow_gate"], "privacy_review_status": "pending"}
        result = run_shadow_bundle(manifest=manifest, graph_nodes=nodes, graph_relations=relations, review_decisions=reviews, learning_events=events)
        self.assertEqual(result.status, "not_ready")
        self.assertEqual(result.report["error_codes"], ("PRIVACY_REVIEW_STATUS_REQUIRED",))

    def test_raw_student_id_as_pseudonym_is_rejected(self) -> None:
        nodes, relations, reviews, events = self._inputs()
        artifacts = {"graph_nodes": nodes, "graph_relations": relations, "review_decisions": reviews, "learning_events": events}
        result = run_shadow_bundle(manifest=self._manifest(artifacts, student_key="1"), graph_nodes=nodes, graph_relations=relations, review_decisions=reviews, learning_events=events)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.report["error_codes"], ("SHADOW_BUNDLE_STUDENT_KEY_NOT_PSEUDONYMIZED",))

    def test_changed_artifact_cannot_reuse_a_reviewed_bundle_manifest(self) -> None:
        nodes, relations, reviews, events = self._inputs()
        artifacts = {"graph_nodes": nodes, "graph_relations": relations, "review_decisions": reviews, "learning_events": events}
        changed_events = [dict(events[0], metadata={"quiz_id": "task", "is_correct": False})]
        result = run_shadow_bundle(manifest=self._manifest(artifacts), graph_nodes=nodes, graph_relations=relations, review_decisions=reviews, learning_events=changed_events)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.report["error_codes"], ("SHADOW_BUNDLE_LEARNING_EVENTS_HASH_MISMATCH",))


if __name__ == "__main__":
    unittest.main()
