"""Regression coverage for teacher-original PPT slide renditions.

These tests deliberately replace LibreOffice and object storage.  They prove
the asset contract without invoking a paid service or an installed office
runtime.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from sqlmodel import select

from app.models.course_build_model import SourceMaterial, SourceMaterialVersion
from app.models.course_model import Course, CourseStatus
from app.models.document_parse_model import EvidenceRenderAsset, RenderAssetType
from app.models.user_model import User, UserRole
from app.core.security import get_password_hash
from app.services import ppt_slide_render_service
from app.services.ppt_manifest_service import sign_manifest_pages


class _MemoryStorage:
    def __init__(self, initial: dict[str, bytes] | None = None):
        self.objects = dict(initial or {})

    def get(self, object_key: str) -> bytes:
        return self.objects[object_key]

    def put(self, object_key: str, content: bytes, **_kwargs) -> None:
        self.objects[object_key] = content

    def exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def sign_read_url(self, object_key: str, **_kwargs) -> str:
        return f"/signed/{object_key}"


class _FakeLibreOfficeConverter:
    def __init__(self):
        self.requested_page_sets: list[tuple[int, ...] | None] = []

    def convert_to_pdf(self, _source_path: str, *, output_dir: str):
        pdf_path = Path(output_dir) / "source.pdf"
        pdf_path.write_bytes(b"fake-pdf")
        return SimpleNamespace(pdf_path=str(pdf_path))

    def render_pages(self, _pdf_path: str, *, output_dir: str, pages=None, **_kwargs):
        requested = tuple(pages) if pages is not None else None
        self.requested_page_sets.append(requested)
        result = []
        for page in (pages if pages is not None else [1, 2]):
            if page not in {1, 2}:
                continue
            image = Image.new("RGB", (64, 36), color=(page * 40, 30, 20))
            image_path = Path(output_dir) / f"slide_{page}.png"
            image.save(image_path)
            assert image_path.is_file(), (image_path, list(Path(output_dir).iterdir()))
            result.append(str(image_path))
        return result


def _course_with_uploaded_ppt(session, *, fixture_key: str = "default"):
    teacher = User(
        username=f"original-slide-render-teacher-{fixture_key}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
    )
    session.add(teacher)
    session.flush()
    course = Course(
        fanya_course_id=f"original-slide-render-course-{fixture_key}",
        fanya_course_name="Original slides",
        title="Original slides",
        teacher_id=teacher.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.flush()
    material = SourceMaterial(
        course_id=course.id,
        name="teacher-deck.pptx",
        material_type="slide",
        material_role="primary_courseware",
    )
    session.add(material)
    session.flush()
    version = SourceMaterialVersion(
        course_id=course.id,
        material_id=material.material_id,
        file_path="source-material/course/deck.pptx",
        file_hash="teacher-deck-hash",
    )
    session.add(version)
    session.commit()
    return course, version


def test_original_slide_render_ignores_generic_evidence_and_completes_whole_deck(session, monkeypatch):
    course, version = _course_with_uploaded_ppt(session, fixture_key="whole-deck")
    storage = _MemoryStorage({version.file_path: b"teacher-pptx-bytes"})
    converter = _FakeLibreOfficeConverter()
    monkeypatch.setattr(ppt_slide_render_service, "get_object_storage", lambda: storage)
    import app.platform.document_intelligence.libreoffice_converter as converter_module
    monkeypatch.setattr(converter_module, "libreoffice_converter", converter)

    # This records the historical OCR/text reconstruction. It must never be
    # returned as the courseware image for the teacher's deck.
    generic = EvidenceRenderAsset(
        course_id=course.id,
        page_number=1,
        asset_type=RenderAssetType.PAGE_IMAGE,
        object_key="evidence-render/course/page-1.png",
        content_hash="synthetic-text-image",
    )
    session.add(generic)
    session.commit()

    first_page = ppt_slide_render_service.ensure_ppt_source_slide_renders(
        session,
        course_id=course.id,
        material_version_id=version.version_id,
        page_numbers=[1],
    )
    assert first_page[1].asset_type == RenderAssetType.PPT_SLIDE_IMAGE
    assert first_page[1].object_key.startswith(
        f"ppt-slide-render/course{course.id}/{version.version_id}/page-1-"
    )
    assert first_page[1].object_key != generic.object_key

    # A later release needs the entire deck, even if an earlier mapping page
    # request had only warmed the first slide.
    all_pages = ppt_slide_render_service.ensure_ppt_source_slide_renders(
        session,
        course_id=course.id,
        material_version_id=version.version_id,
        force_full=True,
    )
    assert sorted(all_pages) == [1, 2]
    assert converter.requested_page_sets == [(1,), None]
    persisted = session.exec(select(EvidenceRenderAsset).where(
        EvidenceRenderAsset.course_id == course.id,
        EvidenceRenderAsset.asset_type == RenderAssetType.PPT_SLIDE_IMAGE,
    )).all()
    assert {asset.page_number for asset in persisted} == {1, 2}


def test_manifest_cache_inventory_renders_only_missing_pptx_page(session, monkeypatch):
    """A partial mapping cache must not be discarded by manifest generation."""
    course, version = _course_with_uploaded_ppt(session, fixture_key="cache-gap")
    storage = _MemoryStorage({version.file_path: b"teacher-pptx-bytes"})
    converter = _FakeLibreOfficeConverter()
    monkeypatch.setattr(ppt_slide_render_service, "get_object_storage", lambda: storage)
    monkeypatch.setattr(
        ppt_slide_render_service,
        "_expected_page_count",
        lambda *_args, **_kwargs: 2,
    )
    import app.platform.document_intelligence.libreoffice_converter as converter_module
    monkeypatch.setattr(converter_module, "libreoffice_converter", converter)

    ppt_slide_render_service.ensure_ppt_source_slide_renders(
        session,
        course_id=course.id,
        material_version_id=version.version_id,
        page_numbers=[1],
    )
    completed = ppt_slide_render_service.ensure_ppt_source_slide_renders(
        session,
        course_id=course.id,
        material_version_id=version.version_id,
    )

    assert sorted(completed) == [1, 2]
    # The second call is the manifest-style full-deck request.  It keeps the
    # mapped first page and asks LibreOffice for page 2 only.
    assert converter.requested_page_sets == [(1,), (2,)]


def test_sign_manifest_pages_preserves_per_deck_teacher_slide_urls():
    storage = _MemoryStorage()
    manifest = {
        "schema": "ppt-manifest/v1",
        "source_sha256": "primary-hash",
        "primary_material_version_id": "smv_primary",
        "pages": [{"page": 1, "image_object_key": "ppt-slide-render/primary/1.png"}],
        "decks": [
            {
                "material_version_id": "smv_primary",
                "material_name": "Primary deck",
                "source_sha256": "primary-hash",
                "pages": [{"page": 1, "image_object_key": "ppt-slide-render/primary/1.png"}],
            },
            {
                "material_version_id": "smv_appendix",
                "material_name": "Appendix",
                "source_sha256": "appendix-hash",
                "pages": [{"page": 3, "image_object_key": "ppt-slide-render/appendix/3.png"}],
            },
        ],
    }

    signed = sign_manifest_pages(manifest, storage, course_id=7, release_id="mrel_test")

    assert signed["primary_material_version_id"] == "smv_primary"
    assert signed["pages"][0]["image_url"].endswith("ppt-slide-render/primary/1.png")
    assert [deck["material_version_id"] for deck in signed["decks"]] == [
        "smv_primary",
        "smv_appendix",
    ]
    assert signed["decks"][1]["pages"][0]["page"] == 3
