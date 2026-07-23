"""PaddleNLP UIE candidate generator for interaction semantics.

This adapter never computes performance or mastery.  Its output must pass the
KG-MEST dialogue evidence gate, which applies a per-label confidence threshold
and keeps interaction state separate from ``observed_performance_score``.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
from typing import Any, Callable, Mapping


PADDLE_UIE_POLICY_VERSION = "paddlenlp-uie-interaction-candidate/1.0"
PADDLE_UIE_MODEL = "uie-mini"
PADDLE_UIE_SCHEMA: Mapping[str, str] = {
    "confusion_risk": "困惑表达",
    "inquiry_depth": "概念性追问",
    "hint_dependency": "提示请求",
    "explanation_need": "解释需求",
}


@dataclass(frozen=True)
class UIEInteractionCandidate:
    source_event_id: str
    labels: Mapping[str, bool]
    label_confidences: Mapping[str, float]
    evidence_spans: Mapping[str, tuple[str, ...]]
    model_version: str
    policy_version: str = PADDLE_UIE_POLICY_VERSION

    def as_interaction_payload(self) -> dict[str, Any]:
        """Convert to the input shape consumed by DialogueInteractionExtractor."""
        return {
            "candidate_source_event_id": self.source_event_id,
            "classification_confidence": max(self.label_confidences.values(), default=0.0),
            "interaction_labels": dict(self.labels),
            "interaction_label_confidences": dict(self.label_confidences),
            "candidate_evidence_spans": {key: list(value) for key, value in self.evidence_spans.items()},
            "candidate_model_version": self.model_version,
            "candidate_policy_version": self.policy_version,
        }


class PaddleNLPUIEInteractionCandidateProvider:
    """Offline-only UIE wrapper with an explicit local-model gate."""

    def __init__(self, taskflow: Callable[[str], list[Mapping[str, Any]]] | None = None) -> None:
        self._taskflow = taskflow

    @staticmethod
    def availability() -> Mapping[str, bool]:
        return {
            "paddle_installed": importlib.util.find_spec("paddle") is not None,
            "paddlenlp_installed": importlib.util.find_spec("paddlenlp") is not None,
            "local_uie_mini_present": PaddleNLPUIEInteractionCandidateProvider._model_path().is_dir(),
        }

    @staticmethod
    def _model_path() -> Path:
        home = Path(os.environ.get("PPNLP_HOME", Path.home() / ".paddlenlp"))
        return home / "taskflow" / "information_extraction" / PADDLE_UIE_MODEL

    def _get_taskflow(self) -> Callable[[str], list[Mapping[str, Any]]]:
        if self._taskflow is not None:
            return self._taskflow
        availability = self.availability()
        if not all(availability.values()):
            raise RuntimeError("PaddleNLP UIE local runtime or model is unavailable; downloads are intentionally disabled")
        from paddlenlp import Taskflow  # imported lazily so standard tests need no Paddle

        self._taskflow = Taskflow(
            "information_extraction",
            model=PADDLE_UIE_MODEL,
            schema=list(PADDLE_UIE_SCHEMA.values()),
            device_id=-1,
        )
        return self._taskflow

    def classify(self, *, source_event_id: str, text: str) -> UIEInteractionCandidate:
        raw_batch = self._get_taskflow()(text)
        raw = dict(raw_batch[0]) if raw_batch else {}
        labels: dict[str, bool] = {}
        confidences: dict[str, float] = {}
        spans: dict[str, tuple[str, ...]] = {}
        for internal_name, schema_name in PADDLE_UIE_SCHEMA.items():
            matches = tuple(raw.get(schema_name, ()))
            probabilities = [float(match.get("probability", 0.0)) for match in matches]
            confidences[internal_name] = max(probabilities, default=0.0)
            labels[internal_name] = bool(matches)
            spans[internal_name] = tuple(str(match.get("text", "")) for match in matches if match.get("text"))
        return UIEInteractionCandidate(
            source_event_id=source_event_id,
            labels=labels,
            label_confidences=confidences,
            evidence_spans=spans,
            model_version=PADDLE_UIE_MODEL,
        )
