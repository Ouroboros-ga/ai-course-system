from __future__ import annotations

import unittest

from benchmarks.shadow_gate import ShadowGateInput, evaluate_shadow_gate


class ShadowGateTests(unittest.TestCase):
    def test_synthetic_research_is_not_shadow_ready(self) -> None:
        result = evaluate_shadow_gate(ShadowGateInput(
            research_tests_passed=True,
            contract_ablation_passed=True,
            graph_snapshot_status="synthetic_only",
            graph_course_isolation_verified=True,
            interaction_gold_status="synthetic_only",
            privacy_review_status="not_started",
            provider_contract_tests_passed=False,
            append_only_audit_verified=False,
            no_production_write_verified=True,
        ))
        self.assertEqual(result["status"], "not_ready")
        self.assertIn("INTERACTION_GOLD_STATUS_REQUIRED", result["error_codes"])
        self.assertIsNone(result["promotion"])

    def test_all_required_evidence_allows_read_only_shadow_only(self) -> None:
        result = evaluate_shadow_gate(ShadowGateInput(
            research_tests_passed=True,
            contract_ablation_passed=True,
            graph_snapshot_status="accepted",
            graph_course_isolation_verified=True,
            interaction_gold_status="approved_protected_gold",
            privacy_review_status="approved",
            provider_contract_tests_passed=True,
            append_only_audit_verified=True,
            no_production_write_verified=True,
        ))
        self.assertEqual(result, {"status": "ready_for_shadow", "error_codes": (), "promotion": "read_only_shadow"})


if __name__ == "__main__":
    unittest.main()
