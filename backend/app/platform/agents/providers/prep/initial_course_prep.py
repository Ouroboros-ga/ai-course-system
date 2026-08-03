"""Provider for the Initial course build pipeline.

Wraps ``InitialCoursePrepService.build()`` and adapts it to the
``InitialCoursePrepPort`` protocol. The adapter translates string-typed
request fields (from ``InitialPrepRequestState``) into the service's
native call (integer course_id, integer created_by, SQLModel Session)
and wraps the returned ``DraftAssetResult`` into an ``InitialPrepResult``
DTO.

The provider holds a ``session_factory`` (callable returning a SQLModel
``Session``) and the service singleton. The optional ``workflow`` parameter
allows injecting a ``ControlledPrepWorkflow`` configured with the
``PrepLLMAdapter``; when not supplied, the service uses its default
``controlled_prep_workflow`` singleton.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from sqlmodel import Session

from app.services.course_initial_prep_service import InitialCoursePrepService
from app.services.document_draft_builders import DraftAssetResult

from ...prep.initial.dependencies import InitialPrepResult

logger = logging.getLogger(__name__)


class InitialCoursePrepProvider:
    """Adapt ``InitialCoursePrepService.build()`` to ``InitialCoursePrepPort``.

    Attributes:
        session_factory: Callable returning a SQLModel ``Session``. The
            provider opens and closes a session per call.
        service: The ``InitialCoursePrepService`` instance. Defaults to
            the module-level singleton when not injected.
        workflow: Optional ``ControlledPrepWorkflow`` to inject into the
            service call (for LLM adapter wiring). When ``None``, the
            service uses its default workflow singleton.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        service: InitialCoursePrepService | None = None,
        workflow: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._service = service or InitialCoursePrepService()
        self._workflow = workflow

    async def build(
        self,
        *,
        teacher_id: str,
        course_id: str,
        corpus_snapshot_id: str,
        build_task_id: str | None,
        on_stage: Callable[[str, int, Any], Awaitable[None] | None] | None,
        replace_unreviewed_initial: bool,
    ) -> InitialPrepResult:
        """Call ``InitialCoursePrepService.build()`` and wrap the result.

        Translates string IDs to integers for the service call and extracts
        the relevant fields from ``DraftAssetResult`` into ``InitialPrepResult``.
        """
        try:
            course_id_int = int(course_id)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid course_id {course_id!r}: {error}") from error

        try:
            teacher_id_int = int(teacher_id) if teacher_id else None
        except (TypeError, ValueError):
            teacher_id_int = None

        session = self._session_factory()
        try:
            result: DraftAssetResult = await self._service.build(
                session,
                course_id=course_id_int,
                corpus_snapshot_id=corpus_snapshot_id,
                created_by=teacher_id_int,
                build_task_id=build_task_id,
                workflow=self._workflow,
                replace_unreviewed_initial=replace_unreviewed_initial,
                on_stage=on_stage,
            )
            # The provider owns this short-lived session. The service waits
            # for the LLM before mutating records, so commit only a complete
            # build and roll back automatically on any failure.
            session.commit()
        finally:
            session.close()

        return InitialPrepResult(
            outline_version_id=result.outline_version_id or "",
            script_version_id=result.script_version_id or "",
            graph_candidate_batch_id=result.graph_candidate_batch_id or "",
            warnings=list(result.warnings or []),
            rag_indexed_chunks=result.rag_indexed_chunks,
            graph_node_candidates=result.graph_node_candidates,
            graph_relation_candidates=result.graph_relation_candidates,
            outline_node_count=result.outline_node_count,
            script_node_count=result.script_node_count,
            markdown_resource_id=result.markdown_resource_id or "",
            markdown_resource_version_id=result.markdown_resource_version_id or "",
        )


__all__ = ["InitialCoursePrepProvider"]
