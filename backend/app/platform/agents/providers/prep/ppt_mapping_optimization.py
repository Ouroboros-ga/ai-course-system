"""Provider for the PPT mapping optimization pipeline.

Wraps ``PptMappingOptimizationService.optimize_mappings()`` and adapts it
to the ``PptMappingOptimizationPort`` protocol. The adapter translates
string-typed request fields (from ``PptMappingRequestState``) into the
service's native call (integer course_id, SQLModel Session) and wraps
the returned ``PptMappingOptimizationSummary`` into a
``PptMappingOptimizationResult`` DTO.
"""

from __future__ import annotations

import logging
from typing import Callable

from sqlmodel import Session

from app.services.ppt_mapping_optimization_service import (
    PptMappingOptimizationService,
)

from ...prep.ppt_mapping.dependencies import (
    PptMappingOptimizationResult,
    PptMappingSuggestion,
)

logger = logging.getLogger(__name__)


class PptMappingOptimizationProvider:
    """Adapt ``PptMappingOptimizationService`` to ``PptMappingOptimizationPort``.

    Attributes:
        session_factory: Callable returning a SQLModel ``Session``. The
            provider opens and closes a session per call.
        service: The ``PptMappingOptimizationService`` instance. Defaults
            to the module-level singleton when not injected.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        service: PptMappingOptimizationService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._service = service or PptMappingOptimizationService()

    async def optimize_mappings(
        self,
        *,
        course_id: str,
        material_version_ids: list[str],
        outline_node_ids: list[str] | None = None,
        page_refs_by_material: dict[str, list[int]] | None = None,
        seed_from_evidence: bool = True,
    ) -> PptMappingOptimizationResult:
        """Call ``PptMappingOptimizationService.optimize_mappings()`` and wrap the result."""
        try:
            course_id_int = int(course_id)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid course_id {course_id!r}: {error}") from error

        session = self._session_factory()
        try:
            summary = await self._service.optimize_mappings(
                session,
                course_id=course_id_int,
                material_version_ids=material_version_ids,
                outline_node_ids=outline_node_ids,
                page_refs_by_material=page_refs_by_material,
                seed_from_evidence=seed_from_evidence,
            )
        finally:
            session.close()

        suggestions = [
            PptMappingSuggestion(
                outline_node_id=s.outline_node_id,
                page_refs=list(s.page_refs),
                confidence=s.confidence,
                reason=s.reason,
                material_version_id=s.material_version_id,
            )
            for s in summary.suggestions
        ]
        return PptMappingOptimizationResult(
            total_mappings=summary.total_mappings,
            updated_count=summary.updated_count,
            suggestions=suggestions,
            material_version_ids=list(summary.material_version_ids),
        )


__all__ = ["PptMappingOptimizationProvider"]
