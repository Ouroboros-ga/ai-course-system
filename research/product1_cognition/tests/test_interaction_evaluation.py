from __future__ import annotations

import json
from pathlib import Path
import unittest

from benchmarks.interaction_evaluation import evaluate


FIXTURE = Path(__file__).parents[1] / "fixtures" / "interaction_gold_synthetic_v1.json"


class InteractionEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]

    def test_metrics_are_label_specific_and_deterministic(self) -> None:
        predictions = {
            "synthetic-01": {"confusion_risk": True, "explanation_need": True},
            "synthetic-02": {"hint_dependency": True},
            "synthetic-03": {"inquiry_depth": True},
            "synthetic-04": {"confusion_risk": True},
            "synthetic-05": {"hint_dependency": False},
            "synthetic-06": {"confusion_risk": True},
        }
        result = evaluate(self.records, predictions)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metrics"]["confusion_risk"]["true_positive"], 2)
        self.assertEqual(result["metrics"]["confusion_risk"]["false_positive"], 1)
        self.assertEqual(result["metrics"]["hint_dependency"]["false_negative"], 1)

    def test_missing_predictions_rejects_instead_of_scoring_partial_subset(self) -> None:
        result = evaluate(self.records, {"synthetic-01": {"confusion_risk": True}})
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error_code"], "PREDICTION_COVERAGE_MISMATCH")
        self.assertEqual(len(result["missing_source_event_ids"]), 5)


if __name__ == "__main__":
    unittest.main()
