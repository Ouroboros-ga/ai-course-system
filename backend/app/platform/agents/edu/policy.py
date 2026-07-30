"""Deterministic policy: models do not choose the teaching action.

Migrated from ``app.platform.agents.policies.teaching_action``; the old
module re-exports this verbatim for backward compatibility.
"""

from __future__ import annotations

from typing import Any, Mapping


def decide_teaching_action(state: Mapping[str, Any]) -> tuple[str, str]:
    if state.get("current_code_submission_id"):
        return "code_debugging", "code_submission_context_present"
    if float(state.get("concept_grounding_confidence", 0.0)) < 0.55:
        return "diagnostic_question", "concept_grounding_insufficient"
    learner = state.get("student_concept_state") or {}
    if not learner or float(learner.get("confidence", 0.0)) < 0.45:
        return "diagnostic_question", "student_state_insufficient"
    mastery_score = learner.get("mastery_score")
    if mastery_score is None:
        return "diagnostic_question", "observed_performance_unknown"
    graph = state.get("graph_context") or {}
    prerequisites = graph.get("prerequisites") or state.get("prerequisites") or []
    weak_ids = {str(item.get("concept_id")) for item in state.get("weak_concepts", [])}
    if any(str(item.get("concept_id")) in weak_ids for item in prerequisites):
        return "prerequisite_review", "confirmed_weak_prerequisite"
    repeated_error_risk = learner.get("repeated_error_risk")
    if repeated_error_risk is not None and float(repeated_error_risk) >= 0.7:
        return "misconception_repair", "repeated_error_risk_high"
    hint_dependency = learner.get("hint_dependency")
    if float(mastery_score) < 0.7 and hint_dependency is not None and float(hint_dependency) >= 0.6:
        return "hint_scaffolding", "hint_dependency_high"
    transfer_score = learner.get("transfer_score")
    if float(mastery_score) >= 0.75 and transfer_score is not None and float(transfer_score) < 0.5:
        return "transfer_practice", "transfer_evidence_insufficient"
    return "normal_answer", "sufficient_course_evidence"
