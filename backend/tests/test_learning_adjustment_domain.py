"""Contracts for learner-confirmed, version-pinned learning adjustments."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.learning_adjustment import (
    LearningAdjustmentProposal,
    LearningAdjustmentStatus,
    QuestionObservation,
    ReturnAnchor,
    ReviewTarget,
)


def _coordinate_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "course_release_id": "cr_release_1",
        "media_release_id": "mrel_release_1",
        "media_release_item_id": "mrit_item_1",
        "outline_node_id": "128",
        "local_time_ms": 48_200,
        "page": 6,
        "global_time_ms": 93_600,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "payload",
    [
        _coordinate_payload(media_release_item_id=None),
        _coordinate_payload(local_time_ms=None),
        {"global_time_ms": 93_600},
        _coordinate_payload(review_target={"local_time_ms": 1}),
        _coordinate_payload(playback_rate=2.0),
        _coordinate_payload(student_id="someone-else"),
        _coordinate_payload(unexpected="not-allowed"),
    ],
)
def test_question_observation_rejects_client_control_or_ambiguous_coordinates(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        QuestionObservation.model_validate(payload)


def test_global_time_is_optional_compatibility_data_but_never_a_coordinate_by_itself() -> None:
    observation = QuestionObservation.model_validate(
        _coordinate_payload(global_time_ms=None)
    )
    assert observation.media_release_item_id == "mrit_item_1"
    assert observation.global_time_ms is None


def test_proposal_keeps_three_coordinate_meanings_separate_and_has_no_return_anchor() -> None:
    observation = QuestionObservation.model_validate(_coordinate_payload(local_time_ms=8_200))
    target = ReviewTarget.model_validate(
        _coordinate_payload(
            media_release_item_id="mrit_item_3",
            outline_node_id="8",
            local_time_ms=48_200,
        )
    )
    proposal = LearningAdjustmentProposal(
        adjustment_id="lad_123",
        status=LearningAdjustmentStatus.PROPOSED,
        question_observation=observation,
        review_target=target,
        teaching_action="prerequisite_review",
        reason_codes=("EXPLANATION_NEED_HIGH",),
        recommended_playback_rate=0.85,
        requires_confirmation=True,
    )

    assert proposal.return_anchor is None
    assert proposal.question_observation.local_time_ms == 8_200
    assert proposal.review_target.media_release_item_id == "mrit_item_3"
    dumped = proposal.model_dump(mode="json")
    assert {"prompt", "raw_model", "raw_answer", "trace", "citations"}.isdisjoint(dumped)


def test_lifecycle_has_exactly_three_statuses_and_minimal_decline_invalidation_metadata() -> None:
    assert {status.value for status in LearningAdjustmentStatus} == {
        "proposed",
        "applied",
        "returned",
    }
    proposal = LearningAdjustmentProposal(
        adjustment_id="lad_123",
        status=LearningAdjustmentStatus.PROPOSED,
        question_observation=QuestionObservation.model_validate(_coordinate_payload()),
        review_target=ReviewTarget.model_validate(_coordinate_payload()),
        teaching_action="misconception_repair",
        reason_codes=("CURRENT_CONCEPT_CONFIRMED",),
        recommended_playback_rate=0.85,
        requires_confirmation=True,
        declined_at=datetime(2026, 8, 12, tzinfo=UTC),
        invalidated_at=datetime(2026, 8, 13, tzinfo=UTC),
        invalidation_reason_code="RELEASE_CHANGED",
    )
    assert proposal.declined_at is not None
    assert proposal.invalidated_at is not None
    assert proposal.invalidation_reason_code == "RELEASE_CHANGED"


def test_reason_codes_and_review_rate_are_bounded() -> None:
    with pytest.raises(ValidationError):
        LearningAdjustmentProposal(
            adjustment_id="lad_123",
            status=LearningAdjustmentStatus.PROPOSED,
            question_observation=QuestionObservation.model_validate(_coordinate_payload()),
            review_target=ReviewTarget.model_validate(_coordinate_payload()),
            teaching_action="normal_answer",
            reason_codes=tuple(f"CODE_{index}" for index in range(9)),
            recommended_playback_rate=0.85,
            requires_confirmation=True,
        )
    with pytest.raises(ValidationError):
        LearningAdjustmentProposal(
            adjustment_id="lad_123",
            status=LearningAdjustmentStatus.PROPOSED,
            question_observation=QuestionObservation.model_validate(_coordinate_payload()),
            review_target=ReviewTarget.model_validate(_coordinate_payload()),
            teaching_action="normal_answer",
            reason_codes=("OK",),
            recommended_playback_rate=1.5,
            requires_confirmation=True,
        )


def test_return_anchor_is_a_distinct_click_time_coordinate() -> None:
    anchor = ReturnAnchor.model_validate(
        _coordinate_payload(media_release_item_id="mrit_item_7", local_time_ms=193_420)
    )
    assert anchor.media_release_item_id == "mrit_item_7"
    assert anchor.local_time_ms == 193_420
