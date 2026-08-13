"""Deterministic, release-pinned learning adjustment operations.

No LLM, editable draft, or client supplied review target participates in target
resolution.  The service holds no session and is safe to wrap in a
request-scoped Agent Port.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from sqlmodel import Session, select

from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_outline_model import CourseOutlineNode
from app.models.learning_adjustment_model import LearningAdjustmentRecord
from app.models.media_release_model import (
    MediaRelease,
    MediaReleaseCue,
    MediaReleaseItem,
    MediaReleaseStatus,
)
from app.schemas.learning_adjustment import (
    LearningAdjustmentProposal,
    LearningAdjustmentStatus,
    QuestionObservation,
    ReturnAnchor,
    ReviewTarget,
)
from app.core.time_utils import utcnow_aware
from app.services.object_storage import ObjectStorageProvider, get_object_storage


@dataclass(frozen=True)
class ReviewTargetResolution:
    review_target: ReviewTarget | None
    reason_code: str | None = None


class LearningAdjustmentConflict(ValueError):
    """A safe, client-addressable state or release conflict."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LearningAdjustmentService:
    """Resolve a target only from an active immutable course/media release pair."""

    _REDIRECT_ACTIONS = {
        "prerequisite_review",
        "misconception_repair",
        "hint_scaffolding",
        "diagnostic_question",
    }

    def create_proposal(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        observation: QuestionObservation,
        teaching_action: str,
        current_concept_id: str | None,
        prerequisites: Iterable[Mapping[str, Any]],
        weak_concepts: Iterable[Mapping[str, Any]],
        reason_codes: tuple[str, ...],
        source_trace_id: str | None = None,
        recommended_playback_rate: float = 0.85,
    ) -> LearningAdjustmentProposal | None:
        """Persist a review proposal only after resolving a frozen target.

        A missing or ambiguous target is intentionally a no-op.  The teaching
        answer remains valid, but the learner never receives an unsafe jump.
        """
        resolution = self.resolve_review_target(
            session,
            course_id=course_id,
            observation=observation,
            teaching_action=teaching_action,
            current_concept_id=current_concept_id,
            prerequisites=prerequisites,
            weak_concepts=weak_concepts,
        )
        if resolution.review_target is None:
            return None
        target = resolution.review_target
        # Construct the public contract first so bounds are enforced before
        # any durable state is written.
        candidate = LearningAdjustmentProposal(
            adjustment_id="lad_" + uuid.uuid4().hex,
            status=LearningAdjustmentStatus.PROPOSED,
            question_observation=observation,
            review_target=target,
            teaching_action=teaching_action,
            reason_codes=reason_codes,
            recommended_playback_rate=recommended_playback_rate,
            requires_confirmation=True,
        )
        record = LearningAdjustmentRecord(
            adjustment_id=candidate.adjustment_id,
            course_id=course_id,
            student_id=student_id,
            source_trace_id=self._bounded_trace_id(source_trace_id),
            status=LearningAdjustmentStatus.PROPOSED.value,
            question_course_release_id=observation.course_release_id,
            question_media_release_id=observation.media_release_id,
            question_media_release_item_id=observation.media_release_item_id,
            question_outline_node_id=observation.outline_node_id,
            question_local_time_ms=observation.local_time_ms,
            question_page=observation.page,
            question_global_time_ms=observation.global_time_ms,
            review_course_release_id=target.course_release_id,
            review_media_release_id=target.media_release_id,
            review_media_release_item_id=target.media_release_item_id,
            review_outline_node_id=target.outline_node_id,
            review_local_time_ms=target.local_time_ms,
            review_page=target.page,
            review_global_time_ms=target.global_time_ms,
            teaching_action=teaching_action,
            reason_codes=list(candidate.reason_codes),
            recommended_playback_rate=candidate.recommended_playback_rate,
            requires_confirmation=True,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return self._proposal_from_record(record)

    @staticmethod
    def _bounded_trace_id(value: str | None) -> str | None:
        """Keep compatibility correlation metadata bounded and non-contentful."""
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        return candidate[:128] or None

    def find_compatibility_proposal(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        trace_id: str,
    ) -> LearningAdjustmentProposal | None:
        """Find only a proposal produced by this learner's validated turn.

        The matching answer remains exclusively in ``conversation_messages``.
        This method intentionally exposes no message text, citations, or raw
        runtime state to the legacy compatibility adapter.
        """
        bounded_trace_id = self._bounded_trace_id(trace_id)
        if bounded_trace_id is None:
            return None
        record = session.exec(
            select(LearningAdjustmentRecord)
            .where(
                LearningAdjustmentRecord.course_id == course_id,
                LearningAdjustmentRecord.student_id == student_id,
                LearningAdjustmentRecord.source_trace_id == bounded_trace_id,
                LearningAdjustmentRecord.declined_at.is_(None),
                LearningAdjustmentRecord.invalidated_at.is_(None),
            )
            .order_by(LearningAdjustmentRecord.created_at.desc())
        ).first()
        if record is None:
            return None
        try:
            self._assert_record_release_active(session, record)
        except LearningAdjustmentConflict:
            return None
        return self._proposal_from_record(record)

    def accept_proposal(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        adjustment_id: str,
        return_anchor: ReturnAnchor,
        idempotency_key: str,
    ) -> LearningAdjustmentProposal:
        """Record learner acceptance, never a browser-navigation assertion."""
        record = self._load_owned_record(
            session, course_id=course_id, student_id=student_id, adjustment_id=adjustment_id
        )
        if record.status == LearningAdjustmentStatus.APPLIED.value:
            if record.apply_idempotency_key == idempotency_key:
                return self._proposal_from_record(record)
            raise LearningAdjustmentConflict("ADJUSTMENT_ALREADY_ACCEPTED")
        if record.status == LearningAdjustmentStatus.RETURNED.value:
            raise LearningAdjustmentConflict("ADJUSTMENT_ALREADY_RETURNED")
        if record.declined_at is not None:
            raise LearningAdjustmentConflict("ADJUSTMENT_DISMISSED")
        self._assert_record_release_active(session, record)
        self._assert_click_anchor_valid(session, record, return_anchor)
        now = utcnow_aware()
        record.status = LearningAdjustmentStatus.APPLIED.value
        record.apply_idempotency_key = idempotency_key
        record.return_course_release_id = return_anchor.course_release_id
        record.return_media_release_id = return_anchor.media_release_id
        record.return_media_release_item_id = return_anchor.media_release_item_id
        record.return_outline_node_id = return_anchor.outline_node_id
        record.return_local_time_ms = return_anchor.local_time_ms
        record.return_page = return_anchor.page
        record.return_global_time_ms = return_anchor.global_time_ms
        record.applied_at = now
        record.updated_at = now
        session.add(record)
        session.commit()
        session.refresh(record)
        return self._proposal_from_record(record)

    def mark_returned(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        adjustment_id: str,
        idempotency_key: str,
    ) -> LearningAdjustmentProposal:
        """Record the learner's voluntary return after review."""
        record = self._load_owned_record(
            session, course_id=course_id, student_id=student_id, adjustment_id=adjustment_id
        )
        if record.status == LearningAdjustmentStatus.RETURNED.value:
            if record.return_idempotency_key == idempotency_key:
                return self._proposal_from_record(record)
            raise LearningAdjustmentConflict("ADJUSTMENT_ALREADY_RETURNED")
        if record.status != LearningAdjustmentStatus.APPLIED.value:
            raise LearningAdjustmentConflict("ADJUSTMENT_NOT_ACCEPTED")
        self._assert_record_release_active(session, record)
        now = utcnow_aware()
        record.status = LearningAdjustmentStatus.RETURNED.value
        record.return_idempotency_key = idempotency_key
        record.returned_at = now
        record.updated_at = now
        session.add(record)
        session.commit()
        session.refresh(record)
        return self._proposal_from_record(record)

    def dismiss_proposal(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        adjustment_id: str,
        idempotency_key: str,
    ) -> LearningAdjustmentProposal:
        """Dismiss without introducing a fourth lifecycle status."""
        record = self._load_owned_record(
            session, course_id=course_id, student_id=student_id, adjustment_id=adjustment_id
        )
        if record.declined_at is not None:
            if record.dismiss_idempotency_key == idempotency_key:
                return self._proposal_from_record(record)
            raise LearningAdjustmentConflict("ADJUSTMENT_ALREADY_DISMISSED")
        if record.status != LearningAdjustmentStatus.PROPOSED.value:
            raise LearningAdjustmentConflict("ADJUSTMENT_NOT_DISMISSIBLE")
        now = utcnow_aware()
        record.dismiss_idempotency_key = idempotency_key
        record.declined_at = now
        record.updated_at = now
        session.add(record)
        session.commit()
        session.refresh(record)
        return self._proposal_from_record(record)

    @staticmethod
    def _load_owned_record(
        session: Session, *, course_id: int, student_id: int, adjustment_id: str
    ) -> LearningAdjustmentRecord:
        record = session.exec(select(LearningAdjustmentRecord).where(
            LearningAdjustmentRecord.course_id == course_id,
            LearningAdjustmentRecord.student_id == student_id,
            LearningAdjustmentRecord.adjustment_id == adjustment_id,
        )).first()
        if record is None:
            # The public HTTP adapter intentionally maps this to 404 so an
            # unauthorised learner cannot distinguish another learner's row.
            raise LearningAdjustmentConflict("ADJUSTMENT_NOT_FOUND")
        return record

    def _assert_record_release_active(
        self, session: Session, record: LearningAdjustmentRecord
    ) -> None:
        active = self._active_course_release(session, record.course_id)
        if active is None or active.release_id != record.review_course_release_id:
            self._invalidate(session, record, "ADJUSTMENT_RELEASE_STALE")
            raise LearningAdjustmentConflict("ADJUSTMENT_RELEASE_STALE")
        media_release_id = str((active.media_snapshot or {}).get("media_release_id") or "")
        if media_release_id != record.review_media_release_id:
            self._invalidate(session, record, "ADJUSTMENT_RELEASE_STALE")
            raise LearningAdjustmentConflict("ADJUSTMENT_RELEASE_STALE")
        media_release = session.exec(select(MediaRelease).where(
            MediaRelease.course_id == record.course_id,
            MediaRelease.release_id == record.review_media_release_id,
            MediaRelease.status == MediaReleaseStatus.ACTIVE,
        )).first()
        if media_release is None:
            self._invalidate(session, record, "ADJUSTMENT_RELEASE_STALE")
            raise LearningAdjustmentConflict("ADJUSTMENT_RELEASE_STALE")
        target_item = session.exec(select(MediaReleaseItem).where(
            MediaReleaseItem.course_id == record.course_id,
            MediaReleaseItem.release_id == record.review_media_release_id,
            MediaReleaseItem.item_id == record.review_media_release_item_id,
            MediaReleaseItem.outline_node_id == record.review_outline_node_id,
            MediaReleaseItem.status == "ready",
        )).first()
        if (
            target_item is None
            or not target_item.audio_object_key
            or not self._coordinate_matches_item(
                ReviewTarget(
                    course_release_id=record.review_course_release_id,
                    media_release_id=record.review_media_release_id,
                    media_release_item_id=record.review_media_release_item_id,
                    outline_node_id=record.review_outline_node_id,
                    local_time_ms=record.review_local_time_ms,
                    page=record.review_page,
                    global_time_ms=record.review_global_time_ms,
                ),
                target_item,
            )
            or not self._review_target_has_frozen_cue(
                session,
                media_release=media_release,
                item=target_item,
                record=record,
            )
        ):
            self._invalidate(session, record, "ADJUSTMENT_TARGET_UNAVAILABLE")
            raise LearningAdjustmentConflict("ADJUSTMENT_TARGET_UNAVAILABLE")

        if record.status == LearningAdjustmentStatus.APPLIED.value:
            return_anchor = self._return_anchor_from_record(record)
            try:
                if return_anchor is None:
                    raise LearningAdjustmentConflict("RETURN_ANCHOR_INVALID")
                self._assert_click_anchor_valid(session, record, return_anchor)
            except LearningAdjustmentConflict:
                self._invalidate(session, record, "RETURN_ANCHOR_UNAVAILABLE")
                raise LearningAdjustmentConflict("RETURN_ANCHOR_UNAVAILABLE") from None

    def _review_target_has_frozen_cue(
        self,
        session: Session,
        *,
        media_release: MediaRelease,
        item: MediaReleaseItem,
        record: LearningAdjustmentRecord,
    ) -> bool:
        """Confirm the persisted item-local target still maps to a frozen Cue."""
        cues = session.exec(select(MediaReleaseCue).where(
            MediaReleaseCue.course_id == record.course_id,
            MediaReleaseCue.release_id == record.review_media_release_id,
            MediaReleaseCue.node_id == item.node_id,
            MediaReleaseCue.ppt_page == record.review_page,
        )).all()
        for cue in cues:
            local_time_ms, _global_time_ms, error_code = self._resolve_cue_coordinate(
                cue=cue,
                item=item,
                media_release=media_release,
                storage=None,
            )
            if error_code is None and local_time_ms == record.review_local_time_ms:
                return True
        return False

    def _assert_click_anchor_valid(
        self,
        session: Session,
        record: LearningAdjustmentRecord,
        anchor: ReturnAnchor,
    ) -> None:
        if (
            anchor.course_release_id != record.question_course_release_id
            or anchor.media_release_id != record.question_media_release_id
        ):
            raise LearningAdjustmentConflict("RETURN_ANCHOR_RELEASE_MISMATCH")
        item = session.exec(select(MediaReleaseItem).where(
            MediaReleaseItem.course_id == record.course_id,
            MediaReleaseItem.release_id == record.question_media_release_id,
            MediaReleaseItem.item_id == anchor.media_release_item_id,
            MediaReleaseItem.outline_node_id == anchor.outline_node_id,
            MediaReleaseItem.status == "ready",
        )).first()
        if item is None or not item.audio_object_key or not self._coordinate_matches_item(anchor, item):
            raise LearningAdjustmentConflict("RETURN_ANCHOR_INVALID")
        media_release = session.exec(select(MediaRelease).where(
            MediaRelease.course_id == record.course_id,
            MediaRelease.release_id == record.question_media_release_id,
            MediaRelease.status == MediaReleaseStatus.ACTIVE,
        )).first()
        if media_release is None or not self._global_clock_matches_frozen_playlist(
            anchor,
            media_release=media_release,
            item=item,
            storage=None,
        ):
            raise LearningAdjustmentConflict("RETURN_ANCHOR_INVALID")
        cues = list(session.exec(select(MediaReleaseCue).where(
            MediaReleaseCue.course_id == record.course_id,
            MediaReleaseCue.release_id == record.question_media_release_id,
            MediaReleaseCue.node_id == item.node_id,
            MediaReleaseCue.ppt_page == anchor.page,
        )).all())
        if not any(self._cue_covers_coordinate(cue, anchor) for cue in cues):
            raise LearningAdjustmentConflict("RETURN_ANCHOR_INVALID")

    @staticmethod
    def _cue_covers_coordinate(cue: MediaReleaseCue, coordinate: Any) -> bool:
        """Accept only an item-local frozen Cue; unknown historical clocks fail closed."""
        metadata = dict(cue.cue_metadata or {})
        if metadata.get("time_basis") != "item_local_v1":
            return False
        try:
            start_ms = int(round(float(cue.start_time) * 1_000))
            end_ms = int(round(float(cue.end_time) * 1_000))
        except (TypeError, ValueError):
            return False
        return start_ms <= coordinate.local_time_ms <= end_ms

    def list_recent(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        limit: int = 20,
    ) -> list[LearningAdjustmentProposal]:
        """Return only currently playable metadata-only history for one learner.

        A persisted proposal can become stale between requests when its active
        release or media item changes.  Refresh recovery must not surface such
        a row as a retryable browser destination.
        """
        records = session.exec(select(LearningAdjustmentRecord).where(
            LearningAdjustmentRecord.course_id == course_id,
            LearningAdjustmentRecord.student_id == student_id,
        ).order_by(LearningAdjustmentRecord.created_at.desc()).limit(limit)).all()
        proposals: list[LearningAdjustmentProposal] = []
        for record in records:
            if record.declined_at is not None or record.invalidated_at is not None:
                continue
            try:
                self._assert_record_release_active(session, record)
            except LearningAdjustmentConflict:
                continue
            proposals.append(self._proposal_from_record(record))
        return proposals

    @staticmethod
    def course_id_for_owned_adjustment(
        session: Session, *, student_id: int, adjustment_id: str
    ) -> int:
        """Resolve a record before course authorization without leaking another learner's row."""
        record = session.exec(select(LearningAdjustmentRecord).where(
            LearningAdjustmentRecord.student_id == student_id,
            LearningAdjustmentRecord.adjustment_id == adjustment_id,
        )).first()
        if record is None:
            raise LearningAdjustmentConflict("ADJUSTMENT_NOT_FOUND")
        return record.course_id

    @staticmethod
    def _invalidate(
        session: Session, record: LearningAdjustmentRecord, reason_code: str
    ) -> None:
        if record.invalidated_at is not None:
            return
        record.invalidated_at = utcnow_aware()
        record.invalidation_reason_code = reason_code
        record.updated_at = record.invalidated_at
        session.add(record)
        session.commit()

    @staticmethod
    def _return_anchor_from_record(record: LearningAdjustmentRecord) -> ReturnAnchor | None:
        if record.return_media_release_item_id is None:
            return None
        return ReturnAnchor(
            course_release_id=str(record.return_course_release_id),
            media_release_id=str(record.return_media_release_id),
            media_release_item_id=str(record.return_media_release_item_id),
            outline_node_id=str(record.return_outline_node_id),
            local_time_ms=int(record.return_local_time_ms or 0),
            page=int(record.return_page or 1),
            global_time_ms=record.return_global_time_ms,
        )

    @classmethod
    def _proposal_from_record(cls, record: LearningAdjustmentRecord) -> LearningAdjustmentProposal:
        return_anchor = cls._return_anchor_from_record(record)
        return LearningAdjustmentProposal(
            adjustment_id=record.adjustment_id,
            status=LearningAdjustmentStatus(record.status),
            question_observation=QuestionObservation(
                course_release_id=record.question_course_release_id,
                media_release_id=record.question_media_release_id,
                media_release_item_id=record.question_media_release_item_id,
                outline_node_id=record.question_outline_node_id,
                local_time_ms=record.question_local_time_ms,
                page=record.question_page,
                global_time_ms=record.question_global_time_ms,
            ),
            review_target=ReviewTarget(
                course_release_id=record.review_course_release_id,
                media_release_id=record.review_media_release_id,
                media_release_item_id=record.review_media_release_item_id,
                outline_node_id=record.review_outline_node_id,
                local_time_ms=record.review_local_time_ms,
                page=record.review_page,
                global_time_ms=record.review_global_time_ms,
            ),
            return_anchor=return_anchor,
            teaching_action=record.teaching_action,
            reason_codes=tuple(record.reason_codes or []),
            recommended_playback_rate=record.recommended_playback_rate,
            requires_confirmation=record.requires_confirmation,
            declined_at=record.declined_at,
            invalidated_at=record.invalidated_at,
            invalidation_reason_code=record.invalidation_reason_code,
        )

    def resolve_review_target(
        self,
        session: Session,
        *,
        course_id: int,
        observation: QuestionObservation,
        teaching_action: str,
        current_concept_id: str | None,
        prerequisites: Iterable[Mapping[str, Any]],
        weak_concepts: Iterable[Mapping[str, Any]],
        storage: ObjectStorageProvider | None = None,
    ) -> ReviewTargetResolution:
        if teaching_action not in self._REDIRECT_ACTIONS:
            return ReviewTargetResolution(None, "ACTION_DOES_NOT_REQUIRE_REVIEW")

        course_release = self._active_course_release(session, course_id)
        if course_release is None or observation.course_release_id != course_release.release_id:
            return ReviewTargetResolution(None, "QUESTION_OBSERVATION_STALE")
        media_release_id = str((course_release.media_snapshot or {}).get("media_release_id") or "")
        if not media_release_id or observation.media_release_id != media_release_id:
            return ReviewTargetResolution(None, "QUESTION_OBSERVATION_STALE")
        media_release = session.exec(select(MediaRelease).where(
            MediaRelease.course_id == course_id,
            MediaRelease.release_id == media_release_id,
            MediaRelease.status == MediaReleaseStatus.ACTIVE,
        )).first()
        if media_release is None:
            return ReviewTargetResolution(None, "MEDIA_TARGET_UNAVAILABLE")

        observed_item = session.exec(select(MediaReleaseItem).where(
            MediaReleaseItem.course_id == course_id,
            MediaReleaseItem.release_id == media_release_id,
            MediaReleaseItem.item_id == observation.media_release_item_id,
            MediaReleaseItem.outline_node_id == observation.outline_node_id,
        )).first()
        if (
            observed_item is None
            or not self._coordinate_matches_item(observation, observed_item)
            or not self._global_clock_matches_frozen_playlist(
                observation,
                media_release=media_release,
                item=observed_item,
                storage=storage,
            )
        ):
            return ReviewTargetResolution(None, "QUESTION_OBSERVATION_STALE")
        observed_cues = session.exec(select(MediaReleaseCue).where(
            MediaReleaseCue.course_id == course_id,
            MediaReleaseCue.release_id == media_release_id,
            MediaReleaseCue.node_id == observed_item.node_id,
            MediaReleaseCue.ppt_page == observation.page,
        )).all()
        if not any(self._cue_covers_coordinate(cue, observation) for cue in observed_cues):
            return ReviewTargetResolution(None, "QUESTION_OBSERVATION_STALE")

        target_outline_node_id = self._target_outline_node(
            session,
            course_release=course_release,
            teaching_action=teaching_action,
            current_concept_id=current_concept_id,
            prerequisites=prerequisites,
            weak_concepts=weak_concepts,
        )
        if target_outline_node_id is None:
            return ReviewTargetResolution(None, "MEDIA_TARGET_UNAVAILABLE")
        target_item = session.exec(select(MediaReleaseItem).where(
            MediaReleaseItem.course_id == course_id,
            MediaReleaseItem.release_id == media_release_id,
            MediaReleaseItem.outline_node_id == target_outline_node_id,
            MediaReleaseItem.status == "ready",
        )).first()
        if target_item is None or not target_item.audio_object_key:
            return ReviewTargetResolution(None, "MEDIA_TARGET_UNAVAILABLE")

        cue = session.exec(select(MediaReleaseCue).where(
            MediaReleaseCue.course_id == course_id,
            MediaReleaseCue.release_id == media_release_id,
            MediaReleaseCue.node_id == target_item.node_id,
            MediaReleaseCue.ppt_page.is_not(None),
        ).order_by(MediaReleaseCue.cue_index, MediaReleaseCue.start_time)).first()
        if cue is None or cue.ppt_page is None:
            return ReviewTargetResolution(None, "MEDIA_TARGET_UNAVAILABLE")
        local_time_ms, global_time_ms, error_code = self._resolve_cue_coordinate(
            cue=cue,
            item=target_item,
            media_release=media_release,
            storage=storage,
        )
        if error_code:
            return ReviewTargetResolution(None, error_code)
        return ReviewTargetResolution(
            ReviewTarget(
                course_release_id=course_release.release_id,
                media_release_id=media_release_id,
                media_release_item_id=target_item.item_id,
                outline_node_id=target_outline_node_id,
                local_time_ms=local_time_ms,
                page=cue.ppt_page,
                global_time_ms=global_time_ms,
            )
        )

    @staticmethod
    def _active_course_release(session: Session, course_id: int) -> CourseRelease | None:
        return session.exec(select(CourseRelease).where(
            CourseRelease.course_id == course_id,
            CourseRelease.status == ReleaseStatus.PUBLISHED,
            CourseRelease.is_active == True,  # noqa: E712
        )).first()

    @staticmethod
    def _coordinate_matches_item(observation: QuestionObservation, item: MediaReleaseItem) -> bool:
        return observation.local_time_ms <= max(0, int(item.duration_ms or 0))

    def _global_clock_matches_frozen_playlist(
        self,
        coordinate: QuestionObservation | ReturnAnchor | ReviewTarget,
        *,
        media_release: MediaRelease,
        item: MediaReleaseItem,
        storage: ObjectStorageProvider | None,
    ) -> bool:
        """Verify optional global time against the immutable playlist clock."""
        if coordinate.global_time_ms is None:
            return True
        expected_global_time = self._playlist_global_time(
            media_release,
            item.item_id,
            coordinate.local_time_ms,
            storage,
        )
        # Older releases may not have a readable playlist. Their item-local
        # coordinate remains the source of truth; current clients omit the
        # optional global clock when it cannot be resolved.
        return expected_global_time is None or coordinate.global_time_ms == expected_global_time

    def _target_outline_node(
        self,
        session: Session,
        *,
        course_release: CourseRelease,
        teaching_action: str,
        current_concept_id: str | None,
        prerequisites: Iterable[Mapping[str, Any]],
        weak_concepts: Iterable[Mapping[str, Any]],
    ) -> str | None:
        nodes = list(session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == course_release.course_id,
            CourseOutlineNode.outline_version_id == course_release.outline_version_id,
        )).all())
        by_concept = {
            str(node.knowledge_graph_node_id): node.outline_node_id
            for node in nodes if node.knowledge_graph_node_id
        }
        if teaching_action == "prerequisite_review":
            weak_ids = {str(item.get("concept_id") or "") for item in weak_concepts}
            for prerequisite in prerequisites:
                concept_id = str(prerequisite.get("concept_id") or "")
                if concept_id in weak_ids and concept_id in by_concept:
                    return by_concept[concept_id]
            return None
        if teaching_action in {"misconception_repair", "hint_scaffolding", "diagnostic_question"}:
            return by_concept.get(str(current_concept_id or ""))
        return None

    def _resolve_cue_coordinate(
        self,
        *,
        cue: MediaReleaseCue,
        item: MediaReleaseItem,
        media_release: MediaRelease,
        storage: ObjectStorageProvider | None,
    ) -> tuple[int, int | None, str | None]:
        metadata = dict(cue.cue_metadata or {})
        basis = metadata.get("time_basis")
        cue_ms = int(round(float(cue.start_time) * 1_000))
        if basis == "item_local_v1":
            if cue_ms > int(item.duration_ms or 0):
                return 0, None, "CUE_COORDINATE_AMBIGUOUS"
            return cue_ms, self._playlist_global_time(media_release, item.item_id, cue_ms, storage), None
        playlist = self._frozen_playlist(media_release, storage)
        if playlist is None:
            return 0, None, "CUE_COORDINATE_AMBIGUOUS"
        matches = [row for row in playlist if row["item_id"] == item.item_id]
        if len(matches) != 1:
            return 0, None, "CUE_COORDINATE_AMBIGUOUS"
        matched = matches[0]
        if basis == "playlist_global_v1":
            local = cue_ms - matched["offset_ms"]
            if local < 0 or local > matched["duration_ms"]:
                return 0, None, "CUE_COORDINATE_AMBIGUOUS"
            return local, cue_ms, None
        # Legacy rows carry an undocumented clock.  Convert only if that value
        # lies in exactly one frozen item interval, then require it be this item.
        containing = [row for row in playlist if row["offset_ms"] <= cue_ms <= row["offset_ms"] + row["duration_ms"]]
        if len(containing) != 1 or containing[0]["item_id"] != item.item_id:
            return 0, None, "CUE_COORDINATE_AMBIGUOUS"
        return cue_ms - matched["offset_ms"], cue_ms, None

    def _playlist_global_time(
        self,
        media_release: MediaRelease,
        item_id: str,
        local_time_ms: int,
        storage: ObjectStorageProvider | None,
    ) -> int | None:
        playlist = self._frozen_playlist(media_release, storage)
        if playlist is None:
            return None
        matches = [row for row in playlist if row["item_id"] == item_id]
        if len(matches) != 1:
            return None
        return matches[0]["offset_ms"] + local_time_ms

    @staticmethod
    def _frozen_playlist(
        media_release: MediaRelease, storage: ObjectStorageProvider | None
    ) -> list[dict[str, int | str]] | None:
        if not media_release.audio_playlist_object_key:
            return None
        try:
            raw = json.loads((storage or get_object_storage()).get(media_release.audio_playlist_object_key).decode("utf-8"))
        except Exception:  # noqa: BLE001 - unavailable immutable source is a safe no-op
            return None
        if raw.get("schema") != "audio-playlist/v1":
            return None
        items: list[dict[str, int | str]] = []
        for entry in raw.get("items") or []:
            item_id = str(entry.get("item_id") or "")
            if not item_id:
                continue
            try:
                offset = int(entry.get("offset_ms"))
                duration = int(entry.get("duration_ms"))
            except (TypeError, ValueError):
                return None
            if offset < 0 or duration < 0:
                return None
            items.append({"item_id": item_id, "offset_ms": offset, "duration_ms": duration})
        return items or None


learning_adjustment_service = LearningAdjustmentService()
