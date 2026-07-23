from __future__ import annotations

import unittest

from benchmarks.kg_mest_ablation import run


class KGMESTAblationTests(unittest.TestCase):
    def test_contract_ablation_has_expected_non_claiming_differences(self) -> None:
        result = run()
        self.assertEqual(result["baseline"]["action"], "review_confirmed_weak_prerequisite")
        self.assertIsNone(result["without_q_matrix"]["observed_performance_score"])
        self.assertEqual(result["without_q_matrix"]["action"], "diagnose")
        self.assertGreater(
            result["invalid_interaction_leakage"]["counterfactual_score"],
            result["invalid_interaction_leakage"]["baseline_score"],
        )
        self.assertGreater(
            result["invalid_no_source_deduplication"]["invalid_raw_score"],
            result["invalid_no_source_deduplication"]["baseline_deduplicated_score"],
        )
        self.assertGreater(
            result["invalid_no_source_deduplication"]["invalid_raw_mastery_evidence_count"],
            result["invalid_no_source_deduplication"]["deduplicated_mastery_evidence_count"],
        )


if __name__ == "__main__":
    unittest.main()
