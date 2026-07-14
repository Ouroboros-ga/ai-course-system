"""
Evidence aggregation rules and engine.

Aggregates LearningEvents into LearningEvidence according to
declarative EvidenceAggregationRule definitions.

Version: 1.0
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .event import EventType, LearningEvent
from .evidence import (
    EvidenceAggregationRule,
    EvidenceType,
    LearningEvidence,
)


# =========================================================================
# Built-in aggregation rules
# =========================================================================

#: Default aggregation rules that ship with the system.
DEFAULT_AGGREGATION_RULES: List[EvidenceAggregationRule] = [
    EvidenceAggregationRule(
        rule_id="node-completion-rate",
        name="Node completion rate",
        description="Aggregate node completion events into completion evidence",
        evidence_type=EvidenceType.NODE_COMPLETION,
        min_events=1,
        aggregation_method="rate",
        source="aggregation",
    ),
    EvidenceAggregationRule(
        rule_id="quiz-accuracy-window",
        name="Quiz accuracy over window",
        description="Aggregate quiz correct/incorrect events into accuracy evidence",
        evidence_type=EvidenceType.QUIZ_ACCURACY,
        min_events=1,
        window_seconds=None,  # no window limit
        aggregation_method="rate",
        source="aggregation",
    ),
    EvidenceAggregationRule(
        rule_id="quiz-pattern-repeated-errors",
        name="Repeated quiz error patterns",
        description="Detect repeated incorrect answers for the same question",
        evidence_type=EvidenceType.QUIZ_PATTERN,
        min_events=2,
        aggregation_method="pattern",
        source="aggregation",
    ),
    EvidenceAggregationRule(
        rule_id="engagement-access-frequency",
        name="Engagement from access frequency",
        description="Measure engagement from node access events",
        evidence_type=EvidenceType.ENGAGEMENT,
        min_events=1,
        aggregation_method="count",
        source="aggregation",
    ),
    EvidenceAggregationRule(
        rule_id="prereq-gap-evidence",
        name="Prerequisite gap evidence",
        description="Aggregate prerequisite gap detection events",
        evidence_type=EvidenceType.PREREQ_GAP,
        min_events=1,
        aggregation_method="count",
        source="aggregation",
    ),
    EvidenceAggregationRule(
        rule_id="prereq-recovery-evidence",
        name="Prerequisite recovery evidence",
        description="Aggregate prerequisite jump return events",
        evidence_type=EvidenceType.PREREQ_RECOVERY,
        min_events=1,
        aggregation_method="count",
        source="aggregation",
    ),
]


# =========================================================================
# Aggregation functions
# =========================================================================


def _aggregate_count(
    events: List[LearningEvent],
    rule: EvidenceAggregationRule,
) -> Optional[LearningEvidence]:
    """Simple count aggregation: count matching events."""
    if not events:
        return None
    return LearningEvidence(
        evidence_type=rule.evidence_type,
        student_id=events[0].student_id,
        course_id=events[0].course_id,
        event_refs=[e.event_id for e in events],
        confidence=min(1.0, len(events) / 10.0),  # more events = higher confidence
        value=float(len(events)),
        label=rule.name,
        description=(
            f"{len(events)} event(s) matched rule '{rule.rule_id}'"
        ),
        source=rule.source,
        metadata={
            "rule_id": rule.rule_id,
            "aggregation_method": "count",
            "event_count": len(events),
        },
    )


def _aggregate_rate(
    events: List[LearningEvent],
    rule: EvidenceAggregationRule,
    type_a: EventType,
    type_b: EventType,
    label_a: str = "positive",
    label_b: str = "total",
) -> Optional[LearningEvidence]:
    """Rate aggregation: count of type_a / (count of type_a + type_b)."""
    if not events:
        return None
    count_a = sum(1 for e in events if e.event_type == type_a)
    count_b = sum(1 for e in events if e.event_type == type_b)
    total = count_a + count_b
    if total == 0:
        return None
    rate = count_a / total
    confidence = min(1.0, total / 5.0)

    return LearningEvidence(
        evidence_type=rule.evidence_type,
        student_id=events[0].student_id,
        course_id=events[0].course_id,
        event_refs=[e.event_id for e in events],
        confidence=confidence,
        value=round(rate, 4),
        label=rule.name,
        description=(
            f"{count_a}/{total} {label_a} events "
            f"(rate={rate:.2f}) via rule '{rule.rule_id}'"
        ),
        source=rule.source,
        metadata={
            "rule_id": rule.rule_id,
            "aggregation_method": "rate",
            f"{label_a}_count": count_a,
            f"{label_b}_count": total,
            "rate": rate,
        },
    )


def _aggregate_quiz_accuracy(
    events: List[LearningEvent],
    rule: EvidenceAggregationRule,
) -> Optional[LearningEvidence]:
    """Quiz accuracy aggregation.

    Accuracy is derived from the ``is_correct`` metadata carried on quiz
    answer events, not from distinct QUIZ_CORRECT/QUIZ_INCORRECT event
    types.  A quiz event counts as "answered" when it is a QUIZ_ANSWERED
    event (the canonical recorded answer); it counts as "correct" when
    its ``is_correct`` metadata is ``True``.  Standalone QUIZ_CORRECT and
    QUIZ_INCORRECT events (without an ``is_correct`` flag) do not change
    the answered denominator, so they cannot inflate or deflate accuracy.

    This keeps accuracy = correct / answered stable and explainable, and
    matches the contract that an answer is an observation recorded with an
    explicit correctness flag.
    """
    answered_events = [e for e in events if e.event_type == EventType.QUIZ_ANSWERED]
    if not answered_events:
        return None
    correct_count = sum(
        1 for e in answered_events if e.metadata.get("is_correct") is True
    )
    answered_count = len(answered_events)
    rate = correct_count / answered_count
    confidence = min(1.0, answered_count / 5.0)

    return LearningEvidence(
        evidence_type=rule.evidence_type,
        student_id=events[0].student_id,
        course_id=events[0].course_id,
        event_refs=[e.event_id for e in answered_events],
        confidence=confidence,
        value=round(rate, 4),
        label=rule.name,
        description=(
            f"{correct_count}/{answered_count} correct answered events "
            f"(rate={rate:.2f}) via rule '{rule.rule_id}'"
        ),
        source=rule.source,
        metadata={
            "rule_id": rule.rule_id,
            "aggregation_method": "rate",
            "correct_count": correct_count,
            "answered_count": answered_count,
            "rate": rate,
        },
    )


def _aggregate_pattern(
    events: List[LearningEvent],
    rule: EvidenceAggregationRule,
) -> Optional[LearningEvidence]:
    """Pattern aggregation: detect repeated events with similar metadata."""
    if not events:
        return None

    # Look for repeated question patterns in quiz events
    question_counter: Counter = Counter()
    for e in events:
        qid = e.metadata.get("quiz_id") or e.metadata.get("question", "")
        if qid:
            question_counter[qid] += 1

    repeated = {qid: count for qid, count in question_counter.items() if count >= 2}

    if not repeated:
        return None

    return LearningEvidence(
        evidence_type=rule.evidence_type,
        student_id=events[0].student_id,
        course_id=events[0].course_id,
        event_refs=[e.event_id for e in events],
        confidence=min(1.0, len(repeated) / 3.0),
        value=float(len(repeated)),
        label=rule.name,
        description=(
            f"Found {len(repeated)} repeated pattern(s) via rule '{rule.rule_id}': "
            + "; ".join(f"'{q}' x{c}" for q, c in list(repeated.items())[:5])
        ),
        source=rule.source,
        metadata={
            "rule_id": rule.rule_id,
            "aggregation_method": "pattern",
            "repeated_questions": dict(list(repeated.items())[:20]),
            "total_events": len(events),
        },
    )


# =========================================================================
# Main aggregation function
# =========================================================================


def aggregate_evidence(
    events: List[LearningEvent],
    rules: Optional[List[EvidenceAggregationRule]] = None,
) -> List[LearningEvidence]:
    """Aggregate a list of LearningEvents into LearningEvidence.

    Parameters
    ----------
    events : list of LearningEvent
        The events to aggregate.
    rules : list of EvidenceAggregationRule or None
        Rules to apply. Uses DEFAULT_AGGREGATION_RULES if None.

    Returns
    -------
    list of LearningEvidence
    """
    if rules is None:
        rules = DEFAULT_AGGREGATION_RULES

    # Group events by (student_id, course_id)
    groups: Dict[Tuple[int, int], List[LearningEvent]] = {}
    for event in events:
        key = (event.student_id, event.course_id)
        groups.setdefault(key, []).append(event)

    all_evidence: List[LearningEvidence] = []

    for (student_id, course_id), group_events in groups.items():
        for rule in rules:
            evidence = _apply_rule(rule, group_events)
            if evidence is not None:
                all_evidence.append(evidence)

    return all_evidence


def _apply_rule(
    rule: EvidenceAggregationRule,
    events: List[LearningEvent],
) -> Optional[LearningEvidence]:
    """Apply a single aggregation rule to a group of events."""
    if len(events) < rule.min_events:
        return None

    # Filter events within time window if specified
    filtered = events
    if rule.window_seconds is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=rule.window_seconds)
        filtered = [
            e
            for e in events
            if _parse_timestamp(e.timestamp) >= cutoff
        ]
        if len(filtered) < rule.min_events:
            return None

    if rule.aggregation_method == "count":
        return _aggregate_count(filtered, rule)

    elif rule.aggregation_method == "rate":
        # Rate rules dispatch by evidence type
        if rule.evidence_type == EvidenceType.NODE_COMPLETION:
            return _aggregate_rate(
                filtered, rule,
                type_a=EventType.NODE_COMPLETED,
                type_b=EventType.NODE_ACCESSED,
                label_a="completed", label_b="accessed",
            )
        elif rule.evidence_type == EvidenceType.QUIZ_ACCURACY:
            return _aggregate_quiz_accuracy(filtered, rule)
        else:
            return _aggregate_count(filtered, rule)

    elif rule.aggregation_method == "pattern":
        return _aggregate_pattern(filtered, rule)

    else:
        # Fallback: count
        return _aggregate_count(filtered, rule)


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string, returning epoch on failure."""
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


class EvidenceAggregator:
    """Convenience class for aggregating events into evidence.

    Usage::

        aggregator = EvidenceAggregator()
        evidence = aggregator.aggregate(event_list)
    """

    def __init__(
        self,
        rules: Optional[List[EvidenceAggregationRule]] = None,
    ):
        self.rules = rules or DEFAULT_AGGREGATION_RULES

    def aggregate(self, events: List[LearningEvent]) -> List[LearningEvidence]:
        """Aggregate events into evidence using configured rules."""
        return aggregate_evidence(events, rules=self.rules)
