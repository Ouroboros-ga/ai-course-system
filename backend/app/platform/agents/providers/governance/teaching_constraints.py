"""Session-scoped TeachingConstraint provider; policy is read on every request."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping

from app.services.teaching_constraint_service import teaching_constraint_service


class SessionScopedTeachingConstraintPort:
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    async def resolve(
        self,
        *,
        course_id: str,
        student_id: str,
        intent: str,
        concept_id: str | None,
    ) -> Mapping[str, Any]:
        def _read() -> Mapping[str, Any]:
            with self._session_factory() as session:
                version, envelope = teaching_constraint_service.resolve(
                    session,
                    course_id=int(course_id),
                    student_id=int(student_id),
                    intent=intent,
                    concept_id=concept_id,
                )
                return {
                    "policy_version": version.version if version else 0,
                    "envelope": envelope.model_dump(mode="json"),
                }

        return await asyncio.to_thread(_read)

    async def record_evaluation(
        self,
        *,
        trace_id: str,
        course_id: str,
        student_id: str,
        summary: Mapping[str, Any],
    ) -> None:
        def _write() -> None:
            with self._session_factory() as session:
                policy_version = int(summary.get("policy_version") or 0)
                if policy_version <= 0:
                    # Platform default has no immutable DB row to reference.
                    return
                version = teaching_constraint_service.get_version(
                    session,
                    course_id=int(course_id),
                    version=policy_version,
                )
                if version is None or version.id is None:
                    return
                teaching_constraint_service.record_evaluation(
                    session,
                    trace_id=trace_id,
                    course_id=int(course_id),
                    student_id=int(student_id),
                    policy_version_id=version.id,
                    effective_level=str(summary.get("effective_level") or "balanced"),
                    matched_rule_ids=tuple(summary.get("matched_rule_ids") or ()),
                    applied_scopes=tuple(summary.get("applied_scopes") or ()),
                    decision_codes=tuple(summary.get("decision_codes") or ()),
                    context_input_chars=int(summary.get("context_input_chars") or 0),
                    context_output_chars=int(summary.get("context_output_chars") or 0),
                    valid_citation_count=int(summary.get("valid_citation_count") or 0),
                    enforcement_status=str(summary.get("enforcement_status") or "enforced"),
                )
                session.commit()

        await asyncio.to_thread(_write)


def make_session_scoped_teaching_constraint_port(
    session_factory: Callable[[], Any],
) -> SessionScopedTeachingConstraintPort:
    return SessionScopedTeachingConstraintPort(session_factory)


__all__ = [
    "SessionScopedTeachingConstraintPort",
    "make_session_scoped_teaching_constraint_port",
]
