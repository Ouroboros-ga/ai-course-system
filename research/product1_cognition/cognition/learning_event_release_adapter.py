"""Read-only bridge from existing LearningEvent exports to KG-MEST events.

The application event contract is append-only and has stable IDs, but its
legacy quiz mapper emits an answered fact plus a derived correct/incorrect
fact.  Only the scored primary fact is eligible for the performance axis.
This adapter never imports the application models, reads a database, or writes
new LearningEvidence; it converts a protected export of plain mappings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .kg_mest import LearningEvent, MeasurementRole


@dataclass(frozen=True)
class LearningEventReleaseResult:
    status: str
    events: tuple[LearningEvent, ...]
    skipped_event_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    rejection_details: Mapping[str, str]


def adapt_learning_event_release(
    *,
    source_student_id: int,
    source_course_id: int,
    student_key: str,
    course_key: str,
    data_version: str,
    events: list[Mapping[str, Any]],
) -> LearningEventReleaseResult:
    """Convert a pseudonymised, course-isolated LearningEvent export.

    ``student_key`` is a protected pseudonym supplied by the export process;
    this function never exposes the source numeric student ID in its outputs.
    Missing identity/scope/timestamp fields reject the whole release. Supported
    primary scored types are ``quiz_answered`` and ``exercise_submitted``.
    ``quiz_correct`` and ``quiz_incorrect`` are deliberately reported as
    skipped derived facts, which prevents same-attempt double counting.
    """
    converted: list[LearningEvent] = []
    skipped: list[str] = []
    reasons: set[str] = set()
    errors: set[str] = set()

    for raw in events:
        event_id = raw.get("event_id")
        if not event_id:
            errors.add("LEARNING_EVENT_ID_MISSING")
            continue
        event_ref = str(event_id)
        if raw.get("student_id") != source_student_id or raw.get("course_id") != source_course_id:
            errors.add("LEARNING_EVENT_SCOPE_MISMATCH")
            continue
        timestamp = raw.get("timestamp")
        if not _valid_timestamp(timestamp):
            errors.add("LEARNING_EVENT_TIMESTAMP_INVALID")
            continue
        sequence_number = raw.get("sequence_number")
        if isinstance(sequence_number, bool) or not isinstance(sequence_number, int):
            errors.add("LEARNING_EVENT_SEQUENCE_INVALID")
            continue
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, Mapping):
            errors.add("LEARNING_EVENT_METADATA_INVALID")
            continue

        event_type = _value(raw.get("event_type"))
        if event_type in {"quiz_correct", "quiz_incorrect"}:
            skipped.append(event_ref)
            reasons.add("DERIVED_QUIZ_OUTCOME_NOT_CONSUMED")
            continue
        if event_type in {"quiz_answered", "exercise_submitted"}:
            converted_event = _adapt_scored_event(
                raw=raw, metadata=metadata, event_type=event_type, student_key=student_key,
                course_key=course_key, data_version=data_version,
            )
            if converted_event is None:
                skipped.append(event_ref)
                reasons.add("SCORED_EVENT_MISSING_MEASUREMENT_OR_TASK_ID")
            else:
                converted.append(converted_event)
            continue
        if event_type == "question_asked":
            converted_event = _adapt_labelled_dialogue_event(
                raw=raw, metadata=metadata, student_key=student_key,
                course_key=course_key, data_version=data_version,
            )
            if converted_event is None:
                skipped.append(event_ref)
                reasons.add("UNLABELLED_QUESTION_NOT_COGNITIVE_EVIDENCE")
            else:
                converted.append(converted_event)
            continue
        skipped.append(event_ref)
        reasons.add("UNSUPPORTED_LEGACY_EVENT_NOT_CONSUMED")

    if errors:
        return LearningEventReleaseResult(
            "rejected", (), tuple(sorted(set(skipped))), tuple(sorted(errors)),
            {"expected_student_scope": "protected", "expected_course_key": course_key},
        )
    return LearningEventReleaseResult(
        "accepted",
        tuple(sorted(converted, key=lambda item: (item.sequence_number, item.event_id))),
        tuple(sorted(set(skipped))),
        tuple(sorted(reasons)),
        {},
    )


def _adapt_scored_event(
    *, raw: Mapping[str, Any], metadata: Mapping[str, Any], event_type: str,
    student_key: str, course_key: str, data_version: str,
) -> LearningEvent | None:
    observed_score = _observed_score(metadata)
    task_id = metadata.get("task_id") or metadata.get("quiz_id") or metadata.get("exercise_id")
    if observed_score is None or not task_id:
        return None
    scoring = metadata.get("scoring", {})
    if not isinstance(scoring, Mapping):
        scoring = {}
    payload: dict[str, Any] = {
        "observed_score": observed_score,
        "task_id": str(task_id),
        "scoring": dict(scoring),
    }
    for name in ("hint_level", "is_delayed_retest", "is_transfer_task"):
        if name in metadata:
            payload[name] = metadata[name]
    return LearningEvent(
        event_id=str(raw["event_id"]), source_event_id=str(raw["event_id"]),
        attempt_group_key=str(metadata.get("attempt_group_key") or metadata.get("attempt_id") or raw["event_id"]),
        student_key=student_key, course_key=course_key, sequence_number=int(raw["sequence_number"]),
        occurred_at=str(raw["timestamp"]), event_type="assessment" if event_type == "quiz_answered" else "exercise_submission",
        concept_ids=_concept_ids(metadata), measurement_role=MeasurementRole.EXPLICIT_PERFORMANCE,
        payload=payload, data_version=data_version,
    )


def _adapt_labelled_dialogue_event(
    *, raw: Mapping[str, Any], metadata: Mapping[str, Any], student_key: str,
    course_key: str, data_version: str,
) -> LearningEvent | None:
    labels = metadata.get("interaction_labels")
    concepts = _concept_ids(metadata)
    if not isinstance(labels, Mapping) or not concepts:
        return None
    if metadata.get("candidate_source_event_id") != raw["event_id"]:
        return None
    payload = {
        "interaction_labels": dict(labels),
        "resolved_interaction_labels": dict(metadata.get("resolved_interaction_labels", {})),
        "interaction_label_confidences": dict(metadata.get("interaction_label_confidences", {})),
        "classification_confidence": metadata.get("classification_confidence", 0.0),
        "candidate_evidence_spans": dict(metadata.get("candidate_evidence_spans", {})),
        "candidate_model_version": metadata.get("candidate_model_version", ""),
        "candidate_prompt_version": metadata.get("candidate_prompt_version", ""),
        "candidate_policy_version": metadata.get("candidate_policy_version", ""),
    }
    return LearningEvent(
        event_id=str(raw["event_id"]), source_event_id=str(raw["event_id"]),
        attempt_group_key=str(metadata.get("conversation_turn_id") or raw["event_id"]),
        student_key=student_key, course_key=course_key, sequence_number=int(raw["sequence_number"]),
        occurred_at=str(raw["timestamp"]), event_type="dialogue", concept_ids=concepts,
        measurement_role=MeasurementRole.INTERACTION_SEMANTIC, payload=payload, data_version=data_version,
    )


def _observed_score(metadata: Mapping[str, Any]) -> float | None:
    value = metadata.get("observed_score", metadata.get("score"))
    if value is None and isinstance(metadata.get("is_correct"), bool):
        return 1.0 if metadata["is_correct"] else 0.0
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if 0.0 <= score <= 1.0 else None


def _concept_ids(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    value = metadata.get("concept_ids", ())
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(sorted({str(item) for item in value if item}))


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")
