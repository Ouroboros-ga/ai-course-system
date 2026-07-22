from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path


RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.fixture_io import validate_fixture
from src.release_gate import ReleaseGateBlocked, check_b_r1_release, check_reviewed_silver_preparation


FIXTURE = RESEARCH_ROOT / "datasets" / "reviewed_silver_v0_2"
RELEASE_REPORT = RESEARCH_ROOT / "reports" / "reviewed_silver_v0_2_b_r1_release_check.json"


class ReviewedSilverTests(unittest.TestCase):
    def test_real_courseware_silver_fixture_is_closed_and_non_gold(self) -> None:
        audit = validate_fixture(FIXTURE)
        self.assertEqual(audit["dataset_level"], "reviewed_silver")
        self.assertEqual(audit["counts"], {
            "courses": 4, "source_blocks": 1083, "evidence": 1083, "chunks": 1083,
            "queries": 96, "knowledge_points": 71, "slides": 253,
        })
        self.assertFalse(audit["gold"]["eligible_for_algorithm_comparison"])
        splits = json.loads((FIXTURE / "splits.json").read_text(encoding="utf-8"))
        self.assertEqual({key: len(value) for key, value in splits.items() if key.endswith("_query_ids")}, {
            "train_query_ids": 56, "validation_query_ids": 20, "test_query_ids": 20,
        })

    def test_silver_gate_allows_only_offline_baseline_preparation(self) -> None:
        silver = check_reviewed_silver_preparation(FIXTURE)
        self.assertTrue(silver["offline_baseline_implementation_eligible"])
        self.assertEqual(silver["production_integration"], "not_authorized")
        with self.assertRaises(ReleaseGateBlocked) as raised:
            check_b_r1_release(FIXTURE)
        self.assertIn("dataset_level_is_not_human_gold", str(raised.exception))
        report = json.loads(RELEASE_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["manifest_sha256"], silver["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
