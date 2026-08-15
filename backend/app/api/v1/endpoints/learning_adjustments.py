"""Learner-owned transitions for release-pinned review proposals.

``applied`` means the learner accepted a proposal.  It never claims that a
browser switched source or completed a seek; the client reports ``returned``
only after its own restore operation succeeds.
"""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.core.security import get_current_user
from app.models.database import get_session
from app.schemas.learning_adjustment import (
    ApplyLearningAdjustmentRequest,
    DismissLearningAdjustmentRequest,
    ReturnLearningAdjustmentRequest,
)
from app.services.course_access_service import require_course_permission
from app.services.learning_adjustment_service import (
    LearningAdjustmentConflict,
    learning_adjustment_service,
)
from app.services.unified_learning_service import record_agent_learning_action

router = APIRouter()


def _require_learner(session: Session, current_user: dict[str, Any], course_id: int) -> int:
    context = require_course_permission(session, current_user, course_id, "course.question.ask")
    if not context.analytics_eligible:
        raise HTTPException(
            status_code=403,
            detail={"code": "LEARNING_ADJUSTMENT_LEARNER_REQUIRED"},
        )
    return int(current_user["user_id"])


def _owned_course_id(session: Session, *, student_id: int, adjustment_id: str) -> int:
    try:
        return learning_adjustment_service.course_id_for_owned_adjustment(
            session, student_id=student_id, adjustment_id=adjustment_id
        )
    except LearningAdjustmentConflict as error:
        raise HTTPException(status_code=404, detail={"code": error.code}) from error


def _transition_error(error: LearningAdjustmentConflict) -> HTTPException:
    if error.code == "ADJUSTMENT_NOT_FOUND":
        return HTTPException(status_code=404, detail={"code": error.code})
    return HTTPException(status_code=409, detail={"code": error.code})


def _action_key(action: str, proposal_id: str, client_key: str) -> str:
    digest = hashlib.sha256(f"{action}:{proposal_id}:{client_key}".encode("utf-8")).hexdigest()
    return f"learning-adjustment:{digest}"


def _record_action(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    proposal: Any,
    action: str,
    idempotency_key: str,
) -> str | None:
    """Best-effort minimized audit that never rewrites learning projections."""
    payload: dict[str, Any] = {
        "adjustment_id": proposal.adjustment_id,
        "reason_codes": list(proposal.reason_codes),
        "review_media_release_id": proposal.review_target.media_release_id,
        "review_media_release_item_id": proposal.review_target.media_release_item_id,
        "review_outline_node_id": proposal.review_target.outline_node_id,
        "review_local_time_ms": proposal.review_target.local_time_ms,
    }
    if proposal.return_anchor is not None:
        payload.update({
            "return_media_release_id": proposal.return_anchor.media_release_id,
            "return_media_release_item_id": proposal.return_anchor.media_release_item_id,
            "return_outline_node_id": proposal.return_anchor.outline_node_id,
            "return_local_time_ms": proposal.return_anchor.local_time_ms,
        })
    try:
        record_agent_learning_action(
            session,
            student_id=student_id,
            course_id=course_id,
            release_id=proposal.review_target.course_release_id,
            outline_node_id=proposal.review_target.outline_node_id,
            idempotency_key=_action_key(action, proposal.adjustment_id, idempotency_key),
            action=action,
            payload=payload,
        )
    except Exception:  # noqa: BLE001 - completed browser state remains truthful
        session.rollback()
        return "LEARNING_ADJUSTMENT_AUDIT_UNAVAILABLE"
    return None


def _response(proposal: Any, warning: str | None = None) -> dict[str, Any]:
    data = proposal.model_dump(mode="json")
    if warning is not None:
        data["warnings"] = [warning]
    return data


@router.get("/course/{course_id}/recent")
async def list_recent_adjustments(
    course_id: int,
    limit: int = Query(default=20, ge=1, le=50),
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    student_id = _require_learner(session, current_user, course_id)
    proposals = learning_adjustment_service.list_recent(
        session, course_id=course_id, student_id=student_id, limit=limit
    )
    return {"course_id": course_id, "items": [item.model_dump(mode="json") for item in proposals]}


@router.post("/{adjustment_id}/apply")
async def apply_adjustment(
    adjustment_id: str,
    body: ApplyLearningAdjustmentRequest,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    student_id = int(current_user["user_id"])
    course_id = _owned_course_id(session, student_id=student_id, adjustment_id=adjustment_id)
    _require_learner(session, current_user, course_id)
    try:
        proposal = learning_adjustment_service.accept_proposal(
            session,
            course_id=course_id,
            student_id=student_id,
            adjustment_id=adjustment_id,
            return_anchor=body.return_anchor,
            idempotency_key=body.idempotency_key,
        )
    except LearningAdjustmentConflict as error:
        raise _transition_error(error) from error
    warning = _record_action(
        session,
        student_id=student_id,
        course_id=course_id,
        proposal=proposal,
        action="review_accepted",
        idempotency_key=body.idempotency_key,
    )
    return _response(proposal, warning)


@router.post("/{adjustment_id}/return")
async def return_from_adjustment(
    adjustment_id: str,
    body: ReturnLearningAdjustmentRequest,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    student_id = int(current_user["user_id"])
    course_id = _owned_course_id(session, student_id=student_id, adjustment_id=adjustment_id)
    _require_learner(session, current_user, course_id)
    try:
        proposal = learning_adjustment_service.mark_returned(
            session,
            course_id=course_id,
            student_id=student_id,
            adjustment_id=adjustment_id,
            idempotency_key=body.idempotency_key,
        )
    except LearningAdjustmentConflict as error:
        raise _transition_error(error) from error
    warning = _record_action(
        session,
        student_id=student_id,
        course_id=course_id,
        proposal=proposal,
        action="review_returned",
        idempotency_key=body.idempotency_key,
    )
    return _response(proposal, warning)


@router.post("/{adjustment_id}/dismiss")
async def dismiss_adjustment(
    adjustment_id: str,
    body: DismissLearningAdjustmentRequest,
    session: Session = Depends(get_session),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    student_id = int(current_user["user_id"])
    course_id = _owned_course_id(session, student_id=student_id, adjustment_id=adjustment_id)
    _require_learner(session, current_user, course_id)
    try:
        proposal = learning_adjustment_service.dismiss_proposal(
            session,
            course_id=course_id,
            student_id=student_id,
            adjustment_id=adjustment_id,
            idempotency_key=body.idempotency_key,
        )
    except LearningAdjustmentConflict as error:
        raise _transition_error(error) from error
    warning = _record_action(
        session,
        student_id=student_id,
        course_id=course_id,
        proposal=proposal,
        action="review_dismissed",
        idempotency_key=body.idempotency_key,
    )
    return _response(proposal, warning)
