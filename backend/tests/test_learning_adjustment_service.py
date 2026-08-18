"""Deterministic target resolution for learning adjustments."""
from __future__ import annotations

from datetime import datetime
import json
import uuid

import pytest
from sqlmodel import Session, select

import app.services.learning_adjustment_service as learning_adjustment_module
from app.core.security import get_password_hash
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import CourseOutlineNode
from app.models.media_release_model import (
    MediaRelease,
    MediaReleaseCue,
    MediaReleaseItem,
    MediaReleaseStatus,
)
from app.models.user_model import User, UserRole
from app.schemas.learning_adjustment import QuestionObservation, ReturnAnchor
from app.services.learning_adjustment_service import (
    LearningAdjustmentConflict,
    learning_adjustment_service,
)


def _setup_frozen_course(session: Session) -> tuple[Course, User, dict[str, str]]:
    tag = uuid.uuid4().hex[:10]
    ids = {
        "course_release_id": f"cr_adjustment_{tag}",
        "media_release_id": f"mrel_adjustment_{tag}",
        "current_item_id": f"mrit_current_{tag}",
        "prerequisite_item_id": f"mrit_prerequisite_{tag}",
        "outline_version_id": f"ov_adjustment_{tag}",
        "current_outline_node_id": f"on_current_{tag}",
        "prerequisite_outline_node_id": f"on_prerequisite_{tag}",
    }
    teacher = User(
        username=f"adjustment-teacher-{datetime.now().timestamp()}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(teacher)
    session.flush()
    course = Course(
        fanya_course_id=f"adjustment-{datetime.now().timestamp()}",
        fanya_course_name="Adjustment course",
        title="Adjustment course",
        teacher_id=teacher.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.flush()
    release = CourseRelease(
        release_id=ids["course_release_id"],
        course_id=course.id,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        outline_version_id=ids["outline_version_id"],
        media_snapshot={"media_release_id": ids["media_release_id"]},
    )
    session.add(release)
    current = CourseOutlineNode(
        outline_node_id=ids["current_outline_node_id"],
        outline_version_id=ids["outline_version_id"],
        course_id=course.id,
        knowledge_graph_node_id="concept-current",
        title="Current",
    )
    prerequisite = CourseOutlineNode(
        outline_node_id=ids["prerequisite_outline_node_id"],
        outline_version_id=ids["outline_version_id"],
        course_id=course.id,
        knowledge_graph_node_id="concept-prerequisite",
        title="Prerequisite",
    )
    session.add(current)
    session.add(prerequisite)
    media = MediaRelease(
        release_id=ids["media_release_id"],
        course_id=course.id,
        status=MediaReleaseStatus.ACTIVE,
        created_by=teacher.id,
        release_metadata={"audio_playlist_schema": "audio-playlist/v1"},
    )
    session.add(media)
    session.flush()
    current_item = MediaReleaseItem(
        item_id=ids["current_item_id"],
        release_id=media.release_id,
        course_id=course.id,
        node_id=1001,
        outline_node_id=current.outline_node_id,
        duration_ms=120_000,
        audio_object_key="course/current.mp3",
        status="ready",
    )
    prerequisite_item = MediaReleaseItem(
        item_id=ids["prerequisite_item_id"],
        release_id=media.release_id,
        course_id=course.id,
        node_id=1002,
        outline_node_id=prerequisite.outline_node_id,
        duration_ms=120_000,
        audio_object_key="course/prerequisite.mp3",
        status="ready",
    )
    session.add(current_item)
    session.add(prerequisite_item)
    session.add(MediaReleaseCue(
        release_id=media.release_id,
        course_id=course.id,
        node_id=1001,
        cue_index=0,
        start_time=8.2,
        end_time=18.0,
        ppt_page=4,
        audio_object_key="course/current.mp3",
        cue_metadata={"time_basis": "item_local_v1", "outline_node_id": current.outline_node_id},
    ))
    session.add(MediaReleaseCue(
        release_id=media.release_id,
        course_id=course.id,
        node_id=1002,
        cue_index=0,
        start_time=48.2,
        end_time=65.0,
        ppt_page=6,
        audio_object_key="course/prerequisite.mp3",
        cue_metadata={"time_basis": "item_local_v1", "outline_node_id": prerequisite.outline_node_id},
    ))
    session.commit()
    return course, teacher, ids


def _observation(ids: dict[str, str]) -> QuestionObservation:
    return QuestionObservation(
        course_release_id=ids["course_release_id"],
        media_release_id=ids["media_release_id"],
        media_release_item_id=ids["current_item_id"],
        outline_node_id=ids["current_outline_node_id"],
        local_time_ms=8_200,
        page=4,
        global_time_ms=8_200,
    )


class _FrozenPlaylistStorage:
    """Minimal immutable playlist reader used only by coordinate tests."""

    def __init__(self, raw_playlist: dict[str, object]) -> None:
        self._raw_playlist = raw_playlist

    def get(self, object_key: str) -> bytes:
        assert object_key == "course/adjustment-playlist.json"
        return json.dumps(self._raw_playlist).encode("utf-8")


def _install_frozen_playlist(session: Session, ids: dict[str, str]) -> _FrozenPlaylistStorage:
    media = session.exec(select(MediaRelease).where(
        MediaRelease.release_id == ids["media_release_id"]
    )).one()
    media.audio_playlist_object_key = "course/adjustment-playlist.json"
    session.add(media)
    session.commit()
    return _FrozenPlaylistStorage({
        "schema": "audio-playlist/v1",
        "items": [
            {"item_id": ids["current_item_id"], "offset_ms": 0, "duration_ms": 120_000},
            {"item_id": ids["prerequisite_item_id"], "offset_ms": 120_000, "duration_ms": 120_000},
        ],
    })


def test_prerequisite_review_uses_frozen_cue_item_local_coordinate(session: Session) -> None:
    course, _, ids = _setup_frozen_course(session)

    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
    )

    assert result.reason_code is None
    assert result.review_target is not None
    assert result.review_target.media_release_item_id == ids["prerequisite_item_id"]
    assert result.review_target.local_time_ms == 48_200
    assert result.review_target.page == 6


def test_requested_jump_targets_the_learner_requested_node(session: Session) -> None:
    """学生主动请求学习某知识点（requested_jump）时，跳转目标是请求的节点。

    requested_jump 不要求该节点与当前节点存在"已确认薄弱"关系：
    学生可能想先了解任何前置/后继知识点（2026-08-18）。
    """
    course, _, ids = _setup_frozen_course(session)

    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=_observation(ids),
        teaching_action="requested_jump",
        current_concept_id="concept-current",
        prerequisites=[],
        weak_concepts=[],
        requested_concept_id="concept-prerequisite",
    )

    assert result.reason_code is None
    assert result.review_target is not None
    assert result.review_target.media_release_item_id == ids["prerequisite_item_id"]
    assert result.review_target.outline_node_id == ids["prerequisite_outline_node_id"]
    assert result.review_target.local_time_ms == 48_200
    assert result.review_target.page == 6


def test_requested_jump_unknown_node_is_a_safe_noop(session: Session) -> None:
    """学生请求的节点不在当前课程 outline 中时，不产出跳转目标（安全 no-op）。"""
    course, _, ids = _setup_frozen_course(session)

    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=_observation(ids),
        teaching_action="requested_jump",
        current_concept_id="concept-current",
        prerequisites=[],
        weak_concepts=[],
        requested_concept_id="concept-not-in-course",
    )

    assert result.review_target is None
    assert result.reason_code == "MEDIA_TARGET_UNAVAILABLE"


def test_requested_jump_falls_back_to_title_keyword_without_outline_mapping(
    session: Session,
) -> None:
    """outline 无 knowledge_graph_node_id 映射时，图谱标题↔outline 标题共享关键词回退。

    课程5 的 outline 映射为空（数据缺口），学生请求图谱节点"传递函数"时，
    通过标题关键词定位到 outline"传递函数的定义与性质"及其媒体 item（2026-08-18）。
    """
    from app.models.graph_production_model import CourseKnowledgeNode

    course, _, ids = _setup_frozen_course(session)
    # 无映射的 outline（knowledge_graph_node_id 留空）+ 对应媒体 item/cue
    outline_no_map = CourseOutlineNode(
        outline_node_id=f"on_transfer_{uuid.uuid4().hex[:8]}",
        outline_version_id=ids["outline_version_id"],
        course_id=course.id,
        title="传递函数的定义与性质",
    )
    session.add(outline_no_map)
    session.add(CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_transfer_title",
        title="传递函数",
    ))
    media = session.exec(select(MediaRelease).where(
        MediaRelease.release_id == ids["media_release_id"]
    )).one()
    session.add(MediaReleaseItem(
        item_id=f"mrit_transfer_{uuid.uuid4().hex[:8]}",
        release_id=media.release_id,
        course_id=course.id,
        node_id=1003,
        outline_node_id=outline_no_map.outline_node_id,
        duration_ms=120_000,
        audio_object_key="course/transfer.mp3",
        status="ready",
    ))
    session.add(MediaReleaseCue(
        release_id=media.release_id,
        course_id=course.id,
        node_id=1003,
        cue_index=0,
        start_time=12.5,
        end_time=30.0,
        ppt_page=3,
        audio_object_key="course/transfer.mp3",
        cue_metadata={"time_basis": "item_local_v1", "outline_node_id": outline_no_map.outline_node_id},
    ))
    session.commit()

    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=_observation(ids),
        teaching_action="requested_jump",
        current_concept_id="concept-current",
        prerequisites=[],
        weak_concepts=[],
        requested_concept_id="kn_transfer_title",
    )

    assert result.reason_code is None
    assert result.review_target is not None
    assert result.review_target.outline_node_id == outline_no_map.outline_node_id
    assert result.review_target.local_time_ms == 12_500
    assert result.review_target.page == 3


def test_requested_jump_skips_candidates_without_playable_item(session: Session) -> None:
    """标题回退命中多个同主题 outline 时，跳过无媒体项、取第一个有 ready item 的。

    课程5 场景：图谱节点"传递函数"命中"传递函数与图形表示"（无媒体 item）
    与"传递函数的定义与性质"（有媒体 item），目标应取后者（2026-08-18）。
    """
    from app.models.graph_production_model import CourseKnowledgeNode

    course, _, ids = _setup_frozen_course(session)
    # 无媒体 item 的同主题 outline（标题也共享"传递函数"关键词）
    outline_no_item = CourseOutlineNode(
        outline_node_id=f"on_noitem_{uuid.uuid4().hex[:8]}",
        outline_version_id=ids["outline_version_id"],
        course_id=course.id,
        title="传递函数与图形表示",
    )
    session.add(outline_no_item)
    # 有媒体 item 的同主题 outline + 对应 item/cue
    outline_with_item = CourseOutlineNode(
        outline_node_id=f"on_withitem_{uuid.uuid4().hex[:8]}",
        outline_version_id=ids["outline_version_id"],
        course_id=course.id,
        title="传递函数的定义与性质",
    )
    session.add(outline_with_item)
    session.add(CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_transfer_multi",
        title="传递函数",
    ))
    media = session.exec(select(MediaRelease).where(
        MediaRelease.release_id == ids["media_release_id"]
    )).one()
    session.add(MediaReleaseItem(
        item_id=f"mrit_multi_{uuid.uuid4().hex[:8]}",
        release_id=media.release_id,
        course_id=course.id,
        node_id=1004,
        outline_node_id=outline_with_item.outline_node_id,
        duration_ms=120_000,
        audio_object_key="course/transfer-multi.mp3",
        status="ready",
    ))
    session.add(MediaReleaseCue(
        release_id=media.release_id,
        course_id=course.id,
        node_id=1004,
        cue_index=0,
        start_time=9.0,
        end_time=25.0,
        ppt_page=2,
        audio_object_key="course/transfer-multi.mp3",
        cue_metadata={"time_basis": "item_local_v1", "outline_node_id": outline_with_item.outline_node_id},
    ))
    session.commit()

    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=_observation(ids),
        teaching_action="requested_jump",
        current_concept_id="concept-current",
        prerequisites=[],
        weak_concepts=[],
        requested_concept_id="kn_transfer_multi",
    )

    assert result.reason_code is None
    assert result.review_target is not None
    assert result.review_target.outline_node_id == outline_with_item.outline_node_id
    assert result.review_target.local_time_ms == 9_000
    assert result.review_target.page == 2


def test_stale_question_observation_never_falls_forward_to_newest_media(session: Session) -> None:
    course, _, ids = _setup_frozen_course(session)
    stale = _observation(ids).model_copy(update={"media_release_item_id": "mrit_not_current"})

    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=stale,
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[],
        weak_concepts=[],
    )

    assert result.review_target is None
    assert result.reason_code == "QUESTION_OBSERVATION_STALE"


def test_question_observation_must_match_frozen_cue_page_and_time(session: Session) -> None:
    course, _, ids = _setup_frozen_course(session)
    mismatched = _observation(ids).model_copy(update={"page": 5})

    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=mismatched,
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[],
        weak_concepts=[],
    )

    assert result.review_target is None
    assert result.reason_code == "QUESTION_OBSERVATION_STALE"


def test_question_observation_rejects_mismatched_frozen_playlist_clock(
    session: Session,
) -> None:
    """A supplied global clock must agree with the immutable item offset."""
    course, _, ids = _setup_frozen_course(session)
    storage = _install_frozen_playlist(session, ids)
    forged = _observation(ids).model_copy(update={"global_time_ms": 8_201})

    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=forged,
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[],
        weak_concepts=[],
        storage=storage,
    )

    assert result.review_target is None
    assert result.reason_code == "QUESTION_OBSERVATION_STALE"


def test_action_without_redirect_is_a_safe_noop(session: Session) -> None:
    course, _, ids = _setup_frozen_course(session)
    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=_observation(ids),
        teaching_action="normal_answer",
        current_concept_id="concept-current",
        prerequisites=[],
        weak_concepts=[],
    )
    assert result.review_target is None
    assert result.reason_code == "ACTION_DOES_NOT_REQUIRE_REVIEW"


@pytest.mark.parametrize(
    "action",
    ["diagnostic_question", "misconception_repair", "hint_scaffolding"],
)
def test_non_prerequisite_actions_never_offer_review(
    session: Session, action: str
) -> None:
    """回归（2026-08-16）：仅 prerequisite_review 可产出回顾提案。

    诊断提问 / 纠错 / 支架等动作的目标是当前知识点，不是"回退到前置知识点"。
    即使观测有效、薄弱前置存在，也不得弹出"建议回顾第 X 页"。
    """
    course, _, ids = _setup_frozen_course(session)
    result = learning_adjustment_service.resolve_review_target(
        session,
        course_id=course.id,
        observation=_observation(ids),
        teaching_action=action,
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
    )
    assert result.review_target is None
    assert result.reason_code == "ACTION_DOES_NOT_REQUIRE_REVIEW"


def test_acceptance_captures_click_time_anchor_and_return_is_explicit(session: Session) -> None:
    """``applied`` means learner acceptance, not a claimed browser seek."""
    course, teacher, ids = _setup_frozen_course(session)
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
    )

    assert proposal is not None
    assert proposal.status.value == "proposed"
    assert proposal.return_anchor is None

    accepted = learning_adjustment_service.accept_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        adjustment_id=proposal.adjustment_id,
        return_anchor=ReturnAnchor(
            course_release_id=ids["course_release_id"],
            media_release_id=ids["media_release_id"],
            media_release_item_id=ids["current_item_id"],
            outline_node_id=ids["current_outline_node_id"],
            local_time_ms=10_170,
            page=4,
            global_time_ms=10_170,
        ),
        idempotency_key="apply-click-time-anchor",
    )

    assert accepted.status.value == "applied"
    assert accepted.return_anchor is not None
    assert accepted.return_anchor.local_time_ms == 10_170
    assert accepted.review_target.local_time_ms == 48_200

    returned = learning_adjustment_service.mark_returned(
        session,
        course_id=course.id,
        student_id=teacher.id,
        adjustment_id=proposal.adjustment_id,
        idempotency_key="return-click-time-anchor",
    )
    assert returned.status.value == "returned"


def test_compatibility_lookup_is_scoped_to_the_existing_validated_turn(session: Session) -> None:
    """A legacy ``qaRecordId`` may only resolve the originating agent trace.

    The lookup returns the metadata-only proposal.  Supplement text remains in
    the separately governed Conversation Domain and is never copied here.
    """
    course, teacher, ids = _setup_frozen_course(session)
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
        source_trace_id="compat-trace-1",
    )

    assert proposal is not None
    matched = learning_adjustment_service.find_compatibility_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        trace_id="compat-trace-1",
    )
    assert matched is not None
    assert matched.adjustment_id == proposal.adjustment_id

    assert learning_adjustment_service.find_compatibility_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        trace_id="another-trace",
    ) is None


def test_compatibility_lookup_rejects_a_no_longer_playable_review_target(session: Session) -> None:
    """A trace match is insufficient when the frozen review item is unavailable."""
    course, teacher, ids = _setup_frozen_course(session)
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
        source_trace_id="compat-stale-target",
    )
    assert proposal is not None
    review_item = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.item_id == ids["prerequisite_item_id"]
    )).one()
    review_item.status = "failed"
    session.add(review_item)
    session.commit()

    assert learning_adjustment_service.find_compatibility_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        trace_id="compat-stale-target",
    ) is None


def test_acceptance_rejects_return_anchor_without_matching_frozen_cue(session: Session) -> None:
    """A click-time anchor is valid only on the immutable item's frozen Cue."""
    course, teacher, ids = _setup_frozen_course(session)
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
    )
    assert proposal is not None

    with pytest.raises(LearningAdjustmentConflict, match="RETURN_ANCHOR_INVALID"):
        learning_adjustment_service.accept_proposal(
            session,
            course_id=course.id,
            student_id=teacher.id,
            adjustment_id=proposal.adjustment_id,
            return_anchor=ReturnAnchor(
                course_release_id=ids["course_release_id"],
                media_release_id=ids["media_release_id"],
                media_release_item_id=ids["current_item_id"],
                outline_node_id=ids["current_outline_node_id"],
                local_time_ms=10_170,
                page=5,
            ),
            idempotency_key="apply-invalid-cue-page",
        )


def test_acceptance_rejects_return_anchor_with_forged_playlist_clock(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The click-time anchor cannot pair a valid local Cue with another clock."""
    course, teacher, ids = _setup_frozen_course(session)
    storage = _install_frozen_playlist(session, ids)
    monkeypatch.setattr(learning_adjustment_module, "get_object_storage", lambda: storage)
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
    )
    assert proposal is not None

    with pytest.raises(LearningAdjustmentConflict, match="RETURN_ANCHOR_INVALID"):
        learning_adjustment_service.accept_proposal(
            session,
            course_id=course.id,
            student_id=teacher.id,
            adjustment_id=proposal.adjustment_id,
            return_anchor=ReturnAnchor(
                course_release_id=ids["course_release_id"],
                media_release_id=ids["media_release_id"],
                media_release_item_id=ids["current_item_id"],
                outline_node_id=ids["current_outline_node_id"],
                local_time_ms=10_170,
                page=4,
                global_time_ms=10_171,
            ),
            idempotency_key="apply-forged-global-clock",
        )


def test_acceptance_rejects_withdrawn_media_release(session: Session) -> None:
    """The active CourseRelease is insufficient when its media release is no longer active."""
    course, teacher, ids = _setup_frozen_course(session)
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
    )
    assert proposal is not None
    media = session.exec(select(MediaRelease).where(
        MediaRelease.release_id == ids["media_release_id"]
    )).one()
    media.status = MediaReleaseStatus.WITHDRAWN
    session.add(media)
    session.commit()

    with pytest.raises(LearningAdjustmentConflict, match="ADJUSTMENT_RELEASE_STALE"):
        learning_adjustment_service.accept_proposal(
            session,
            course_id=course.id,
            student_id=teacher.id,
            adjustment_id=proposal.adjustment_id,
            return_anchor=ReturnAnchor(
                course_release_id=ids["course_release_id"],
                media_release_id=ids["media_release_id"],
                media_release_item_id=ids["current_item_id"],
                outline_node_id=ids["current_outline_node_id"],
                local_time_ms=10_170,
                page=4,
            ),
            idempotency_key="apply-withdrawn-media",
        )


def test_release_change_invalidates_pending_adjustment_before_acceptance(session: Session) -> None:
    course, teacher, ids = _setup_frozen_course(session)
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
    )
    assert proposal is not None

    release = session.exec(
        select(CourseRelease).where(CourseRelease.release_id == ids["course_release_id"])
    ).one()
    release.is_active = False
    session.add(release)
    session.commit()

    with pytest.raises(Exception, match="ADJUSTMENT_RELEASE_STALE"):
        learning_adjustment_service.accept_proposal(
            session,
            course_id=course.id,
            student_id=teacher.id,
            adjustment_id=proposal.adjustment_id,
            return_anchor=ReturnAnchor(
                course_release_id=ids["course_release_id"],
                media_release_id=ids["media_release_id"],
                media_release_item_id=ids["current_item_id"],
                outline_node_id=ids["current_outline_node_id"],
                local_time_ms=10_170,
                page=5,
            ),
            idempotency_key="apply-after-release-change",
        )


def test_recent_adjustments_omit_release_stale_records(session: Session) -> None:
    """Refresh recovery must not offer a review target from an old release."""
    course, teacher, ids = _setup_frozen_course(session)
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
    )
    assert proposal is not None

    release = session.exec(
        select(CourseRelease).where(CourseRelease.release_id == ids["course_release_id"])
    ).one()
    release.is_active = False
    session.add(release)
    session.commit()

    recent = learning_adjustment_service.list_recent(
        session,
        course_id=course.id,
        student_id=teacher.id,
    )

    assert recent == []


def test_recent_adjustments_omit_accepted_review_when_return_anchor_is_unavailable(
    session: Session,
) -> None:
    """Refresh must not offer a review that can no longer restore the learner."""
    course, teacher, ids = _setup_frozen_course(session)
    proposal = learning_adjustment_service.create_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        observation=_observation(ids),
        teaching_action="prerequisite_review",
        current_concept_id="concept-current",
        prerequisites=[{"concept_id": "concept-prerequisite"}],
        weak_concepts=[{"concept_id": "concept-prerequisite"}],
        reason_codes=("EXPLANATION_NEED_HIGH",),
    )
    assert proposal is not None
    learning_adjustment_service.accept_proposal(
        session,
        course_id=course.id,
        student_id=teacher.id,
        adjustment_id=proposal.adjustment_id,
        return_anchor=ReturnAnchor(
            course_release_id=ids["course_release_id"],
            media_release_id=ids["media_release_id"],
            media_release_item_id=ids["current_item_id"],
            outline_node_id=ids["current_outline_node_id"],
            local_time_ms=10_170,
            page=4,
        ),
        idempotency_key="apply-return-anchor-recovery",
    )
    return_item = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.item_id == ids["current_item_id"]
    )).one()
    return_item.status = "failed"
    session.add(return_item)
    session.commit()

    recent = learning_adjustment_service.list_recent(
        session,
        course_id=course.id,
        student_id=teacher.id,
    )

    assert recent == []
