"""Regression tests for the pure TeachingAgent constraint policy kernel."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import SQLModel, Session, create_engine

from app.platform.agents.edu.constraints import (
    ALL_SCOPES,
    ConstraintSubject,
    canonicalize_snapshot,
    resolve_effective_constraint,
)
from app.schemas.teaching_constraint import TeachingConstraintSnapshot


def _now() -> datetime:
    return datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def test_locked_profile_enforces_research_and_confirmation_platform_floors():
    """A relaxed teacher override must not weaken the locked profile's floor."""
    snapshot = canonicalize_snapshot({
        "level": "locked",
        "scopes": ALL_SCOPES,
        "parameters": {
            "external_research": "tool_policy",
            "confirmation_mode": "high_risk",
        },
        "rules": [],
    })

    envelope = resolve_effective_constraint(
        snapshot=snapshot,
        subject=ConstraintSubject(student_id="9"),
        now=_now(),
    )

    assert envelope.level == "locked"
    assert envelope.parameters.external_research == "disabled"
    assert envelope.parameters.confirmation_mode == "all_actions"
    assert "question_generation" in envelope.disabled_tools


def test_snapshot_rejects_unknown_policy_fields():
    """A misspelled or student-controlled field cannot silently change policy."""
    with pytest.raises(ValidationError):
        TeachingConstraintSnapshot.model_validate({
            "baseline": {"level": "balanced", "scopes": ALL_SCOPES},
            "student_hardness": "locked",
        })


def test_student_rule_beats_group_rule_at_equal_priority():
    """Specific learner exceptions must win over broader group exceptions."""
    snapshot = canonicalize_snapshot({
        "level": "balanced",
        "scopes": ALL_SCOPES,
        "rules": [
            {
                "rule_id": "rule_group",
                "priority": 100,
                "target_type": "group",
                "target_id": "cg_a",
                "level": "flexible",
                "reason": "Group needs more direct examples.",
            },
            {
                "rule_id": "rule_student",
                "priority": 100,
                "target_type": "student",
                "target_id": "9",
                "level": "strict",
                "reason": "Learner needs evidence-led guidance.",
            },
        ],
    })

    envelope = resolve_effective_constraint(
        snapshot=snapshot,
        subject=ConstraintSubject(student_id="9", group_ids=("cg_a",)),
        now=_now(),
    )

    assert envelope.level == "strict"
    assert envelope.matched_rule_ids == ("rule_student",)


def test_more_restrictive_level_wins_when_selectors_are_equally_specific():
    """Equal selectors must resolve deterministically toward the safer level."""
    snapshot = canonicalize_snapshot({
        "level": "balanced",
        "scopes": ALL_SCOPES,
        "rules": [
            {
                "rule_id": "rule_alpha",
                "priority": 30,
                "target_type": "student",
                "target_id": "9",
                "level": "strict",
                "reason": "Needs guided evidence review.",
            },
            {
                "rule_id": "rule_beta",
                "priority": 30,
                "target_type": "student",
                "target_id": "9",
                "level": "locked",
                "reason": "Temporary assessment lock.",
            },
        ],
    })

    envelope = resolve_effective_constraint(
        snapshot=snapshot,
        subject=ConstraintSubject(student_id="9"),
        now=_now(),
    )

    assert envelope.level == "locked"
    assert envelope.matched_rule_ids == ("rule_beta",)


def test_expired_rule_cannot_override_course_baseline():
    """An old exception must stop affecting the learner after its time window."""
    now = _now()
    snapshot = canonicalize_snapshot({
        "level": "balanced",
        "scopes": ALL_SCOPES,
        "rules": [
            {
                "rule_id": "rule_expired",
                "priority": 100,
                "target_type": "student",
                "target_id": "9",
                "level": "locked",
                "reason": "Expired temporary lock.",
                "effective_from": (now - timedelta(days=2)).isoformat(),
                "effective_until": (now - timedelta(days=1)).isoformat(),
            },
        ],
    })

    envelope = resolve_effective_constraint(
        snapshot=snapshot,
        subject=ConstraintSubject(student_id="9"),
        now=now,
    )

    assert envelope.level == "balanced"
    assert envelope.matched_rule_ids == ()


@pytest.fixture
def policy_session(tmp_path):
    """Use only the two new tables; no production DB or application startup."""
    from app.models.teaching_constraint_model import (
        TeachingConstraintEvaluation,
        TeachingConstraintPolicyVersion,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'constraints.db'}")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            TeachingConstraintPolicyVersion.__table__,
            TeachingConstraintEvaluation.__table__,
        ],
    )
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_save_requires_expected_version_and_preserves_immutable_snapshots(policy_session):
    from app.services.teaching_constraint_service import TeachingConstraintService

    service = TeachingConstraintService()
    first = service.save(
        policy_session,
        course_id=2,
        expected_version=0,
        actor_user_id=7,
        change_reason="Course baseline",
        payload={"level": "balanced", "scopes": ALL_SCOPES, "rules": []},
    )
    first_snapshot = first.policy_snapshot
    second = service.save(
        policy_session,
        course_id=2,
        expected_version=first.version,
        actor_user_id=7,
        change_reason="Assessment week",
        payload={"level": "strict", "scopes": ALL_SCOPES, "rules": []},
    )

    policy_session.refresh(first)
    assert first.is_active is False
    assert first.policy_snapshot == first_snapshot
    assert second.version == 2
    assert first.policy_hash != second.policy_hash


def test_stale_expected_version_is_rejected_without_partial_write(policy_session):
    from app.models.teaching_constraint_model import TeachingConstraintPolicyVersion
    from app.services.teaching_constraint_service import TeachingConstraintService
    from sqlmodel import func, select

    service = TeachingConstraintService()
    service.save(
        policy_session,
        course_id=3,
        expected_version=0,
        actor_user_id=7,
        change_reason="Initial policy",
        payload={"level": "balanced", "scopes": ALL_SCOPES, "rules": []},
    )

    with pytest.raises(HTTPException) as error:
        service.save(
            policy_session,
            course_id=3,
            expected_version=0,
            actor_user_id=7,
            change_reason="Stale writer",
            payload={"level": "locked", "scopes": ALL_SCOPES, "rules": []},
        )

    count = policy_session.exec(
        select(func.count(TeachingConstraintPolicyVersion.id)).where(
            TeachingConstraintPolicyVersion.course_id == 3
        )
    ).one()
    assert error.value.status_code == 409
    assert error.value.detail["error_code"] == "STATE_CONFLICT"
    assert count == 1


def test_rollback_appends_a_new_version_instead_of_reactivating_history(policy_session):
    from app.services.teaching_constraint_service import TeachingConstraintService

    service = TeachingConstraintService()
    first = service.save(
        policy_session,
        course_id=4,
        expected_version=0,
        actor_user_id=7,
        change_reason="Initial policy",
        payload={"level": "balanced", "scopes": ALL_SCOPES, "rules": []},
    )
    second = service.save(
        policy_session,
        course_id=4,
        expected_version=1,
        actor_user_id=7,
        change_reason="Temporary lock",
        payload={"level": "locked", "scopes": ALL_SCOPES, "rules": []},
    )
    rolled_back = service.rollback(
        policy_session,
        course_id=4,
        target_version=first.version,
        expected_version=second.version,
        actor_user_id=7,
        change_reason="Restore teaching baseline",
    )

    assert rolled_back.version == 3
    assert rolled_back.policy_hash == first.policy_hash
    assert rolled_back.id != first.id


def test_evaluation_record_contains_only_bounded_governance_metadata(policy_session):
    from app.services.teaching_constraint_service import TeachingConstraintService

    service = TeachingConstraintService()
    version = service.save(
        policy_session,
        course_id=5,
        expected_version=0,
        actor_user_id=7,
        change_reason="Initial policy",
        payload={"level": "strict", "scopes": ALL_SCOPES, "rules": []},
    )
    record = service.record_evaluation(
        policy_session,
        trace_id="trace_safe_1",
        course_id=5,
        student_id=9,
        policy_version_id=version.id,
        effective_level="strict",
        matched_rule_ids=(),
        applied_scopes=ALL_SCOPES,
        decision_codes=("PLATFORM_FLOOR_APPLIED",),
        context_input_chars=2000,
        context_output_chars=900,
        valid_citation_count=2,
        enforcement_status="enforced",
    )

    columns = set(record.__table__.columns.keys())
    assert not columns.intersection({"prompt", "raw_message", "answer", "model_output"})
