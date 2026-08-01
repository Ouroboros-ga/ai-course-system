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

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Sequence

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


@dataclass(frozen=True)
class PptTextBlock:
    """Ephemeral page text obtained from a rendered ``ppt-manifest/v1`` page.

    This is deliberately not persisted as a ``DocumentBlock``: manifest OCR is
    an optimization-time fallback, while durable parse output must still be
    produced through the document-parse pipeline with its normal provenance.
    """

    page: int
    text: str
    source_kind: str = "ppt_manifest_ocr"


class PptMappingContentUnavailable(RuntimeError):
    """No trustworthy course-scoped text source is available for matching."""

    error_code = "PPT_MAPPING_CONTENT_UNAVAILABLE"


@dataclass
class PptMappingSuggestion:
    """One LLM-produced mapping suggestion.

    Uses ``page_refs`` (a list of page numbers) instead of a contiguous
    ``page_start``/``page_end`` range, because PPT content for one
    knowledge point often spans non-consecutive slides.
    """

    outline_node_id: str
    page_refs: list[int]
    confidence: float
    reason: str = ""
    # Mapping pages are meaningful only inside one source-material version.
    # The service attaches this after each per-deck LLM call; the model never
    # chooses it itself.
    material_version_id: str = ""

    @property
    def page_start(self) -> int:
        return min(self.page_refs) if self.page_refs else 1

    @property
    def page_end(self) -> int:
        return max(self.page_refs) if self.page_refs else 1


@dataclass
class PptMappingOptimizationSummary:
    """Result of ``optimize_mappings()``."""

    total_mappings: int
    updated_count: int
    suggestions: list[PptMappingSuggestion] = field(default_factory=list)
    material_version_ids: list[str] = field(default_factory=list)


class PptMappingOptimizationService:
    """Service for optimising PPT-to-outline mappings via LLM."""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        client: Any | None = None,
        ocr_port: Any | None = None,
        storage: Any | None = None,
    ) -> None:
        """
        Args:
            llm: Optional ``PrepLLMAdapter`` (or any object exposing
                ``optimize_ppt_mappings(blocks, nodes, mappings)``). When
                injected, the service delegates the LLM call to it.
            client: Optional raw LLM client (e.g. ``llm_client``). Used
                when ``llm`` is not injected. Defaults to the module-level
                ``llm_client`` singleton.
            ocr_port: The deterministic ``DocumentOcrPort`` dependency used
                only when no durable document blocks are available and a
                course-scoped ``ppt-manifest/v1`` is present.
            storage: Optional object-storage dependency.  This seam keeps
                manifest/OCR tests local and prevents a model-facing tool.
        """
        self._llm = llm
        self._client = client or llm_client
        self._ocr_port = ocr_port
        self._storage = storage

    async def optimize_mappings(
        self,
        session: Session,
        *,
        course_id: int,
        material_version_id: str | None = None,
        material_version_ids: Sequence[str] | None = None,
        outline_node_ids: Sequence[str] | None = None,
        page_refs_by_material: dict[str, Sequence[int]] | None = None,
        seed_from_evidence: bool = True,
    ) -> PptMappingOptimizationSummary:
        """Optimise ``CoursePptMapping`` rows for one or more PPT versions.

        Args:
            session: SQLModel ``Session`` for DB access.
            course_id: Integer course ID.
            material_version_id: Backward-compatible single
                ``SourceMaterialVersion.version_id`` input.
            material_version_ids: Current PPT material versions to optimise.
                Each version is matched independently, because slide page
                numbers restart for every uploaded deck.

        Returns:
            Summary with total/updated counts and the suggestions applied.
        """
        version_ids = self._normalise_material_version_ids(
            material_version_id=material_version_id,
            material_version_ids=material_version_ids,
        )
        nodes = self._load_knowledge_nodes(
            session,
            course_id=course_id,
            outline_node_ids=outline_node_ids,
        )
        if not nodes:
            logger.info(
                "PptMappingOptimization: no knowledge_point nodes for course=%s",
                course_id,
            )
            return PptMappingOptimizationSummary(total_mappings=0, updated_count=0)

        # Initial course preparation already records the evidence block IDs
        # that produced each knowledge point.  They are a stronger source of
        # truth than asking the model to rediscover the same page, especially
        # for legacy courses whose first-pass rows were all accidentally
        # assigned to the first uploaded PPT.  Repair those draft mappings
        # before the semantic LLM pass so every deck starts from the OCR
        # provenance that actually belongs to it.
        source_seeded_count, source_seeded_suggestions = (0, [])
        if seed_from_evidence:
            source_seeded_count, source_seeded_suggestions = (
                self._seed_mappings_from_outline_evidence(
                    session,
                    course_id=course_id,
                    nodes=nodes,
                    material_version_ids=version_ids,
                )
            )
        if source_seeded_count:
            session.flush()

        # 加载讲稿内容和父级标题，为 LLM 提供语义上下文
        script_contents = self._load_script_contents(session, nodes=nodes)
        parent_titles = self._load_parent_titles(session, nodes=nodes)

        # Read all database inputs before starting LLM work and before adding
        # any mappings. This gives a multi-deck run all-or-nothing persistence
        # semantics: unavailable content in one deck cannot leave other decks
        # half-applied.
        prepared: list[tuple[str, list[DocumentBlock | PptTextBlock], list[CoursePptMapping]]] = []
        for version_id in version_ids:
            blocks = self._load_blocks(
                session,
                course_id=course_id,
                material_version_id=version_id,
            )
            if not blocks:
                if len(version_ids) != 1:
                    raise PptMappingContentUnavailable(
                        "PPT 材料缺少可用解析文本，无法在多文件映射中安全确定 "
                        f"ppt-manifest/v1 的归属：{version_id}"
                    )
                # A release-side ppt-manifest is a valid rendered source when
                # there is exactly one deck. With multiple materials the
                # release manifest has no material-version provenance, so it
                # must not be applied to an arbitrary deck.
                blocks = await self._load_manifest_ocr_blocks(session, course_id=course_id)
            requested_pages = {
                int(page)
                for page in (page_refs_by_material or {}).get(version_id, [])
                if int(page) > 0
            }
            if requested_pages:
                blocks = [
                    block for block in blocks
                    if int(
                        block.page if isinstance(block, PptTextBlock)
                        else (block.page_or_slide or block.page_number or 0)
                    ) in requested_pages
                ]
                if not blocks:
                    raise PptMappingContentUnavailable(
                        f"所选 PPT 页没有可用于匹配的 OCR 文本：{version_id}"
                    )
            existing = self._load_existing_mappings(
                session,
                course_id=course_id,
                material_version_id=version_id,
            )
            prepared.append((version_id, blocks, existing))

        # Three concurrent deck plans keep ordinary multi-PPT courses fast
        # without allowing a large upload batch to fan out unbounded LLM work.
        planner_semaphore = asyncio.Semaphore(3)

        async def plan_deck(
            blocks: list[DocumentBlock | PptTextBlock],
            existing: list[CoursePptMapping],
        ) -> list[PptMappingSuggestion]:
            async with planner_semaphore:
                return await self._call_llm(
                    blocks,
                    nodes,
                    existing,
                    script_contents=script_contents,
                    parent_titles=parent_titles,
                )

        raw_suggestion_batches = await asyncio.gather(*(
            plan_deck(blocks, existing)
            for _version_id, blocks, existing in prepared
        ))

        total_mappings = 0
        updated = source_seeded_count
        all_suggestions: list[PptMappingSuggestion] = list(source_seeded_suggestions)
        for (version_id, blocks, existing), suggestions in zip(prepared, raw_suggestion_batches):
            valid_suggestions = [
                replace(suggestion, material_version_id=version_id)
                for suggestion in self._validate_suggestions(
                    suggestions,
                    nodes,
                    max_page=self._max_page(blocks),
                    allowed_pages=(page_refs_by_material or {}).get(version_id),
                )
            ]
            total_mappings += len(existing)
            updated += self._apply_suggestions(
                session,
                course_id=course_id,
                material_version_id=version_id,
                suggestions=valid_suggestions,
                existing=existing,
            )
            all_suggestions.extend(valid_suggestions)

        session.commit()
        return PptMappingOptimizationSummary(
            total_mappings=total_mappings,
            updated_count=updated,
            suggestions=all_suggestions,
            material_version_ids=version_ids,
        )

    # -- internal helpers ------------------------------------------------

    @staticmethod
    def _normalise_material_version_ids(
        *,
        material_version_id: str | None,
        material_version_ids: Sequence[str] | None,
    ) -> list[str]:
        """Return a stable, non-empty, de-duplicated set of version IDs."""
        candidates = list(material_version_ids or [])
        if material_version_id:
            candidates.append(material_version_id)
        result = list(dict.fromkeys(str(value).strip() for value in candidates if str(value).strip()))
        if not result:
            raise ValueError("PPT mapping requires at least one material_version_id")
        return result

    @staticmethod
    def _max_page(blocks: Sequence[DocumentBlock | PptTextBlock]) -> int:
        """Infer the highest valid slide number from one deck's source text."""
        pages = [
            int(block.page if isinstance(block, PptTextBlock) else (block.page_or_slide or block.page_number or 0))
            for block in blocks
        ]
        return max(pages, default=0)

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

    async def _load_manifest_ocr_blocks(
        self,
        session: Session,
        *,
        course_id: int,
    ) -> list[PptTextBlock]:
        """Recognize the newest course-scoped ``ppt-manifest/v1`` pages.

        ``DocumentBlock`` remains the preferred, durable source.  This
        fallback exists for the real transition case where the course already
        has an immutable rendered PPT manifest but the material parser has not
        yet projected text blocks.  It fails closed rather than returning a
        partial mapping from an unavailable OCR service.
        """
        from app.models.media_release_model import MediaRelease
        from app.platform.document_intelligence.ocr_port import (
            OcrUnavailable,
            get_ocr_port,
        )
        from app.services.object_storage import get_object_storage
        from app.services.ppt_manifest_service import load_manifest

        release = session.exec(
            select(MediaRelease).where(
                MediaRelease.course_id == course_id,
                MediaRelease.ppt_manifest_object_key.is_not(None),
            ).order_by(MediaRelease.version_number.desc(), MediaRelease.id.desc())
        ).first()
        if release is None or not release.ppt_manifest_object_key:
            raise PptMappingContentUnavailable(
                "PPT 尚无可用的解析文本或 ppt-manifest/v1 页面；请等待材料解析完成，"
                "或先生成 PPT manifest。"
            )

        storage = self._storage or get_object_storage()
        try:
            manifest = load_manifest(storage, release.ppt_manifest_object_key)
        except Exception as error:  # noqa: BLE001 - surface the actionable source issue
            raise PptMappingContentUnavailable(
                f"ppt-manifest/v1 无法读取，暂不能优化映射：{type(error).__name__}: {error}"
            ) from error

        pages = [
            item for item in manifest.get("pages", [])
            if isinstance(item, dict) and item.get("image_object_key")
        ]
        if not pages:
            raise PptMappingContentUnavailable("ppt-manifest/v1 不含可供 OCR 识别的页面。")

        ocr_port = self._ocr_port or get_ocr_port()
        if not getattr(ocr_port, "is_available", False):
            raise PptMappingContentUnavailable(
                "已发现 ppt-manifest/v1，但 OCR 服务当前不可用；请启动 OCR 服务后重试。"
            )

        semaphore = asyncio.Semaphore(3)

        async def recognize(item: dict[str, Any]) -> PptTextBlock:
            page = int(item.get("page") or 1)
            object_key = str(item["image_object_key"])
            async with semaphore:
                try:
                    image_bytes = await asyncio.to_thread(storage.get, object_key)
                    result = await asyncio.to_thread(
                        ocr_port.ocr_image,
                        image_bytes,
                        lang="ch",
                        page=page,
                    )
                except OcrUnavailable as error:
                    raise PptMappingContentUnavailable(
                        f"PPT 第 {page} 页 OCR 失败（{error.error_code}）：{error.message}"
                    ) from error
                except Exception as error:  # noqa: BLE001 - no partial mapping on failed pages
                    raise PptMappingContentUnavailable(
                        f"PPT 第 {page} 页 OCR 失败：{type(error).__name__}: {error}"
                    ) from error
            text = "\n".join(
                block.text.strip()
                for result_page in result.pages
                for block in result_page.blocks
                if (block.text or "").strip()
            )
            return PptTextBlock(page=page, text=text)

        recognized = await asyncio.gather(*(recognize(item) for item in pages))
        text_blocks = [item for item in recognized if item.text]
        if not text_blocks:
            raise PptMappingContentUnavailable(
                "ppt-manifest/v1 页面已完成 OCR，但未识别到可用于知识点匹配的文本。"
            )
        return text_blocks

    def _load_knowledge_nodes(
        self,
        session: Session,
        *,
        course_id: int,
        outline_node_ids: Sequence[str] | None = None,
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
        requested_ids = [str(node_id).strip() for node_id in (outline_node_ids or []) if str(node_id).strip()]
        statement = select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == course_id,
            CourseOutlineNode.outline_version_id == outline_version.outline_version_id,
            CourseOutlineNode.node_type == OutlineNodeType.KNOWLEDGE_POINT,
        )
        if requested_ids:
            statement = statement.where(CourseOutlineNode.outline_node_id.in_(requested_ids))
        return list(session.exec(statement.order_by(CourseOutlineNode.order_index)).all())

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

    @staticmethod
    def _seed_mappings_from_outline_evidence(
        session: Session,
        *,
        course_id: int,
        nodes: Sequence[CourseOutlineNode],
        material_version_ids: Sequence[str],
    ) -> tuple[int, list[PptMappingSuggestion]]:
        """Restore draft mapping rows from authoritative OCR provenance.

        ``CourseOutlineNode.source_block_refs`` originates from the course
        corpus.  A referenced ``DocumentBlock`` already knows both its PPT
        material version and slide number, making it a deterministic mapping
        seed.  This also repairs the old single-deck bug where mappings for
        several decks were stored under the first PPT version.

        Teacher-locked mappings are never moved or overwritten.  The method
        returns only rows that were actually created, moved, or changed, so
        callers can distinguish a completed runtime from a real write.
        """
        current_versions = {
            str(version_id).strip()
            for version_id in material_version_ids
            if str(version_id).strip()
        }
        if not current_versions:
            return 0, []

        blocks = list(session.exec(
            select(DocumentBlock).where(
                DocumentBlock.course_id == course_id,
                DocumentBlock.material_version_id.in_(current_versions),
            )
        ).all())
        block_lookup = {
            block.block_id: (block.material_version_id, int(block.page_or_slide or block.page_number or 0))
            for block in blocks
            if block.block_id and block.material_version_id and int(block.page_or_slide or block.page_number or 0) > 0
        }
        if not block_lookup:
            return 0, []

        mappings = list(session.exec(
            select(CoursePptMapping).where(
                CoursePptMapping.course_id == course_id,
                CoursePptMapping.status == "draft",
            )
        ).all())
        mappings_by_key = {
            (mapping.outline_node_id, mapping.material_version_id): mapping
            for mapping in mappings
            if mapping.material_version_id in current_versions
        }
        mappings_by_node: dict[str, list[CoursePptMapping]] = {}
        for mapping in mappings:
            mappings_by_node.setdefault(mapping.outline_node_id, []).append(mapping)

        changed = 0
        suggestions: list[PptMappingSuggestion] = []
        for node in nodes:
            refs = [
                str(ref).strip()
                for ref in (node.source_block_refs or [])
                if str(ref).strip() in block_lookup
            ]
            if not refs:
                continue
            refs_by_version: dict[str, list[str]] = {}
            pages_by_version: dict[str, set[int]] = {}
            for ref in refs:
                version_id, page = block_lookup[ref]
                refs_by_version.setdefault(version_id, []).append(ref)
                pages_by_version.setdefault(version_id, set()).add(page)

            source_versions = set(refs_by_version)
            for version_id, source_refs in refs_by_version.items():
                page_refs = sorted(pages_by_version[version_id])
                mapping = mappings_by_key.get((node.outline_node_id, version_id))
                moved = False
                if mapping is not None and mapping.teacher_locked:
                    continue
                if mapping is None:
                    # Prefer moving a legacy row that carries the same source
                    # evidence instead of leaving an incorrect duplicate in
                    # another deck's page-number space.
                    mapping = next(
                        (
                            candidate
                            for candidate in mappings_by_node.get(node.outline_node_id, [])
                            if not candidate.teacher_locked
                            and candidate.material_version_id not in source_versions
                            and set(candidate.source_block_refs or []).intersection(source_refs)
                        ),
                        None,
                    )
                    if mapping is not None:
                        old_key = (mapping.outline_node_id, mapping.material_version_id)
                        mappings_by_key.pop(old_key, None)
                        mapping.material_version_id = version_id
                        moved = True
                        mappings_by_key[(node.outline_node_id, version_id)] = mapping
                    else:
                        mapping = CoursePptMapping(
                            course_id=course_id,
                            outline_node_id=node.outline_node_id,
                            material_version_id=version_id,
                            confidence=0.95,
                            status="draft",
                        )
                        mappings.append(mapping)
                        mappings_by_node.setdefault(node.outline_node_id, []).append(mapping)
                        mappings_by_key[(node.outline_node_id, version_id)] = mapping

                is_changed = (
                    moved
                    or mapping.page_refs != page_refs
                    or mapping.page_start != page_refs[0]
                    or mapping.page_end != page_refs[-1]
                    or list(mapping.source_block_refs or []) != source_refs
                    or mapping.status != "draft"
                )
                if not is_changed:
                    continue
                mapping.page_refs = page_refs
                mapping.page_start = page_refs[0]
                mapping.page_end = page_refs[-1]
                mapping.source_block_refs = source_refs
                mapping.status = "draft"
                session.add(mapping)
                changed += 1
                suggestions.append(PptMappingSuggestion(
                    outline_node_id=node.outline_node_id,
                    page_refs=page_refs,
                    confidence=mapping.confidence,
                    reason="根据课程原始 OCR 证据块定位到对应 PPT 页码",
                    material_version_id=version_id,
                ))
        return changed, suggestions

    @staticmethod
    def _load_script_contents(
        session: Session,
        *,
        nodes: list[CourseOutlineNode],
    ) -> dict[str, str]:
        """Load teaching script content for each knowledge-point node.

        Returns a mapping ``outline_node_id -> script_content`` (truncated
        to 500 chars to keep the LLM payload small). Nodes without a
        script are absent from the dict.
        """
        from app.models.course_outline_model import TeachingScriptNode, TeachingScriptVersion
        from app.models.course_outline_model import OutlineLifecycleStatus

        outline_version_id = nodes[0].outline_version_id if nodes else None
        if not outline_version_id:
            return {}
        # Find the latest draft script version aligned with the outline
        script_version = session.exec(
            select(TeachingScriptVersion).where(
                TeachingScriptVersion.course_id == nodes[0].course_id,
                TeachingScriptVersion.outline_version_id == outline_version_id,
                TeachingScriptVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
            ).order_by(TeachingScriptVersion.version.desc())
        ).first()
        if script_version is None:
            return {}
        script_rows = list(session.exec(
            select(TeachingScriptNode).where(
                TeachingScriptNode.script_version_id == script_version.script_version_id,
                TeachingScriptNode.outline_node_id.in_(
                    [n.outline_node_id for n in nodes]
                ),
            )
        ).all())
        return {
            row.outline_node_id: (row.content or "")[:500]
            for row in script_rows
            if (row.content or "").strip()
        }

    @staticmethod
    def _load_parent_titles(
        session: Session,
        *,
        nodes: list[CourseOutlineNode],
    ) -> dict[str, str]:
        """Load parent chapter/section titles for context.

        Returns a mapping ``outline_node_id -> "父标题 / 祖父标题"``.
        Nodes without a parent are absent from the dict.
        """
        parent_ids = {n.parent_node_id for n in nodes if n.parent_node_id}
        if not parent_ids:
            return {}
        parent_rows = list(session.exec(
            select(CourseOutlineNode).where(
                CourseOutlineNode.outline_node_id.in_(parent_ids)
            )
        ).all())
        parent_map = {r.outline_node_id: r for r in parent_rows}
        result: dict[str, str] = {}
        for n in nodes:
            if not n.parent_node_id:
                continue
            parent = parent_map.get(n.parent_node_id)
            if parent is None:
                continue
            # Build hierarchical context: grandparent / parent
            titles = [parent.title]
            if parent.parent_node_id and parent.parent_node_id in parent_map:
                titles.insert(0, parent_map[parent.parent_node_id].title)
            result[n.outline_node_id] = " / ".join(titles)
        return result

    async def _call_llm(
        self,
        blocks: list[DocumentBlock | PptTextBlock],
        nodes: list[CourseOutlineNode],
        existing: list[CoursePptMapping],
        *,
        script_contents: dict[str, str],
        parent_titles: dict[str, str],
    ) -> list[PptMappingSuggestion]:
        """Call the LLM (adapter or raw client) for mapping suggestions.

        ``nodes_payload`` carries full semantic context (script content,
        parent chapter/section title, source_block_refs) so the LLM can
        judge PPT-to-knowledge-point correspondence beyond title-only
        matching.
        """
        blocks_payload = [
            {
                "page": (
                    block.page if isinstance(block, PptTextBlock)
                    else block.page_or_slide or block.page_number
                ),
                "text": (block.text or "")[:500],
                "source_kind": (
                    block.source_kind if isinstance(block, PptTextBlock)
                    else block.source_kind or "document_parse"
                ),
            }
            for block in blocks
        ]
        nodes_payload = [
            {
                "outline_node_id": n.outline_node_id,
                "title": n.title,
                "parent_title": parent_titles.get(n.outline_node_id, ""),
                "script_content": script_contents.get(n.outline_node_id, ""),
                "source_block_refs": n.source_block_refs or [],
            }
            for n in nodes
        ]
        # existing_payload includes source_block_refs so the LLM can see
        # the first-pass mapping provenance as a reference input.
        existing_payload = [
            {
                "outline_node_id": m.outline_node_id,
                "page_refs": m.page_refs or list(range(m.page_start, m.page_end + 1)),
                "teacher_locked": m.teacher_locked,
                "source_block_refs": m.source_block_refs or [],
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
        """Parse raw LLM output into ``PptMappingSuggestion`` list.

        Accepts both the new ``page_refs: [int, ...]`` format and the
        legacy ``page_start``/``page_end`` range format for backward
        compatibility with older LLM responses.
        """
        if not isinstance(raw, list):
            return []
        result: list[PptMappingSuggestion] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                page_refs_raw = item.get("page_refs")
                if page_refs_raw is not None:
                    # New format: page_refs list
                    page_refs = [int(p) for p in page_refs_raw if p is not None]
                else:
                    # Legacy format: page_start + page_end range
                    start = int(item.get("page_start", 1))
                    end = int(item.get("page_end", start))
                    page_refs = list(range(start, end + 1))
                if not page_refs:
                    continue
                result.append(PptMappingSuggestion(
                    outline_node_id=str(item["outline_node_id"]),
                    page_refs=page_refs,
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
        *,
        max_page: int,
        allowed_pages: Sequence[int] | None = None,
    ) -> list[PptMappingSuggestion]:
        """Reject unknown nodes and slide numbers outside this deck.

        A mapping row stores a material-version ID, so page 40 from one PPT
        must never be accepted merely because another PPT in the course has
        forty slides. Normalising here also keeps ``page_start`` and
        ``page_end`` deterministic for non-contiguous suggestions.
        """
        valid_ids = {n.outline_node_id for n in nodes}
        allowed_page_set = {int(page) for page in (allowed_pages or []) if int(page) > 0}
        valid: list[PptMappingSuggestion] = []
        for suggestion in suggestions:
            page_refs = sorted(set(suggestion.page_refs))
            if (
                suggestion.outline_node_id not in valid_ids
                or not page_refs
                or max_page < 1
                or any(page < 1 or page > max_page for page in page_refs)
                or (allowed_page_set and not set(page_refs).issubset(allowed_page_set))
            ):
                continue
            valid.append(replace(suggestion, page_refs=page_refs))
        return valid

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

        Updates non-locked mappings in place AND creates new mappings
        for knowledge-point nodes that have no existing row. This
        ensures teacher-added nodes (post-structure-adjustment) receive
        PPT mappings during optimization. Returns the count of rows
        created or updated.
        """
        existing_by_node = {m.outline_node_id: m for m in existing}
        touched = 0
        for suggestion in suggestions:
            mapping = existing_by_node.get(suggestion.outline_node_id)
            if mapping is None:
                # Create a new mapping for nodes without an existing row
                # (e.g. teacher-added knowledge points after structure
                # adjustment).
                mapping = CoursePptMapping(
                    course_id=course_id,
                    outline_node_id=suggestion.outline_node_id,
                    material_version_id=material_version_id,
                    page_refs=list(suggestion.page_refs),
                    page_start=suggestion.page_start,
                    page_end=suggestion.page_end,
                    confidence=suggestion.confidence,
                    status="draft",
                    teacher_locked=False,
                )
                session.add(mapping)
                touched += 1
                continue
            if mapping.teacher_locked:
                continue
            mapping.page_refs = list(suggestion.page_refs)
            mapping.page_start = suggestion.page_start
            mapping.page_end = suggestion.page_end
            mapping.confidence = suggestion.confidence
            mapping.status = "draft"
            session.add(mapping)
            touched += 1
        return touched

    @staticmethod
    def _llm_is_configured() -> bool:
        """Check if the LLM client has the required configuration."""
        return bool(
            getattr(settings, "LLM_API_KEY", "") and getattr(settings, "LLM_MODEL_NAME", "")
        )


# Module-level singleton (mirrors CoursePrepAgentService convention).
ppt_mapping_optimization_service = PptMappingOptimizationService()


__all__ = [
    "PptMappingContentUnavailable",
    "PptMappingSuggestion",
    "PptMappingOptimizationSummary",
    "PptMappingOptimizationService",
    "ppt_mapping_optimization_service",
]
