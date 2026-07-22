from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.release_gate import (
    ALGORITHM_PREPARATION_SPEC,
    CONTRACT_BASELINE_SHA256,
    ReleaseGateBlocked,
    check_algorithm_preparation,
    check_b_r1_release,
    check_contract_baseline,
)

FIXTURE = RESEARCH_ROOT / "datasets" / "micro_contract_v1"


class ReleaseGateTests(unittest.TestCase):
    def test_algorithm_preparation_is_machine_checkable_but_not_a_release(self) -> None:
        result = check_algorithm_preparation(FIXTURE)
        self.assertEqual(result["gate"], "B-P0")
        self.assertEqual(result["status"], "prepared_not_released")
        self.assertFalse(result["implementation_authorized"])
        self.assertFalse(result["quality_comparison_authorized"])
        self.assertEqual(result["contract_files_verified"], len(CONTRACT_BASELINE_SHA256))
        self.assertEqual(result["spec_version"], "graph-retrieval-algorithm-preparation/1.0")
        self.assertEqual(
            result["spec_sha256"],
            "f4e89dc3ac2d5333208a434ca089810ec5498f47e90acdb1788317ca21790a9e",
        )

    def test_preparation_spec_freezes_deterministic_rules(self) -> None:
        self.assertEqual(
            ALGORITHM_PREPARATION_SPEC["tokenizer"]["query_term_frequency"],
            "unique_terms_first_occurrence_order",
        )
        self.assertEqual(
            ALGORITHM_PREPARATION_SPEC["bm25"]["tie_break"],
            ["score_desc", "research_chunk_id_asc"],
        )
        self.assertEqual(
            ALGORITHM_PREPARATION_SPEC["result"]["abstain_reasons"],
            ["empty_query", "scope_not_available", "no_lexical_match", "no_active_evidence"],
        )
        self.assertIn("graphrag", ALGORITHM_PREPARATION_SPEC["prohibited"])
        self.assertEqual(
            ALGORITHM_PREPARATION_SPEC["mapping"]["candidate_evidence_policy"],
            "exclude_ineligible_then_abstain_if_none_remain",
        )

    def test_contract_drift_gate_fails_closed_on_missing_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReleaseGateBlocked) as raised:
                check_contract_baseline(Path(directory))
        self.assertIn("contract_missing:", str(raised.exception))

    def test_micro_fixture_cannot_release_b_r1(self) -> None:
        with self.assertRaises(ReleaseGateBlocked) as raised:
            check_b_r1_release(FIXTURE)
        message = str(raised.exception)
        self.assertIn("dataset_level_is_not_human_gold", message)
        self.assertIn("p1_00_not_approved", message)
        self.assertIn("p1_10_not_approved", message)


if __name__ == "__main__":
    unittest.main()
