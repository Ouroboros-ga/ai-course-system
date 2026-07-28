"""P4 regression: published learners read only the frozen release manifest."""
from __future__ import annotations

from sqlmodel import select

from app.core.security import get_password_hash
from app.models.course_build_model import (
    CourseRelease,
    CourseRetrievalSnapshot,
    ReleaseStatus,
)
from app.models.course_model import Course, CourseStatus
from app.models.document_parse_model import DocumentIRVersion, RetrievalChunk
from app.models.user_model import User, UserRole
from app.platform.retrieval.providers.canonical_document_ir import CanonicalDocumentIRRetriever
from app.platform.retrieval.schemas import RetrievalScope


def _course(session) -> Course:
    user = User(
        username="p4_release_teacher",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(user)
    session.flush()
    course = Course(
        fanya_course_id="p4-release-freeze",
        fanya_course_name="P4 release freeze",
        title="P4 release freeze",
        teacher_id=user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.flush()
    return course


def _ir(session, course_id: int, run_id: str, document_id: str) -> DocumentIRVersion:
    version = DocumentIRVersion(
        course_id=course_id,
        material_version_id=f"material-{run_id}",
        run_id=run_id,
        document_id=document_id,
        artifact_id=f"artifact-{run_id}",
    )
    session.add(version)
    session.flush()
    return version


def test_student_retrieval_uses_frozen_chunk_manifest_after_reparse(session):
    """A later active chunk cannot leak into an already published release."""
    course = _course(session)
    first_ir = _ir(session, course.id, "run-p4-1", "doc-p4-1")
    frozen_chunk = RetrievalChunk(
        chunk_id="chunk-p4-frozen",
        course_id=course.id,
        ir_version_id=first_ir.ir_version_id,
        document_id=first_ir.document_id,
        text="热力学第一定律的冻结版本说明",
        anchor_ids=["anchor-p4-frozen"],
        status="active",
    )
    snapshot = CourseRetrievalSnapshot(
        course_id=course.id,
        corpus_snapshot_id="corpus-p4-v1",
        document_ir_version_ids=[first_ir.ir_version_id],
        snapshot_kind="release",
        retrieval_chunk_ids=[frozen_chunk.chunk_id],
        evidence_anchor_ids=["anchor-p4-frozen"],
        status="ready",
    )
    session.add(frozen_chunk)
    session.add(snapshot)
    session.flush()
    release = CourseRelease(
        course_id=course.id,
        version=1,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        document_ir_version_ids=[first_ir.ir_version_id],
        retrieval_snapshot_id=snapshot.retrieval_snapshot_id,
    )
    session.add(release)
    session.commit()

    initial = CanonicalDocumentIRRetriever.retrieve(
        "热力学", scope=RetrievalScope.course(course.id), top_k=5,
    )
    assert [item.chunk_id for item in initial] == ["chunk-p4-frozen"]

    # A newly parsed/reviewed material becomes active in construction space,
    # but its chunk ID was not part of the previous release manifest.
    second_ir = _ir(session, course.id, "run-p4-2", "doc-p4-2")
    # Subsequent teacher-side review may change a projection's current status;
    # it still cannot mutate the already frozen learner manifest.
    frozen_chunk.status = "rejected"
    session.add(frozen_chunk)
    session.add(RetrievalChunk(
        chunk_id="chunk-p4-later",
        course_id=course.id,
        ir_version_id=second_ir.ir_version_id,
        document_id=second_ir.document_id,
        text="热力学重解析后的新材料，学生当前发布版不应读取",
        anchor_ids=["anchor-p4-later"],
        status="active",
    ))
    session.commit()

    after_reparse = CanonicalDocumentIRRetriever.retrieve(
        "热力学", scope=RetrievalScope.course(course.id), top_k=5,
    )
    assert [item.chunk_id for item in after_reparse] == ["chunk-p4-frozen"]
    assert session.exec(select(CourseRelease).where(
        CourseRelease.release_id == release.release_id,
    )).one().retrieval_snapshot_id == snapshot.retrieval_snapshot_id
