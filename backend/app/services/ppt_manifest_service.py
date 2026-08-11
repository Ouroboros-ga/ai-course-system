"""Build and serve immutable ``ppt-manifest/v1`` release assets.

PPTX/PDF rendering belongs to the course-build/release side.  Learners only
receive signed image URLs and never receive source file paths or PPTX bytes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from PIL import Image
from sqlmodel import Session, select

from app.models.course_build_model import SourceMaterial, SourceMaterialVersion
from app.models.course_model import Course
from app.models.media_release_model import MediaRelease
from app.models.media_timeline_model import MediaAsset, StorageBackend
from app.services.object_storage import ObjectStorageProvider, get_object_storage

logger = logging.getLogger(__name__)

PPT_MANIFEST_SCHEMA = "ppt-manifest/v1"


class PptManifestGenerationError(RuntimeError):
    """Raised when a declared PPT/PDF source cannot be rendered."""


def material_deck_sort_key(
    material: SourceMaterial | None,
    version: SourceMaterialVersion | None,
    *,
    fallback_id: str = "",
) -> tuple[Any, ...]:
    """Return the canonical teacher-deck ordering used by mapping and playback."""
    return (
        bool(material and material.material_role != "primary_courseware"),
        version.created_at.isoformat() if version and version.created_at else "",
        version.version_id if version else fallback_id,
        fallback_id,
    )


def _read_course_source(course: Course, storage: ObjectStorageProvider) -> tuple[bytes, str] | None:
    """Read a legacy local path or an object-storage source without exposing it."""
    source_ref = course.source_file_path or course.pdf_file_path or ""
    if not source_ref:
        return None
    source_path = Path(source_ref)
    if source_path.is_file():
        return source_path.read_bytes(), source_path.suffix.lower()
    try:
        if storage.exists(source_ref):
            suffix = Path(course.source_file_name or source_ref).suffix.lower()
            return storage.get(source_ref), suffix
    except Exception:
        logger.debug("Unable to read course source object", exc_info=True)
    return None


def _current_uploaded_slide_versions(
    session: Session,
    *,
    course_id: int,
) -> list[tuple[SourceMaterial, SourceMaterialVersion]]:
    """Return deduplicated current teacher-uploaded decks in playback order."""
    rows = list(session.exec(select(SourceMaterial, SourceMaterialVersion).where(
        SourceMaterial.course_id == course_id,
        SourceMaterial.material_id == SourceMaterialVersion.material_id,
        SourceMaterialVersion.course_id == course_id,
        SourceMaterialVersion.is_current == True,  # noqa: E712
        SourceMaterial.material_type == "slide",
    )).all())
    rows.sort(key=lambda item: material_deck_sort_key(item[0], item[1]))
    deduplicated: list[tuple[SourceMaterial, SourceMaterialVersion]] = []
    seen_hashes: set[str] = set()
    for material, version in rows:
        fingerprint = version.file_hash or version.version_id
        if not version.file_path or fingerprint in seen_hashes:
            continue
        seen_hashes.add(fingerprint)
        deduplicated.append((material, version))
    return deduplicated


def has_ppt_manifest_source(session: Session, *, course_id: int) -> bool:
    """Whether this course declares a source that requires a PPT manifest.

    Audio-only releases are valid.  This check is intentionally metadata-only:
    it must not read a source object, invoke LibreOffice, or turn activation
    into a long-running request.
    """
    if _current_uploaded_slide_versions(session, course_id=course_id):
        return True
    course = session.get(Course, course_id)
    if course is None:
        return False
    source_ref = course.source_file_path or course.pdf_file_path or ""
    source_name = course.source_file_name or source_ref
    return bool(source_ref and Path(source_name).suffix.lower() in {".ppt", ".pptx", ".pdf"})


def _manifest_deck_from_uploaded_source(
    session: Session,
    *,
    course_id: int,
    material: SourceMaterial,
    version: SourceMaterialVersion,
    on_page_rendered: Optional[Callable[[int], None]] = None,
) -> dict[str, Any]:
    """Build one deck entry from the shared original-slide render cache."""
    from app.services.ppt_slide_render_service import ensure_ppt_source_slide_renders

    assets = ensure_ppt_source_slide_renders(
        session,
        course_id=course_id,
        material_version_id=version.version_id,
        on_page_rendered=on_page_rendered,
    )
    pages = [
        {
            "page": page,
            "image_object_key": asset.object_key,
            "width": asset.width,
            "height": asset.height,
        }
        for page, asset in sorted(assets.items())
        if asset.object_key
    ]
    if not pages:
        raise PptManifestGenerationError("teacher PPT source rendered no usable slide images")
    return {
        "material_version_id": version.version_id,
        "material_name": material.name,
        "source_sha256": version.file_hash,
        "pages": pages,
    }


def _register_asset(
    session: Session,
    *,
    storage: ObjectStorageProvider,
    course_id: int,
    object_key: str,
    asset_type: str,
    mime_type: str,
    size_bytes: int,
    content_hash: str,
) -> None:
    """Keep the signed media route's asset ledger in sync with the object."""
    existing = session.exec(select(MediaAsset).where(MediaAsset.object_key == object_key)).first()
    if existing:
        return
    storage_backend = getattr(storage, "backend_name", "local")
    backend = StorageBackend.LOCAL if storage_backend == "local" else StorageBackend.OSS
    session.add(MediaAsset(
        course_id=course_id,
        object_key=object_key,
        asset_type=asset_type,
        backend=backend,
        mime_type=mime_type,
        size_bytes=size_bytes,
        content_hash=content_hash,
        resource_version="ppt-manifest/v1",
    ))


def load_manifest(storage: ObjectStorageProvider, object_key: str) -> dict[str, Any]:
    """Load and minimally validate an immutable manifest object."""
    payload = json.loads(storage.get(object_key).decode("utf-8"))
    if payload.get("schema") != PPT_MANIFEST_SCHEMA:
        raise ValueError("PPT manifest schema 不受支持")
    if not isinstance(payload.get("pages"), list):
        raise ValueError("PPT manifest pages 缺失")
    return payload


def sign_manifest_pages(
    manifest: dict[str, Any],
    storage: ObjectStorageProvider,
    *,
    course_id: int,
    release_id: str,
) -> dict[str, Any]:
    """Materialize short-lived image URLs from immutable object keys."""
    def sign_pages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pages = []
        for item in items:
            object_key = item.get("image_object_key")
            if not object_key:
                continue
            pages.append({
                "page": int(item.get("page") or 1),
                "image_url": storage.sign_read_url(
                    object_key,
                    scope={
                        "course_id": course_id,
                        "purpose": "ppt_playback",
                        "release_id": release_id,
                    },
                ),
                "width": int(item.get("width") or 0),
                "height": int(item.get("height") or 0),
            })
        return pages

    pages = sign_pages(manifest.get("pages", []))
    decks = []
    for deck in manifest.get("decks", []):
        if not isinstance(deck, dict) or not deck.get("material_version_id"):
            continue
        decks.append({
            "material_version_id": str(deck["material_version_id"]),
            "material_name": str(deck.get("material_name") or "PPT"),
            "source_sha256": str(deck.get("source_sha256") or ""),
            "pages": sign_pages(deck.get("pages") or []),
        })
    return {
        "schema": PPT_MANIFEST_SCHEMA,
        "source_sha256": manifest.get("source_sha256", ""),
        "primary_material_version_id": manifest.get("primary_material_version_id"),
        "pages": pages,
        "decks": decks,
    }


def ppt_manifest_input_fingerprint(session: Session, *, course_id: int) -> str:
    """Stable fingerprint used to deduplicate one release manifest task."""
    course = session.get(Course, course_id)
    deck_inputs = [
        {
            "material_version_id": version.version_id,
            "source_sha256": version.file_hash,
            "file_path": version.file_path,
        }
        for _material, version in _current_uploaded_slide_versions(session, course_id=course_id)
    ]
    payload = {
        "decks": deck_inputs,
        "legacy_source": (course.source_file_path or course.pdf_file_path or "") if course else "",
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_ppt_manifest(
    session: Session,
    *,
    course_id: int,
    release: MediaRelease,
    storage: Optional[ObjectStorageProvider] = None,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any] | None:
    """Render a course source and bind a release-scoped immutable manifest.

    Returns ``None`` when the course has no source deck.  This preserves legacy
    courses while making the missing release asset explicit to the caller.
    """
    course = session.get(Course, course_id)
    if course is None:
        return None
    storage = storage or get_object_storage()

    # The course build workspace stores teacher uploads as material versions.
    # Prefer those exact PPTX sources over legacy ``Course.source_file_path``
    # so mapping and learner playback share the same visual assets.
    uploaded_decks: list[dict[str, Any]] = []
    uploaded_sources = _current_uploaded_slide_versions(session, course_id=course_id)
    if uploaded_sources:
        from app.services.ppt_slide_render_service import (
            PptSlideRenderError,
            get_ppt_source_slide_render_status,
        )

        statuses = {
            version.version_id: get_ppt_source_slide_render_status(
                session,
                course_id=course_id,
                material_version_id=version.version_id,
                storage=storage,
            )
            for _material, version in uploaded_sources
        }
        total_pages = sum(
            status.expected_page_count if status.expected_page_count is not None else status.cached_page_count
            for status in statuses.values()
        )
        progress = {
            "stage": "checking_cache",
            "total_pages": total_pages,
            "completed_pages": sum(status.cached_page_count for status in statuses.values()),
            "cached_pages": sum(status.cached_page_count for status in statuses.values()),
            "missing_pages": sum(len(status.missing_pages) for status in statuses.values()),
            "deck_count": len(uploaded_sources),
        }

        def emit_progress(stage: str, **updates: Any) -> None:
            if progress_callback is None:
                return
            progress["stage"] = stage
            progress.update(updates)
            progress_callback(dict(progress))

        emit_progress("checking_cache")
    else:
        statuses = {}
        progress = {}

        def emit_progress(_stage: str, **_updates: Any) -> None:
            return

    for material, version in uploaded_sources:
        status = statuses[version.version_id]

        def on_page_rendered(_page_number: int, *, deck_version_id: str = version.version_id) -> None:
            progress["completed_pages"] = min(
                int(progress.get("total_pages") or 0),
                int(progress.get("completed_pages") or 0) + 1,
            )
            emit_progress("rendering_pages", material_version_id=deck_version_id)

        try:
            uploaded_decks.append(_manifest_deck_from_uploaded_source(
                session,
                course_id=course_id,
                material=material,
                version=version,
                on_page_rendered=on_page_rendered,
            ))
        except PptSlideRenderError as exc:
            # Surface the renderer's stable, actionable cause (for example
            # CONVERTER_UNAVAILABLE when LibreOffice is missing) to the caller
            # instead of leaking an unhandled 500.
            raise PptManifestGenerationError(f"{exc.error_code}: {exc.message}") from exc
        if status.expected_page_count is None:
            # Legacy decks may only reveal their exact count after the cached
            # assets are read.  Keep progress truthful instead of inventing a
            # denominator before a render is complete.
            progress["total_pages"] = max(
                int(progress.get("total_pages") or 0),
                sum(len(deck["pages"]) for deck in uploaded_decks),
            )
            progress["completed_pages"] = min(
                int(progress["total_pages"]),
                max(int(progress.get("completed_pages") or 0), sum(len(deck["pages"]) for deck in uploaded_decks)),
            )
        emit_progress("binding_manifest", material_version_id=version.version_id)
    if uploaded_decks:
        primary_deck = uploaded_decks[0]
        emit_progress("writing_manifest")
        manifest = {
            "schema": PPT_MANIFEST_SCHEMA,
            "source_sha256": primary_deck["source_sha256"],
            "primary_material_version_id": primary_deck["material_version_id"],
            # Existing players consume top-level pages.  Keep those bound to
            # the designated primary deck while new players select a deck from
            # the additive ``decks`` collection via the PPT mapping snapshot.
            "pages": primary_deck["pages"],
            "decks": uploaded_decks,
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_key = (
            f"ppt-manifest/course{course_id}/{release.release_id}/"
            f"manifest-{manifest_hash[:16]}.json"
        )
        if not storage.exists(manifest_key):
            storage.put(manifest_key, manifest_bytes, mime_type="application/json")
        _register_asset(
            session,
            storage=storage,
            course_id=course_id,
            object_key=manifest_key,
            asset_type="ppt_manifest",
            mime_type="application/json",
            size_bytes=len(manifest_bytes),
            content_hash=manifest_hash,
        )
        release.ppt_manifest_object_key = manifest_key
        release.release_metadata = {
            **(release.release_metadata or {}),
            "ppt_manifest_schema": PPT_MANIFEST_SCHEMA,
            "ppt_source_sha256": primary_deck["source_sha256"],
            "ppt_page_count": len(primary_deck["pages"]),
            "ppt_deck_count": len(uploaded_decks),
            "ppt_primary_material_version_id": primary_deck["material_version_id"],
        }
        session.add(release)
        session.flush()
        emit_progress("completed")
        return manifest

    source = _read_course_source(course, storage)
    if source is None:
        if course.source_file_path or course.pdf_file_path:
            raise PptManifestGenerationError("declared PPT/PDF source is unavailable")
        return None
    source_bytes, suffix = source
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    work_dir = Path(tempfile.gettempdir()) / "ai_course_ppt_release" / str(course_id) / release.release_id
    work_dir.mkdir(parents=True, exist_ok=True)
    source_path = work_dir / f"source{suffix or '.bin'}"
    if not source_path.exists() or source_path.read_bytes() != source_bytes:
        source_path.write_bytes(source_bytes)

    from app.common.slide_converter import get_or_create_pdf, render_pdf_to_images

    try:
        pdf_path = get_or_create_pdf(str(source_path), str(work_dir / "pdf"))
    except Exception as exc:
        raise PptManifestGenerationError("PPT/PDF source conversion failed") from exc
    if not pdf_path:
        raise PptManifestGenerationError("PPT/PDF source conversion returned no PDF")
    image_dir = work_dir / "images"
    try:
        image_paths = render_pdf_to_images(pdf_path, str(image_dir), dpi=150)
    except Exception as exc:
        raise PptManifestGenerationError("PDF page rendering failed") from exc
    if not image_paths:
        raise PptManifestGenerationError("PDF rendering returned no pages")

    pages: list[dict[str, Any]] = []
    for page_number, image_path in enumerate(image_paths, 1):
        image_bytes = Path(image_path).read_bytes()
        content_hash = hashlib.sha256(image_bytes).hexdigest()
        object_key = (
            f"ppt-manifest/course{course_id}/{release.release_id}/"
            f"page-{page_number}-{content_hash[:16]}.png"
        )
        if not storage.exists(object_key):
            storage.put(object_key, image_bytes, mime_type="image/png")
        with Image.open(image_path) as image:
            width, height = image.size
        _register_asset(
            session,
            storage=storage,
            course_id=course_id,
            object_key=object_key,
            asset_type="ppt_image",
            mime_type="image/png",
            size_bytes=len(image_bytes),
            content_hash=content_hash,
        )
        pages.append({
            "page": page_number,
            "image_object_key": object_key,
            "width": width,
            "height": height,
        })

    manifest = {
        "schema": PPT_MANIFEST_SCHEMA,
        "source_sha256": source_sha256,
        "pages": pages,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # Include the source digest so a forced rebuild never overwrites an
    # immutable manifest already observed by learners.
    manifest_key = (
        f"ppt-manifest/course{course_id}/{release.release_id}/"
        f"manifest-{source_sha256[:16]}.json"
    )
    if not storage.exists(manifest_key):
        storage.put(manifest_key, manifest_bytes, mime_type="application/json")
    _register_asset(
        session,
        storage=storage,
        course_id=course_id,
        object_key=manifest_key,
        asset_type="ppt_manifest",
        mime_type="application/json",
        size_bytes=len(manifest_bytes),
        content_hash=hashlib.sha256(manifest_bytes).hexdigest(),
    )
    release.ppt_manifest_object_key = manifest_key
    release.release_metadata = {
        **(release.release_metadata or {}),
        "ppt_manifest_schema": PPT_MANIFEST_SCHEMA,
        "ppt_source_sha256": source_sha256,
        "ppt_page_count": len(pages),
    }
    session.add(release)
    session.flush()
    return manifest
