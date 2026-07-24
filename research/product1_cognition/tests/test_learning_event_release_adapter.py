from __future__ import annotations

import unittest

from cognition.kg_mest import MeasurementRole
from cognition.learning_event_release_adapter import adapt_learning_event_release


class LearningEventReleaseAdapterTests(unittest.TestCase):
    def _quiz_answered(self) -> dict[str, object]:
        return {
            "event_id": "quiz-answer-1", "event_type": "quiz_answered", "student_id": 101, "course_id": 202,
            "sequence_number": 10, "timestamp": "2026-07-23T10:00:00+00:00",
            "metadata": {"quiz_id": "exercise-boundary-01", "is_correct": False, "attempt_group_key": "attempt-1"},
        }

    def _adapt(self, events: list[dict[str, object]]):
        return adapt_learning_event_release(
            source_student_id=101, source_course_id=202, student_key="student-pseudo-a",
            course_key="course-a", data_version="protected-export-v1", events=events,
        )

    def test_primary_scored_quiz_is_pseudonymised_and_uses_quiz_id_as_q_matrix_task(self) -> None:
        result = self._adapt([self._quiz_answered()])
        self.assertEqual(result.status, "accepted")
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.student_key, "student-pseudo-a")
        self.assertEqual(event.source_event_id, "quiz-answer-1")
        self.assertEqual(event.attempt_group_key, "attempt-1")
        self.assertEqual(event.payload["observed_score"], 0.0)
        self.assertEqual(event.payload["task_id"], "exercise-boundary-01")
        self.assertEqual(event.measurement_role, MeasurementRole.EXPLICIT_PERFORMANCE)

    def test_derived_quiz_outcome_is_not_double_counted(self) -> None:
        derived = {
            "event_id": "quiz-outcome-1", "event_type": "quiz_incorrect", "student_id": 101, "course_id": 202,
            "sequence_number": 11, "timestamp": "2026-07-23T10:00:01+00:00", "metadata": {"quiz_id": "exercise-boundary-01"},
        }
        result = self._adapt([self._quiz_answered(), derived])
        self.assertEqual(tuple(event.event_id for event in result.events), ("quiz-answer-1",))
        self.assertEqual(result.skipped_event_refs, ("quiz-outcome-1",))
        self.assertEqual(result.reason_codes, ("DERIVED_QUIZ_OUTCOME_NOT_CONSUMED",))

    def test_unlabelled_question_is_not_used_as_cognitive_evidence(self) -> None:
        question = {
            "event_id": "question-1", "event_type": "question_asked", "student_id": 101, "course_id": 202,
            "sequence_number": 12, "timestamp": "2026-07-23T10:01:00+00:00", "metadata": {"question": "为什么？"},
        }
        result = self._adapt([question])
        self.assertEqual(result.events, ())
        self.assertEqual(result.skipped_event_refs, ("question-1",))
        self.assertEqual(result.reason_codes, ("UNLABELLED_QUESTION_NOT_COGNITIVE_EVIDENCE",))

    def test_labelled_question_keeps_candidate_provenance_only_when_bound_to_same_event(self) -> None:
        question = {
            "event_id": "question-2", "event_type": "question_asked", "student_id": 101, "course_id": 202,
            "sequence_number": 12, "timestamp": "2026-07-23T10:01:00+00:00",
            "metadata": {
                "candidate_source_event_id": "question-2", "concept_ids": ["binary-search-boundary"],
                "interaction_labels": {"confusion_risk": True},
                "interaction_label_confidences": {"confusion_risk": 0.95},
                "candidate_evidence_spans": {"confusion_risk": ["我不明白"]},
                "candidate_model_version": "uie-mini", "candidate_prompt_version": "none",
                "candidate_policy_version": "external-interaction-candidate/1.0",
            },
        }
        result = self._adapt([question])
        self.assertEqual(len(result.events), 1)
        payload = result.events[0].payload
        self.assertEqual(payload["candidate_model_version"], "uie-mini")
        self.assertEqual(payload["candidate_evidence_spans"], {"confusion_risk": ["我不明白"]})

    def test_label_candidate_bound_to_another_event_is_not_consumed(self) -> None:
        question = {
            "event_id": "question-3", "event_type": "question_asked", "student_id": 101, "course_id": 202,
            "sequence_number": 12, "timestamp": "2026-07-23T10:01:00+00:00",
            "metadata": {"candidate_source_event_id": "other", "concept_ids": ["c"], "interaction_labels": {"confusion_risk": True}},
        }
        result = self._adapt([question])
        self.assertEqual(result.events, ())
        self.assertEqual(result.reason_codes, ("UNLABELLED_QUESTION_NOT_COGNITIVE_EVIDENCE",))

    def test_mixed_student_or_course_scope_rejects_entire_release(self) -> None:
        invalid = self._quiz_answered()
        invalid["course_id"] = 999
        result = self._adapt([self._quiz_answered(), invalid])
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.events, ())
        self.assertEqual(result.reason_codes, ("LEARNING_EVENT_SCOPE_MISMATCH",))


if __name__ == "__main__":
    unittest.main()
