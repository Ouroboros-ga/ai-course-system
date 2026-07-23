"""Deterministic KG-MEST research baseline.

The module implements the minimum evidence-centred design described in the
KG-MEST integration plan.  It is intentionally dependency-free and does not
import application models, databases, LLM clients or production Memory.

The important safety invariant is enforced in code: only evidence with the
``explicit_performance`` measurement role can affect the eight-dimensional
concept state.  Conversation labels are returned as separate instructional
states and never change ``observed_performance_score``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from math import exp
from typing import Any, Iterable, Mapping


KG_MEST_VERSION = "kg-mest/research-baseline/1.0"
KG_MEST_POLICY_VERSION = "kg-mest-policy/1.0"
SCORING_POLICY_VERSION = "observed-performance/1.0"
CONFIDENCE_POLICY_VERSION = "evidence-confidence/1.0"
INTERACTION_POLICY_VERSION = "interaction-state/1.0"
RECOMMENDATION_POLICY_VERSION = "graph-path/1.0"


class Dimension(StrEnum):
    MASTERY = "mastery"
    STABILITY = "stability"
    INDEPENDENCE = "independence"
    TRANSFER = "transfer"
    STRATEGY_QUALITY = "strategy_quality"
    RECOVERY_EFFICIENCY = "recovery_efficiency"
    HINT_DEPENDENCY = "hint_dependency"
    RECURRING_ERROR_RISK = "recurring_error_risk"


class MeasurementRole(StrEnum):
    EXPLICIT_PERFORMANCE = "explicit_performance"
    INTERACTION_SEMANTIC = "interaction_semantic"


class InteractionKind(StrEnum):
    CONFUSION_RISK = "confusion_risk"
    INQUIRY_DEPTH = "inquiry_depth"
    HINT_DEPENDENCY = "hint_dependency"
    EXPLANATION_NEED = "explanation_need"


class ScopeMismatchError(ValueError):
    """Raised when a batch combines different student/course scopes."""


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _utc(timestamp: str | datetime) -> datetime:
    if isinstance(timestamp, datetime):
        result = timestamp
    else:
        result = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class LearningEvent:
    """Research input fact with stable origin and measurement semantics."""

    event_id: str
    source_event_id: str
    attempt_group_key: str
    student_key: str
    course_key: str
    sequence_number: int
    occurred_at: str
    event_type: str
    concept_ids: tuple[str, ...]
    measurement_role: MeasurementRole
    payload: Mapping[str, Any] = field(default_factory=dict)
    data_version: str = "synthetic-v1"


@dataclass(frozen=True)
class EvidenceSignal:
    """A single, scope-bound observation of one state dimension."""

    evidence_id: str
    source_event_id: str
    student_key: str
    course_key: str
    concept_id: str
    dimension: Dimension
    value: float
    occurred_at: str
    sequence_number: int
    measurement_role: MeasurementRole
    source_reliability: float
    grounding_confidence: float
    task_discrimination: float
    independence_factor: float
    evidence_quality: float
    reason_code: str
    policy_version: str = SCORING_POLICY_VERSION
    derived_from: tuple[str, ...] = ()

    @property
    def weight(self) -> float:
        result = 1.0
        for factor in (
            self.source_reliability,
            self.grounding_confidence,
            self.task_discrimination,
            self.independence_factor,
            self.evidence_quality,
        ):
            result *= _clamp(factor)
        return result


@dataclass(frozen=True)
class InteractionEvidence:
    """A teaching-state observation, never a performance observation."""

    evidence_id: str
    source_event_id: str
    student_key: str
    course_key: str
    concept_id: str
    kind: InteractionKind
    label_confidence: float
    occurred_at: str
    sequence_number: int
    reason_code: str
    polarity: int = 1
    derived_from: tuple[str, ...] = ()
    evidence_spans: tuple[str, ...] = ()
    classifier_model_version: str = ""
    classifier_prompt_version: str = ""
    classifier_policy_version: str = ""
    policy_version: str = INTERACTION_POLICY_VERSION


@dataclass(frozen=True)
class BetaCell:
    alpha: float = 1.5
    beta: float = 1.5
    updated_at: str = "1970-01-01T00:00:00+00:00"

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def effective_strength(self) -> float:
        return max(0.0, self.alpha + self.beta - 3.0)

    def update(self, signal: EvidenceSignal, half_life_days: float) -> "BetaCell":
        before = _utc(self.updated_at)
        occurred = _utc(signal.occurred_at)
        elapsed_days = max(0.0, (occurred - before).total_seconds() / 86400.0)
        decay = 2 ** (-elapsed_days / half_life_days) if half_life_days > 0 else 1.0
        alpha = 1.5 + decay * (self.alpha - 1.5) + signal.weight * _clamp(signal.value)
        beta = 1.5 + decay * (self.beta - 1.5) + signal.weight * (1.0 - _clamp(signal.value))
        return BetaCell(alpha=alpha, beta=beta, updated_at=occurred.isoformat())


@dataclass(frozen=True)
class ConceptState:
    student_key: str
    course_key: str
    concept_id: str
    values: Mapping[str, float | None]
    observed_performance_score: float | None
    confidence: str
    effective_evidence_weight: float
    evidence_refs: tuple[str, ...]
    derived_from: tuple[str, ...]
    reason_codes: tuple[str, ...]
    confidence_reasons: tuple[str, ...]
    rule_contributions: tuple[Mapping[str, Any], ...]
    policy_versions: Mapping[str, str]
    data_version: str
    status: str = "ok"
    rejected_evidence_refs: tuple[str, ...] = ()
    rejection_details: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class InteractionState:
    student_key: str
    course_key: str
    concept_id: str
    values: Mapping[str, str]
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    policy_version: str = INTERACTION_POLICY_VERSION
    classifier_provenance: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class GraphSnapshot:
    """Minimal frozen, course-scoped graph for research fixtures."""

    course_key: str
    graph_version: str
    prerequisites: Mapping[str, tuple[str, ...]]
    resources: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    task_q_matrix: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    task_discrimination: Mapping[str, float] = field(default_factory=dict)


class GraphEvidenceGrounder:
    """Anchor measured tasks to accepted, course-scoped graph components.

    The research baseline intentionally accepts no semantic free-text fallback:
    an unanchored scored event yields no evidence until an accepted Q-Matrix
    mapping exists.
    """

    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.snapshot = snapshot

    def ground(self, event: LearningEvent) -> LearningEvent | None:
        if event.course_key != self.snapshot.course_key:
            raise ScopeMismatchError("event course does not match graph snapshot")
        if event.concept_ids:
            return event
        task_id = str(event.payload.get("task_id", ""))
        concepts = self.snapshot.task_q_matrix.get(task_id, ())
        if not concepts:
            return None
        payload = dict(event.payload)
        scoring = dict(payload.get("scoring", {}))
        scoring.setdefault("task_discrimination", self.snapshot.task_discrimination.get(task_id, 0.7))
        payload["scoring"] = scoring
        return replace(event, concept_ids=tuple(sorted(concepts)), payload=payload)


@dataclass(frozen=True)
class Recommendation:
    concept_id: str
    action_type: str
    priority: float
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    resource_ids: tuple[str, ...]
    policy_version: str = RECOMMENDATION_POLICY_VERSION


HALF_LIFE_DAYS: Mapping[Dimension, float] = {
    Dimension.MASTERY: 45.0,
    Dimension.STABILITY: 90.0,
    Dimension.INDEPENDENCE: 30.0,
    Dimension.TRANSFER: 60.0,
    Dimension.STRATEGY_QUALITY: 30.0,
    Dimension.RECOVERY_EFFICIENCY: 30.0,
    Dimension.HINT_DEPENDENCY: 21.0,
    Dimension.RECURRING_ERROR_RISK: 30.0,
}


def _stable_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(value for value in values if value)))


def _confidence(weight: float, independent_sources: int) -> tuple[str, tuple[str, ...]]:
    if independent_sources == 0:
        return "unknown", ("NO_EXPLICIT_PERFORMANCE_EVIDENCE",)
    if independent_sources == 1 or weight < 0.75:
        return "low", ("INSUFFICIENT_INDEPENDENT_EVIDENCE",)
    if independent_sources < 3 or weight < 2.0:
        return "medium", ("LIMITED_EVIDENCE_WINDOW",)
    return "high", ("MULTIPLE_INDEPENDENT_PERFORMANCE_SIGNALS",)


class AssessmentEvidenceExtractor:
    """Extract scored, explicitly measured performance only."""

    def extract(self, event: LearningEvent) -> list[EvidenceSignal]:
        if event.measurement_role != MeasurementRole.EXPLICIT_PERFORMANCE:
            return []
        score = event.payload.get("observed_score")
        if score is None:
            return []
        scoring = event.payload.get("scoring", {})
        factors = {
            "source_reliability": float(scoring.get("source_reliability", 0.95)),
            "grounding_confidence": float(scoring.get("grounding_confidence", 0.8)),
            "task_discrimination": float(scoring.get("task_discrimination", 0.7)),
            "independence_factor": float(scoring.get("independence_factor", 1.0)),
            "evidence_quality": float(scoring.get("evidence_quality", 0.9)),
        }
        result: list[EvidenceSignal] = []
        for concept_id in event.concept_ids:
            base = dict(
                source_event_id=event.source_event_id,
                student_key=event.student_key,
                course_key=event.course_key,
                concept_id=concept_id,
                occurred_at=event.occurred_at,
                sequence_number=event.sequence_number,
                measurement_role=event.measurement_role,
                **factors,
                derived_from=(event.event_id,),
            )
            result.append(EvidenceSignal(
                evidence_id=f"{event.event_id}:mastery", dimension=Dimension.MASTERY,
                value=_clamp(float(score)), reason_code="SCORED_EXPLICIT_PERFORMANCE", **base,
            ))
            hint_level = event.payload.get("hint_level")
            if hint_level is not None:
                result.append(EvidenceSignal(
                    evidence_id=f"{event.event_id}:independence", dimension=Dimension.INDEPENDENCE,
                    value=1.0 - _clamp(float(hint_level)), reason_code="HINT_ADJUSTED_INDEPENDENCE", **base,
                ))
                result.append(EvidenceSignal(
                    evidence_id=f"{event.event_id}:hint_dependency", dimension=Dimension.HINT_DEPENDENCY,
                    value=_clamp(float(hint_level)), reason_code="SCORED_HINT_USAGE", **base,
                ))
            if event.payload.get("is_delayed_retest"):
                result.append(EvidenceSignal(
                    evidence_id=f"{event.event_id}:stability", dimension=Dimension.STABILITY,
                    value=_clamp(float(score)), reason_code="DELAYED_RETEST", **base,
                ))
            if event.payload.get("is_transfer_task"):
                result.append(EvidenceSignal(
                    evidence_id=f"{event.event_id}:transfer", dimension=Dimension.TRANSFER,
                    value=_clamp(float(score)), reason_code="TRANSFER_TASK", **base,
                ))
        return result


class CodeEvidenceExtractor:
    """Extract granular code-run signals when test results are available."""

    def extract(self, event: LearningEvent) -> list[EvidenceSignal]:
        if event.measurement_role != MeasurementRole.EXPLICIT_PERFORMANCE:
            return []
        tests = tuple(event.payload.get("test_case_results", ()))
        if not tests:
            return []
        pass_rate = sum(bool(item.get("passed")) for item in tests) / len(tests)
        copied = bool(event.payload.get("copied_reference_solution", False))
        independence = 0.25 if copied else 1.0 - _clamp(float(event.payload.get("hint_level", 0.0)))
        recurring = _clamp(float(event.payload.get("repeated_error_ratio", 0.0)))
        strategy = event.payload.get("strategy_quality")
        recovery = event.payload.get("recovery_efficiency")
        result: list[EvidenceSignal] = []
        for concept_id in event.concept_ids:
            common = dict(
                source_event_id=event.source_event_id, student_key=event.student_key,
                course_key=event.course_key, concept_id=concept_id, occurred_at=event.occurred_at,
                sequence_number=event.sequence_number, measurement_role=event.measurement_role,
                source_reliability=0.98, grounding_confidence=_clamp(float(event.payload.get("grounding_confidence", 0.8))),
                task_discrimination=_clamp(float(event.payload.get("task_discrimination", 0.75))),
                independence_factor=independence, evidence_quality=_clamp(float(event.payload.get("evidence_quality", 0.9))),
                derived_from=(event.event_id,),
            )
            for dimension, value, reason in (
                (Dimension.MASTERY, pass_rate, "CODE_TEST_CASE_PASS_RATE"),
                (Dimension.INDEPENDENCE, independence, "CODE_INDEPENDENT_SUBMISSION"),
                (Dimension.HINT_DEPENDENCY, 1.0 - independence, "CODE_HINT_OR_REFERENCE_DEPENDENCY"),
                (Dimension.RECURRING_ERROR_RISK, recurring, "CODE_REPEATED_ERROR_PATTERN"),
            ):
                result.append(EvidenceSignal(
                    evidence_id=f"{event.event_id}:{dimension.value}", dimension=dimension,
                    value=value, reason_code=reason, **common,
                ))
            if strategy is not None:
                result.append(EvidenceSignal(
                    evidence_id=f"{event.event_id}:strategy_quality", dimension=Dimension.STRATEGY_QUALITY,
                    value=_clamp(float(strategy)), reason_code="CODE_STRATEGY_OBSERVATION", **common,
                ))
            if recovery is not None:
                result.append(EvidenceSignal(
                    evidence_id=f"{event.event_id}:recovery_efficiency", dimension=Dimension.RECOVERY_EFFICIENCY,
                    value=_clamp(float(recovery)), reason_code="CODE_REPAIR_CHAIN", **common,
                ))
        return result


class DialogueInteractionExtractor:
    """Produce separate interaction states from pre-classified dialogue facts."""

    MIN_LABEL_CONFIDENCE = 0.70

    def extract(self, event: LearningEvent) -> list[InteractionEvidence]:
        if event.measurement_role != MeasurementRole.INTERACTION_SEMANTIC:
            return []
        labels = event.payload.get("interaction_labels", {})
        resolved = event.payload.get("resolved_interaction_labels", {})
        confidence = _clamp(float(event.payload.get("classification_confidence", 0.0)))
        label_confidences = event.payload.get("interaction_label_confidences", {})
        spans_by_kind = event.payload.get("candidate_evidence_spans", {})
        model_version = str(event.payload.get("candidate_model_version", ""))
        prompt_version = str(event.payload.get("candidate_prompt_version", ""))
        classifier_policy_version = str(event.payload.get("candidate_policy_version", ""))
        result: list[InteractionEvidence] = []
        for concept_id in event.concept_ids:
            for kind in InteractionKind:
                kind_confidence = _clamp(float(label_confidences.get(kind.value, confidence)))
                if labels.get(kind.value) is True and kind_confidence >= self.MIN_LABEL_CONFIDENCE:
                    result.append(InteractionEvidence(
                        evidence_id=f"{event.event_id}:{kind.value}", source_event_id=event.source_event_id,
                        student_key=event.student_key, course_key=event.course_key, concept_id=concept_id,
                        kind=kind, label_confidence=kind_confidence, occurred_at=event.occurred_at,
                        sequence_number=event.sequence_number, reason_code=f"DIALOGUE_{kind.value.upper()}",
                        derived_from=(event.event_id,), evidence_spans=_spans_for(spans_by_kind, kind.value),
                        classifier_model_version=model_version, classifier_prompt_version=prompt_version,
                        classifier_policy_version=classifier_policy_version,
                    ))
                if resolved.get(kind.value) is True and kind_confidence >= self.MIN_LABEL_CONFIDENCE:
                    result.append(InteractionEvidence(
                        evidence_id=f"{event.event_id}:{kind.value}:resolved", source_event_id=event.source_event_id,
                        student_key=event.student_key, course_key=event.course_key, concept_id=concept_id,
                        kind=kind, label_confidence=kind_confidence, occurred_at=event.occurred_at,
                        sequence_number=event.sequence_number, reason_code=f"DIALOGUE_{kind.value.upper()}_RESOLVED",
                        polarity=-1, derived_from=(event.event_id,), evidence_spans=_spans_for(spans_by_kind, kind.value),
                        classifier_model_version=model_version, classifier_prompt_version=prompt_version,
                        classifier_policy_version=classifier_policy_version,
                    ))
        return result


class MultiSourceEvidenceEngine:
    """Deduplicate, validate and update an isolated concept state."""

    def __init__(self) -> None:
        self._assessment = AssessmentEvidenceExtractor()
        self._code = CodeEvidenceExtractor()
        self._dialogue = DialogueInteractionExtractor()

    def extract(self, events: Iterable[LearningEvent]) -> tuple[list[EvidenceSignal], list[InteractionEvidence]]:
        explicit: list[EvidenceSignal] = []
        interaction: list[InteractionEvidence] = []
        for event in events:
            if event.event_type == "code_submission":
                explicit.extend(self._code.extract(event))
            else:
                explicit.extend(self._assessment.extract(event))
            interaction.extend(self._dialogue.extract(event))
        return self._deduplicate_explicit(explicit), self._deduplicate_interaction(interaction)

    @staticmethod
    def _deduplicate_explicit(signals: Iterable[EvidenceSignal]) -> list[EvidenceSignal]:
        selected: dict[tuple[str, str, str], EvidenceSignal] = {}
        for signal in sorted(signals, key=lambda item: (item.sequence_number, item.evidence_id)):
            key = (signal.source_event_id, signal.concept_id, signal.dimension.value)
            selected.setdefault(key, signal)
        return sorted(selected.values(), key=lambda item: (item.sequence_number, item.evidence_id))

    @staticmethod
    def _deduplicate_interaction(signals: Iterable[InteractionEvidence]) -> list[InteractionEvidence]:
        selected: dict[tuple[str, str, str], InteractionEvidence] = {}
        for signal in sorted(signals, key=lambda item: (item.sequence_number, item.evidence_id)):
            selected.setdefault((signal.source_event_id, signal.concept_id, signal.kind.value, str(signal.polarity)), signal)
        return sorted(selected.values(), key=lambda item: (item.sequence_number, item.evidence_id))

    def build_state(self, *, student_key: str, course_key: str, concept_id: str,
                    explicit_signals: Iterable[EvidenceSignal], data_version: str = "synthetic-v1") -> ConceptState:
        signals = list(explicit_signals)
        mismatched = [s for s in signals if s.student_key != student_key or s.course_key != course_key or s.concept_id != concept_id]
        if mismatched:
            return self.rejected_state(student_key, course_key, concept_id, mismatched, data_version)
        signals = self._deduplicate_explicit(signals)
        cells = {dimension: BetaCell() for dimension in Dimension}
        for signal in signals:
            cells[signal.dimension] = cells[signal.dimension].update(signal, HALF_LIFE_DAYS[signal.dimension])
        by_dimension = {dimension: [s for s in signals if s.dimension == dimension] for dimension in Dimension}
        values: dict[str, float | None] = {}
        for dimension in Dimension:
            values[dimension.value] = round(cells[dimension].mean, 4) if by_dimension[dimension] else None
        mastery_signals = by_dimension[Dimension.MASTERY]
        effective_weight = round(sum(s.weight for s in mastery_signals), 4)
        confidence, confidence_reasons = _confidence(effective_weight, len({s.source_event_id for s in mastery_signals}))
        evidence_refs = tuple(s.evidence_id for s in signals)
        contributions = tuple(sorted(({
            "rule_id": signal.reason_code,
            "effect": signal.dimension.value,
            "evidence_refs": (signal.evidence_id,),
            "weight": round(signal.weight, 6),
        } for signal in signals), key=lambda item: (item["rule_id"], item["effect"], item["evidence_refs"])))
        return ConceptState(
            student_key=student_key, course_key=course_key, concept_id=concept_id, values=values,
            observed_performance_score=values[Dimension.MASTERY.value], confidence=confidence,
            effective_evidence_weight=effective_weight, evidence_refs=evidence_refs,
            derived_from=_stable_unique(ref for s in signals for ref in s.derived_from),
            reason_codes=_stable_unique(s.reason_code for s in signals),
            confidence_reasons=confidence_reasons, rule_contributions=contributions,
            policy_versions={"scoring": SCORING_POLICY_VERSION, "confidence": CONFIDENCE_POLICY_VERSION,
                             "interaction": INTERACTION_POLICY_VERSION, "recommendation": RECOMMENDATION_POLICY_VERSION},
            data_version=data_version,
        )

    @staticmethod
    def rejected_state(student_key: str, course_key: str, concept_id: str,
                       mismatched: Iterable[EvidenceSignal], data_version: str) -> ConceptState:
        mismatched = list(mismatched)
        rejected = tuple(sorted(signal.evidence_id for signal in mismatched))
        return ConceptState(
            student_key=student_key, course_key=course_key, concept_id=concept_id,
            values={dimension.value: None for dimension in Dimension}, observed_performance_score=None,
            confidence="unknown", effective_evidence_weight=0.0, evidence_refs=(), derived_from=(),
            reason_codes=("SCOPE_MISMATCH_REJECTED",), confidence_reasons=("NO_PARTIAL_RESULT_RETURNED",),
            rule_contributions=(), policy_versions={"scoring": SCORING_POLICY_VERSION,
            "confidence": CONFIDENCE_POLICY_VERSION, "interaction": INTERACTION_POLICY_VERSION,
            "recommendation": RECOMMENDATION_POLICY_VERSION}, data_version=data_version, status="rejected",
            rejected_evidence_refs=rejected,
            rejection_details={
                "expected_student_key": student_key,
                "expected_course_key": course_key,
                "actual_student_key": mismatched[0].student_key if mismatched else "",
                "actual_course_key": mismatched[0].course_key if mismatched else "",
            },
        )

    def build_interaction_state(self, *, student_key: str, course_key: str, concept_id: str,
                                interaction_signals: Iterable[InteractionEvidence]) -> InteractionState:
        signals = [s for s in self._deduplicate_interaction(interaction_signals)
                   if s.student_key == student_key and s.course_key == course_key and s.concept_id == concept_id]
        # A fixed recent window prevents a long historic dialogue from permanently
        # dominating a current instructional state.  Each retained entry already
        # represents one independent source event for this kind and polarity.
        signals = sorted(signals, key=lambda item: (item.sequence_number, item.evidence_id))[-10:]
        values: dict[str, str] = {}
        reasons: list[str] = []
        for kind in InteractionKind:
            kind_signals = [s for s in signals if s.kind == kind]
            positive = sum(signal.polarity > 0 for signal in kind_signals)
            negative = sum(signal.polarity < 0 for signal in kind_signals)
            if not kind_signals:
                values[kind.value] = "unknown"
            elif positive and negative and positive == negative:
                values[kind.value] = "unknown"
                reasons.append("CONFLICTING_INTERACTION_EVIDENCE")
            elif positive <= negative:
                values[kind.value] = "low"
            else:
                values[kind.value] = "high" if positive >= 3 else "medium" if positive == 2 else "low"
            reasons.extend(s.reason_code for s in kind_signals)
        provenance = tuple(sorted(({
            "evidence_id": signal.evidence_id,
            "source_event_id": signal.source_event_id,
            "kind": signal.kind.value,
            "label_confidence": signal.label_confidence,
            "evidence_spans": signal.evidence_spans,
            "model_version": signal.classifier_model_version,
            "prompt_version": signal.classifier_prompt_version,
            "classifier_policy_version": signal.classifier_policy_version,
        } for signal in signals), key=lambda item: (
            item["source_event_id"], item["kind"], item["evidence_id"])))
        return InteractionState(student_key, course_key, concept_id, values,
                                tuple(s.evidence_id for s in signals), _stable_unique(reasons),
                                classifier_provenance=provenance)


def _spans_for(value: Any, kind: str) -> tuple[str, ...]:
    spans = value.get(kind, ()) if isinstance(value, Mapping) else ()
    if not isinstance(spans, (list, tuple)):
        return ()
    return tuple(str(span) for span in spans if span)


class LearningPathRecommender:
    """Graph-constrained, deterministic recommendation baseline."""

    def __init__(self, graph: GraphSnapshot, weak_threshold: float = 0.60) -> None:
        self.graph = graph
        self.weak_threshold = weak_threshold

    def recommend(self, state: ConceptState, prerequisite_states: Mapping[str, ConceptState]) -> tuple[Recommendation, ...]:
        if state.status != "ok" or state.confidence in {"unknown", "low"}:
            return (self._recommend(state.concept_id, "diagnose", 1.0, ("INSUFFICIENT_EVIDENCE",), state.evidence_refs),)
        confirmed_weak = tuple(sorted(prerequisite for prerequisite in self.graph.prerequisites.get(state.concept_id, ())
                                      if self._is_confirmed_weak(prerequisite_states.get(prerequisite))))
        if confirmed_weak:
            return tuple(self._recommend(concept, "review_confirmed_weak_prerequisite", 0.95,
                                         ("CONFIRMED_WEAK_PREREQUISITE",), prerequisite_states[concept].evidence_refs)
                         for concept in confirmed_weak)
        value = state.values
        recommendations: list[Recommendation] = []
        if (value.get(Dimension.RECURRING_ERROR_RISK.value) or 0.0) >= 0.60:
            recommendations.append(self._recommend(state.concept_id, "misconception_repair", 0.90, ("RECURRING_ERROR_RISK",), state.evidence_refs))
        if (value.get(Dimension.HINT_DEPENDENCY.value) or 0.0) >= 0.60:
            recommendations.append(self._recommend(state.concept_id, "fade_hints_practice", 0.85, ("HIGH_HINT_DEPENDENCY",), state.evidence_refs))
        if (value.get(Dimension.TRANSFER.value) is not None and value[Dimension.TRANSFER.value] < 0.50 and
                (state.observed_performance_score or 0.0) >= 0.70):
            recommendations.append(self._recommend(state.concept_id, "transfer_practice", 0.80, ("TRANSFER_EVIDENCE_LOW",), state.evidence_refs))
        if (value.get(Dimension.STABILITY.value) is not None and value[Dimension.STABILITY.value] < 0.50 and
                (state.observed_performance_score or 0.0) >= 0.65):
            recommendations.append(self._recommend(state.concept_id, "spaced_review", 0.75, ("STABILITY_EVIDENCE_LOW",), state.evidence_refs))
        return tuple(sorted(recommendations or [self._recommend(state.concept_id, "continue", 0.10, ("NO_CONFIRMED_GAP",), state.evidence_refs)],
                            key=lambda item: (-item.priority, item.action_type, item.concept_id)))

    def _is_confirmed_weak(self, state: ConceptState | None) -> bool:
        return bool(state and state.status == "ok" and state.confidence in {"medium", "high"} and
                    state.observed_performance_score is not None and state.observed_performance_score < self.weak_threshold)

    def _recommend(self, concept_id: str, action: str, priority: float, reasons: tuple[str, ...], refs: tuple[str, ...]) -> Recommendation:
        return Recommendation(concept_id=concept_id, action_type=action, priority=priority,
                              reason_codes=reasons, evidence_refs=refs,
                              resource_ids=tuple(sorted(self.graph.resources.get(concept_id, ()))) )
