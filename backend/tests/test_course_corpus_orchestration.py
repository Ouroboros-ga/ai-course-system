"""P2 regression coverage for course-level material aggregation."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import select

from app.core.security import get_password_hash
from app.models.course_build_model import (
    CourseCorpusItem,
    CourseDraftBuildStatus,
    CourseDraftBuildTask,
    MaterialStatus,
    SourceMaterial,
    SourceMaterialVersion,
)
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import CourseOutlineNode, OutlineNodeType
from app.models.document_parse_model import DocumentBlock, DocumentIRVersion, DocumentParseRun, ParseRunStatus
from app.models.task_model import TaskRecord
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.course_corpus_service import course_corpus_service
from app.services.document_draft_builders import build_draft_assets


def _course_owner(session):
    token = uuid4().hex[:10]
    user = User(username=f"p2_corpus_owner_{token}", hashed_password=get_password_hash("pw"), role=UserRole.TEACHER)
    session.add(user); session.commit(); session.refresh(user)
    course = Course(
        fanya_course_id=f"p2-corpus-course-{token}", fanya_course_name="P2 Corpus",
        title="P2 Corpus", teacher_id=user.id, status=CourseStatus.DRAFT,
    )
    session.add(course); session.commit(); session.refresh(course)
    establish_course_access_baseline(session, course.id, user.id)
    return user, course


def _parsed_material(session, *, course_id, owner_id, role, status=ParseRunStatus.SUCCEEDED):
    material = SourceMaterial(
        course_id=course_id, name=f"{role}.pdf", material_role=role,
        status=MaterialStatus.NEEDS_REVIEW if status == ParseRunStatus.PARTIAL_SUCCESS else MaterialStatus.PARSED,
        created_by=owner_id,
    )
    session.add(material); session.flush()
    version = SourceMaterialVersion(
        course_id=course_id, material_id=material.material_id, file_hash=f"hash-{role}",
        file_path=f"course-source/{role}.pdf", is_current=True,
        parse_status=material.status, created_by=owner_id,
    )
    session.add(version); session.flush()
    material.current_version_id = version.version_id
    run = DocumentParseRun(
        course_id=course_id, material_id=material.material_id, material_version_id=version.version_id,
        initiated_by=owner_id, status=status, started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    session.add(run); session.flush()
    ir = DocumentIRVersion(
        course_id=course_id, material_version_id=version.version_id, run_id=run.run_id,
        document_id=f"doc-{role}", artifact_id=f"artifact-{role}", object_key=f"ir/{role}.json",
    )
    session.add(ir); session.flush()
    run.document_ir_version_id = ir.ir_version_id
    session.add(run); session.commit()
    return material, version


def test_corpus_is_one_role_aware_snapshot_and_partial_parse_is_warning(session):
    owner, course = _course_owner(session)
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="textbook")
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="primary_courseware")
    _parsed_material(
        session, course_id=course.id, owner_id=owner.id, role="experiment_guide",
        status=ParseRunStatus.PARTIAL_SUCCESS,
    )

    corpus = course_corpus_service.create_ready_snapshot(
        session, course_id=course.id, owner_user_id=owner.id,
    )
    assert corpus is not None
    assert len(corpus.material_version_ids) == 3
    assert corpus.warnings
    items = session.exec(select(CourseCorpusItem).where(
        CourseCorpusItem.corpus_snapshot_id == corpus.corpus_snapshot_id,
    )).all()
    assert [(item.material_role, item.priority) for item in sorted(items, key=lambda item: item.priority)] == [
        ("primary_courseware", 10), ("textbook", 30), ("experiment_guide", 40),
    ]
    assert any(item.quality_warning for item in items if item.material_role == "experiment_guide")

    first_build, first_task_id = course_corpus_service.create_build_task(
        session, corpus=corpus, owner_user_id=owner.id, quiet_window_seconds=0,
    )
    same_build, same_task_id = course_corpus_service.create_build_task(
        session, corpus=corpus, owner_user_id=owner.id, quiet_window_seconds=0,
    )
    assert first_build.build_task_id == same_build.build_task_id
    assert first_task_id == same_task_id
    assert session.exec(select(CourseDraftBuildTask).where(
        CourseDraftBuildTask.course_id == course.id,
    )).all()


def test_failed_material_blocks_until_teacher_excludes_it(session):
    owner, course = _course_owner(session)
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="primary_courseware")
    failed = SourceMaterial(
        course_id=course.id, name="broken.pdf", material_role="reference",
        status=MaterialStatus.FAILED, created_by=owner.id,
    )
    session.add(failed); session.flush()
    session.add(SourceMaterialVersion(
        course_id=course.id, material_id=failed.material_id, file_hash="failed", file_path="failed.pdf",
        is_current=True, parse_status=MaterialStatus.FAILED, created_by=owner.id,
    ))
    session.commit()

    assert course_corpus_service.create_ready_snapshot(session, course_id=course.id, owner_user_id=owner.id) is None
    failed.include_in_course_corpus = False
    session.add(failed); session.commit()
    assert course_corpus_service.create_ready_snapshot(session, course_id=course.id, owner_user_id=owner.id) is not None


def test_corpus_role_strategy_keeps_primary_order_and_layers_other_materials(session):
    owner, course = _course_owner(session)
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="textbook")
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="primary_courseware")
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="experiment_guide")
    corpus = course_corpus_service.create_ready_snapshot(session, course_id=course.id, owner_user_id=owner.id)
    assert corpus is not None
    items = {item.material_role: item for item in session.exec(select(CourseCorpusItem).where(
        CourseCorpusItem.corpus_snapshot_id == corpus.corpus_snapshot_id,
    )).all()}
    primary_title = DocumentBlock(
        course_id=course.id, run_id=items["primary_courseware"].parse_run_id,
        text="Primary concept", page_number=1, page_or_slide=1,
        semantic_role="knowledge_title", material_version_id=items["primary_courseware"].material_version_id,
    )
    textbook_detail = DocumentBlock(
        course_id=course.id, run_id=items["textbook"].parse_run_id,
        text="Textbook explanation", page_number=1, page_or_slide=1,
        semantic_role="explanation", material_version_id=items["textbook"].material_version_id,
    )
    experiment_task = DocumentBlock(
        course_id=course.id, run_id=items["experiment_guide"].parse_run_id,
        text="Experiment task", page_number=1, page_or_slide=1,
        semantic_role="explanation", material_version_id=items["experiment_guide"].material_version_id,
    )
    session.add(primary_title); session.add(textbook_detail); session.add(experiment_task); session.commit()

    result = build_draft_assets(
        session, course_id=course.id, corpus_snapshot_id=corpus.corpus_snapshot_id, created_by=owner.id,
    )
    nodes = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == result.outline_version_id,
    )).all()
    knowledge = next(node for node in nodes if node.node_type == OutlineNodeType.KNOWLEDGE_POINT)
    assert knowledge.title == "Primary concept"
    assert textbook_detail.block_id in knowledge.source_block_refs
    practice = next(node for node in nodes if node.node_type == OutlineNodeType.PRACTICE_SUGGESTION)
    assert practice.source_block_refs == [experiment_task.block_id]


def test_material_change_invalidates_stale_queued_build_with_interrupted_task(session):
    """A restart must not make the next material upload return a 409."""
    owner, course = _course_owner(session)
    task = TaskRecord(
        task_id=uuid4().hex,
        task_type="course_draft_build",
        status="interrupted",
        owner_user_id=owner.id,
        course_id=course.id,
    )
    session.add(task)
    session.flush()
    build = CourseDraftBuildTask(
        course_id=course.id,
        corpus_snapshot_id=f"snapshot-{uuid4().hex}",
        task_id=task.task_id,
        owner_user_id=owner.id,
        status=CourseDraftBuildStatus.QUEUED,
    )
    session.add(build)
    session.commit()

    course_corpus_service.invalidate_queued_builds(
        session, course_id=course.id, reason="materials changed",
    )

    session.refresh(build)
    session.refresh(task)
    assert build.status == CourseDraftBuildStatus.CANCELLED
    assert task.status == "interrupted"
