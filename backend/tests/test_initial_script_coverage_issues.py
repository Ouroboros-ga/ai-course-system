"""Regression coverage for partial initial lecture-script persistence."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel import select

from app.core.security import get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseScriptCoverageIssue,
    OutlineNodeType,
    TeachingScriptNode,
)
from app.models.user_model import User, UserRole
from app.schemas.controlled_prep import (
    EvidenceFinding,
    EvidenceVerifierResult,
    OutlineCandidate,
    OutlinePlannerResult,
    TeachingScriptNodeDraft,
    TeachingStyleConfig,
)
from app.services.course_initial_prep_service import InitialCoursePrepService
from app.services.document_draft_builders import DraftAssetResult


def _course_and_owner(session) -> tuple[Course, User]:
    token = uuid4().hex[:10]
    owner = User(
        username=f"script_coverage_{token}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(owner)
    session.flush()
    course = Course(
        fanya_course_id=f"script-coverage-{token}",
        fanya_course_name="Script coverage",
        title="Script coverage",
        teacher_id=owner.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.flush()
    return course, owner


def _prepared_batch(session, *, course: Course, count: int, omitted: set[str], failed: set[str]):
    chapter = OutlineCandidate(
        candidate_id="chapter",
        node_type="chapter",
        title="Chapter",
        evidence_ids=["block-1"],
    )
    section = OutlineCandidate(
        candidate_id="section",
        node_type="section",
        title="Section",
        parent_candidate_id=chapter.candidate_id,
        evidence_ids=["block-1"],
    )
    candidates = [chapter, section]
    nodes: dict[str, CourseOutlineNode] = {}
    for index in range(1, count + 1):
        candidate_id = f"kp-{index:02d}"
        candidates.append(OutlineCandidate(
            candidate_id=candidate_id,
            node_type="knowledge_point",
            title=f"Knowledge point {index}",
            parent_candidate_id=section.candidate_id,
            evidence_ids=["block-1"],
        ))
        node = CourseOutlineNode(
            course_id=course.id,
            outline_version_id=f"ov_{uuid4().hex}",
            node_type=OutlineNodeType.KNOWLEDGE_POINT,
            title=f"Knowledge point {index}",
            order_index=index,
            source_block_refs=["block-1"],
        )
        session.add(node)
        session.flush()
        nodes[candidate_id] = node

    scripts: list[TeachingScriptNodeDraft] = []
    verifications: list[EvidenceVerifierResult] = []
    for candidate in candidates[2:]:
        if candidate.candidate_id in omitted:
            continue
        content = f"Verified lecture script for {candidate.candidate_id}."
        scripts.append(TeachingScriptNodeDraft(
            candidate_id=candidate.candidate_id,
            title=candidate.title,
            evidence_ids=["block-1"],
            course_positioning="Coverage test",
            style=TeachingStyleConfig(level="beginner"),
            content=content,
            claims=[f"Claim for {candidate.candidate_id}"],
            paragraph_evidence=[["block-1"]],
        ))
        is_failed = candidate.candidate_id in failed
        verifications.append(EvidenceVerifierResult(
            verdict="failed" if is_failed else "passed",
            findings=[EvidenceFinding(
                claim=f"Claim for {candidate.candidate_id}",
                evidence_ids=["block-1"],
                supported=not is_failed,
                reason="verification failure" if is_failed else "",
            )],
        ))
    return {
        "outline": OutlinePlannerResult(candidates=candidates),
        "scripts": scripts,
        "verifications": verifications,
    }, nodes


@pytest.mark.parametrize(
    ("count", "omitted", "failed", "expected_saved", "expected_codes"),
    [
        (
            3,
            set(),
            set(),
            3,
            {},
        ),
        (
            16,
            set(),
            {"kp-07", "kp-12"},
            14,
            {"kp-07": "EVIDENCE_VERIFICATION_FAILED", "kp-12": "EVIDENCE_VERIFICATION_FAILED"},
        ),
        (
            3,
            {"kp-03"},
            set(),
            2,
            {"kp-03": "SCRIPT_OUTPUT_MISSING"},
        ),
        (
            3,
            set(),
            {"kp-01", "kp-02", "kp-03"},
            0,
            {
                "kp-01": "EVIDENCE_VERIFICATION_FAILED",
                "kp-02": "EVIDENCE_VERIFICATION_FAILED",
                "kp-03": "EVIDENCE_VERIFICATION_FAILED",
            },
        ),
    ],
)
def test_initial_script_coverage_is_accounted_for_without_saving_rejected_content(
    session,
    count,
    omitted,
    failed,
    expected_saved,
    expected_codes,
):
    course, owner = _course_and_owner(session)
    prepared, candidate_to_node = _prepared_batch(
        session,
        course=course,
        count=count,
        omitted=omitted,
        failed=failed,
    )
    result = DraftAssetResult(course_id=course.id, run_id="coverage-test", material_version_id=None)

    InitialCoursePrepService._persist_scripts(
        session,
        course_id=course.id,
        corpus_snapshot_id=f"ccs_{uuid4().hex}",
        build_task_id=f"cdbt_{uuid4().hex}",
        created_by=owner.id,
        outline_version_id=f"ov_{uuid4().hex}",
        prepared=prepared,
        candidate_to_node=candidate_to_node,
        valid_block_ids={"block-1"},
        result=result,
    )
    session.commit()

    saved = list(session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.course_id == course.id,
    )).all())
    issues = list(session.exec(select(CourseScriptCoverageIssue).where(
        CourseScriptCoverageIssue.course_id == course.id,
    )).all())
    by_outline_id = {node.outline_node_id: candidate_id for candidate_id, node in candidate_to_node.items()}

    assert len(saved) == expected_saved
    assert result.script_node_count == expected_saved
    assert len(issues) == len(expected_codes)
    assert {
        by_outline_id[issue.outline_node_id]: issue.issue_code
        for issue in issues
    } == expected_codes
    assert all(set(issue.model_dump()) <= {
        "id", "issue_id", "course_id", "build_task_id", "script_version_id",
        "outline_node_id", "issue_code", "status", "resolved_by", "created_at", "resolved_at",
    } for issue in issues)
    assert all("content" not in issue.model_dump() for issue in issues)
    assert all(set(issue) == {"outline_node_id", "code"} for issue in result.script_coverage_issues)
