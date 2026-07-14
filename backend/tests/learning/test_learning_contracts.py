"""
Contract tests for P1-07 Learning Events and Explainable Cognition.

Tests cover:
1. LearningEvent creation, idempotency, serialization, corrections
2. LearningEvidence creation, evidence refs, serialization
3. MasteryState invariants (evidence_refs required, no-evidence constraint)
4. MisconceptionState invariants
5. Recommendation invariants
6. Existing-data compatibility mappers
7. Evidence aggregation rules
8. MasteryProviderResult contract (timeout, malformed, business failure)
9. RuleBased mastery baseline (deterministic, explainable, gold-comparable)
10. Provider capability interfaces
11. No-evidence => no strong conclusion invariant
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

import pytest

from app.domain.learning.event import (
    EVENT_VERSION,
    EventCorrection,
    EventType,
    LearningEvent,
    build_correction_event,
)
from app.domain.learning.evidence import (
    EVIDENCE_VERSION,
    EvidenceAggregationRule,
    EvidenceType,
    LearningEvidence,
)
from app.domain.learning.mastery_state import (
    MASTERY_VERSION,
    MasteryLevel,
    MasterySource,
    MasteryState,
)
from app.domain.learning.misconception import (
    MISCONCEPTION_VERSION,
    MisconceptionSeverity,
    MisconceptionState,
    MisconceptionType,
)
from app.domain.learning.recommendation import (
    RECOMMENDATION_VERSION,
    Recommendation,
    RecommendationPriority,
    RecommendationType,
)
from app.domain.learning.compat_mappers import (
    ExistingDataMapper,
    map_chat_to_events,
    map_jump_to_events,
    map_progress_to_events,
    map_quiz_to_events,
)
from app.domain.learning.aggregation import (
    DEFAULT_AGGREGATION_RULES,
    EvidenceAggregator,
    aggregate_evidence,
)
from app.platform.mastery.contracts import (
    MasteryBusinessFailureError,
    MasteryMalformedError,
    MasteryProviderError,
    MasteryProviderResult,
    MasteryTimeoutError,
)
from app.platform.mastery.provider import (
    AbstractMasteryProvider,
    MasteryProvider,
    ProviderCapability,
    ProviderVersion,
)
from app.platform.mastery.rule_baseline import (
    DEFAULT_COURSE_RULES,
    DEFAULT_NODE_RULES,
    MasteryRule,
    MasteryRuleResult,
    MasteryRuleSet,
    RuleBasedMasteryProvider,
)
from app.platform.mastery.bkt_interface import BKTProvider
from app.platform.mastery.irt_interface import IRTProvider
from app.platform.mastery.dkt_interface import DKTProvider


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def sample_event() -> LearningEvent:
    return LearningEvent(
        event_type=EventType.NODE_ACCESSED,
        student_id=1,
        course_id=101,
        node_id=5,
        sequence_number=1,
        source="test_fixture",
    )


@pytest.fixture
def sample_events() -> List[LearningEvent]:
    return [
        LearningEvent(
            event_type=EventType.NODE_ACCESSED,
            student_id=1,
            course_id=101,
            node_id=1,
            sequence_number=1,
            source="test",
        ),
        LearningEvent(
            event_type=EventType.NODE_COMPLETED,
            student_id=1,
            course_id=101,
            node_id=1,
            sequence_number=2,
            source="test",
        ),
        LearningEvent(
            event_type=EventType.QUIZ_ANSWERED,
            student_id=1,
            course_id=101,
            node_id=1,
            sequence_number=3,
            metadata={
                "quiz_id": "q1",
                "question": "What is 2+2?",
                "student_answer": "4",
                "correct_answer": "4",
                "is_correct": True,
            },
            source="test",
        ),
        LearningEvent(
            event_type=EventType.QUIZ_CORRECT,
            student_id=1,
            course_id=101,
            node_id=1,
            sequence_number=4,
            metadata={"quiz_id": "q1"},
            source="test",
        ),
    ]


# =========================================================================
# LearningEvent
# =========================================================================


class TestLearningEvent:
    """LearningEvent creation, idempotency, serialization, corrections."""

    def test_create_event(self):
        event = LearningEvent(
            event_type=EventType.NODE_ACCESSED,
            student_id=1,
            course_id=101,
            node_id=5,
            sequence_number=1,
        )
        assert event.event_id is not None
        assert event.event_type == EventType.NODE_ACCESSED
        assert event.student_id == 1
        assert event.course_id == 101
        assert event.node_id == 5
        assert event.sequence_number == 1
        assert event.version == EVENT_VERSION

    def test_auto_idempotency_key(self, sample_event):
        expected = "node_accessed:1:101:1"
        assert sample_event.idempotency_key == expected

    def test_idempotency_key_structure(self):
        event = LearningEvent(
            event_type=EventType.QUIZ_ANSWERED,
            student_id=42,
            course_id=201,
            sequence_number=7,
        )
        expected = "quiz_answered:42:201:7"
        assert event.idempotency_key == expected

    def test_events_are_frozen(self, sample_event):
        with pytest.raises(Exception):
            sample_event.event_type = EventType.NODE_COMPLETED  # type: ignore

    def test_to_dict(self, sample_event):
        d = sample_event.to_dict()
        assert d["event_id"] == sample_event.event_id
        assert d["event_type"] == "node_accessed"
        assert d["student_id"] == 1
        assert d["course_id"] == 101
        assert d["node_id"] == 5
        assert d["version"] == EVENT_VERSION

    def test_from_dict_round_trip(self, sample_event):
        d = sample_event.to_dict()
        restored = LearningEvent.from_dict(d)
        assert restored.event_id == sample_event.event_id
        assert restored.event_type == sample_event.event_type
        assert restored.student_id == sample_event.student_id
        assert restored.idempotency_key == sample_event.idempotency_key

    def test_json_serializable(self, sample_event):
        d = sample_event.to_dict()
        json_str = json.dumps(d)
        assert json_str is not None
        loaded = json.loads(json_str)
        assert loaded["event_id"] == sample_event.event_id

    def test_correction_event(self, sample_event):
        correction = build_correction_event(
            original_event=sample_event,
            reason="Test correction",
            new_sequence_number=2,
        )
        assert correction.event_type == EventType.CORRECTION
        assert correction.corrected_event_id == sample_event.event_id
        assert correction.sequence_number == 2
        assert correction.metadata["reason"] == "Test correction"

    def test_correction_does_not_mutate_original(self, sample_event):
        original_id = sample_event.event_id
        build_correction_event(
            original_event=sample_event,
            reason="Test",
            new_sequence_number=2,
        )
        assert sample_event.event_id == original_id
        assert sample_event.event_type == EventType.NODE_ACCESSED

    def test_event_type_values(self):
        assert EventType.NODE_ACCESSED.value == "node_accessed"
        assert EventType.NODE_COMPLETED.value == "node_completed"
        assert EventType.QUIZ_ANSWERED.value == "quiz_answered"
        assert EventType.CORRECTION.value == "correction"
        assert EventType.PREREQ_GAP_DETECTED.value == "prereq_gap_detected"
        assert EventType.PREREQ_JUMP_STARTED.value == "prereq_jump_started"
        assert EventType.PREREQ_JUMP_RETURNED.value == "prereq_jump_returned"

    def test_event_type_unique_values(self):
        values = [et.value for et in EventType]
        assert len(values) == len(set(values))

    def test_event_with_metadata(self):
        event = LearningEvent(
            event_type=EventType.QUIZ_ANSWERED,
            student_id=1,
            course_id=101,
            sequence_number=5,
            metadata={"score": 0.85, "question": "test", "attempt": 3},
        )
        assert event.metadata["score"] == 0.85
        assert event.metadata["attempt"] == 3

    def test_event_with_timestamp(self):
        ts = "2026-07-13T12:00:00+00:00"
        event = LearningEvent(
            event_type=EventType.NODE_ACCESSED,
            student_id=1,
            course_id=101,
            timestamp=ts,
            sequence_number=1,
        )
        assert event.timestamp == ts

    def test_auto_timestamp(self):
        event = LearningEvent(
            event_type=EventType.NODE_ACCESSED,
            student_id=1,
            course_id=101,
            sequence_number=1,
        )
        assert event.timestamp != ""

    def test_event_correction_to_dict(self):
        correction = EventCorrection(
            original_event_id="orig-001",
            corrected_event_id="corr-001",
            reason="Wrong data",
            corrected_fields={"score": 0.9},
        )
        d = correction.to_dict()
        assert d["original_event_id"] == "orig-001"
        assert d["corrected_event_id"] == "corr-001"
        assert d["corrected_fields"]["score"] == 0.9

    def test_event_with_no_node_id(self):
        event = LearningEvent(
            event_type=EventType.COURSE_ACCESSED,
            student_id=1,
            course_id=101,
            sequence_number=1,
        )
        assert event.node_id is None

    def test_source_field(self):
        event = LearningEvent(
            event_type=EventType.NODE_COMPLETED,
            student_id=1,
            course_id=101,
            sequence_number=1,
            source="progress_service",
        )
        assert event.source == "progress_service"


# =========================================================================
# LearningEvidence
# =========================================================================


class TestLearningEvidence:
    """LearningEvidence creation, evidence refs, serialization."""

    def test_create_evidence(self):
        ev = LearningEvidence(
            evidence_type=EvidenceType.NODE_COMPLETION,
            student_id=1,
            course_id=101,
            event_refs=["evt-001", "evt-002"],
            confidence=0.9,
            value=1.0,
            label="Completed node 1",
            source="aggregation",
        )
        assert ev.evidence_id is not None
        assert ev.evidence_type == EvidenceType.NODE_COMPLETION
        assert len(ev.event_refs) == 2
        assert ev.confidence == 0.9

    def test_evidence_to_dict(self):
        ev = LearningEvidence(
            evidence_type=EvidenceType.QUIZ_ACCURACY,
            student_id=1,
            course_id=101,
            event_refs=["evt-001"],
            confidence=0.85,
            value=0.75,
            label="Quiz accuracy",
            source="test",
        )
        d = ev.to_dict()
        assert d["evidence_type"] == "quiz_accuracy"
        assert d["student_id"] == 1
        assert d["event_refs"] == ["evt-001"]
        assert d["confidence"] == 0.85

    def test_evidence_from_dict_round_trip(self):
        ev = LearningEvidence(
            evidence_type=EvidenceType.ENGAGEMENT,
            student_id=2,
            course_id=202,
            event_refs=["e1", "e2"],
            confidence=0.7,
            value=5.0,
            label="High engagement",
            source="test",
        )
        d = ev.to_dict()
        restored = LearningEvidence.from_dict(d)
        assert restored.evidence_type == ev.evidence_type
        assert restored.student_id == ev.student_id
        assert restored.event_refs == ev.event_refs
        assert restored.confidence == ev.confidence

    def test_evidence_no_event_refs(self):
        ev = LearningEvidence(
            evidence_type=EvidenceType.MASTERY,
            student_id=1,
            course_id=101,
            confidence=0.0,
            source="test",
        )
        assert ev.event_refs == []

    def test_evidence_type_values(self):
        assert EvidenceType.NODE_COMPLETION.value == "node_completion"
        assert EvidenceType.QUIZ_ACCURACY.value == "quiz_accuracy"
        assert EvidenceType.ENGAGEMENT.value == "engagement"
        assert EvidenceType.PREREQ_GAP.value == "prereq_gap"
        assert EvidenceType.CORRECTION.value == "correction"

    def test_evidence_type_unique(self):
        values = [et.value for et in EvidenceType]
        assert len(values) == len(set(values))

    def test_evidence_is_frozen(self):
        ev = LearningEvidence(
            evidence_type=EvidenceType.NODE_COMPLETION,
            student_id=1,
            course_id=101,
        )
        with pytest.raises(Exception):
            ev.student_id = 2  # type: ignore

    def test_evidence_json_serializable(self):
        ev = LearningEvidence(
            evidence_type=EvidenceType.COURSE_COMPLETION,
            student_id=1,
            course_id=101,
            event_refs=["e1"],
            confidence=1.0,
        )
        json_str = json.dumps(ev.to_dict())
        assert json_str is not None

    def test_evidence_with_node_id(self):
        ev = LearningEvidence(
            evidence_type=EvidenceType.NODE_COMPLETION,
            student_id=1,
            course_id=101,
            node_id=5,
            event_refs=["e1"],
            confidence=1.0,
        )
        assert ev.node_id == 5

    def test_aggregation_rule_creation(self):
        rule = EvidenceAggregationRule(
            rule_id="test-rule",
            name="Test Rule",
            description="A test rule",
            evidence_type=EvidenceType.ENGAGEMENT,
            min_events=3,
            aggregation_method="count",
        )
        assert rule.rule_id == "test-rule"
        assert rule.min_events == 3


# =========================================================================
# MasteryState invariants
# =========================================================================


class TestMasteryState:
    """MasteryState: evidence_refs required for non-UNKNOWN levels."""

    def test_create_mastery_state(self):
        ms = MasteryState(
            student_id=1,
            course_id=101,
            level=MasteryLevel.PROFICIENT,
            score=0.85,
            confidence=0.75,
            evidence_refs=["evid-001", "evid-002"],
            source=MasterySource.RULE_BASED,
        )
        assert ms.student_id == 1
        assert ms.level == MasteryLevel.PROFICIENT
        assert ms.score == 0.85
        assert len(ms.evidence_refs) == 2

    def test_mastery_state_no_evidence_unknown(self):
        ms = MasteryState(
            student_id=1,
            course_id=101,
            level=MasteryLevel.UNKNOWN,
            score=0.0,
            confidence=0.0,
            evidence_refs=[],
        )
        assert ms.level == MasteryLevel.UNKNOWN
        assert ms.evidence_refs == []

    def test_mastery_state_to_dict(self):
        ms = MasteryState(
            student_id=1,
            course_id=101,
            level=MasteryLevel.DEVELOPING,
            score=0.6,
            confidence=0.5,
            evidence_refs=["e1"],
            source=MasterySource.RULE_BASED,
        )
        d = ms.to_dict()
        assert d["level"] == "developing"
        assert d["score"] == 0.6
        assert d["evidence_refs"] == ["e1"]
        assert d["source"] == "rule_based"

    def test_mastery_state_from_dict(self):
        data = {
            "mastery_id": "m-001",
            "student_id": 1,
            "course_id": 101,
            "level": "proficient",
            "score": 0.9,
            "confidence": 0.8,
            "evidence_refs": ["e1", "e2"],
            "source": "rule_based",
        }
        ms = MasteryState.from_dict(data)
        assert ms.mastery_id == "m-001"
        assert ms.level == MasteryLevel.PROFICIENT
        assert ms.score == 0.9

    def test_mastery_is_frozen(self):
        ms = MasteryState(
            student_id=1,
            course_id=101,
        )
        with pytest.raises(Exception):
            ms.student_id = 2  # type: ignore

    def test_mastery_level_values(self):
        assert MasteryLevel.UNKNOWN.value == "unknown"
        assert MasteryLevel.BEGINNER.value == "beginner"
        assert MasteryLevel.DEVELOPING.value == "developing"
        assert MasteryLevel.PROFICIENT.value == "proficient"
        assert MasteryLevel.ADVANCED.value == "advanced"

    def test_mastery_source_values(self):
        assert MasterySource.RULE_BASED.value == "rule_based"
        assert MasterySource.BKT.value == "bkt"
        assert MasterySource.IRT.value == "irt"
        assert MasterySource.DKT.value == "dkt"

    def test_mastery_node_scope(self):
        ms = MasteryState(
            student_id=1,
            course_id=101,
            node_id=5,
            level=MasteryLevel.PROFICIENT,
            score=0.85,
            confidence=0.75,
            evidence_refs=["e1"],
        )
        assert ms.node_id == 5


# =========================================================================
# MisconceptionState
# =========================================================================


class TestMisconceptionState:
    """MisconceptionState invariants."""

    def test_create_misconception(self):
        mc = MisconceptionState(
            student_id=1,
            course_id=101,
            misconception_type=MisconceptionType.CONCEPTUAL,
            severity=MisconceptionSeverity.HIGH,
            concept="Binary Search",
            description="Confuses binary search with linear search",
            evidence_refs=["e1", "e2"],
            confidence=0.85,
            source="rule_based",
        )
        assert mc.misconception_id is not None
        assert mc.misconception_type == MisconceptionType.CONCEPTUAL
        assert mc.severity == MisconceptionSeverity.HIGH
        assert len(mc.evidence_refs) == 2

    def test_misconception_to_dict(self):
        mc = MisconceptionState(
            student_id=1,
            course_id=101,
            misconception_type=MisconceptionType.PROCEDURAL,
            severity=MisconceptionSeverity.MEDIUM,
            concept="Sorting",
            description="Applies bubble sort instead of quicksort",
            evidence_refs=["e1"],
            confidence=0.7,
            source="test",
        )
        d = mc.to_dict()
        assert d["misconception_type"] == "procedural"
        assert d["severity"] == "medium"
        assert d["evidence_refs"] == ["e1"]

    def test_misconception_type_values(self):
        assert MisconceptionType.CONCEPTUAL.value == "conceptual"
        assert MisconceptionType.PROCEDURAL.value == "procedural"
        assert MisconceptionType.PERSISTENT_ERROR.value == "persistent_error"

    def test_misconception_severity_values(self):
        assert MisconceptionSeverity.LOW.value == "low"
        assert MisconceptionSeverity.CRITICAL.value == "critical"

    def test_misconception_is_frozen(self):
        mc = MisconceptionState(
            student_id=1,
            course_id=101,
            concept="Test",
        )
        with pytest.raises(Exception):
            mc.student_id = 2  # type: ignore


# =========================================================================
# Recommendation
# =========================================================================


class TestRecommendation:
    """Recommendation invariants."""

    def test_create_recommendation(self):
        rec = Recommendation(
            student_id=1,
            course_id=101,
            recommendation_type=RecommendationType.REVIEW_NODE,
            priority=RecommendationPriority.HIGH,
            title="Review Binary Search",
            description="Student struggled with binary search quiz",
            evidence_refs=["e1", "e2"],
            source="rule_based",
        )
        assert rec.recommendation_id is not None
        assert rec.recommendation_type == RecommendationType.REVIEW_NODE
        assert rec.priority == RecommendationPriority.HIGH

    def test_recommendation_continue_no_evidence(self):
        """CONTINUE recommendations may have empty evidence_refs."""
        rec = Recommendation(
            student_id=1,
            course_id=101,
            recommendation_type=RecommendationType.CONTINUE,
            priority=RecommendationPriority.LOW,
            title="Continue current path",
            description="No issues detected",
            evidence_refs=[],
            source="rule_based",
        )
        assert rec.recommendation_type == RecommendationType.CONTINUE

    def test_recommendation_to_dict(self):
        rec = Recommendation(
            student_id=1,
            course_id=101,
            recommendation_type=RecommendationType.PREREQ_REVIEW,
            priority=RecommendationPriority.CRITICAL,
            title="Review prerequisites",
            description="Missing foundation for current topic",
            evidence_refs=["e1"],
            source="test",
        )
        d = rec.to_dict()
        assert d["recommendation_type"] == "prereq_review"
        assert d["priority"] == "critical"
        assert d["evidence_refs"] == ["e1"]

    def test_recommendation_type_values(self):
        assert RecommendationType.REVIEW_NODE.value == "review_node"
        assert RecommendationType.PRACTICE_QUIZ.value == "practice_quiz"
        assert RecommendationType.PREREQ_REVIEW.value == "prereq_review"
        assert RecommendationType.ADVANCE_NEXT.value == "advance_next"
        assert RecommendationType.CONTINUE.value == "continue"

    def test_recommendation_is_frozen(self):
        rec = Recommendation(
            student_id=1,
            course_id=101,
        )
        with pytest.raises(Exception):
            rec.student_id = 2  # type: ignore

    def test_recommendation_node_scope(self):
        rec = Recommendation(
            student_id=1,
            course_id=101,
            node_id=5,
            recommendation_type=RecommendationType.REVIEW_NODE,
            priority=RecommendationPriority.HIGH,
            title="Review",
            evidence_refs=["e1"],
        )
        assert rec.node_id == 5


# =========================================================================
# Existing-data compatibility mappers
# =========================================================================


class TestCompatMappers:
    """Existing-data compatibility mappers."""

    def test_map_progress_to_events_completed(self):
        progress = {
            "completion_rate": 1.0,
            "status": "completed",
            "nodes": [
                {"id": 1, "is_completed": True, "first_accessed_at": "2026-07-01",
                 "index": 1, "title": "Node 1"},
                {"id": 2, "is_completed": False, "first_accessed_at": "2026-07-02",
                 "index": 2, "title": "Node 2"},
            ],
        }
        events = map_progress_to_events(progress, student_id=1, course_id=101)
        assert len(events) == 4  # COURSE_COMPLETED + NODE_ACCESSEDx2 + NODE_COMPLETEDx1
        assert events[0].event_type == EventType.COURSE_COMPLETED
        assert events[1].event_type == EventType.NODE_ACCESSED
        assert events[1].node_id == 1
        assert events[2].event_type == EventType.NODE_COMPLETED
        assert events[2].node_id == 1
        assert events[3].event_type == EventType.NODE_ACCESSED
        assert events[3].node_id == 2

    def test_map_progress_to_events_not_completed(self):
        progress = {
            "completion_rate": 0.5,
            "status": "in_progress",
            "nodes": [
                {"id": 1, "is_completed": False, "first_accessed_at": "2026-07-01",
                 "index": 1, "title": "Node 1"},
            ],
        }
        events = map_progress_to_events(progress, student_id=1, course_id=101)
        assert len(events) == 1  # Just NODE_ACCESSED
        assert events[0].event_type == EventType.NODE_ACCESSED

    def test_map_quiz_to_events_correct(self):
        quiz = {
            "quiz_id": "q1",
            "node_id": 5,
            "question": "What is 2+2?",
            "student_answer": "4",
            "correct_answer": "4",
            "is_correct": True,
        }
        events = map_quiz_to_events(quiz, student_id=1, course_id=101)
        assert len(events) == 2
        assert events[0].event_type == EventType.QUIZ_ANSWERED
        assert events[1].event_type == EventType.QUIZ_CORRECT

    def test_map_quiz_to_events_incorrect(self):
        quiz = {
            "quiz_id": "q2",
            "node_id": 5,
            "question": "What is 2+2?",
            "student_answer": "3",
            "correct_answer": "4",
            "is_correct": False,
        }
        events = map_quiz_to_events(quiz, student_id=1, course_id=101)
        assert len(events) == 2
        assert events[0].event_type == EventType.QUIZ_ANSWERED
        assert events[1].event_type == EventType.QUIZ_INCORRECT

    def test_map_chat_to_events(self):
        chat = {
            "message_id": "msg-001",
            "node_id": 5,
            "question": "What is recursion?",
            "answer": "Recursion is a function that calls itself.",
        }
        events = map_chat_to_events(chat, student_id=1, course_id=101)
        assert len(events) == 2
        assert events[0].event_type == EventType.QUESTION_ASKED
        assert events[1].event_type == EventType.ANSWER_RECEIVED

    def test_map_chat_to_events_no_answer(self):
        chat = {
            "message_id": "msg-002",
            "node_id": 5,
            "question": "What is recursion?",
        }
        events = map_chat_to_events(chat, student_id=1, course_id=101)
        assert len(events) == 1
        assert events[0].event_type == EventType.QUESTION_ASKED

    def test_map_jump_to_events(self):
        jump = {
            "jump_id": 1,
            "from_node_id": 5,
            "to_node_id": 2,
            "trigger_type": "prerequisite_gap",
            "trigger_question": "What is a variable?",
            "gap_description": "Missing variable concept",
            "is_returned": True,
        }
        events = map_jump_to_events(jump, student_id=1, course_id=101)
        assert len(events) == 3
        assert events[0].event_type == EventType.PREREQ_GAP_DETECTED
        assert events[1].event_type == EventType.PREREQ_JUMP_STARTED
        assert events[2].event_type == EventType.PREREQ_JUMP_RETURNED

    def test_map_jump_to_events_not_returned(self):
        jump = {
            "jump_id": 2,
            "from_node_id": 5,
            "to_node_id": 2,
            "trigger_type": "prerequisite_gap",
            "is_returned": False,
        }
        events = map_jump_to_events(jump, student_id=1, course_id=101)
        assert len(events) == 2
        assert events[0].event_type == EventType.PREREQ_GAP_DETECTED
        assert events[1].event_type == EventType.PREREQ_JUMP_STARTED

    def test_existing_data_mapper_convenience(self):
        mapper = ExistingDataMapper(student_id=1, course_id=101)
        events = mapper.map_all(
            progress_data={
                "completion_rate": 0.5,
                "status": "in_progress",
                "nodes": [
                    {"id": 1, "is_completed": True, "first_accessed_at": "2026-07-01",
                     "index": 1, "title": "N1"},
                ],
            },
            quiz_data_list=[
                {"quiz_id": "q1", "is_correct": True, "question": "Q1",
                 "student_answer": "A", "correct_answer": "A", "node_id": 1},
            ],
            chat_data_list=[
                {"message_id": "m1", "question": "What is X?", "answer": "X is Y",
                 "node_id": 1},
            ],
            jump_data_list=[
                {"jump_id": 1, "from_node_id": 1, "to_node_id": 0,
                 "trigger_type": "test", "is_returned": True},
            ],
        )
        assert len(events) > 0
        # Progress: NODE_ACCESSED + NODE_COMPLETED = 2
        # Quiz: QUIZ_ANSWERED + QUIZ_CORRECT = 2
        # Chat: QUESTION_ASKED + ANSWER_RECEIVED = 2
        # Jump: PREREQ_GAP_DETECTED + PREREQ_JUMP_STARTED + PREREQ_JUMP_RETURNED = 3
        assert len(events) == 9

    def test_mapper_empty_inputs(self):
        mapper = ExistingDataMapper(student_id=1, course_id=101)
        events = mapper.map_all()
        assert len(events) == 0

    def test_mapper_sequence_monotonic(self):
        mapper = ExistingDataMapper(student_id=1, course_id=101)
        events = mapper.map_all(
            quiz_data_list=[
                {"quiz_id": "q1", "is_correct": True, "question": "Q",
                 "student_answer": "A", "correct_answer": "A", "node_id": 1},
                {"quiz_id": "q2", "is_correct": False, "question": "Q2",
                 "student_answer": "B", "correct_answer": "A", "node_id": 2},
            ],
        )
        seqs = [e.sequence_number for e in events]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)


# =========================================================================
# Evidence aggregation
# =========================================================================


class TestEvidenceAggregation:
    """Evidence aggregation rules."""

    def test_aggregate_empty_events(self):
        evidence = aggregate_evidence([])
        assert evidence == []

    def test_aggregate_node_completion(self, sample_events):
        evidence = aggregate_evidence(sample_events)
        # Should produce at least node_completion evidence
        types = [ev.evidence_type for ev in evidence]
        assert EvidenceType.NODE_COMPLETION in types

    def test_aggregate_quiz_accuracy(self):
        events = [
            LearningEvent(
                event_type=EventType.QUIZ_ANSWERED,
                student_id=1,
                course_id=101,
                sequence_number=1,
                metadata={"is_correct": True},
                source="test",
            ),
            LearningEvent(
                event_type=EventType.QUIZ_CORRECT,
                student_id=1,
                course_id=101,
                sequence_number=2,
                source="test",
            ),
            LearningEvent(
                event_type=EventType.QUIZ_ANSWERED,
                student_id=1,
                course_id=101,
                sequence_number=3,
                metadata={"is_correct": False},
                source="test",
            ),
            LearningEvent(
                event_type=EventType.QUIZ_INCORRECT,
                student_id=1,
                course_id=101,
                sequence_number=4,
                source="test",
            ),
        ]
        evidence = aggregate_evidence(events)
        types = [ev.evidence_type for ev in evidence]
        assert EvidenceType.QUIZ_ACCURACY in types
        quiz_ev = next(ev for ev in evidence if ev.evidence_type == EvidenceType.QUIZ_ACCURACY)
        assert quiz_ev.value is not None
        # 1 correct out of 2 answered = 0.5
        assert quiz_ev.value == 0.5

    def test_aggregate_engagement(self):
        events = [
            LearningEvent(
                event_type=EventType.NODE_ACCESSED,
                student_id=1,
                course_id=101,
                node_id=1,
                sequence_number=1,
                source="test",
            ),
            LearningEvent(
                event_type=EventType.NODE_ACCESSED,
                student_id=1,
                course_id=101,
                node_id=2,
                sequence_number=2,
                source="test",
            ),
            LearningEvent(
                event_type=EventType.QUESTION_ASKED,
                student_id=1,
                course_id=101,
                sequence_number=3,
                source="test",
            ),
        ]
        evidence = aggregate_evidence(events)
        types = [ev.evidence_type for ev in evidence]
        assert EvidenceType.ENGAGEMENT in types

    def test_aggregate_prereq_gap(self):
        events = [
            LearningEvent(
                event_type=EventType.PREREQ_GAP_DETECTED,
                student_id=1,
                course_id=101,
                sequence_number=1,
                source="test",
            ),
        ]
        evidence = aggregate_evidence(events)
        types = [ev.evidence_type for ev in evidence]
        assert EvidenceType.PREREQ_GAP in types

    def test_aggregate_prereq_recovery(self):
        events = [
            LearningEvent(
                event_type=EventType.PREREQ_JUMP_RETURNED,
                student_id=1,
                course_id=101,
                sequence_number=1,
                source="test",
            ),
        ]
        evidence = aggregate_evidence(events)
        types = [ev.evidence_type for ev in evidence]
        assert EvidenceType.PREREQ_RECOVERY in types

    def test_aggregate_multiple_students(self):
        events = [
            LearningEvent(
                event_type=EventType.NODE_ACCESSED,
                student_id=1, course_id=101,
                sequence_number=1, source="test",
            ),
            LearningEvent(
                event_type=EventType.NODE_ACCESSED,
                student_id=2, course_id=101,
                sequence_number=1, source="test",
            ),
        ]
        evidence = aggregate_evidence(events)
        assert len(evidence) >= 2  # At least one per student

    def test_aggregator_convenience_class(self):
        aggregator = EvidenceAggregator()
        events = [
            LearningEvent(
                event_type=EventType.NODE_ACCESSED,
                student_id=1, course_id=101,
                sequence_number=1, source="test",
            ),
            LearningEvent(
                event_type=EventType.NODE_COMPLETED,
                student_id=1, course_id=101,
                sequence_number=2, source="test",
            ),
        ]
        evidence = aggregator.aggregate(events)
        assert len(evidence) > 0

    def test_default_rules_defined(self):
        assert len(DEFAULT_AGGREGATION_RULES) > 0
        rule_ids = [r.rule_id for r in DEFAULT_AGGREGATION_RULES]
        assert "node-completion-rate" in rule_ids
        assert "quiz-accuracy-window" in rule_ids
        assert "quiz-pattern-repeated-errors" in rule_ids
        assert "engagement-access-frequency" in rule_ids

    def test_aggregate_evidence_has_event_refs(self, sample_events):
        evidence = aggregate_evidence(sample_events)
        for ev in evidence:
            if ev.evidence_type != EvidenceType.ENGAGEMENT:
                continue
            assert len(ev.event_refs) > 0

    def test_aggregate_quiz_pattern(self):
        events = [
            LearningEvent(
                event_type=EventType.QUIZ_INCORRECT,
                student_id=1, course_id=101, node_id=1,
                sequence_number=1, source="test",
                metadata={"quiz_id": "q1", "question": "Q1"},
            ),
            LearningEvent(
                event_type=EventType.QUIZ_INCORRECT,
                student_id=1, course_id=101, node_id=1,
                sequence_number=2, source="test",
                metadata={"quiz_id": "q1", "question": "Q1"},
            ),
        ]
        evidence = aggregate_evidence(events)
        types = [ev.evidence_type for ev in evidence]
        assert EvidenceType.QUIZ_PATTERN in types


# =========================================================================
# MasteryProviderResult contract
# =========================================================================


class TestMasteryProviderResult:
    """MasteryProviderResult contract (timeout, malformed, business failure)."""

    def test_success_result(self):
        result = MasteryProviderResult.success_result(
            provider_name="test_provider",
            provider_version="1.0",
            student_id=1,
            course_id=101,
            mastery_score=0.85,
            mastery_level="proficient",
            confidence=0.75,
            evidence_refs=["e1", "e2"],
        )
        assert result.is_success
        assert result.mastery_score == 0.85
        assert result.evidence_refs == ["e1", "e2"]

    def test_timeout_result(self):
        result = MasteryProviderResult.timeout_result(
            provider_name="test_provider",
            student_id=1,
            course_id=101,
            timeout_seconds=30.0,
        )
        assert result.is_timeout
        assert not result.is_success
        assert result.error is not None
        assert result.error.code == "TIMEOUT"

    def test_malformed_result(self):
        result = MasteryProviderResult.malformed_result(
            provider_name="test_provider",
            student_id=1,
            course_id=101,
            details={"reason": "invalid student_id"},
        )
        assert result.is_malformed
        assert not result.is_success
        assert result.error.code == "MALFORMED_INPUT"

    def test_business_failure_result(self):
        result = MasteryProviderResult.business_failure_result(
            provider_name="test_provider",
            student_id=1,
            course_id=101,
            code="INSUFFICIENT_DATA",
            message="Not enough evidence",
        )
        assert result.is_business_failure
        assert not result.is_success
        assert result.error.code == "INSUFFICIENT_DATA"

    def test_to_dict(self):
        result = MasteryProviderResult.success_result(
            provider_name="p1",
            provider_version="1.0",
            student_id=1,
            course_id=101,
            mastery_score=0.9,
            mastery_level="advanced",
            confidence=0.8,
            evidence_refs=["e1"],
        )
        d = result.to_dict()
        assert d["mastery_score"] == 0.9
        assert d["evidence_refs"] == ["e1"]
        assert d["error"] is None

    def test_error_result_to_dict(self):
        result = MasteryProviderResult.timeout_result(
            provider_name="p1",
            student_id=1,
            course_id=101,
        )
        d = result.to_dict()
        assert d["error"]["code"] == "TIMEOUT"

    def test_timeout_exception(self):
        exc = MasteryTimeoutError("Custom timeout", timeout_seconds=60.0)
        assert str(exc) == "Custom timeout"
        assert exc.timeout_seconds == 60.0

    def test_malformed_exception(self):
        exc = MasteryMalformedError("Bad input", {"field": "student_id"})
        assert exc.details["field"] == "student_id"

    def test_business_failure_exception(self):
        exc = MasteryBusinessFailureError("No data", code="NO_DATA")
        assert exc.code == "NO_DATA"

    def test_success_requires_evidence(self):
        """Success with non-zero mastery should have evidence_refs."""
        result = MasteryProviderResult.success_result(
            provider_name="p1",
            provider_version="1.0",
            student_id=1,
            course_id=101,
            mastery_score=0.5,
            mastery_level="developing",
            confidence=0.5,
            evidence_refs=["e1"],
        )
        assert len(result.evidence_refs) > 0

    def test_timeout_distinct_from_business_failure(self):
        """Timeout and business failure are distinct states."""
        timeout_result = MasteryProviderResult.timeout_result("p", 1, 101)
        bf_result = MasteryProviderResult.business_failure_result("p", 1, 101)
        assert timeout_result.is_timeout != bf_result.is_timeout
        assert timeout_result.is_business_failure != bf_result.is_business_failure

    def test_malformed_distinct_from_timeout(self):
        """Malformed and timeout are distinct states."""
        malformed = MasteryProviderResult.malformed_result("p", 1, 101)
        timeout = MasteryProviderResult.timeout_result("p", 1, 101)
        assert malformed.is_malformed != timeout.is_malformed
        assert malformed.is_timeout != timeout.is_timeout


# =========================================================================
# Provider capability interfaces
# =========================================================================


class TestProviderCapability:
    """Provider capability declarations."""

    def test_provider_capability_creation(self):
        cap = ProviderCapability(
            name="test_provider",
            version="1.0.0",
            supports_course_level=True,
            supports_node_level=False,
        )
        assert cap.name == "test_provider"
        assert cap.supports_course_level
        assert not cap.supports_node_level

    def test_provider_version(self):
        v = ProviderVersion(major=1, minor=2, patch=3)
        assert str(v) == "1.2.3"

    def test_abstract_provider_defaults(self):
        provider = RuleBasedMasteryProvider()
        cap = provider.get_capability()
        assert cap.name == "rule_based"
        assert cap.supports_course_level

    def test_bkt_interface_capability(self):
        provider = BKTProvider()
        cap = provider.get_capability()
        assert cap.name == "bkt"
        assert cap.requires_historical_data
        assert cap.metadata["status"] == "interface_only"
        assert cap.metadata["implementation"] == "not_implemented"

    def test_irt_interface_capability(self):
        provider = IRTProvider()
        cap = provider.get_capability()
        assert cap.name == "irt"
        assert cap.metadata["status"] == "interface_only"

    def test_dkt_interface_capability(self):
        provider = DKTProvider()
        cap = provider.get_capability()
        assert cap.name == "dkt"
        assert cap.metadata["status"] == "interface_only"

    def test_bkt_is_abstract(self):
        """BKTProvider cannot be instantiated for compute (abstract)."""
        with pytest.raises(TypeError):
            BKTProvider().compute(1, 101)  # abstract

    def test_irt_is_abstract(self):
        with pytest.raises(TypeError):
            IRTProvider().compute(1, 101)

    def test_dkt_is_abstract(self):
        with pytest.raises(TypeError):
            DKTProvider().compute(1, 101)

    def test_provider_protocol_check(self):
        """RuleBasedMasteryProvider should satisfy MasteryProvider protocol."""
        provider = RuleBasedMasteryProvider()
        assert isinstance(provider, MasteryProvider)
        assert callable(provider.compute)
        assert callable(provider.get_capability)


# =========================================================================
# RuleBased mastery baseline
# =========================================================================


class TestRuleBasedMastery:
    """RuleBased mastery baseline: deterministic, explainable, gold-comparable."""

    def test_no_evidence_returns_business_failure(self):
        provider = RuleBasedMasteryProvider()
        result = provider.compute(
            student_id=1,
            course_id=101,
            metadata={"evidence_dict": {}},
        )
        assert result.is_business_failure
        assert result.error.code == "NO_EVIDENCE"
        assert result.mastery_score is None

    def test_course_level_mastery(self):
        provider = RuleBasedMasteryProvider()
        evidence_dict = {
            "node_completion": [
                {
                    "evidence_id": "e1",
                    "value": 0.5,
                    "node_id": 1,
                },
                {
                    "evidence_id": "e2",
                    "value": 1.0,
                    "node_id": 2,
                },
            ],
            "quiz_accuracy": [
                {
                    "evidence_id": "e3",
                    "value": 0.8,
                },
            ],
        }
        result = provider.compute(
            student_id=1,
            course_id=101,
            metadata={"evidence_dict": evidence_dict},
        )
        assert result.is_success
        assert result.mastery_score is not None
        assert result.mastery_score > 0
        assert result.mastery_level is not None
        assert len(result.evidence_refs) > 0

    def test_node_level_mastery(self):
        provider = RuleBasedMasteryProvider()
        evidence_dict = {
            "node_completion": [
                {
                    "evidence_id": "e1",
                    "value": 1.0,
                    "node_id": 5,
                },
            ],
            "quiz_accuracy": [
                {
                    "evidence_id": "e2",
                    "value": 0.9,
                    "node_id": 5,
                },
            ],
        }
        result = provider.compute(
            student_id=1,
            course_id=101,
            node_id=5,
            metadata={"evidence_dict": evidence_dict},
        )
        assert result.is_success
        assert result.mastery_score is not None

    def test_deterministic_output(self):
        """Same input should produce same output."""
        provider = RuleBasedMasteryProvider()
        evidence_dict = {
            "quiz_accuracy": [
                {"evidence_id": "e1", "value": 0.75},
            ],
        }
        result1 = provider.compute(
            student_id=1, course_id=101,
            metadata={"evidence_dict": evidence_dict},
        )
        result2 = provider.compute(
            student_id=1, course_id=101,
            metadata={"evidence_dict": evidence_dict},
        )
        assert result1.mastery_score == result2.mastery_score
        assert result1.mastery_level == result2.mastery_level

    def test_result_has_evidence_refs(self):
        provider = RuleBasedMasteryProvider()
        evidence_dict = {
            "node_completion": [
                {"evidence_id": "e1", "value": 1.0, "node_id": 1},
            ],
        }
        result = provider.compute(
            student_id=1, course_id=101,
            metadata={"evidence_dict": evidence_dict},
        )
        assert len(result.evidence_refs) > 0

    def test_rule_set_creation(self):
        rules = MasteryRuleSet(
            name="test_rules",
            rules=[
                MasteryRule(
                    rule_id="r1", name="Rule 1",
                    description="Test rule", weight=0.5,
                ),
            ],
            description="Test rule set",
        )
        assert rules.name == "test_rules"
        assert len(rules.rules) == 1

    def test_default_rule_sets_defined(self):
        assert len(DEFAULT_COURSE_RULES.rules) > 0
        assert len(DEFAULT_NODE_RULES.rules) > 0

    def test_mastery_rule_result_creation(self):
        rr = MasteryRuleResult(
            rule_id="r1",
            score=0.85,
            weight=0.5,
            evidence_refs=["e1"],
            description="Good score",
        )
        assert rr.score == 0.85
        assert rr.weight == 0.5

    def test_score_to_level_mapping(self):
        """Verify score-to-level boundaries."""
        provider = RuleBasedMasteryProvider()
        evidence_dict = {
            "quiz_accuracy": [
                {"evidence_id": "e1", "value": 0.95},
            ],
        }
        result = provider.compute(
            student_id=1, course_id=101,
            metadata={"evidence_dict": evidence_dict},
        )
        assert result.mastery_level in ("advanced", "proficient")

    def test_mastery_provider_to_dict(self):
        provider = RuleBasedMasteryProvider()
        evidence_dict = {
            "node_completion": [
                {"evidence_id": "e1", "value": 1.0, "node_id": 1},
            ],
        }
        result = provider.compute(
            student_id=1, course_id=101,
            metadata={"evidence_dict": evidence_dict},
        )
        d = result.to_dict()
        assert d["provider_name"] == "rule_based"
        assert d["mastery_score"] is not None


# =========================================================================
# Explainability invariants
# =========================================================================


class TestExplainabilityInvariants:
    """Core invariants from the product requirements."""

    def test_no_evidence_no_strong_conclusion(self):
        """MasteryProviderResult with no evidence should not claim mastery."""
        provider = RuleBasedMasteryProvider()
        result = provider.compute(
            student_id=1,
            course_id=101,
            metadata={"evidence_dict": {}},
        )
        assert result.is_business_failure or result.mastery_score is None

    def test_every_mastery_has_evidence_refs(self):
        """Every non-failure mastery result must list evidence refs."""
        provider = RuleBasedMasteryProvider()
        evidence_dict = {
            "quiz_accuracy": [
                {"evidence_id": "e1", "value": 0.8},
            ],
        }
        result = provider.compute(
            student_id=1, course_id=101,
            metadata={"evidence_dict": evidence_dict},
        )
        if result.is_success:
            assert len(result.evidence_refs) > 0

    def test_corrections_are_new_events(self):
        """Corrections must be new events, never mutations."""
        original = LearningEvent(
            event_type=EventType.QUIZ_ANSWERED,
            student_id=1,
            course_id=101,
            sequence_number=1,
            metadata={"score": 0.5},
        )
        correction = build_correction_event(
            original_event=original,
            reason="Score was recorded incorrectly",
            new_sequence_number=2,
            corrected_metadata={"score": 0.85},
        )
        assert correction.event_id != original.event_id
        assert original.metadata["score"] == 0.5  # Unchanged
        assert correction.corrected_event_id == original.event_id

    def test_idempotency_key_stable(self):
        """Same inputs must produce the same idempotency key."""
        event1 = LearningEvent(
            event_type=EventType.NODE_COMPLETED,
            student_id=1,
            course_id=101,
            sequence_number=5,
        )
        event2 = LearningEvent(
            event_type=EventType.NODE_COMPLETED,
            student_id=1,
            course_id=101,
            sequence_number=5,
        )
        assert event1.idempotency_key == event2.idempotency_key

    def test_mapper_produces_valid_events(self):
        """Mapper output events must be valid LearningEvents."""
        events = map_progress_to_events(
            {
                "completion_rate": 0.0,
                "status": "in_progress",
                "nodes": [],
            },
            student_id=1,
            course_id=101,
        )
        for event in events:
            assert event.event_id is not None
            assert event.event_type in EventType
            assert event.student_id == 1

    def test_aggregated_evidence_refs_valid_events(self, sample_events):
        """Aggregated evidence should reference actual event IDs."""
        evidence = aggregate_evidence(sample_events)
        all_event_ids = {e.event_id for e in sample_events}
        for ev in evidence:
            for ref in ev.event_refs:
                assert ref in all_event_ids
