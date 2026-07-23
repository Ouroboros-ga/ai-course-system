from __future__ import annotations

import unittest

from cognition.kg_mest import (
    Dimension,
    GraphEvidenceGrounder,
    GraphSnapshot,
    LearningEvent,
    LearningPathRecommender,
    MeasurementRole,
    MultiSourceEvidenceEngine,
)


def event(*, event_id: str, source_event_id: str, sequence: int, concept: str | None = "binary-search",
          role: MeasurementRole = MeasurementRole.EXPLICIT_PERFORMANCE, event_type: str = "assessment",
          payload: dict | None = None, student: str = "student-a", course: str = "course-a") -> LearningEvent:
    return LearningEvent(
        event_id=event_id,
        source_event_id=source_event_id,
        attempt_group_key=source_event_id,
        student_key=student,
        course_key=course,
        sequence_number=sequence,
        occurred_at=f"2026-07-{sequence:02d}T10:00:00+00:00",
        event_type=event_type,
        concept_ids=() if concept is None else (concept,),
        measurement_role=role,
        payload=payload or {},
    )


class KGMESTTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MultiSourceEvidenceEngine()

    def _state(self, events: list[LearningEvent], concept: str = "binary-search"):
        explicit, _ = self.engine.extract(events)
        return self.engine.build_state(student_key="student-a", course_key="course-a", concept_id=concept,
                                       explicit_signals=explicit)

    def test_no_explicit_evidence_is_unknown(self) -> None:
        state = self._state([])
        self.assertEqual(state.confidence, "unknown")
        self.assertIsNone(state.observed_performance_score)
        self.assertEqual(state.confidence_reasons, ("NO_EXPLICIT_PERFORMANCE_EVIDENCE",))

    def test_interaction_labels_never_change_observed_performance(self) -> None:
        score_event = event(event_id="assessment-1", source_event_id="attempt-1", sequence=1,
                            payload={"observed_score": 0.8})
        interaction_event = event(event_id="dialogue-1", source_event_id="conversation-1", sequence=2,
                                  role=MeasurementRole.INTERACTION_SEMANTIC, event_type="dialogue",
                                  payload={"classification_confidence": 0.95, "interaction_labels": {
                                      "confusion_risk": True, "explanation_need": True,
                                  }, "candidate_evidence_spans": {"confusion_risk": ["不明白"]},
                                  "candidate_model_version": "uie-mini", "candidate_prompt_version": "none",
                                  "candidate_policy_version": "paddlenlp-uie-interaction-candidate/1.0"})
        baseline = self._state([score_event])
        with_interaction = self._state([score_event, interaction_event])
        _, interactions = self.engine.extract([score_event, interaction_event])
        interaction_state = self.engine.build_interaction_state(
            student_key="student-a", course_key="course-a", concept_id="binary-search", interaction_signals=interactions,
        )
        self.assertEqual(baseline.observed_performance_score, with_interaction.observed_performance_score)
        self.assertEqual(interaction_state.values["confusion_risk"], "low")
        self.assertEqual(interaction_state.values["explanation_need"], "low")
        self.assertEqual(interaction_state.values["inquiry_depth"], "unknown")
        self.assertEqual(interaction_state.classifier_provenance[0]["model_version"], "uie-mini")
        self.assertEqual(interaction_state.classifier_provenance[0]["evidence_spans"], ("不明白",))

    def test_low_confidence_dialogue_label_is_ignored(self) -> None:
        dialogue = event(event_id="dialogue-low", source_event_id="conversation-1", sequence=1,
                         role=MeasurementRole.INTERACTION_SEMANTIC, event_type="dialogue",
                         payload={"classification_confidence": 0.69, "interaction_labels": {"confusion_risk": True}})
        _, interactions = self.engine.extract([dialogue])
        state = self.engine.build_interaction_state(student_key="student-a", course_key="course-a",
                                                    concept_id="binary-search", interaction_signals=interactions)
        self.assertEqual(state.values["confusion_risk"], "unknown")
        self.assertEqual(state.evidence_refs, ())

    def test_low_confidence_label_cannot_ride_on_another_high_confidence_label(self) -> None:
        dialogue = event(event_id="dialogue-mixed", source_event_id="conversation-1", sequence=1,
                         role=MeasurementRole.INTERACTION_SEMANTIC, event_type="dialogue",
                         payload={
                             "classification_confidence": 0.95,
                             "interaction_labels": {"confusion_risk": True, "hint_dependency": True},
                             "interaction_label_confidences": {"confusion_risk": 0.95, "hint_dependency": 0.40},
                         })
        _, interactions = self.engine.extract([dialogue])
        state = self.engine.build_interaction_state(student_key="student-a", course_key="course-a",
                                                    concept_id="binary-search", interaction_signals=interactions)
        self.assertEqual(state.values["confusion_risk"], "low")
        self.assertEqual(state.values["hint_dependency"], "unknown")

    def test_same_source_event_is_only_counted_once_per_dimension(self) -> None:
        first = event(event_id="answer-1", source_event_id="attempt-1", sequence=1, payload={"observed_score": 1.0})
        migrated_copy = event(event_id="migration-1", source_event_id="attempt-1", sequence=2, payload={"observed_score": 0.0})
        signals, _ = self.engine.extract([migrated_copy, first])
        mastery = [item for item in signals if item.dimension == Dimension.MASTERY]
        self.assertEqual(len(mastery), 1)
        self.assertEqual(mastery[0].evidence_id, "answer-1:mastery")
        state = self._state([migrated_copy, first])
        self.assertGreater(state.observed_performance_score or 0.0, 0.5)

    def test_scope_mismatch_rejects_whole_result_without_partial_values(self) -> None:
        valid = event(event_id="a1", source_event_id="at1", sequence=1, payload={"observed_score": 0.9})
        foreign = event(event_id="a2", source_event_id="at2", sequence=2, course="course-b", payload={"observed_score": 0.1})
        signals, _ = self.engine.extract([valid, foreign])
        state = self.engine.build_state(student_key="student-a", course_key="course-a", concept_id="binary-search",
                                        explicit_signals=signals)
        self.assertEqual(state.status, "rejected")
        self.assertIsNone(state.observed_performance_score)
        self.assertTrue(all(value is None for value in state.values.values()))
        self.assertEqual(state.reason_codes, ("SCOPE_MISMATCH_REJECTED",))
        self.assertEqual(state.rejected_evidence_refs, ("a2:mastery",))
        self.assertEqual(state.rejection_details["actual_course_key"], "course-b")

    def test_interaction_conflict_returns_unknown_instead_of_a_claim(self) -> None:
        confused = event(event_id="dialogue-confused", source_event_id="conversation-1", sequence=1,
                         role=MeasurementRole.INTERACTION_SEMANTIC, event_type="dialogue",
                         payload={"classification_confidence": 0.90, "interaction_labels": {"confusion_risk": True}})
        resolved = event(event_id="dialogue-resolved", source_event_id="conversation-2", sequence=2,
                         role=MeasurementRole.INTERACTION_SEMANTIC, event_type="dialogue",
                         payload={"classification_confidence": 0.90, "resolved_interaction_labels": {"confusion_risk": True}})
        _, interactions = self.engine.extract([confused, resolved])
        state = self.engine.build_interaction_state(student_key="student-a", course_key="course-a",
                                                    concept_id="binary-search", interaction_signals=interactions)
        self.assertEqual(state.values["confusion_risk"], "unknown")
        self.assertIn("CONFLICTING_INTERACTION_EVIDENCE", state.reason_codes)

    def test_code_test_case_evidence_and_recommendations_are_explainable(self) -> None:
        code = event(event_id="code-1", source_event_id="submission-1", sequence=1, event_type="code_submission",
                     payload={
                         "observed_score": 0.5,
                         "test_case_results": ({"passed": True}, {"passed": False}),
                         "repeated_error_ratio": 0.8,
                         "strategy_quality": 0.4,
                         "recovery_efficiency": 0.6,
                     })
        state = self._state([code])
        graph = GraphSnapshot(course_key="course-a", graph_version="fixture-v1", prerequisites={},
                              resources={"binary-search": ("exercise-fix-boundary",)})
        recommendation = LearningPathRecommender(graph).recommend(state, {})
        self.assertEqual(recommendation[0].action_type, "diagnose")
        self.assertEqual(recommendation[0].reason_codes, ("INSUFFICIENT_EVIDENCE",))
        self.assertIn("code-1:mastery", state.evidence_refs)
        self.assertIn("CODE_TEST_CASE_PASS_RATE", state.reason_codes)

    def test_confirmed_weak_prerequisite_set_requires_medium_or_high_confidence(self) -> None:
        prereq_events = [
            event(event_id="p1", source_event_id="p-attempt-1", sequence=1, concept="loop-invariant", payload={"observed_score": 0.0}),
            event(event_id="p2", source_event_id="p-attempt-2", sequence=2, concept="loop-invariant", payload={"observed_score": 0.1}),
        ]
        target_events = [
            event(event_id="t1", source_event_id="t-attempt-1", sequence=3, payload={"observed_score": 0.5}),
            event(event_id="t2", source_event_id="t-attempt-2", sequence=4, payload={"observed_score": 0.5}),
        ]
        prereq_state = self._state(prereq_events, concept="loop-invariant")
        target_state = self._state(target_events)
        graph = GraphSnapshot(course_key="course-a", graph_version="fixture-v1",
                              prerequisites={"binary-search": ("loop-invariant",)},
                              resources={"loop-invariant": ("lesson-loop-invariant",)})
        result = LearningPathRecommender(graph).recommend(target_state, {"loop-invariant": prereq_state})
        self.assertEqual(prereq_state.confidence, "medium")
        self.assertEqual(result[0].action_type, "review_confirmed_weak_prerequisite")
        self.assertEqual(result[0].concept_id, "loop-invariant")
        self.assertEqual(result[0].resource_ids, ("lesson-loop-invariant",))

    def test_identical_event_sequence_has_deterministic_output_order(self) -> None:
        events = [
            event(event_id="b", source_event_id="b", sequence=2, payload={"observed_score": 0.8}),
            event(event_id="a", source_event_id="a", sequence=1, payload={"observed_score": 0.7}),
        ]
        first = self._state(events)
        second = self._state(list(reversed(events)))
        self.assertEqual(first, second)
        self.assertEqual(first.evidence_refs, ("a:mastery", "b:mastery"))

    def test_q_matrix_grounds_scored_task_and_unmapped_task_cannot_create_evidence(self) -> None:
        graph = GraphSnapshot(
            course_key="course-a", graph_version="fixture-v1", prerequisites={},
            task_q_matrix={"exercise-boundary": ("binary-search",)},
            task_discrimination={"exercise-boundary": 0.9},
        )
        unanchored = event(event_id="task-1", source_event_id="attempt-1", sequence=1, concept=None,
                           payload={"task_id": "exercise-boundary", "observed_score": 0.8})
        grounded = GraphEvidenceGrounder(graph).ground(unanchored)
        self.assertIsNotNone(grounded)
        self.assertEqual(grounded.concept_ids, ("binary-search",))
        state = self._state([grounded])
        self.assertIn("task-1:mastery", state.evidence_refs)
        unknown = event(event_id="task-2", source_event_id="attempt-2", sequence=2, concept=None,
                        payload={"task_id": "not-in-q-matrix", "observed_score": 1.0})
        self.assertIsNone(GraphEvidenceGrounder(graph).ground(unknown))


if __name__ == "__main__":
    unittest.main()
