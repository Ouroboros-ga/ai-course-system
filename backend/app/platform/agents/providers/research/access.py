"""Session-scoped Course Access re-authorization for ResearchAgent."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from app.services.course_access_service import require_course_permission


class CourseAccessResearchScopePort:
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    async def authorize(
        self,
        *,
        course_id: str,
        actor_user_id: str,
        permission: str,
    ) -> Mapping[str, Any]:
        try:
            numeric_course_id = int(course_id)
            numeric_user_id = int(actor_user_id)
        except (TypeError, ValueError):
            return {"allowed": False, "reason_code": "RESEARCH_INVALID_SCOPE"}
        try:
            with self._session_factory() as session:
                context = require_course_permission(
                    session,
                    {"user_id": numeric_user_id},
                    numeric_course_id,
                    permission,
                )
            return {
                "allowed": True,
                "course_id": numeric_course_id,
                "actor_user_id": numeric_user_id,
                "course_role": context.role.value if context.role else None,
            }
        except Exception as error:  # noqa: BLE001 - do not leak authorization detail
            return {"allowed": False, "reason_code": type(error).__name__}


__all__ = ["CourseAccessResearchScopePort"]
