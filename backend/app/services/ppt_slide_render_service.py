"""Render teacher-uploaded PPT sources into immutable slide images.

These assets are the visual source of truth for both the construction mapping
workbench and learner playback.  They are intentionally separate from OCR
evidence renders: OCR may describe a slide, but must never be used to rebuild
or replace the teacher's slide image.
"""
from __future__ import annotations

import hashlib
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from sqlmodel import Session, select

from app.models.course_build_model import SourceMaterialVersion
from app.models.document_parse_model import EvidenceRenderAsset, RenderAssetType
from app.services.object_storage import get_object_storage


class PptSlideRenderError(RuntimeError):
    """A safe, actionable failure while rendering an original slide source."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class PptSlideRenderStatus:
    """Cache inventory for one teacher-uploaded deck, without rendering it."""

    material_version_id: str
    expected_page_count: Optional[int]
    cached_pages: tuple[int, ...]
    missing_pages: tuple[int, ...]

    @property
    def cached_page_count(self) -> int:
        return len(self.cached_pages)

    @property
    def is_complete(self) -> bool:
        return self.expected_page_count is not None and not self.missing_pages


def _normalise_pages(page_numbers: Optional[Iterable[int]]) -> list[int]:
    if page_numbers is None:
        return []
    result: set[int] = set()
    for value in page_numbers:
        try:
            page = int(value)
        except (TypeError, ValueError):
            continue
        if page >= 1:
            result.add(page)
    return sorted(result)


def _load_source_version(
    session: Session,
    *,
    course_id: int,
    material_version_id: str,
) -> SourceMaterialVersion:
    version = session.exec(select(SourceMaterialVersion).where(
        SourceMaterialVersion.course_id == course_id,
        SourceMaterialVersion.version_id == material_version_id,
    )).first()
    if version is None or not version.file_path:
        raise PptSlideRenderError("PPT_SOURCE_UNAVAILABLE", "PPT source version is unavailable")
    if Path(version.file_path).suffix.lower() not in {".pptx", ".ppt"}:
        raise PptSlideRenderError("PPT_SOURCE_INVALID", "Source material is not a PPT/PPTX file")
    return version


def _cached_assets_by_page(
    session: Session,
    *,
    course_id: int,
    material_version_id: str,
    storage,
) -> dict[int, EvidenceRenderAsset]:
    rows = list(session.exec(select(EvidenceRenderAsset).where(
        EvidenceRenderAsset.course_id == course_id,
        EvidenceRenderAsset.asset_type == RenderAssetType.PPT_SLIDE_IMAGE,
        EvidenceRenderAsset.object_key.like(f"ppt-slide-render/course{course_id}/{material_version_id}/%"),
    ).order_by(EvidenceRenderAsset.created_at.desc(), EvidenceRenderAsset.id.desc())).all())
    existing_by_page: dict[int, EvidenceRenderAsset] = {}
    for asset in rows:
        if asset.page_number < 1 or asset.page_number in existing_by_page or not asset.object_key:
            continue
        try:
            if not storage.exists(asset.object_key):
                continue
        except Exception:
            # A cache probe must never turn a transient storage lookup error
            # into a full LibreOffice conversion.
            continue
        existing_by_page[asset.page_number] = asset
    return existing_by_page


def _expected_page_count(
    session: Session,
    *,
    course_id: int,
    version: SourceMaterialVersion,
    storage,
    cached_pages: Iterable[int],
) -> Optional[int]:
    """Resolve deck size without converting the deck again."""
    if Path(version.file_path).suffix.lower() == ".pptx":
        try:
            from pptx import Presentation

            presentation = Presentation(io.BytesIO(storage.get(version.file_path)))
            return len(presentation.slides)
        except Exception:
            # The renderer remains the authoritative failure path when the
            # source is actually needed. Inventory inspection is best-effort.
            pass

    # Legacy .ppt has no native in-process counter.  Its parse projection is
    # still a safe lower-bound inventory and does not invoke LibreOffice.
    try:
        from app.models.document_parse_model import DocumentBlock

        pages = list(session.exec(select(DocumentBlock.page_or_slide).where(
            DocumentBlock.course_id == course_id,
            DocumentBlock.material_version_id == version.version_id,
            DocumentBlock.page_or_slide > 0,
        )).all())
    except Exception:
        pages = []
    known_pages = [int(page) for page in pages if int(page or 0) > 0]
    known_pages.extend(int(page) for page in cached_pages if int(page) > 0)
    return max(known_pages) if known_pages else None


def get_ppt_source_slide_render_status(
    session: Session,
    *,
    course_id: int,
    material_version_id: str,
    storage=None,
) -> PptSlideRenderStatus:
    """Return cached and missing original-slide pages without rendering."""
    version = _load_source_version(
        session,
        course_id=course_id,
        material_version_id=material_version_id,
    )
    storage = storage or get_object_storage()
    existing_by_page = _cached_assets_by_page(
        session,
        course_id=course_id,
        material_version_id=material_version_id,
        storage=storage,
    )
    expected_page_count = _expected_page_count(
        session,
        course_id=course_id,
        version=version,
        storage=storage,
        cached_pages=existing_by_page,
    )
    expected_pages = set(range(1, expected_page_count + 1)) if expected_page_count else set()
    return PptSlideRenderStatus(
        material_version_id=material_version_id,
        expected_page_count=expected_page_count,
        cached_pages=tuple(sorted(existing_by_page)),
        missing_pages=tuple(sorted(expected_pages.difference(existing_by_page))),
    )


def ensure_ppt_source_slide_renders(
    session: Session,
    *,
    course_id: int,
    material_version_id: str,
    page_numbers: Optional[Iterable[int]] = None,
    force_full: bool = False,
    run_id: Optional[str] = None,
    document_id: Optional[str] = None,
    on_page_rendered: Optional[Callable[[int], None]] = None,
) -> dict[int, EvidenceRenderAsset]:
    """Return original-slide image assets, rendering only missing requested pages.

    ``page_numbers=None`` intentionally means render the whole deck during the
    parse pipeline.  Mapping workspaces pass one small page window, avoiding
    large request payloads and retaining a deterministic cache for later
    learner playback.
    """
    version = session.exec(select(SourceMaterialVersion).where(
        SourceMaterialVersion.course_id == course_id,
        SourceMaterialVersion.version_id == material_version_id,
    )).first()
    if version is None or not version.file_path:
        raise PptSlideRenderError("PPT_SOURCE_UNAVAILABLE", "未找到当前 PPT 原课件版本。")
    suffix = Path(version.file_path).suffix.lower()
    if suffix not in {".pptx", ".ppt"}:
        raise PptSlideRenderError("PPT_SOURCE_INVALID", "当前材料不是可渲染的 PPT/PPTX 原课件。")

    requested_pages = _normalise_pages(page_numbers)
    existing_rows = list(session.exec(select(EvidenceRenderAsset).where(
        EvidenceRenderAsset.course_id == course_id,
        EvidenceRenderAsset.asset_type == RenderAssetType.PPT_SLIDE_IMAGE,
        EvidenceRenderAsset.object_key.like(f"ppt-slide-render/course{course_id}/{material_version_id}/%"),
    ).order_by(EvidenceRenderAsset.created_at.desc(), EvidenceRenderAsset.id.desc())).all())
    existing_by_page: dict[int, EvidenceRenderAsset] = {}
    for asset in existing_rows:
        if asset.page_number >= 1 and asset.page_number not in existing_by_page and asset.object_key:
            existing_by_page[asset.page_number] = asset

    storage = get_object_storage()
    # Re-read through the storage inventory: DB rows whose immutable object
    # disappeared are cache misses, not valid manifest pages.
    existing_by_page = _cached_assets_by_page(
        session,
        course_id=course_id,
        material_version_id=material_version_id,
        storage=storage,
    )
    expected_page_count: Optional[int] = None
    if page_numbers is None and not force_full:
        expected_page_count = _expected_page_count(
            session,
            course_id=course_id,
            version=version,
            storage=storage,
            cached_pages=existing_by_page,
        )
        if expected_page_count is not None:
            requested_pages = list(range(1, expected_page_count + 1))
        elif existing_by_page:
            # Do not perform a full conversion merely because a legacy deck
            # has no reliable in-process page inventory.
            return existing_by_page

    missing = [page for page in requested_pages if page not in existing_by_page]
    if page_numbers is None and expected_page_count is not None and not missing and not force_full:
        return existing_by_page
    if page_numbers is not None and not missing:
        return {page: existing_by_page[page] for page in requested_pages}
    rendered_images: list[tuple[int, bytes]] = []
    try:
        content = storage.get(version.file_path)
    except FileNotFoundError as exc:
        raise PptSlideRenderError("PPT_SOURCE_UNAVAILABLE", "教师上传的 PPT 原文件已不可读取。") from exc
    except Exception as exc:
        raise PptSlideRenderError("PPT_SOURCE_UNAVAILABLE", f"读取 PPT 原文件失败：{type(exc).__name__}") from exc

    try:
        from app.platform.document_intelligence.libreoffice_converter import (
            ConversionError,
            libreoffice_converter,
        )
        with tempfile.TemporaryDirectory(prefix="ppt_source_slide_") as temp_dir:
            source_path = Path(temp_dir) / f"source{suffix}"
            source_path.write_bytes(content)
            conversion = libreoffice_converter.convert_to_pdf(str(source_path), output_dir=temp_dir)
            # ``requested_pages`` is populated with the full PPTX inventory
            # for manifest construction.  That makes a partial cache render
            # only the gaps rather than re-rendering every cached slide.
            target_pages = None if force_full or not requested_pages else missing
            image_paths = libreoffice_converter.render_pages(
                conversion.pdf_path,
                output_dir=temp_dir,
                pages=target_pages,
            )
            for image_path in image_paths:
                page_number = _page_number_from_image_path(image_path)
                if page_number is not None:
                    rendered_images.append((page_number, Path(image_path).read_bytes()))
    except ConversionError as exc:
        raise PptSlideRenderError(exc.error_code, exc.message) from exc
    except Exception as exc:
        raise PptSlideRenderError(
            "PPT_SOURCE_RENDER_FAILED",
            f"PPT 原课件页图生成失败：{type(exc).__name__}",
        ) from exc
    if not rendered_images:
        raise PptSlideRenderError("PPT_SOURCE_RENDER_FAILED", "PPT 原课件未生成任何可用页图。")

    for page_number, image_bytes in rendered_images:
        content_hash = hashlib.sha256(image_bytes).hexdigest()
        object_key = (
            f"ppt-slide-render/course{course_id}/{material_version_id}/"
            f"page-{page_number}-{content_hash[:16]}.png"
        )
        if not storage.exists(object_key):
            storage.put(object_key, image_bytes, mime_type="image/png")
        with io.BytesIO(image_bytes) as stream:
            from PIL import Image
            with Image.open(stream) as image:
                width, height = image.size
        asset = session.exec(select(EvidenceRenderAsset).where(
            EvidenceRenderAsset.course_id == course_id,
            EvidenceRenderAsset.asset_type == RenderAssetType.PPT_SLIDE_IMAGE,
            EvidenceRenderAsset.object_key == object_key,
        )).first()
        if asset is None:
            asset = EvidenceRenderAsset(
                course_id=course_id,
                run_id=run_id,
                document_id=document_id,
                page_number=page_number,
                asset_type=RenderAssetType.PPT_SLIDE_IMAGE,
                object_key=object_key,
                mime_type="image/png",
                width=width,
                height=height,
                content_hash=content_hash,
            )
            session.add(asset)
            session.flush()
        # The guarded media content route serves objects only when they are
        # present in the MediaAsset ledger.  Without this registration the
        # learner playback manifests sign URLs that 404 even though the bytes
        # exist in object storage.
        from app.models.media_timeline_model import MediaAsset, StorageBackend
        existing_media = session.exec(select(MediaAsset).where(
            MediaAsset.object_key == object_key,
        )).first()
        if existing_media is None:
            storage_backend = getattr(storage, "backend_name", "local")
            session.add(MediaAsset(
                course_id=course_id,
                object_key=object_key,
                asset_type="ppt_image",
                backend=StorageBackend.LOCAL if storage_backend == "local" else StorageBackend.OSS,
                mime_type="image/png",
                size_bytes=len(image_bytes),
                content_hash=content_hash,
                resource_version="ppt-manifest/v1",
            ))
        existing_by_page[page_number] = asset
        if on_page_rendered is not None:
            on_page_rendered(page_number)

    if page_numbers is not None:
        return {page: existing_by_page[page] for page in requested_pages if page in existing_by_page}
    return existing_by_page


def _page_number_from_image_path(image_path: str) -> Optional[int]:
    """Read the stable ``slide-{page}.png`` filename from the shared renderer."""
    stem = Path(image_path).stem
    if not stem.startswith("slide_"):
        return None
    try:
        page = int(stem.removeprefix("slide_"))
    except ValueError:
        return None
    return page if page >= 1 else None
