"""P2 regression coverage for course-level material aggregation."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Session, select

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
from app.models.course_outline_model import CourseOutlineNode, CourseOutlineVersion, CoursePptMapping, OutlineNodeType
from app.models.document_parse_model import DocumentBlock, DocumentIRVersion, DocumentParseRun, ParseRunStatus
from app.models.task_model import TaskRecord
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.course_corpus_service import course_corpus_service
from app.services.document_draft_builders import build_draft_assets
from app.services.course_initial_prep_service import initial_course_prep_service
from app.schemas.controlled_prep import (
    EvidenceFinding,
    EvidenceSegment,
    EvidenceSegmenterResult,
    EvidenceVerifierResult,
    OutlineCandidate,
    OutlinePlannerResult,
    TeachingScriptNodeDraft,
    TeachingStyleConfig,
)
from app.services.task_service import task_service
from app.platform.tasks.handlers import course_draft_build_handler
from app.platform.tasks.worker import TaskHandlerContext
from app.platform.tasks.course_draft_build_queue import recover_course_draft_build_queue


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
    task = session.exec(select(TaskRecord).where(TaskRecord.task_id == first_task_id)).one()
    assert json.loads(task.input_payload)["build_task_id"] == first_build.build_task_id


def test_legacy_course_build_retry_payload_is_repaired(session):
    owner, course = _course_owner(session)
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="primary_courseware")
    corpus = course_corpus_service.create_ready_snapshot(
        session, course_id=course.id, owner_user_id=owner.id,
    )
    build, task_id = course_corpus_service.create_build_task(
        session, corpus=corpus, owner_user_id=owner.id, quiet_window_seconds=0,
    )

    task = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).one()
    task.input_payload = json.dumps({
        "course_id": course.id,
        "corpus_snapshot_id": corpus.corpus_snapshot_id,
    })
    task.status = "failed"
    task.error_code = "VALIDATION_FAILED"
    task.error_message = "course_draft_build 缺少课程或语料快照"
    task.retryable = False
    session.add(task)
    session.commit()

    assert course_corpus_service.repair_legacy_build_task_retry(
        session, task_id=task_id, owner_user_id=owner.id,
    ) is True
    session.refresh(task)
    assert json.loads(task.input_payload)["build_task_id"] == build.build_task_id
    assert task.retryable is True

    retried = task_service.retry(session, task_id, operator_user_id=owner.id)
    assert retried.status == "pending"


def test_teacher_restart_can_request_initial_mode_after_an_unreviewed_draft(session):
    owner, course = _course_owner(session)
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="primary_courseware")
    corpus = course_corpus_service.create_ready_snapshot(
        session, course_id=course.id, owner_user_id=owner.id,
    )
    first, _ = course_corpus_service.create_build_task(
        session, corpus=corpus, owner_user_id=owner.id, quiet_window_seconds=0,
    )
    first.status = CourseDraftBuildStatus.CANCELLED
    session.add(first)
    session.add(CourseOutlineVersion(
        course_id=course.id,
        version=1,
        generation_source="agent_initial_generation",
        review_status="pending",
    ))
    session.commit()

    restart, _ = course_corpus_service.create_build_task(
        session,
        corpus=corpus,
        owner_user_id=owner.id,
        trigger="teacher_restart_unreviewed_initial",
        quiet_window_seconds=0,
        force_initial=True,
    )
    assert restart.generation_mode == "initial"
    assert restart.trigger == "teacher_restart_unreviewed_initial"


def test_restart_recovers_interrupted_current_course_build(session):
    owner, course = _course_owner(session)
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="primary_courseware")
    corpus = course_corpus_service.create_ready_snapshot(
        session, course_id=course.id, owner_user_id=owner.id,
    )
    build, task_id = course_corpus_service.create_build_task(
        session, corpus=corpus, owner_user_id=owner.id, quiet_window_seconds=0,
    )
    task_service.mark_interrupted(session, task_id, reason="test restart")

    submitted: list[tuple[str, dict]] = []

    class CapturingWorker:
        def submit(self, _session_factory, submitted_task_id, payload):
            submitted.append((submitted_task_id, payload))

    test_engine = session.get_bind()
    recovered = asyncio.run(recover_course_draft_build_queue(
        lambda: Session(test_engine), CapturingWorker(),
    ))

    session.expire_all()
    task = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).one()
    session.refresh(build)
    assert recovered == 1
    assert task.status == "pending"
    assert build.status == CourseDraftBuildStatus.QUEUED
    assert submitted == [(task_id, json.loads(task.input_payload))]


def test_course_draft_build_handler_executes_with_persisted_payload(session, monkeypatch):
    owner, course = _course_owner(session)
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="primary_courseware")
    corpus = course_corpus_service.create_ready_snapshot(
        session, course_id=course.id, owner_user_id=owner.id,
    )
    item = session.exec(select(CourseCorpusItem).where(
        CourseCorpusItem.corpus_snapshot_id == corpus.corpus_snapshot_id,
    )).one()
    session.add(DocumentBlock(
        course_id=course.id,
        run_id=item.parse_run_id,
        text="Handler regression concept",
        page_number=1,
        page_or_slide=1,
        semantic_role="knowledge_title",
        material_version_id=item.material_version_id,
    ))
    build, task_id = course_corpus_service.create_build_task(
        session, corpus=corpus, owner_user_id=owner.id, quiet_window_seconds=0,
    )
    session.commit()
    task = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).one()
    payload = json.loads(task.input_payload)
    test_engine = session.get_bind()

    async def fake_initial_build(_session, **_kwargs):
        from app.services.document_draft_builders import DraftAssetResult
        return DraftAssetResult(course_id=course.id, run_id="fake", material_version_id=None)

    monkeypatch.setattr(initial_course_prep_service, "build", fake_initial_build)

    asyncio.run(course_draft_build_handler(TaskHandlerContext(
        task_id=task_id,
        input_payload=payload,
        session_factory=lambda: Session(test_engine),
        service=task_service,
    )))

    session.expire_all()
    final = task_service.get_task(session, task_id, owner_user_id=owner.id)
    session.refresh(build)
    assert final.status == "succeeded"
    assert build.status == CourseDraftBuildStatus.SUCCEEDED


def test_initial_agent_draft_uses_teaching_tree_and_primary_ppt_evidence_only(session):
    owner, course = _course_owner(session)
    primary, _ = _parsed_material(session, course_id=course.id, owner_id=owner.id, role="primary_courseware")
    primary.material_type = "slide"
    session.add(primary)
    _parsed_material(session, course_id=course.id, owner_id=owner.id, role="textbook")
    corpus = course_corpus_service.create_ready_snapshot(session, course_id=course.id, owner_user_id=owner.id)
    assert corpus is not None
    items = {item.material_role: item for item in session.exec(select(CourseCorpusItem).where(
        CourseCorpusItem.corpus_snapshot_id == corpus.corpus_snapshot_id,
    )).all()}
    primary_block = DocumentBlock(
        course_id=course.id, run_id=items["primary_courseware"].parse_run_id,
        material_version_id=items["primary_courseware"].material_version_id,
        text="四冲程发动机的工作过程", semantic_role="knowledge_title",
        page_number=3, page_or_slide=3,
    )
    textbook_block = DocumentBlock(
        course_id=course.id, run_id=items["textbook"].parse_run_id,
        material_version_id=items["textbook"].material_version_id,
        text="进气、压缩、做功和排气构成一个完整循环。", semantic_role="explanation",
        page_number=99, page_or_slide=99,
    )
    caption_block = DocumentBlock(
        course_id=course.id, run_id=items["primary_courseware"].parse_run_id,
        material_version_id=items["primary_courseware"].material_version_id,
        text="图 2-1 发动机结构示意图", semantic_role="explanation",
        page_number=4, page_or_slide=4,
    )
    session.add(primary_block); session.add(textbook_block); session.add(caption_block); session.commit()

    class FakeWorkflow:
        async def run(self, request):
            ids = {item.text: item.evidence_id for item in request.evidence}
            primary_id = ids["四冲程发动机的工作过程"]
            textbook_id = ids["进气、压缩、做功和排气构成一个完整循环。"]
            outline = OutlinePlannerResult(
                stage="outline_planner",
                candidates=[
                    OutlineCandidate(candidate_id="chapter", node_type="chapter", title="发动机基础", evidence_ids=[primary_id]),
                    OutlineCandidate(candidate_id="section", node_type="section", title="四冲程发动机", parent_candidate_id="chapter", evidence_ids=[primary_id]),
                    OutlineCandidate(candidate_id="kp", node_type="knowledge_point", title="四冲程工作原理", parent_candidate_id="section", evidence_ids=[primary_id, textbook_id]),
                ],
                prerequisites=[],
            )
            script = TeachingScriptNodeDraft(
                stage="script_writer", candidate_id="kp", title="四冲程工作原理",
                evidence_ids=[primary_id, textbook_id], course_positioning="发动机课程",
                prerequisites=[], style=TeachingStyleConfig(level="beginner"),
                content="四冲程发动机依次经历进气、压缩、做功和排气。",
                claims=["四冲程包含进气、压缩、做功和排气"],
                paragraph_evidence=[[primary_id, textbook_id]],
            )
            verification = EvidenceVerifierResult(
                stage="evidence_verifier", verdict="passed",
                findings=[EvidenceFinding(claim=script.claims[0], evidence_ids=script.evidence_ids, supported=True)],
            )
            return {
                "segments": EvidenceSegmenterResult(stage="evidence_segmenter", segments=[EvidenceSegment(segment_id="seg", title="四冲程", topic="发动机工作", evidence_ids=[primary_id])]),
                "outline": outline,
                "scripts": [script],
                "verifications": [verification],
            }

    result = asyncio.run(initial_course_prep_service.build(
        session,
        course_id=course.id,
        corpus_snapshot_id=corpus.corpus_snapshot_id,
        created_by=owner.id,
        workflow=FakeWorkflow(),
    ))
    nodes = session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == result.outline_version_id,
    )).all()
    assert [(node.node_type, node.title) for node in nodes] == [
        (OutlineNodeType.CHAPTER, "发动机基础"),
        (OutlineNodeType.SECTION, "四冲程发动机"),
        (OutlineNodeType.KNOWLEDGE_POINT, "四冲程工作原理"),
    ]
    mapping = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course.id,
    )).one()
    assert mapping.page_refs == [3]
    assert caption_block.block_id not in mapping.source_block_refs
    assert result.script_node_count == 1


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
