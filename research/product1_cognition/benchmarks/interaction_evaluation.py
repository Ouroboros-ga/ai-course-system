"""Deterministic per-label evaluation for interaction candidate providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


LABELS = ("confusion_risk", "inquiry_depth", "hint_dependency", "explanation_need")


@dataclass(frozen=True)
class LabelMetrics:
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float | None:
        denominator = self.true_positive + self.false_positive
        return round(self.true_positive / denominator, 4) if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positive + self.false_negative
        return round(self.true_positive / denominator, 4) if denominator else None

    @property
    def f1(self) -> float | None:
        if self.precision is None or self.recall is None or self.precision + self.recall == 0:
            return None
        return round(2 * self.precision * self.recall / (self.precision + self.recall), 4)

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


def evaluate(
    gold_records: Iterable[Mapping[str, object]],
    predictions: Mapping[str, Mapping[str, bool]],
    *,
    labels: tuple[str, ...] = LABELS,
) -> dict[str, object]:
    """Evaluate only records with a prediction; absent prediction is an error.

    This prevents an unavailable provider from appearing accurate by silently
    skipping difficult items.
    """
    records = list(gold_records)
    ids = [str(record["source_event_id"]) for record in records]
    missing = tuple(sorted(set(ids) - set(predictions)))
    unexpected = tuple(sorted(set(predictions) - set(ids)))
    if missing or unexpected:
        return {
            "status": "rejected",
            "error_code": "PREDICTION_COVERAGE_MISMATCH",
            "missing_source_event_ids": missing,
            "unexpected_source_event_ids": unexpected,
            "metrics": {},
        }
    metrics: dict[str, LabelMetrics] = {}
    for label in labels:
        tp = fp = fn = 0
        for record in records:
            record_id = str(record["source_event_id"])
            actual = bool(dict(record.get("labels", {})).get(label, False))
            predicted = bool(predictions[record_id].get(label, False))
            tp += int(actual and predicted)
            fp += int(not actual and predicted)
            fn += int(actual and not predicted)
        metrics[label] = LabelMetrics(tp, fp, fn)
    macro_f1_values = [metric.f1 for metric in metrics.values() if metric.f1 is not None]
    return {
        "status": "ok",
        "record_count": len(records),
        "metrics": {label: metric.as_dict() for label, metric in metrics.items()},
        "macro_f1_over_defined_labels": round(sum(macro_f1_values) / len(macro_f1_values), 4) if macro_f1_values else None,
    }
