"""HTTP-level regression coverage for a learner-confirmed review round trip."""
from __future__ import annotations

from sqlmodel import Session, select

from app.core.security import create_access_token
from app.models.access_control_model import CourseCapability, CourseMembership, CourseRole, MembershipStatus
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.unified_learning_model import LearningEvent, LearningEventType, StudentLearningProjection
from app.models.user_model import User, UserRole
from app.schemas.learning_adjustment import ReturnAnchor
from app.services.course_access_service import establish_course_access_baseline
from app.services.learning_adjustment_service import learning_adjustment_service
from test_learning_adjustment_service import _observation, _setup_frozen_course


def test_review_round_trip_records_interaction_without_learning_evidence(
    client,
    session: Session,
) -> None:
    """Accepted and returned reviews are traceable interactions, not mastery facts."""
    course, _, ids = _setup_frozen_course(session)
    student = User(
        username="adjustment-e2e-student",
        hashed_password="test-password-hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    session.add(student)
    session.flush()
    establish_course_access_baseline(session, course.id, course.teacher_id)
    session.add(CourseMembership(
        user_id=student.id,
        course_id=course.id,
        role=CourseRole.STUDENT,
        status=MembershipStatus.ACTIVE,
        analytics_excluded=False,
    ))
    session.commit()
    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    assert capability.learning is True
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=student.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
    )
    assert proposal is not None
    assert proposal.question_observation.local_time_ms == 8_200
    assert proposal.review_target.local_time_ms == 48_200

    token = create_access_token({
        "sub": str(student.id),
        "username": student.username,
        "role": student.role.value,
        "school_id": student.school_id or "test-school",
    })
    headers = {"Authorization": f"Bearer {token}"}
    anchor = ReturnAnchor(
        course_release_id=ids["course_release_id"],
        media_release_id=ids["media_release_id"],
        media_release_item_id=ids["current_item_id"],
        outline_node_id=ids["current_outline_node_id"],
        local_time_ms=10_170,
        page=4,
        global_time_ms=10_170,
    )

    accepted = client.post(
        f"/api/v1/learning-adjustments/{proposal.adjustment_id}/apply",
        headers=headers,
        json={
            "return_anchor": anchor.model_dump(mode="json"),
            "idempotency_key": "e2e-accepted-click-anchor",
        },
    )

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "applied"
    assert accepted.json()["return_anchor"]["local_time_ms"] == 10_170
    assert accepted.json()["review_target"]["local_time_ms"] == 48_200

    returned = client.post(
        f"/api/v1/learning-adjustments/{proposal.adjustment_id}/return",
        headers=headers,
        json={"idempotency_key": "e2e-returned-after-seeked"},
    )

    assert returned.status_code == 200
    assert returned.json()["status"] == "returned"
    events = session.exec(
        select(LearningEvent)
        .where(LearningEvent.course_id == course.id)
        .order_by(LearningEvent.created_at)
    ).all()
    assert [event.event_type for event in events] == [
        LearningEventType.AGENT_LEARNING_ACTION,
        LearningEventType.AGENT_LEARNING_ACTION,
    ]
    assert [event.payload["action"] for event in events] == [
        "review_accepted",
        "review_returned",
    ]
    assert session.exec(
        select(StudentLearningProjection).where(StudentLearningProjection.course_id == course.id)
    ).all() == []
    assert session.exec(
        select(LearningEvidenceRecord).where(LearningEvidenceRecord.course_id == course.id)
    ).all() == []
