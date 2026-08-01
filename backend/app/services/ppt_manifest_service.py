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
from typing import Any, Optional

from PIL import Image
from sqlmodel import Session, select

from app.models.course_model import Course
from app.models.media_release_model import MediaRelease
from app.models.media_timeline_model import MediaAsset, StorageBackend
from app.services.object_storage import ObjectStorageProvider, get_object_storage

logger = logging.getLogger(__name__)

PPT_MANIFEST_SCHEMA = "ppt-manifest/v1"


class PptManifestGenerationError(RuntimeError):
    """Raised when a declared PPT/PDF source cannot be rendered."""


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
    pages = []
    for item in manifest.get("pages", []):
        object_key = item.get("image_object_key")
        if not object_key:
            continue
        page = {
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
        }
        pages.append(page)
    return {
        "schema": PPT_MANIFEST_SCHEMA,
        "source_sha256": manifest.get("source_sha256", ""),
        "pages": pages,
    }


def build_ppt_manifest(
    session: Session,
    *,
    course_id: int,
    release: MediaRelease,
    storage: Optional[ObjectStorageProvider] = None,
) -> dict[str, Any] | None:
    """Render a course source and bind a release-scoped immutable manifest.

    Returns ``None`` when the course has no source deck.  This preserves legacy
    courses while making the missing release asset explicit to the caller.
    """
    course = session.get(Course, course_id)
    if course is None:
        return None
    storage = storage or get_object_storage()
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
