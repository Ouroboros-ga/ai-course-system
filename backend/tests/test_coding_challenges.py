"""Conversation-scoped coding challenge contracts for TeachingAgent."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta

import pytest
from app.core.time_utils import utcnow_aware
from app.models.access_control_model import CourseCapability
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
)
from app.models.experiment_model import (
    AttemptStatus,
    CodingChallengeOffer,
    CodingEvidenceEpisode,
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentRun,
    ExperimentVersion,
    RunOutcome,
)
from app.models.graph_production_model import (
    CourseKnowledgeNode,
    CourseKnowledgeNodeStatus,
)
from app.models.unified_learning_model import LearningEvidenceContext
from app.platform.agents.tools.catalog import DEFAULT_TOOL_CATALOG, ToolRisk
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from sqlmodel import select

BASE = "/api/v1/teaching-agent/coding-challenges"


def test_coding_challenge_tool_is_medium_risk_without_per_offer_confirmation():
    descriptor = DEFAULT_TOOL_CATALOG.get("coding_challenge")

    assert descriptor is not None
    assert descriptor.risk is ToolRisk.MEDIUM
    assert descriptor.default_enabled is True
    assert descriptor.supports_confirmation is False
    assert descriptor.requires_teacher_confirmation is False


def test_ai_challenge_prefers_the_learners_recent_supported_language(
    session,
    teacher_user,
    student_user,
):
    course = _learning_course(session, teacher_user, student_user)
    session.add(ExperimentRun(
        course_id=course.id,
        attempt_id="recent-language-attempt",
        student_id=student_user.id,
        language="java",
        source_code="class Main {}",
        idempotency_key="recent-language-run",
    ))
    session.commit()

    from app.services.coding_challenge_service import coding_challenge_service

    assert coding_challenge_service._preferred_ai_language(
        session,
        course_id=course.id,
        student_id=student_user.id,
    ) == "java"


def test_decision_prefers_verified_published_course_experiment(
    session,
    teacher_user,
    student_user,
):
    course = _learning_course(session, teacher_user, student_user)
    node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_existing_binary",
        title="二分查找",
        status=CourseKnowledgeNodeStatus.PUBLISHED,
    )
    outline = CourseOutlineVersion(
        course_id=course.id,
        lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
        created_by=teacher_user.id,
    )
    outline_node = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        title="二分查找",
        knowledge_graph_node_id=node.node_key,
    )
    release = CourseRelease(
        course_id=course.id,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        outline_version_id=outline.outline_version_id,
        created_by=teacher_user.id,
    )
    definition = ExperimentDefinition(
        course_id=course.id,
        title="课程题：二分查找",
        language_whitelist=["python3"],
        knowledge_node_ids=[],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        created_by=teacher_user.id,
    )
    session.add(node)
    session.flush()
    definition.knowledge_node_ids = [node.id]
    version = ExperimentVersion(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_number=1,
        is_locked=True,
        is_active=True,
        reference_preview_verified_at=utcnow_aware(),
        created_by=teacher_user.id,
    )
    definition.default_version_id = version.version_id
    session.add(outline)
    session.add(outline_node)
    session.add(release)
    session.add(definition)
    session.add(version)
    session.commit()

    from app.services.coding_challenge_service import coding_challenge_service

    unavailable = asyncio.run(coding_challenge_service.maybe_create_offer(
        session,
        course_id=course.id,
        student_id=student_user.id,
        conversation_session_id="decision-session",
        trace_id="decision-trace-unavailable",
        message="给我一道二分查找练习题",
        concept_id=node.node_key,
        teaching_action="check_understanding",
        sandbox_available=False,
    ))
    assert unavailable is None

    offer = asyncio.run(coding_challenge_service.maybe_create_offer(
        session,
        course_id=course.id,
        student_id=student_user.id,
        conversation_session_id="decision-session",
        trace_id="decision-trace",
        message="给我一道二分查找练习题",
        concept_id=node.node_key,
        teaching_action="check_understanding",
        sandbox_available=True,
    ))

    assert offer is not None
    assert offer["status"] == "ready"
    assert offer["source"] == "existing"
    assert offer["title"] == definition.title
    assert offer["actions"]["can_start"] is True

    # The same-concept cooldown belongs to the learner and course. A new
    # conversation must not bypass it after the earlier offer was dismissed.
    stored_offer = session.exec(select(CodingChallengeOffer).where(
        CodingChallengeOffer.offer_id == offer["offer_id"],
    )).one()
    stored_offer.status = "dismissed"
    session.add(stored_offer)
    session.commit()
    cooled_down = asyncio.run(coding_challenge_service.maybe_create_offer(
        session,
        course_id=course.id,
        student_id=student_user.id,
        conversation_session_id="decision-session-new-chat",
        trace_id="decision-trace-cooldown",
        message="二分查找的边界条件怎么处理",
        concept_id=node.node_key,
        teaching_action="check_understanding",
        sandbox_available=True,
    ))
    assert cooled_down is None


def test_conversation_offer_limit_uses_a_bounded_window_and_ignores_replacements(
    session,
    teacher_user,
    student_user,
):
    course = _learning_course(session, teacher_user, student_user)
    now = utcnow_aware()
    session.add_all([
        CodingChallengeOffer(
            course_id=course.id,
            student_id=student_user.id,
            conversation_session_id="long-lived-browser-session",
            trace_id=f"old-{index}",
            status="dismissed",
            source="existing",
            title="old",
            why_now="old",
            languages=["python3"],
            expires_at=now + timedelta(hours=1),
            created_at=now - timedelta(minutes=31 + index),
            updated_at=now - timedelta(minutes=31 + index),
        )
        for index in range(3)
    ])
    session.add(CodingChallengeOffer(
        course_id=course.id,
        student_id=student_user.id,
        conversation_session_id="long-lived-browser-session",
        trace_id="replacement",
        status="dismissed",
        source="existing",
        title="replacement",
        why_now="replacement",
        languages=["python3"],
        replacement_count=1,
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    from app.services.coding_challenge_service import coding_challenge_service

    assert coding_challenge_service._recent_session_offer_count(
        session,
        course_id=course.id,
        student_id=student_user.id,
        conversation_session_id="long-lived-browser-session",
        now=now,
    ) == 0


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _learning_course(session, teacher_user, student_user) -> Course:
    course = Course(
        fanya_course_id=f"challenge-{uuid.uuid4().hex[:10]}",
        fanya_course_name="算法与数据结构",
        title="算法与数据结构",
        teacher_id=teacher_user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_user.id)
    activate_student_membership(session, course.id, student_user.id)
    session.add(StudentEnrollment(
        student_id=student_user.id,
        course_id=course.id,
        overall_progress=0.0,
        is_active=True,
    ))
    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).first()
    capability.experiment = True
    capability.coding_sandbox = True
    capability.cognitive_analysis = True
    session.add(capability)
    session.commit()
    return course


def test_active_challenge_returns_explicit_empty_state(
    client,
    session,
    teacher_user,
    student_user,
    student_token,
):
    """Missing endpoint or an invented offer must fail this contract."""
    course = _learning_course(session, teacher_user, student_user)

    response = client.get(
        f"{BASE}/active",
        params={"course_id": course.id, "session_id": "learn-session-empty"},
        headers=_auth(student_token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"offer": None, "session": None}


def test_startup_recovery_closes_inactive_guided_episode_without_evidence(
    session,
    teacher_user,
    student_user,
):
    course = _learning_course(session, teacher_user, student_user)
    attempt = ExperimentAttempt(
        course_id=course.id,
        experiment_id="stale-guided-experiment",
        version_id="stale-guided-version",
        student_id=student_user.id,
        interaction_mode="guided_practice",
        source_release_id=None,
        outline_node_id=None,
        last_activity_at=utcnow_aware() - timedelta(minutes=46),
    )
    episode = CodingEvidenceEpisode(
        attempt_id=attempt.attempt_id,
        course_id=course.id,
        student_id=student_user.id,
    )
    session.add(attempt)
    session.add(episode)
    session.commit()

    from app.services.coding_challenge_service import coding_challenge_service

    recovered = coding_challenge_service.recover_inactive_sessions(session)

    assert recovered == 1
    session.refresh(attempt)
    session.refresh(episode)
    assert attempt.status == AttemptStatus.CANCELLED
    assert episode.status == "closed"
    assert episode.close_reason == "inactive_timeout"
    assert episode.evidence_id is None


def test_ready_offer_is_scoped_to_learner_course_and_conversation(
    client,
    session,
    teacher_user,
    student_user,
    student_token,
):
    """Dropping any owner/session predicate would expose the wrong offer."""
    course = _learning_course(session, teacher_user, student_user)
    try:
        from app.services.coding_challenge_service import coding_challenge_service
    except ModuleNotFoundError:
        pytest.fail("CodingChallengeService is not implemented")

    offer = coding_challenge_service.create_ready_offer(
        session,
        course_id=course.id,
        student_id=student_user.id,
        conversation_session_id="learn-session-a",
        trace_id="trace-offer-a",
        concept_id="kn_binary_search",
        title="实现二分查找",
        why_now="把刚讨论的边界条件落实到代码。",
        difficulty="medium",
        estimated_minutes=10,
        languages=["python3"],
        experiment_id="exp_ready_a",
        version_id="expv_ready_a",
        source_release_id=None,
        outline_node_id=None,
    )
    session.commit()

    own = client.get(
        f"{BASE}/active",
        params={"course_id": course.id, "session_id": "learn-session-a"},
        headers=_auth(student_token),
    )
    other_session = client.get(
        f"{BASE}/active",
        params={"course_id": course.id, "session_id": "learn-session-b"},
        headers=_auth(student_token),
    )

    assert own.status_code == 200, own.text
    assert own.json()["data"]["offer"] == {
        "offer_id": offer.offer_id,
        "status": "ready",
        "source": "existing",
        "title": "实现二分查找",
        "why_now": "把刚讨论的边界条件落实到代码。",
        "concept_id": "kn_binary_search",
        "difficulty": "medium",
        "estimated_minutes": 10,
        "languages": ["python3"],
        "task_id": None,
        "actions": {"can_start": True, "can_replace": True, "can_dismiss": True},
        "reason_code": "",
    }
    assert own.json()["data"]["session"] is None
    assert other_session.json()["data"] == {"offer": None, "session": None}


def test_start_offer_pins_verified_version_and_opens_one_guided_episode(
    client,
    session,
    teacher_user,
    student_user,
    student_token,
):
    course = _learning_course(session, teacher_user, student_user)
    definition = ExperimentDefinition(
        course_id=course.id,
        title="实现二分查找",
        description="返回有序数组中目标值的位置。",
        language_whitelist=["python3"],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        origin="teacher",
        visibility="course_catalog",
        created_by=teacher_user.id,
    )
    version = ExperimentVersion(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_number=1,
        is_locked=True,
        is_active=True,
        reference_preview_verified_at=utcnow_aware(),
        starter_code={"python3": "def search(nums, target):\n    pass\n"},
        created_by=teacher_user.id,
    )
    definition.default_version_id = version.version_id
    session.add(definition)
    session.add(version)
    session.flush()

    from app.services.coding_challenge_service import coding_challenge_service

    offer = coding_challenge_service.create_ready_offer(
        session,
        course_id=course.id,
        student_id=student_user.id,
        conversation_session_id="learn-session-start",
        trace_id="trace-start",
        concept_id="kn_binary_search",
        title=definition.title,
        why_now="用代码检验边界条件。",
        difficulty="medium",
        estimated_minutes=10,
        languages=["python3"],
        experiment_id=definition.experiment_id,
        version_id=version.version_id,
        source_release_id=None,
        outline_node_id=None,
    )
    session.commit()

    response = client.post(
        f"{BASE}/offers/{offer.offer_id}/start",
        params={"course_id": course.id},
        json={"return_anchor": {"resource_id": "video-1", "local_time_ms": 14200}},
        headers=_auth(student_token),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["offer"]["status"] == "started"
    assert payload["session"]["interaction_mode"] == "guided_practice"
    assert "version_id" not in payload["session"]
    assert payload["session"]["starter_code"] == "def search(nums, target):\n    pass\n"
    assert payload["session"]["problem"]["description"] == definition.description

    attempt = session.exec(
        select(ExperimentAttempt).where(ExperimentAttempt.attempt_id == payload["session"]["session_id"])
    ).one()
    episodes = session.exec(
        select(CodingEvidenceEpisode).where(CodingEvidenceEpisode.attempt_id == attempt.attempt_id)
    ).all()
    assert attempt.status.value == "in_progress"
    assert attempt.interaction_mode == "guided_practice"
    assert attempt.return_anchor["local_time_ms"] == 14200
    assert len(episodes) == 1
    assert episodes[0].status == "open"

    # Starting twice is idempotent and cannot create a second episode.
    replay = client.post(
        f"{BASE}/offers/{offer.offer_id}/start",
        params={"course_id": course.id},
        json={"return_anchor": {}},
        headers=_auth(student_token),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["session"]["session_id"] == attempt.attempt_id
    assert replay.json()["data"]["offer"]["actions"] == {
        "can_start": False,
        "can_replace": False,
        "can_dismiss": False,
    }
    assert len(session.exec(select(CodingEvidenceEpisode).where(
        CodingEvidenceEpisode.attempt_id == attempt.attempt_id,
    )).all()) == 1

    legacy_run = client.post(
        f"/api/v1/experiments/attempts/{attempt.attempt_id}/runs",
        params={"course_id": course.id},
        json={"language": "python3", "source_code": "print('legacy bypass')"},
        headers={**_auth(student_token), "Idempotency-Key": "legacy-guided-bypass"},
    )
    assert legacy_run.status_code == 409
    session.refresh(attempt)
    assert attempt.status == AttemptStatus.IN_PROGRESS

    active = client.get(
        f"{BASE}/active",
        params={"course_id": course.id, "session_id": "learn-session-start"},
        headers=_auth(student_token),
    )
    assert active.status_code == 200, active.text
    assert active.json()["data"]["session"]["session_id"] == attempt.attempt_id

    attempt.status = AttemptStatus.FINALIZED
    session.add(attempt)
    session.commit()
    restored = client.get(
        f"{BASE}/active",
        params={"course_id": course.id, "session_id": "learn-session-start"},
        headers=_auth(student_token),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"] == {"offer": None, "session": None}


def test_private_ai_definition_is_not_exposed_by_legacy_experiment_catalog(
    client,
    session,
    teacher_user,
    student_user,
    teacher_token,
    student_token,
):
    course = _learning_course(session, teacher_user, student_user)
    catalog = ExperimentDefinition(
        course_id=course.id,
        title="Visible course experiment",
        language_whitelist=["python3"],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        visibility="course_catalog",
        created_by=teacher_user.id,
    )
    private = ExperimentDefinition(
        course_id=course.id,
        title="Private generated challenge",
        language_whitelist=["python3"],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        origin="ai_challenge",
        visibility="student_private",
        owner_student_id=student_user.id,
        expires_at=utcnow_aware() + timedelta(hours=24),
        created_by=student_user.id,
    )
    session.add(catalog)
    session.add(private)
    session.commit()

    for token in (student_token, teacher_token):
        response = client.get(
            f"/api/v1/experiments/course/{course.id}/definitions",
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        ids = {item["experiment_id"] for item in response.json()["data"]["items"]}
        assert catalog.experiment_id in ids
        assert private.experiment_id not in ids

        detail = client.get(
            f"/api/v1/experiments/course/{course.id}/definitions/{private.experiment_id}",
            headers=_auth(token),
        )
        assert detail.status_code == 404

        lab_catalog = client.get(
            "/api/v1/lab/catalog",
            params={"course_id": course.id},
            headers=_auth(token),
        )
        assert lab_catalog.status_code == 200, lab_catalog.text
        lab_ids = {item["experiment_id"] for item in lab_catalog.json()["data"]["items"]}
        assert catalog.experiment_id in lab_ids
        assert private.experiment_id not in lab_ids

def test_run_source_hash_normalizes_formatting_only_revisions(
    session,
    teacher_user,
    student_user,
):
    course = _learning_course(session, teacher_user, student_user)
    definition = ExperimentDefinition(
        course_id=course.id,
        title="Formatting noise",
        language_whitelist=["python3"],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        created_by=teacher_user.id,
    )
    version = ExperimentVersion(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_number=1,
        is_locked=True,
        is_active=True,
        reference_preview_verified_at=utcnow_aware(),
        created_by=teacher_user.id,
    )
    definition.default_version_id = version.version_id
    attempt = ExperimentAttempt(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_id=version.version_id,
        student_id=student_user.id,
        interaction_mode="guided_practice",
    )
    session.add(definition)
    session.add(version)
    session.add(attempt)
    session.commit()

    from app.services.experiment_service import run_service

    first = asyncio.run(run_service.create_run(
        session,
        course_id=course.id,
        attempt_id=attempt.attempt_id,
        language="python3",
        source_code="print('ok')\r\n\r\n",
        student_id=student_user.id,
        idempotency_key="guided-run-a",
    ))
    second = asyncio.run(run_service.create_run(
        session,
        course_id=course.id,
        attempt_id=attempt.attempt_id,
        language="python3",
        source_code="print('ok')   \n",
        student_id=student_user.id,
        idempotency_key="guided-run-b",
    ))

    assert len(first.normalized_source_hash) == 64
    assert second.normalized_source_hash == first.normalized_source_hash
    assert first.evidence_quality["is_effective_revision"] is True
    assert second.evidence_quality["is_effective_revision"] is False
    assert second.evidence_quality["duplicate_source"] is True


def test_same_server_error_signature_does_not_inflate_effective_revisions(
    session,
    teacher_user,
    student_user,
):
    course = _learning_course(session, teacher_user, student_user)
    attempt = ExperimentAttempt(
        course_id=course.id,
        experiment_id="signature-experiment",
        version_id="signature-version",
        student_id=student_user.id,
        interaction_mode="guided_practice",
    )
    first = ExperimentRun(
        course_id=course.id,
        attempt_id=attempt.attempt_id,
        student_id=student_user.id,
        language="python3",
        source_code="print('first')",
        normalized_source_hash="a" * 64,
        evidence_quality={"is_effective_revision": True, "duplicate_source": False},
        outcome=RunOutcome.COMPILATION_ERROR,
        compile_ok=False,
        test_summary={"cases": [{"passed": False, "reason": "compilation_error", "hidden": True}]},
    )
    second = ExperimentRun(
        course_id=course.id,
        attempt_id=attempt.attempt_id,
        student_id=student_user.id,
        language="python3",
        source_code="print('second')",
        normalized_source_hash="b" * 64,
        evidence_quality={"is_effective_revision": True, "duplicate_source": False},
        outcome=RunOutcome.COMPILATION_ERROR,
        compile_ok=False,
        test_summary={"cases": [{"passed": False, "reason": "compilation_error", "hidden": True}]},
    )
    session.add(attempt)
    session.add(first)
    session.commit()

    from app.services.experiment_service import run_service

    run_service.record_terminal_evidence_quality(session, first)
    session.add(second)
    session.flush()
    run_service.record_terminal_evidence_quality(session, second)

    assert first.evidence_quality["is_effective_revision"] is True
    assert second.evidence_quality["is_effective_revision"] is False
    assert second.evidence_quality["duplicate_error_signature"] is True
    assert second.evidence_quality["error_signature"] == first.evidence_quality["error_signature"]


def test_guided_run_endpoint_keeps_attempt_open_and_is_idempotent(
    client,
    session,
    teacher_user,
    student_user,
    student_token,
    monkeypatch,
):
    course = _learning_course(session, teacher_user, student_user)
    definition = ExperimentDefinition(
        course_id=course.id,
        title="Repeatable guided run",
        language_whitelist=["python3"],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        created_by=teacher_user.id,
    )
    version = ExperimentVersion(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_number=1,
        is_locked=True,
        is_active=True,
        reference_preview_verified_at=utcnow_aware(),
        created_by=teacher_user.id,
    )
    definition.default_version_id = version.version_id
    attempt = ExperimentAttempt(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_id=version.version_id,
        student_id=student_user.id,
        interaction_mode="guided_practice",
    )
    session.add(definition)
    session.add(version)
    session.add(attempt)
    session.add(CodingEvidenceEpisode(
        attempt_id=attempt.attempt_id,
        course_id=course.id,
        student_id=student_user.id,
    ))
    session.commit()

    from app.platform.tasks.worker import local_task_worker

    monkeypatch.setattr(local_task_worker, "has_handler", lambda _kind: False)
    endpoint = f"{BASE}/sessions/{attempt.attempt_id}/runs"
    first = client.post(
        endpoint,
        params={"course_id": course.id},
        json={"language": "python3", "source_code": "print(1)"},
        headers={**_auth(student_token), "Idempotency-Key": "guided-api-1"},
    )
    replay = client.post(
        endpoint,
        params={"course_id": course.id},
        json={"language": "python3", "source_code": "print(999)"},
        headers={**_auth(student_token), "Idempotency-Key": "guided-api-1"},
    )
    second = client.post(
        endpoint,
        params={"course_id": course.id},
        json={"language": "python3", "source_code": "print(2)"},
        headers={**_auth(student_token), "Idempotency-Key": "guided-api-2"},
    )

    assert first.status_code == replay.status_code == second.status_code == 202
    assert replay.json()["data"]["run_id"] == first.json()["data"]["run_id"]
    assert second.json()["data"]["run_id"] != first.json()["data"]["run_id"]
    session.refresh(attempt)
    assert attempt.status.value == "in_progress"
    assert len(session.exec(
        select(ExperimentRun).where(ExperimentRun.attempt_id == attempt.attempt_id)
    ).all()) == 2
    premature_close = client.post(
        f"{BASE}/sessions/{attempt.attempt_id}/close",
        params={"course_id": course.id},
        json={"reason": "returned_to_course"},
        headers=_auth(student_token),
    )
    assert premature_close.status_code == 409
    session.refresh(attempt)
    assert attempt.status == AttemptStatus.IN_PROGRESS


def test_close_episode_aggregates_runs_into_one_low_noise_node_evidence(
    client,
    session,
    teacher_user,
    student_user,
    student_token,
):
    course = _learning_course(session, teacher_user, student_user)
    node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_episode_binary_search",
        title="二分查找边界",
        status=CourseKnowledgeNodeStatus.PUBLISHED,
    )
    session.add(node)
    session.flush()
    unrelated_node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_episode_unrelated",
        title="不应被本次挑战污染的节点",
        status=CourseKnowledgeNodeStatus.PUBLISHED,
    )
    session.add(unrelated_node)
    session.flush()
    outline = CourseOutlineVersion(
        course_id=course.id,
        lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
        created_by=teacher_user.id,
    )
    outline_node = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        title="二分查找边界",
        knowledge_graph_node_id=node.node_key,
    )
    release = CourseRelease(
        course_id=course.id,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        outline_version_id=outline.outline_version_id,
        created_by=teacher_user.id,
    )
    definition = ExperimentDefinition(
        course_id=course.id,
        title="Episode aggregate",
        language_whitelist=["python3"],
        knowledge_node_ids=[node.id, unrelated_node.id],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        created_by=teacher_user.id,
    )
    version = ExperimentVersion(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_number=1,
        is_locked=True,
        is_active=True,
        writes_formal_evidence=True,
        reference_preview_verified_at=utcnow_aware(),
        created_by=teacher_user.id,
    )
    definition.default_version_id = version.version_id
    attempt = ExperimentAttempt(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_id=version.version_id,
        student_id=student_user.id,
        interaction_mode="guided_practice",
        source_release_id=release.release_id,
        outline_node_id=outline_node.outline_node_id,
    )
    episode = CodingEvidenceEpisode(
        attempt_id=attempt.attempt_id,
        course_id=course.id,
        student_id=student_user.id,
    )
    runs = [
        ExperimentRun(
            course_id=course.id,
            attempt_id=attempt.attempt_id,
            student_id=student_user.id,
            language="python3",
            source_code="print('infra')",
            normalized_source_hash="a" * 64,
            evidence_quality={"is_effective_revision": True},
            outcome=RunOutcome.SANDBOX_UNAVAILABLE,
            error_code="SANDBOX_UNAVAILABLE",
        ),
        ExperimentRun(
            course_id=course.id,
            attempt_id=attempt.attempt_id,
            student_id=student_user.id,
            language="python3",
            source_code="print('partial')",
            normalized_source_hash="b" * 64,
            evidence_quality={"is_effective_revision": True, "hint_used": True},
            outcome=RunOutcome.WRONG_ANSWER,
            passed_count=2,
            total_count=4,
            score=0.0,
        ),
        ExperimentRun(
            course_id=course.id,
            attempt_id=attempt.attempt_id,
            student_id=student_user.id,
            language="python3",
            source_code="print('partial')  ",
            normalized_source_hash="b" * 64,
            evidence_quality={"is_effective_revision": False, "duplicate_source": True},
            outcome=RunOutcome.WRONG_ANSWER,
            passed_count=2,
            total_count=4,
            score=0.0,
        ),
    ]
    session.add(definition)
    session.add(version)
    session.add(outline)
    session.add(outline_node)
    session.add(release)
    session.add(attempt)
    session.add(episode)
    session.add_all(runs)
    session.commit()

    response = client.post(
        f"{BASE}/sessions/{attempt.attempt_id}/close",
        params={"course_id": course.id},
        json={"reason": "returned_to_course"},
        headers=_auth(student_token),
    )

    assert response.status_code == 200, response.text
    summary = response.json()["data"]["episode"]
    assert summary["run_count"] == 3
    assert summary["valid_run_count"] == 2
    assert summary["effective_revision_count"] == 1
    assert summary["best_score"] == 0.5
    assert summary["final_outcome"] == "wrong_answer"
    assert summary["hint_used"] is True
    evidence = session.exec(select(LearningEvidenceRecord).where(
        LearningEvidenceRecord.source == "coding_episode_finalize_service",
    )).all()
    assert len(evidence) == 1
    assert evidence[0].node_id == node.id
    assert evidence[0].value == 0.5
    assert evidence[0].event_refs == [episode.episode_id, attempt.attempt_id]
    assert runs[0].run_id not in evidence[0].event_refs
    evidence_context = session.exec(select(LearningEvidenceContext).where(
        LearningEvidenceContext.evidence_id == evidence[0].evidence_id,
    )).one()
    assert evidence_context.source_release_id == release.release_id
    assert evidence_context.outline_node_id == outline_node.outline_node_id
    session.refresh(attempt)
    assert attempt.status.value == "finalized"
    assert attempt.final_score == 0.5

    from app.services.cognitive_service import compute_cognitive_state

    state = compute_cognitive_state(session, student_user.id, course.id, node.id)
    assert state.observed_performance_score is None
    assert state.mastery_level == "unknown"
    assert "insufficient_effective_scored_weight" in state.reason_codes

    second_episode = CodingEvidenceEpisode(
        attempt_id="second-guided-attempt",
        course_id=course.id,
        student_id=student_user.id,
        status="closed",
        summary={"hint_used": False},
    )
    session.add(second_episode)
    session.flush()
    session.add(LearningEvidenceRecord(
        evidence_id="ev_second_guided_episode",
        student_id=student_user.id,
        course_id=course.id,
        node_id=node.id,
        evidence_type="coding_execution",
        value=0.5,
        confidence=1.0,
        source="coding_episode_finalize_service",
        event_refs=[second_episode.episode_id, second_episode.attempt_id],
        policy_version="coding-episode-v1",
    ))
    session.commit()
    state_with_two_episodes = compute_cognitive_state(
        session, student_user.id, course.id, node.id,
    )
    assert state_with_two_episodes.hint_dependency == 0.5
    assert "hint_dependency_from_attempt_context" in state_with_two_episodes.reason_codes

    replay = client.post(
        f"{BASE}/sessions/{attempt.attempt_id}/close",
        params={"course_id": course.id},
        json={"reason": "returned_to_course"},
        headers=_auth(student_token),
    )
    assert replay.status_code == 200
    assert session.exec(select(LearningEvidenceRecord).where(
        LearningEvidenceRecord.evidence_id == evidence[0].evidence_id,
    )).one().event_refs == [episode.episode_id, attempt.attempt_id]


def test_close_episode_fails_closed_when_release_identity_is_missing(
    client,
    session,
    teacher_user,
    student_user,
    student_token,
):
    course = _learning_course(session, teacher_user, student_user)
    node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_missing_release_identity",
        title="身份不完整的代码证据",
        status=CourseKnowledgeNodeStatus.PUBLISHED,
    )
    definition = ExperimentDefinition(
        course_id=course.id,
        title="Identity fail closed",
        language_whitelist=["python3"],
        knowledge_node_ids=[node.id],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        created_by=teacher_user.id,
    )
    version = ExperimentVersion(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_number=1,
        is_locked=True,
        is_active=True,
        writes_formal_evidence=True,
        reference_preview_verified_at=utcnow_aware(),
        created_by=teacher_user.id,
    )
    definition.default_version_id = version.version_id
    attempt = ExperimentAttempt(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_id=version.version_id,
        student_id=student_user.id,
        interaction_mode="guided_practice",
        source_release_id=None,
        outline_node_id=None,
    )
    episode = CodingEvidenceEpisode(
        attempt_id=attempt.attempt_id,
        course_id=course.id,
        student_id=student_user.id,
    )
    run = ExperimentRun(
        course_id=course.id,
        attempt_id=attempt.attempt_id,
        student_id=student_user.id,
        language="python3",
        source_code="print('valid result, incomplete identity')",
        normalized_source_hash="c" * 64,
        evidence_quality={"is_effective_revision": True},
        outcome=RunOutcome.ACCEPTED,
        passed_count=1,
        total_count=1,
        score=1.0,
    )
    session.add(node)
    session.add(definition)
    session.add(version)
    session.add(attempt)
    session.add(episode)
    session.add(run)
    session.commit()

    response = client.post(
        f"{BASE}/sessions/{attempt.attempt_id}/close",
        params={"course_id": course.id},
        json={"reason": "returned_to_course"},
        headers=_auth(student_token),
    )

    assert response.status_code == 200, response.text
    summary = response.json()["data"]["episode"]
    assert summary["passed"] is True
    assert summary["evidence_status"] == "identity_incomplete"
    assert summary["reason_codes"] == ["EVIDENCE_IDENTITY_INCOMPLETE"]
    assert response.json()["data"]["evidence_id"] is None
    assert session.exec(select(LearningEvidenceRecord).where(
        LearningEvidenceRecord.source == "coding_episode_finalize_service",
        LearningEvidenceRecord.student_id == student_user.id,
        LearningEvidenceRecord.course_id == course.id,
    )).all() == []
    session.refresh(attempt)
    assert attempt.status == AttemptStatus.FINALIZED
    assert attempt.evidence_id is None


def test_run_view_exposes_bounded_teaching_feedback_without_source_or_hidden_io(
    client,
    session,
    teacher_user,
    student_user,
    student_token,
):
    course = _learning_course(session, teacher_user, student_user)
    definition = ExperimentDefinition(
        course_id=course.id,
        title="Private feedback",
        language_whitelist=["python3"],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        created_by=teacher_user.id,
    )
    version = ExperimentVersion(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_number=1,
        is_locked=True,
        is_active=True,
        reference_preview_verified_at=utcnow_aware(),
        created_by=teacher_user.id,
    )
    definition.default_version_id = version.version_id
    attempt = ExperimentAttempt(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_id=version.version_id,
        student_id=student_user.id,
        interaction_mode="guided_practice",
    )
    episode = CodingEvidenceEpisode(
        attempt_id=attempt.attempt_id,
        course_id=course.id,
        student_id=student_user.id,
    )
    run = ExperimentRun(
        course_id=course.id,
        attempt_id=attempt.attempt_id,
        student_id=student_user.id,
        language="python3",
        source_code="SECRET_STUDENT_SOURCE",
        outcome=RunOutcome.WRONG_ANSWER,
        passed_count=1,
        total_count=2,
        test_summary={"cases": [
            {"case_name": "public", "passed": True, "hidden": False, "stdin": "1", "expected": "1", "actual": "1"},
            {"case_name": "hidden_123", "passed": False, "hidden": True, "reason": "wrong_answer"},
        ]},
        runtime_message="",
    )
    session.add(definition)
    session.add(version)
    session.add(attempt)
    session.add(episode)
    session.add(run)
    session.commit()

    from app.services.coding_eduagent_service import coding_eduagent

    coding_eduagent.diagnose_run(
        session,
        course_id=course.id,
        student_id=student_user.id,
        run_id=run.run_id,
    )
    session.commit()

    response = client.get(
        f"{BASE}/runs/{run.run_id}",
        params={"course_id": course.id},
        headers=_auth(student_token),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["result"]["outcome"] == "wrong_answer"
    assert payload["result"]["passed_count"] == 1
    assert payload["teaching_feedback"]["status"] == "ready"
    assert set(payload["teaching_feedback"]) == {
        "status", "result_overview", "done_well", "current_issue",
        "next_step", "optional_hint", "reason_codes", "policy_version",
    }
    assert payload["optional_hint_available"] is True
    assert payload["teaching_feedback"]["optional_hint"] is None
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "SECRET_STUDENT_SOURCE" not in serialized
    assert "source_code" not in serialized
    assert "hidden input" not in serialized
    assert payload["result"]["tests"][1] == {
        "case_name": "hidden_123",
        "passed": False,
        "reason": "wrong_answer",
        "hidden": True,
    }

    reveal = client.post(
        f"{BASE}/runs/{run.run_id}/hint",
        params={"course_id": course.id},
        headers=_auth(student_token),
    )
    assert reveal.status_code == 200, reveal.text
    revealed = reveal.json()["data"]
    assert revealed["teaching_feedback"]["optional_hint"]
    session.refresh(run)
    assert run.evidence_quality["hint_used"] is True
