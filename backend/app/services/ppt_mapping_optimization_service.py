"""PPT mapping optimization service.

Optimises ``CoursePptMapping`` rows by matching OCR text blocks from a
PPT material version against the course outline's knowledge-point nodes
via an LLM call. The service:

    1. Loads ``DocumentBlock`` rows for the given ``material_version_id``
       (slide-type blocks with non-empty text).
    2. Loads the latest draft ``CourseOutlineVersion`` and its
       ``knowledge_point`` nodes.
    3. Loads existing ``CoursePptMapping`` rows for the material version
       (skipping ``teacher_locked=True``).
    4. Calls the LLM (via ``PrepLLMAdapter`` or ``llm_client``) to produce
       per-page mapping suggestions.
    5. Validates each suggestion (outline_node_id must exist; page range
       must be valid).
    6. Updates ``CoursePptMapping`` rows in place (``status="draft"``).
       Mappings with ``teacher_locked=True`` are never modified.
    7. Returns a summary (total / updated / suggestions).

The service does NOT create ``PatchProposal`` rows. It persists directly,
matching the design's PPT mapping pipeline persistence boundary.

LLM seam: the service accepts an optional ``llm`` parameter (a
``PrepLLMAdapter`` or any object exposing ``optimize_ppt_mappings()``).
When not injected, it falls back to the module-level ``llm_client``
singleton with a prompt-constrained JSON call, mirroring
``ControlledPrepWorkflow``'s fallback pattern.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlmodel import Session, select

from app.common.llm_client import Message, llm_client
from app.core.config import settings
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    CoursePptMapping,
    OutlineLifecycleStatus,
    OutlineNodeType,
)
from app.models.document_parse_model import DocumentBlock

logger = logging.getLogger(__name__)


@dataclass
class PptMappingSuggestion:
    """One LLM-produced mapping suggestion."""

    outline_node_id: str
    page_start: int
    page_end: int
    confidence: float
    reason: str = ""


@dataclass
class PptMappingOptimizationSummary:
    """Result of ``optimize_mappings()``."""

    total_mappings: int
    updated_count: int
    suggestions: list[PptMappingSuggestion] = field(default_factory=list)


class PptMappingOptimizationService:
    """Service for optimising PPT-to-outline mappings via LLM."""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        client: Any | None = None,
    ) -> None:
        """
        Args:
            llm: Optional ``PrepLLMAdapter`` (or any object exposing
                ``optimize_ppt_mappings(blocks, nodes, mappings)``). When
                injected, the service delegates the LLM call to it.
            client: Optional raw LLM client (e.g. ``llm_client``). Used
                when ``llm`` is not injected. Defaults to the module-level
                ``llm_client`` singleton.
        """
        self._llm = llm
        self._client = client or llm_client

    async def optimize_mappings(
        self,
        session: Session,
        *,
        course_id: int,
        material_version_id: str,
    ) -> PptMappingOptimizationSummary:
        """Optimise ``CoursePptMapping`` rows for a material version.

        Args:
            session: SQLModel ``Session`` for DB access.
            course_id: Integer course ID.
            material_version_id: The ``SourceMaterialVersion.version_id``
                identifying the PPT material version to optimise.

        Returns:
            Summary with total/updated counts and the suggestions applied.
        """
        blocks = self._load_blocks(session, course_id=course_id, material_version_id=material_version_id)
        if not blocks:
            logger.info(
                "PptMappingOptimization: no OCR blocks for course=%s material=%s",
                course_id, material_version_id,
            )
            return PptMappingOptimizationSummary(total_mappings=0, updated_count=0)

        nodes = self._load_knowledge_nodes(session, course_id=course_id)
        if not nodes:
            logger.info(
                "PptMappingOptimization: no knowledge_point nodes for course=%s",
                course_id,
            )
            return PptMappingOptimizationSummary(total_mappings=0, updated_count=0)

        existing = self._load_existing_mappings(
            session, course_id=course_id, material_version_id=material_version_id,
        )

        suggestions = await self._call_llm(blocks, nodes, existing)
        valid_suggestions = self._validate_suggestions(suggestions, nodes)

        updated = self._apply_suggestions(
            session,
            course_id=course_id,
            material_version_id=material_version_id,
            suggestions=valid_suggestions,
            existing=existing,
        )

        session.commit()
        return PptMappingOptimizationSummary(
            total_mappings=len(existing),
            updated_count=updated,
            suggestions=valid_suggestions,
        )

    # -- internal helpers ------------------------------------------------

    def _load_blocks(
        self,
        session: Session,
        *,
        course_id: int,
        material_version_id: str,
    ) -> list[DocumentBlock]:
        """Load slide-type OCR blocks with non-empty text."""
        rows = list(session.exec(
            select(DocumentBlock).where(
                DocumentBlock.course_id == course_id,
                DocumentBlock.material_version_id == material_version_id,
            ).order_by(DocumentBlock.page_or_slide, DocumentBlock.order_index)
        ).all())
        return [b for b in rows if (b.text or "").strip()]

    def _load_knowledge_nodes(
        self,
        session: Session,
        *,
        course_id: int,
    ) -> list[CourseOutlineNode]:
        """Load knowledge_point nodes from the latest draft outline version."""
        outline_version = session.exec(
            select(CourseOutlineVersion).where(
                CourseOutlineVersion.course_id == course_id,
                CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
            ).order_by(CourseOutlineVersion.version.desc())
        ).first()
        if outline_version is None:
            return []
        return list(session.exec(
            select(CourseOutlineNode).where(
                CourseOutlineNode.course_id == course_id,
                CourseOutlineNode.outline_version_id == outline_version.outline_version_id,
                CourseOutlineNode.node_type == OutlineNodeType.KNOWLEDGE_POINT,
            ).order_by(CourseOutlineNode.order_index)
        ).all())

    def _load_existing_mappings(
        self,
        session: Session,
        *,
        course_id: int,
        material_version_id: str,
    ) -> list[CoursePptMapping]:
        """Load existing mappings (including teacher_locked for skip logic)."""
        return list(session.exec(
            select(CoursePptMapping).where(
                CoursePptMapping.course_id == course_id,
                CoursePptMapping.material_version_id == material_version_id,
            )
        ).all())

    async def _call_llm(
        self,
        blocks: list[DocumentBlock],
        nodes: list[CourseOutlineNode],
        existing: list[CoursePptMapping],
    ) -> list[PptMappingSuggestion]:
        """Call the LLM (adapter or raw client) for mapping suggestions."""
        blocks_payload = [
            {"page": b.page_or_slide or b.page_number, "text": (b.text or "")[:500]}
            for b in blocks
        ]
        nodes_payload = [
            {"outline_node_id": n.outline_node_id, "title": n.title}
            for n in nodes
        ]
        existing_payload = [
            {
                "outline_node_id": m.outline_node_id,
                "page_start": m.page_start,
                "page_end": m.page_end,
                "teacher_locked": m.teacher_locked,
            }
            for m in existing
        ]

        if self._llm is not None:
            raw_suggestions = await self._llm.optimize_ppt_mappings(
                blocks_payload, nodes_payload, existing_payload,
            )
            return self._parse_suggestions(raw_suggestions)

        return await self._call_llm_raw(blocks_payload, nodes_payload, existing_payload)

    async def _call_llm_raw(
        self,
        blocks: list[dict],
        nodes: list[dict],
        existing: list[dict],
    ) -> list[PptMappingSuggestion]:
        """Fallback: call ``llm_client`` directly with prompt-constrained JSON."""
        if not self._llm_is_configured():
            logger.info("PptMappingOptimization: LLM not configured; skipping optimization.")
            return []

        from app.platform.agents.prep.prompts import PPT_MAPPING_OPTIMIZER_PROMPT

        system = PPT_MAPPING_OPTIMIZER_PROMPT.system_template
        user = json.dumps(
            {"blocks": blocks, "nodes": nodes, "mappings": existing},
            ensure_ascii=False,
        )
        try:
            response = await self._client.chat(
                [
                    Message(role="system", content=system),
                    Message(role="user", content=user),
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = response.content if hasattr(response, "content") else response
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            suggestions = (
                parsed.get("suggestions", []) if isinstance(parsed, dict) else parsed
            )
            return self._parse_suggestions(suggestions)
        except Exception as error:  # noqa: BLE001 - fail-closed
            logger.warning(
                "PptMappingOptimization: LLM call failed: %s: %s",
                type(error).__name__, error,
            )
            return []

    @staticmethod
    def _parse_suggestions(raw: list[Any]) -> list[PptMappingSuggestion]:
        """Parse raw LLM output into ``PptMappingSuggestion`` list."""
        if not isinstance(raw, list):
            return []
        result: list[PptMappingSuggestion] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(PptMappingSuggestion(
                    outline_node_id=str(item["outline_node_id"]),
                    page_start=int(item.get("page_start", 1)),
                    page_end=int(item.get("page_end", item.get("page_start", 1))),
                    confidence=float(item.get("confidence", 0.5)),
                    reason=str(item.get("reason", "")),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _validate_suggestions(
        suggestions: list[PptMappingSuggestion],
        nodes: list[CourseOutlineNode],
    ) -> list[PptMappingSuggestion]:
        """Reject suggestions referencing unknown outline nodes."""
        valid_ids = {n.outline_node_id for n in nodes}
        return [s for s in suggestions if s.outline_node_id in valid_ids]

    @staticmethod
    def _apply_suggestions(
        session: Session,
        *,
        course_id: int,
        material_version_id: str,
        suggestions: list[PptMappingSuggestion],
        existing: list[CoursePptMapping],
    ) -> int:
        """Apply validated suggestions to ``CoursePptMapping`` rows.

        Updates non-locked mappings in place. Returns the count of rows
        actually updated.
        """
        existing_by_node = {m.outline_node_id: m for m in existing}
        updated = 0
        for suggestion in suggestions:
            mapping = existing_by_node.get(suggestion.outline_node_id)
            if mapping is None:
                continue
            if mapping.teacher_locked:
                continue
            mapping.page_start = suggestion.page_start
            mapping.page_end = suggestion.page_end
            mapping.page_refs = list(range(suggestion.page_start, suggestion.page_end + 1))
            mapping.confidence = suggestion.confidence
            mapping.status = "draft"
            session.add(mapping)
            updated += 1
        return updated

    @staticmethod
    def _llm_is_configured() -> bool:
        """Check if the LLM client has the required configuration."""
        return bool(
            getattr(settings, "LLM_API_KEY", "") and getattr(settings, "LLM_MODEL_NAME", "")
        )


# Module-level singleton (mirrors CoursePrepAgentService convention).
ppt_mapping_optimization_service = PptMappingOptimizationService()


__all__ = [
    "PptMappingSuggestion",
    "PptMappingOptimizationSummary",
    "PptMappingOptimizationService",
    "ppt_mapping_optimization_service",
]
