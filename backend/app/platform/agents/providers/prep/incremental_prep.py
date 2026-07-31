"""Provider for the Incremental draft modification pipeline.

Wraps ``CoursePrepAgentService.plan()`` and adapts it to the
``IncrementalPrepPort`` protocol. The adapter translates string-typed
request fields (from ``IncrementalPrepRequestState``) into the service's
native call (integer course_id, SQLModel Session) and wraps the returned
``CoursePrepAgentResult`` into an ``IncrementalPrepResult`` DTO.

The provider holds a ``session_factory`` and the service singleton. The
service is currently stateless (no constructor injection of LLM); the LLM
client is resolved inside the service via the module-level ``llm_client``
singleton. Future LLM-adapter wiring will pass through the service's
planning method once its constructor accepts an optional ``llm`` parameter.
"""

from __future__ import annotations

import logging
from typing import Callable, Literal

from sqlmodel import Session

from app.services.course_prep_agent_service import (
    CoursePrepAgentResult,
    CoursePrepAgentService,
)

from ...prep.incremental.dependencies import IncrementalPrepResult

logger = logging.getLogger(__name__)


class IncrementalPrepProvider:
    """Adapt ``CoursePrepAgentService.plan()`` to ``IncrementalPrepPort``.

    Attributes:
        session_factory: Callable returning a SQLModel ``Session``. The
            provider opens and closes a session per call.
        service: The ``CoursePrepAgentService`` instance. Defaults to
            the module-level singleton when not injected.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        service: CoursePrepAgentService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._service = service or CoursePrepAgentService()

    async def plan(
        self,
        *,
        course_id: str,
        instruction: str,
        outline_node_id: str | None,
    ) -> IncrementalPrepResult:
        """Call ``CoursePrepAgentService.plan()`` and wrap the result.

        Translates string ``course_id`` to integer for the service call and
        extracts the relevant fields from ``CoursePrepAgentResult`` into
        ``IncrementalPrepResult``.
        """
        try:
            course_id_int = int(course_id)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid course_id {course_id!r}: {error}") from error

        session = self._session_factory()
        try:
            result: CoursePrepAgentResult = await self._service.plan(
                session,
                course_id=course_id_int,
                instruction=instruction,
                outline_node_id=outline_node_id,
            )
        finally:
            session.close()

        return IncrementalPrepResult(
            summary=result.summary,
            operations=list(result.operations),
            evidence=list(result.evidence),
            excluded_locked_targets=list(result.excluded_locked_targets),
            planner=result.planner,
        )

    async def plan_batch(
        self,
        *,
        course_id: str,
        action: Literal["organize_structure", "optimize_scripts"],
    ) -> IncrementalPrepResult:
        """Call the Service's complete-coverage batch planning path."""
        try:
            course_id_int = int(course_id)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid course_id {course_id!r}: {error}") from error

        session = self._session_factory()
        try:
            result = await self._service.plan_batch(
                session,
                course_id=course_id_int,
                action=action,
            )
        finally:
            session.close()
        return IncrementalPrepResult(
            summary=result.summary,
            operations=list(result.operations),
            evidence=list(result.evidence),
            excluded_locked_targets=list(result.excluded_locked_targets),
            planner=result.planner,
        )


__all__ = ["IncrementalPrepProvider"]
