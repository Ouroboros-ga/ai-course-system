"""阶段4 课程材料解析、Evidence、Citation 与图谱治理 端到端测试。

覆盖路线图 §7 验收与 PageDesign前端API契约规划.md §3.6：
- 解析流水线：创建/查询/列表/重解析，stale_strategy 处理旧证据
- 候选证据审核：教师确认升级为正式证据 + 学生可读 Citation；拒绝、重复确认状态机
- 学生可读 Citation：跨课程隔离、stale/orphaned 语义、学生视图隐藏内部字段
- 图谱候选批次：列表、与课程隔离
- facade 知识空间首屏与课程健康度：降级语义（pending 而非 503）

四类必备测试：成功、权限拒绝、跨课程拒绝、降级。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseCapability
from app.models.course_build_model import (
    CourseRelease,
    ReleaseStatus,
    SourceMaterial,
    SourceMaterialVersion,
)
from app.models.course_model import Course, CourseStatus
from app.models.document_parse_model import (
    CitationStatus,
    DocumentParseRun,
    EvidenceCitation,
    EvidenceSpan,
    EvidenceSpanStatus,
    GraphCandidateBatch,
    GraphReleaseLink,
    ParsePipeline,
    ParseRunStatus,
    StaleStrategy,
)
from app.models.task_model import TaskRecord
from app.models.graph_production_model import (
    CourseEvidenceRecord,
    EvidenceStatus,
    GraphSnapshotRecord,
    SnapshotStatus,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from app.services.document_parse_service import (
    document_parse_service,
    graph_candidate_service,
    graph_release_link_service,
)
from app.services.course_build_service import (
    course_release_service,
    source_material_service,
)


GRAPH = "/api/v1/graph"
FACADE = "/api/v1/facade"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name: str, role: UserRole = UserRole.TEACHER) -> User:
    u = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _course(
    session,
    teacher_id: int,
    *,
    title: str = "Stage4 Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"s4-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=status,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    session.commit()
    return c


def _enable_capabilities(session, course_id: int, **overrides) -> None:
    """激活课程能力开关；默认全开便于阶段4测试。"""
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    defaults = {
        "learning": True,
        "course_building": True,
        "knowledge_graph": True,
        "evidence": True,
        "experiment": False,
        "coding_sandbox": False,
        "cognitive_analysis": True,
        "safety_policy": False,
    }
    defaults.update(overrides)
    if cap is None:
        cap = CourseCapability(course_id=course_id, **defaults)
    else:
        for k, v in defaults.items():
            setattr(cap, k, v)
    session.add(cap)
    session.commit()


def _enroll_student(session, course_id: int, student_id: int) -> None:
    """建立学生选课关系 + CourseMembership（Course Access v1 是唯一授权来源）。"""
    from app.models.course_model import StudentEnrollment

    enr = StudentEnrollment(
        student_id=student_id,
        course_id=course_id,
        overall_progress=0.0,
        last_study_time=datetime.utcnow(),
        is_active=True,
    )
    session.add(enr)
    activate_student_membership(session, course_id, student_id)
    session.commit()


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_material(session, course_id: int, teacher_id: int) -> SourceMaterial:
    """直接通过服务创建材料 + 首版本，返回 SourceMaterial。"""
    material, version = source_material_service.create_material(
        session,
        course_id=course_id,
        name="测试课件.pdf",
        material_type="document",
        file_path="uploads/test.pdf",
        file_hash="hash-" + datetime.utcnow().isoformat(),
        file_size=1024,
        mime_type="application/pdf",
        created_by=teacher_id,
    )
    session.commit()
    return material


def _create_succeeded_run(
    session,
    *,
    course_id: int,
    material_id: str,
    material_version_id: str,
    initiated_by: int,
    pipeline: ParsePipeline = ParsePipeline.FULL,
) -> DocumentParseRun:
    """直接通过服务创建一个已成功的解析运行。"""
    run = document_parse_service.create_run(
        session,
        course_id=course_id,
        material_id=material_id,
        material_version_id=material_version_id,
        pipeline=pipeline,
        initiated_by=initiated_by,
    )
    session.commit()
    document_parse_service.mark_running(
        session, run_id=run.run_id, course_id=course_id,
    )
    document_parse_service.mark_succeeded(
        session,
        run_id=run.run_id,
        course_id=course_id,
        block_count=3,
        evidence_span_count=2,
        graph_candidate_count=1,
    )
    session.commit()
    session.refresh(run)
    return run


def _create_candidate_span(
    session,
    *,
    course_id: int,
    run_id: str,
    block_id: str,
    text_snippet: str = "二分查找要求序列有序。",
    page_number: int = 1,
    node_id: int | None = None,
) -> EvidenceSpan:
    """写入一条候选证据片段。"""
    span = document_parse_service.add_evidence_span(
        session,
        course_id=course_id,
        run_id=run_id,
        block_id=block_id,
        document_id=None,
        page_number=page_number,
        text_snippet=text_snippet,
        char_start=0,
        char_end=len(text_snippet),
        linked_node_ids=[node_id] if node_id else [],
    )
    session.commit()
    session.refresh(span)
    return span


def _create_block(session, *, course_id: int, run_id: str, page: int = 1, text: str = "块文本"):
    block = document_parse_service.add_block(
        session,
        course_id=course_id,
        run_id=run_id,
        document_id=None,
        page_number=page,
        block_type="text",
        text=text,
    )
    session.commit()
    session.refresh(block)
    return block


# ---------------------------------------------------------------------------
# 1. 成功路径：解析任务创建、查询、列表、重解析
# ---------------------------------------------------------------------------


def test_create_ingestion_returns_202(client, session):
    """教师创建解析任务，返回 202 + run_id + status=pending。"""
    teacher = _user(session, "s4_ingest_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)

    resp = client.post(
        f"{GRAPH}/course/{course.id}/ingestions",
        json={
            "material_id": material.material_id,
            "pipeline": "full",
            "stale_strategy": "mark_stale",
        },
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 202
    data = body["data"]
    assert "run_id" in data and data["run_id"].startswith("dpr_")
    assert data["status"] == "pending"
    assert data["stale_strategy"] == "mark_stale"
    task = session.exec(select(TaskRecord).where(TaskRecord.task_id == data["task_id"])).one()
    import json
    assert json.loads(task.input_payload)["run_id"] == data["run_id"]


def test_create_ingestion_rejects_version_from_another_material(client, session):
    """A material version is not interchangeable merely because its course matches."""
    teacher = _user(session, "s4_version_material_isolation")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    first = _create_material(session, course.id, teacher.id)
    second = _create_material(session, course.id, teacher.id)

    response = client.post(
        f"{GRAPH}/course/{course.id}/ingestions",
        json={
            "material_id": first.material_id,
            "material_version_id": second.current_version_id,
            "pipeline": "full",
            "stale_strategy": "mark_stale",
        },
        headers=_auth(_token(teacher)),
    )

    assert response.status_code == 404


def test_get_ingestion_returns_run_detail(client, session):
    """教师查询解析运行详情。"""
    teacher = _user(session, "s4_get_run_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)
    run = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )

    resp = client.get(
        f"{GRAPH}/course/{course.id}/ingestions/{run.run_id}",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["run_id"] == run.run_id
    assert data["course_id"] == course.id
    assert data["status"] == "succeeded"
    assert data["block_count"] == 3
    assert data["evidence_span_count"] == 2
    assert data["graph_candidate_count"] == 1


def test_list_ingestions_filters_by_material(client, session):
    """列出解析运行，按 material_id 过滤。"""
    teacher = _user(session, "s4_list_run_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    m1 = _create_material(session, course.id, teacher.id)
    m2 = _create_material(session, course.id, teacher.id)
    _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=m1.material_id,
        material_version_id=m1.current_version_id,
        initiated_by=teacher.id,
    )
    _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=m2.material_id,
        material_version_id=m2.current_version_id,
        initiated_by=teacher.id,
    )

    resp = client.get(
        f"{GRAPH}/course/{course.id}/ingestions?material_id={m1.material_id}",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["material_id"] == m1.material_id


def test_reparse_preserves_old_evidence_until_explicit_apply(client, session):
    """重解析时旧证据按 mark_stale 策略标记。"""
    teacher = _user(session, "s4_reparse_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)
    run1 = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    # 添加候选证据并确认升级为正式证据 + Citation
    block = _create_block(session, course_id=course.id, run_id=run1.run_id)
    span = _create_candidate_span(
        session, course_id=course.id, run_id=run1.run_id, block_id=block.block_id,
    )
    document_parse_service.confirm_evidence_span(
        session,
        course_id=course.id,
        span_id=span.span_id,
        confirmed_by=teacher.id,
        source_file="test.pdf",
        source_type="document",
        node_id=42,
    )
    session.commit()

    # 触发重解析
    resp = client.post(
        f"{GRAPH}/course/{course.id}/reparse",
        json={
            "material_id": material.material_id,
            "stale_strategy": "mark_stale",
        },
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 202
    data = body["data"]
    assert data["status"] == "pending"
    assert data["stale_strategy"] == "mark_stale"
    assert data["affected_evidence_count"] == 0
    assert data["prev_run_id"] == run1.run_id

    session.refresh(span)
    assert span.status == EvidenceSpanStatus.CONFIRMED
    document_parse_service.mark_running(session, run_id=data["run_id"], course_id=course.id)
    document_parse_service.mark_succeeded(session, run_id=data["run_id"], course_id=course.id)
    document_parse_service.apply_reparse(session, course_id=course.id, run_id=data["run_id"])
    session.commit()
    session.refresh(span)
    assert span.status == EvidenceSpanStatus.STALE
    assert span.stale_reason == "courseware_reparse"


def test_reparse_orphan_strategy_waits_for_explicit_apply(client, session):
    """重解析使用 orphan 策略时，旧证据标记 orphaned。"""
    teacher = _user(session, "s4_orphan_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)
    run1 = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    block = _create_block(session, course_id=course.id, run_id=run1.run_id)
    span = _create_candidate_span(
        session, course_id=course.id, run_id=run1.run_id, block_id=block.block_id,
    )
    document_parse_service.confirm_evidence_span(
        session,
        course_id=course.id,
        span_id=span.span_id,
        confirmed_by=teacher.id,
    )
    session.commit()

    resp = client.post(
        f"{GRAPH}/course/{course.id}/reparse",
        json={
            "material_id": material.material_id,
            "stale_strategy": "orphan",
        },
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200

    session.refresh(span)
    assert span.status == EvidenceSpanStatus.CONFIRMED
    replacement_id = resp.json()["data"]["run_id"]
    document_parse_service.mark_running(session, run_id=replacement_id, course_id=course.id)
    document_parse_service.mark_succeeded(session, run_id=replacement_id, course_id=course.id)
    document_parse_service.apply_reparse(session, course_id=course.id, run_id=replacement_id)
    session.commit()
    session.refresh(span)
    assert span.status == EvidenceSpanStatus.ORPHANED
    assert span.stale_reason == "courseware_orphaned"


# ---------------------------------------------------------------------------
# 2. 候选证据审核：确认、拒绝、状态机
# ---------------------------------------------------------------------------


def test_confirm_evidence_span_creates_formal_evidence_and_citation(client, session):
    """教师确认候选证据：升级为正式 CourseEvidenceRecord + 学生可读 EvidenceCitation。"""
    teacher = _user(session, "s4_confirm_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)
    run = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    block = _create_block(session, course_id=course.id, run_id=run.run_id)
    span = _create_candidate_span(
        session, course_id=course.id, run_id=run.run_id, block_id=block.block_id,
    )

    resp = client.post(
        f"{GRAPH}/course/{course.id}/evidence-spans/{span.span_id}/confirm",
        json={
            "source_file": "lecture.pdf",
            "source_type": "ppt",
            "node_id": 7,
        },
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["span"]["status"] == "confirmed"
    assert data["span"]["confirmed_by"] == teacher.id
    assert data["evidence"]["status"] == "active"
    assert data["evidence"]["evidence_id"].startswith("ev_")
    assert data["citation"]["status"] == "exact"
    assert data["citation"]["student_visible"] is True
    assert data["citation"]["source_file"] == "lecture.pdf"


def test_confirm_evidence_span_idempotent_rejects(client, session):
    """已 confirmed 的证据片段不可重复确认，返回 409 STATE_CONFLICT。"""
    teacher = _user(session, "s4_repeat_confirm_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)
    run = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    block = _create_block(session, course_id=course.id, run_id=run.run_id)
    span = _create_candidate_span(
        session, course_id=course.id, run_id=run.run_id, block_id=block.block_id,
    )
    document_parse_service.confirm_evidence_span(
        session, course_id=course.id, span_id=span.span_id, confirmed_by=teacher.id,
    )
    session.commit()

    resp = client.post(
        f"{GRAPH}/course/{course.id}/evidence-spans/{span.span_id}/confirm",
        json={},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 409
    err = resp.json()["data"]
    assert err["error_code"] == "STATE_CONFLICT"


def test_reject_evidence_span_changes_status(client, session):
    """教师拒绝候选证据后状态变为 rejected，且不可再确认。"""
    teacher = _user(session, "s4_reject_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)
    run = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    block = _create_block(session, course_id=course.id, run_id=run.run_id)
    span = _create_candidate_span(
        session, course_id=course.id, run_id=run.run_id, block_id=block.block_id,
    )

    resp = client.post(
        f"{GRAPH}/course/{course.id}/evidence-spans/{span.span_id}/reject",
        json={"reject_reason": "OCR 误抽"},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "rejected"
    assert resp.json()["data"]["reject_reason"] == "OCR 误抽"

    # rejected 不可再确认
    resp2 = client.post(
        f"{GRAPH}/course/{course.id}/evidence-spans/{span.span_id}/confirm",
        json={},
        headers=_auth(_token(teacher)),
    )
    assert resp2.status_code == 409


def test_list_evidence_spans_filters_by_status(client, session):
    """列出候选证据片段，按 status 过滤。"""
    teacher = _user(session, "s4_list_span_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)
    run = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    block = _create_block(session, course_id=course.id, run_id=run.run_id)
    _create_candidate_span(
        session, course_id=course.id, run_id=run.run_id, block_id=block.block_id,
        text_snippet="候选 A",
    )
    span2 = _create_candidate_span(
        session, course_id=course.id, run_id=run.run_id, block_id=block.block_id,
        text_snippet="候选 B",
    )
    document_parse_service.confirm_evidence_span(
        session, course_id=course.id, span_id=span2.span_id, confirmed_by=teacher.id,
    )
    session.commit()

    # 仅看 candidate
    resp = client.get(
        f"{GRAPH}/course/{course.id}/evidence-spans?status=candidate",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["status"] == "candidate"

    # 仅看 confirmed
    resp2 = client.get(
        f"{GRAPH}/course/{course.id}/evidence-spans?status=confirmed",
        headers=_auth(_token(teacher)),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["total"] == 1
    assert resp2.json()["data"]["items"][0]["status"] == "confirmed"


# ---------------------------------------------------------------------------
# 3. 学生可读 Citation：跨课程隔离、stale 语义、学生视图隐藏内部字段
# ---------------------------------------------------------------------------


def test_student_citations_hide_internal_fields(client, session):
    """学生查询 citations 时不暴露 evidence_id 与 span_id 内部字段。"""
    teacher = _user(session, "s4_cit_internal_teacher")
    student = _user(session, "s4_cit_internal_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    material = _create_material(session, course.id, teacher.id)
    run = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    block = _create_block(session, course_id=course.id, run_id=run.run_id)
    span = _create_candidate_span(
        session, course_id=course.id, run_id=run.run_id, block_id=block.block_id,
    )
    document_parse_service.confirm_evidence_span(
        session, course_id=course.id, span_id=span.span_id, confirmed_by=teacher.id,
    )
    session.commit()

    resp = client.get(
        f"{GRAPH}/course/{course.id}/citations",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 1
    cit = data["items"][0]
    # 学生视图不暴露 evidence_id / span_id
    assert "evidence_id" not in cit
    assert "span_id" not in cit
    assert cit["student_visible"] is True


def test_student_citations_exclude_stale_by_default(client, session):
    """学生默认仅看 exact/approximate；stale/orphaned 不可见。"""
    teacher = _user(session, "s4_cit_stale_teacher")
    student = _user(session, "s4_cit_stale_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    material = _create_material(session, course.id, teacher.id)
    run = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    block = _create_block(session, course_id=course.id, run_id=run.run_id)
    span = _create_candidate_span(
        session, course_id=course.id, run_id=run.run_id, block_id=block.block_id,
    )
    document_parse_service.confirm_evidence_span(
        session, course_id=course.id, span_id=span.span_id, confirmed_by=teacher.id,
    )
    session.commit()

    # A replacement must be explicitly adopted before its stale policy runs.
    replacement = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    document_parse_service.apply_reparse(
        session, course_id=course.id, run_id=replacement.run_id,
    )
    session.commit()

    # 学生只看 exact/approximate -> 此时无可见 citation
    resp = client.get(
        f"{GRAPH}/course/{course.id}/citations",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 0
    assert data["include_stale"] is False

    # 教师可看 stale
    resp_t = client.get(
        f"{GRAPH}/course/{course.id}/citations?include_stale=true",
        headers=_auth(_token(teacher)),
    )
    assert resp_t.status_code == 200
    data_t = resp_t.json()["data"]
    assert data_t["total"] == 1
    assert data_t["items"][0]["status"] == "source_updated"


def test_citations_isolated_across_courses(client, session):
    """课程 A 的 citation 不会出现在课程 B。"""
    teacher_a = _user(session, "s4_iso_teacher_a")
    teacher_b = _user(session, "s4_iso_teacher_b")
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")
    _enable_capabilities(session, course_a.id)
    _enable_capabilities(session, course_b.id)
    material_a = _create_material(session, course_a.id, teacher_a.id)
    run_a = _create_succeeded_run(
        session,
        course_id=course_a.id,
        material_id=material_a.material_id,
        material_version_id=material_a.current_version_id,
        initiated_by=teacher_a.id,
    )
    block_a = _create_block(session, course_id=course_a.id, run_id=run_a.run_id)
    span_a = _create_candidate_span(
        session, course_id=course_a.id, run_id=run_a.run_id, block_id=block_a.block_id,
    )
    document_parse_service.confirm_evidence_span(
        session, course_id=course_a.id, span_id=span_a.span_id, confirmed_by=teacher_a.id,
    )
    session.commit()

    # 教师 B 在课程 B 中看不到课程 A 的 citation
    resp = client.get(
        f"{GRAPH}/course/{course_b.id}/citations",
        headers=_auth(_token(teacher_b)),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


# ---------------------------------------------------------------------------
# 4. 图谱候选批次
# ---------------------------------------------------------------------------


def test_list_candidate_batches_isolated_by_course(client, session):
    """图谱候选批次按课程隔离。"""
    teacher_a = _user(session, "s4_batch_teacher_a")
    teacher_b = _user(session, "s4_batch_teacher_b")
    course_a = _course(session, teacher_a.id, title="批次课程 A")
    course_b = _course(session, teacher_b.id, title="批次课程 B")
    _enable_capabilities(session, course_a.id)
    _enable_capabilities(session, course_b.id)
    graph_candidate_service.create_batch(
        session, course_id=course_a.id, initiated_by=teacher_a.id,
    )
    graph_candidate_service.create_batch(
        session, course_id=course_b.id, initiated_by=teacher_b.id,
    )
    session.commit()

    resp_a = client.get(
        f"{GRAPH}/course/{course_a.id}/candidate-batches",
        headers=_auth(_token(teacher_a)),
    )
    assert resp_a.status_code == 200
    data_a = resp_a.json()["data"]
    assert data_a["total"] == 1
    assert data_a["items"][0]["course_id"] == course_a.id

    resp_b = client.get(
        f"{GRAPH}/course/{course_b.id}/candidate-batches",
        headers=_auth(_token(teacher_b)),
    )
    assert resp_b.status_code == 200
    data_b = resp_b.json()["data"]
    assert data_b["total"] == 1
    assert data_b["items"][0]["course_id"] == course_b.id


def test_candidate_batch_exposes_reviewable_payload(client, session):
    teacher = _user(session, "s4_payload_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    batch = graph_candidate_service.create_batch(
        session, course_id=course.id, initiated_by=teacher.id,
    )
    graph_candidate_service.mark_succeeded(
        session, course_id=course.id, batch_id=batch.batch_id,
        node_candidate_count=2, relation_candidate_count=1,
        node_candidates=[{
            "candidate_id": "node-a", "label": "制冷循环", "kind": "concept",
            "status": "proposed", "confidence": 0.9,
            "source_block_ids": ["block-a"], "anchor_ids": ["anchor-a"],
        }],
        relation_candidates=[{
            "candidate_id": "rel-a", "source_candidate_id": "node-a",
            "target_candidate_id": "node-b", "relation_type": "next_topic",
            "status": "proposed", "confidence": 0.8, "anchor_ids": ["anchor-a"],
        }],
    )
    session.commit()

    response = client.get(
        f"{GRAPH}/course/{course.id}/candidate-batches",
        headers=_auth(_token(teacher)),
    )
    item = response.json()["data"]["items"][0]
    assert item["node_candidates"][0]["label"] == "制冷循环"
    assert item["relation_candidates"][0]["relation_type"] == "next_topic"


def test_new_candidate_batch_supersedes_previous(client, session):
    """新批次产生时旧批次标记为 superseded。"""
    teacher = _user(session, "s4_supersede_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    batch1 = graph_candidate_service.create_batch(
        session, course_id=course.id, initiated_by=teacher.id,
    )
    session.commit()
    graph_candidate_service.mark_succeeded(
        session, course_id=course.id, batch_id=batch1.batch_id,
        node_candidate_count=5, relation_candidate_count=2,
    )
    session.commit()

    # 产生新批次
    batch2 = graph_candidate_service.create_batch(
        session, course_id=course.id, initiated_by=teacher.id,
    )
    session.commit()

    session.refresh(batch1)
    assert batch1.status.value == "superseded"
    assert batch2.prev_batch_id == batch1.batch_id


# ---------------------------------------------------------------------------
# 5. facade：知识空间首屏与课程健康度
# ---------------------------------------------------------------------------


def test_facade_knowledge_view_returns_snapshot_and_citations(client, session):
    """facade /knowledge 返回快照、节点局部图、Citation 与候选治理动作。"""
    teacher = _user(session, "s4_know_teacher")
    student = _user(session, "s4_know_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)

    # 准备已发布快照（关系需挂接本课程有效 Evidence 才能通过校验）
    from app.services.graph_production_service import create_evidence, publish_snapshot

    evidence = create_evidence(
        session,
        course_id=course.id,
        source_file="lecture.pdf",
        page_number=1,
        text_snippet="二分查找要求序列有序。",
    )
    publish_snapshot(
        session,
        course_id=course.id,
        nodes=[
            {"node_id": "n1", "label": "二分查找"},
            {"node_id": "n2", "label": "有序序列"},
        ],
        relations=[
            {
                "relation_id": "r1",
                "source": "n2",
                "target": "n1",
                "type": "prerequisite_of",
                "evidence_ids": [evidence.evidence_id],
            },
        ],
        user_id=teacher.id,
    )
    session.commit()

    resp = client.get(
        f"{FACADE}/course/{course.id}/knowledge?node_id=1",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["course_id"] == course.id
    assert data["snapshot"] is not None
    assert data["can_review"] is False  # 学生不可审核
    assert data["candidate_spans"] == []  # 学生视图不暴露候选片段


def test_facade_knowledge_view_teacher_sees_candidates(client, session):
    """教师视图暴露候选证据片段与图谱候选批次。"""
    teacher = _user(session, "s4_know_teacher_main")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)
    run = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    block = _create_block(session, course_id=course.id, run_id=run.run_id)
    _create_candidate_span(
        session, course_id=course.id, run_id=run.run_id, block_id=block.block_id,
    )
    graph_candidate_service.create_batch(
        session, course_id=course.id, initiated_by=teacher.id,
    )
    session.commit()

    resp = client.get(
        f"{FACADE}/course/{course.id}/knowledge",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["can_review"] is True
    assert len(data["candidate_spans"]) >= 1
    assert len(data["candidate_batches"]) >= 1


def test_facade_health_returns_pending_when_no_data(client, session):
    """facade /health 在无资料/快照时降级为 pending，不返回 503。"""
    teacher = _user(session, "s4_health_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    resp = client.get(
        f"{FACADE}/course/{course.id}/health",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["overall"] == "pending"
    assert data["materials"]["status"] == "pending"
    assert data["graph"]["status"] == "pending"
    assert data["release"]["status"] == "pending"
    assert data["can_view_health_detail"] is True


def test_facade_health_returns_degraded_when_partial(client, session):
    """facade /health 在部分维度就绪时返回 degraded。"""
    teacher = _user(session, "s4_health_partial_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _create_material(session, course.id, teacher.id)

    resp = client.get(
        f"{FACADE}/course/{course.id}/health",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["overall"] == "degraded"
    assert data["materials"]["status"] == "available"
    assert data["graph"]["status"] == "pending"  # 仍无快照


# ---------------------------------------------------------------------------
# 6. 权限拒绝：未登录、学生越权
# ---------------------------------------------------------------------------


def test_create_ingestion_requires_authentication(client, session):
    """未登录创建解析任务返回 401。"""
    teacher = _user(session, "s4_unauth_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)

    resp = client.post(
        f"{GRAPH}/course/{course.id}/ingestions",
        json={"material_id": material.material_id},
    )
    assert resp.status_code == 401


def test_student_cannot_create_ingestion(client, session):
    """学生不能创建解析任务，返回 403。"""
    teacher = _user(session, "s4_student_ingest_teacher")
    student = _user(session, "s4_student_ingest_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    material = _create_material(session, course.id, teacher.id)

    resp = client.post(
        f"{GRAPH}/course/{course.id}/ingestions",
        json={"material_id": material.material_id},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


def test_student_cannot_confirm_evidence_span(client, session):
    """学生不能确认候选证据，返回 403。"""
    teacher = _user(session, "s4_student_confirm_teacher")
    student = _user(session, "s4_student_confirm_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    material = _create_material(session, course.id, teacher.id)
    run = _create_succeeded_run(
        session,
        course_id=course.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher.id,
    )
    block = _create_block(session, course_id=course.id, run_id=run.run_id)
    span = _create_candidate_span(
        session, course_id=course.id, run_id=run.run_id, block_id=block.block_id,
    )

    resp = client.post(
        f"{GRAPH}/course/{course.id}/evidence-spans/{span.span_id}/confirm",
        json={},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


def test_student_cannot_list_candidate_batches(client, session):
    """学生不能查看图谱候选批次（knowledge.review 权限）。"""
    teacher = _user(session, "s4_student_batch_teacher")
    student = _user(session, "s4_student_batch_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    graph_candidate_service.create_batch(
        session, course_id=course.id, initiated_by=teacher.id,
    )
    session.commit()

    resp = client.get(
        f"{GRAPH}/course/{course.id}/candidate-batches",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 7. 跨课程拒绝：教师 B 不可访问课程 A 的解析运行
# ---------------------------------------------------------------------------


def test_get_ingestion_rejects_cross_course(client, session):
    """教师 B 不能查询课程 A 的解析运行（404）。"""
    teacher_a = _user(session, "s4_cross_get_a")
    teacher_b = _user(session, "s4_cross_get_b")
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")
    _enable_capabilities(session, course_a.id)
    _enable_capabilities(session, course_b.id)
    material = _create_material(session, course_a.id, teacher_a.id)
    run = _create_succeeded_run(
        session,
        course_id=course_a.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher_a.id,
    )

    # 教师 B 在课程 B 上下文查询课程 A 的 run_id -> 404
    resp = client.get(
        f"{GRAPH}/course/{course_b.id}/ingestions/{run.run_id}",
        headers=_auth(_token(teacher_b)),
    )
    assert resp.status_code == 404
    assert resp.json()["data"]["error_code"] == "RESOURCE_NOT_FOUND"


def test_confirm_evidence_span_rejects_cross_course(client, session):
    """教师 B 不能确认课程 A 的候选证据（404）。"""
    teacher_a = _user(session, "s4_cross_confirm_a")
    teacher_b = _user(session, "s4_cross_confirm_b")
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")
    _enable_capabilities(session, course_a.id)
    _enable_capabilities(session, course_b.id)
    material = _create_material(session, course_a.id, teacher_a.id)
    run = _create_succeeded_run(
        session,
        course_id=course_a.id,
        material_id=material.material_id,
        material_version_id=material.current_version_id,
        initiated_by=teacher_a.id,
    )
    block = _create_block(session, course_id=course_a.id, run_id=run.run_id)
    span = _create_candidate_span(
        session, course_id=course_a.id, run_id=run.run_id, block_id=block.block_id,
    )

    resp = client.post(
        f"{GRAPH}/course/{course_b.id}/evidence-spans/{span.span_id}/confirm",
        json={},
        headers=_auth(_token(teacher_b)),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 8. 降级与并发保护
# ---------------------------------------------------------------------------


def test_concurrent_ingestion_rejected(client, session):
    """同一 material_version 已有 pending/running 运行时，再次创建返回 409。"""
    teacher = _user(session, "s4_concurrent_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    material = _create_material(session, course.id, teacher.id)

    # 第一次创建 -> 202
    resp1 = client.post(
        f"{GRAPH}/course/{course.id}/ingestions",
        json={"material_id": material.material_id},
        headers=_auth(_token(teacher)),
    )
    assert resp1.status_code == 200
    assert resp1.json()["code"] == 202

    # 第二次创建 -> 409 STATE_CONFLICT
    resp2 = client.post(
        f"{GRAPH}/course/{course.id}/ingestions",
        json={"material_id": material.material_id},
        headers=_auth(_token(teacher)),
    )
    assert resp2.status_code == 409
    assert resp2.json()["data"]["error_code"] == "STATE_CONFLICT"


def test_ingestion_without_version_returns_422(client, session):
    """材料无 current_version_id 时返回 422 VALIDATION_FAILED。"""
    teacher = _user(session, "s4_no_version_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    # 直接造一个没有 version 的材料
    material = SourceMaterial(
        course_id=course.id,
        name="无版本材料.pdf",
        material_type="document",
        current_version_id=None,
        created_by=teacher.id,
    )
    session.add(material)
    session.commit()
    session.refresh(material)

    resp = client.post(
        f"{GRAPH}/course/{course.id}/ingestions",
        json={"material_id": material.material_id},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 422
    assert resp.json()["data"]["error_code"] == "VALIDATION_FAILED"


def test_get_ingestion_unknown_run_returns_404(client, session):
    """查询不存在的 run_id 返回 404。"""
    teacher = _user(session, "s4_unknown_run_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    resp = client.get(
        f"{GRAPH}/course/{course.id}/ingestions/dpr_nonexistent",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 9. 图谱快照 ↔ 课程 release 关联
# ---------------------------------------------------------------------------


def test_graph_release_link_binds_snapshot_to_release(client, session):
    """图谱快照可与课程 release 绑定，支持 release 回滚时图谱联动。"""
    teacher = _user(session, "s4_link_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    from app.services.graph_production_service import publish_snapshot

    snapshot = publish_snapshot(
        session,
        course_id=course.id,
        nodes=[{"node_id": "n1"}],
        relations=[],
        user_id=teacher.id,
    )
    release = CourseRelease(
        course_id=course.id,
        version=1,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        published_by=teacher.id,
        published_at=datetime.utcnow(),
    )
    session.add(release)
    session.commit()
    session.refresh(release)

    link = graph_release_link_service.link(
        session,
        course_id=course.id,
        release_id=release.release_id,
        snapshot_id=snapshot.snapshot_id,
        linked_by=teacher.id,
    )
    session.commit()
    assert link.snapshot_id == snapshot.snapshot_id

    # 幂等更新：重复 link 不报错，更新 snapshot
    link2 = graph_release_link_service.link(
        session,
        course_id=course.id,
        release_id=release.release_id,
        snapshot_id=snapshot.snapshot_id,
        linked_by=teacher.id,
    )
    session.commit()
    assert link2.id == link.id

    # 列表查询
    links = graph_release_link_service.list_links(session, course_id=course.id)
    assert len(links) == 1


def test_graph_release_link_rejects_cross_course_snapshot(client, session):
    """release link 校验快照归属同课程；跨课程返回 404。"""
    teacher_a = _user(session, "s4_link_cross_a")
    teacher_b = _user(session, "s4_link_cross_b")
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")
    _enable_capabilities(session, course_a.id)
    _enable_capabilities(session, course_b.id)

    from app.services.graph_production_service import publish_snapshot

    snapshot_a = publish_snapshot(
        session, course_id=course_a.id, nodes=[{"node_id": "n1"}],
        relations=[], user_id=teacher_a.id,
    )
    release_b = CourseRelease(
        course_id=course_b.id,
        version=1,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        published_by=teacher_b.id,
        published_at=datetime.utcnow(),
    )
    session.add(release_b)
    session.commit()
    session.refresh(release_b)

    # 课程 B 的 release 链接课程 A 的快照 -> 404
    with pytest.raises(Exception):
        graph_release_link_service.link(
            session,
            course_id=course_b.id,
            release_id=release_b.release_id,
            snapshot_id=snapshot_a.snapshot_id,
            linked_by=teacher_b.id,
        )
