"""Governed TeachingAgent experiment-recommendation proposal provider."""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from sqlmodel import Session, select

from app.models.access_control_model import CourseCapability, CourseMembership, MembershipStatus
from app.models.experiment_model import (
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentVersion,
)
from app.services.agent_governance_service import agent_governance_service

logger = logging.getLogger(__name__)


def _recommendable_definition(
    session: Session, *, course_id: int, experiment_id: str,
) -> ExperimentDefinition | None:
    definition = session.exec(
        select(ExperimentDefinition).where(
            ExperimentDefinition.course_id == course_id,
            ExperimentDefinition.experiment_id == experiment_id,
            ExperimentDefinition.publish_status == ExperimentPublishStatus.PUBLISHED,
        )
    ).first()
    if definition is None or not definition.default_version_id:
        return None
    version = session.exec(
        select(ExperimentVersion).where(
            ExperimentVersion.course_id == course_id,
            ExperimentVersion.experiment_id == definition.experiment_id,
            ExperimentVersion.version_id == definition.default_version_id,
            ExperimentVersion.is_active == True,  # noqa: E712
            ExperimentVersion.is_locked == True,  # noqa: E712
        )
    ).first()
    return definition if version is not None else None


def make_session_scoped_experiment_dispatch_port(session_factory: Callable[[], Session]):
    """Build a port that can propose, but never dispatch, an experiment."""

    class SessionScopedExperimentDispatchPort:
        async def list_recommendable_experiments(
            self,
            *,
            course_id: str,
            node_id: str | None = None,
            limit: int = 10,
        ) -> list[Mapping[str, Any]]:
            try:
                course_id_int = int(course_id)
            except (TypeError, ValueError):
                return []
            session = session_factory()
            try:
                capability = session.exec(select(CourseCapability).where(
                    CourseCapability.course_id == course_id_int,
                )).first()
                if capability is None or not capability.experiment or not capability.coding_sandbox:
                    return []
                rows = session.exec(
                    select(ExperimentDefinition).where(
                        ExperimentDefinition.course_id == course_id_int,
                        ExperimentDefinition.publish_status == ExperimentPublishStatus.PUBLISHED,
                    ).order_by(ExperimentDefinition.created_at.desc()).limit(max(1, min(limit, 50)))
                ).all()
                result: list[Mapping[str, Any]] = []
                for definition in rows:
                    if _recommendable_definition(
                        session, course_id=course_id_int, experiment_id=definition.experiment_id,
                    ) is None:
                        continue
                    if node_id is not None and str(node_id) not in {
                        str(value) for value in (definition.knowledge_node_ids or [])
                    }:
                        continue
                    result.append({
                        "experiment_id": definition.experiment_id,
                        "title": definition.title,
                        "knowledge_node_ids": list(definition.knowledge_node_ids or []),
                        "version_id": definition.default_version_id,
                    })
                return result
            except Exception as error:  # noqa: BLE001
                logger.warning("ExperimentDispatchPort.list failed: %s", type(error).__name__)
                return []
            finally:
                session.close()

        async def propose_recommendation(
            self,
            *,
            course_id: str,
            student_id: str,
            experiment_id: str,
            outline_node_id: str | None,
            trace_id: str,
            session_id: str,
        ) -> Mapping[str, Any]:
            try:
                course_id_int = int(course_id)
                student_id_int = int(student_id)
            except (TypeError, ValueError):
                return {"proposal_id": "", "status": "invalid_id"}
            session = session_factory()
            try:
                capability = session.exec(select(CourseCapability).where(
                    CourseCapability.course_id == course_id_int,
                )).first()
                membership = session.exec(select(CourseMembership).where(
                    CourseMembership.course_id == course_id_int,
                    CourseMembership.user_id == student_id_int,
                )).first()
                definition = _recommendable_definition(
                    session, course_id=course_id_int, experiment_id=experiment_id,
                )
                if capability is None or not capability.experiment or not capability.coding_sandbox:
                    return {"proposal_id": "", "status": "experiment_capability_disabled"}
                if membership is None or membership.status != MembershipStatus.ACTIVE:
                    return {"proposal_id": "", "status": "student_membership_invalid"}
                if definition is None:
                    return {"proposal_id": "", "status": "experiment_not_recommendable"}
                if outline_node_id is not None and str(outline_node_id) not in {
                    str(value) for value in (definition.knowledge_node_ids or [])
                }:
                    return {"proposal_id": "", "status": "outline_node_not_in_experiment"}
                proposal = agent_governance_service.create_proposal(
                    session,
                    course_id=course_id_int,
                    student_id=student_id_int,
                    trace_id=trace_id,
                    session_id=session_id,
                    proposal_type="trigger_experiment",
                    tool_name="experiment_dispatch",
                    proposed_action={
                        "experiment_id": definition.experiment_id,
                        "outline_node_id": str(outline_node_id) if outline_node_id is not None else None,
                    },
                    requires_confirmation=True,
                )
                if proposal is None:
                    return {"proposal_id": "", "status": "tool_locked_by_teacher"}
                session.commit()
                return {
                    "proposal_id": proposal.proposal_id,
                    "status": proposal.status,
                    "requires_confirmation": proposal.requires_confirmation,
                    "experiment_id": definition.experiment_id,
                }
            except Exception as error:  # noqa: BLE001
                session.rollback()
                logger.warning("ExperimentDispatchPort.propose failed: %s", type(error).__name__)
                return {"proposal_id": "", "status": "error"}
            finally:
                session.close()

    return SessionScopedExperimentDispatchPort()
