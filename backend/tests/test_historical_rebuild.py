"""阶段10 历史课程补建清单编排端到端测试。

覆盖路线图 §13 历史课程补建清单：
- 6 阶段流水线状态识别：material_pending_version → version_pending_parse →
  parse_pending_evidence → evidence_pending_candidate → candidate_pending_review →
  review_pending_release
- 全局清单按阶段聚合，每课程只出现最前待办阶段
- 全局进度汇总：阶段计数 / 完成率
- 课程级详情：列出全部 6 阶段计数
- 平台 COURSE_AUDIT 权限校验：非审计员拒绝访问全局清单
- 课程教师可查看本课程详情；跨课程访问拒绝
- 失败保留原始 error_code（RESOURCE_NOT_FOUND / FORBIDDEN）
- 按课程状态过滤
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    CourseCapability,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_build_model import (
    CourseRelease,
    ReleaseStatus,
    SourceMaterial,
    SourceMaterialVersion,
)
from app.models.course_model import Course, CourseStatus
from app.models.document_parse_model import (
    CandidateBatchStatus,
    DocumentParseRun,
    EvidenceSpan,
    EvidenceSpanStatus,
    GraphCandidateBatch,
    ParsePipeline,
    ParseRunStatus,
    StaleStrategy,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    establish_course_access_baseline,
)


HIST_REBUILD = "/api/v1/historical-rebuild"


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
    title: str = "Stage10 Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"s10-{teacher_id}-{datetime.utcnow().timestamp()}",
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


def _enable_capabilities(session, course_id: int) -> None:
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    defaults = {
        "learning": True,
        "course_building": True,
        "knowledge_graph": True,
        "evidence": True,
        "experiment": True,
        "coding_sandbox": True,
        "cognitive_analysis": True,
        "safety_policy": True,
    }
    if cap is None:
        cap = CourseCapability(course_id=course_id, **defaults)
    else:
        for k, v in defaults.items():
            setattr(cap, k, v)
    session.add(cap)
    session.commit()


def _grant_platform_audit(session, user_id: int) -> None:
    """授予 platform.course.audit 平台权限。"""
    assignment = PlatformPermissionAssignment(
        user_id=user_id,
        permission=PlatformPermission.COURSE_AUDIT,
        granted_by_user_id=user_id,
    )
    session.add(assignment)
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


def _material(session, course_id: int, teacher_id: int) -> SourceMaterial:
    m = SourceMaterial(
        course_id=course_id,
        name="lesson.pdf",
        material_type="document",
        source_kind="upload",
        created_by=teacher_id,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _material_version(
    session, course_id: int, material_id: str, teacher_id: int, *, version: int = 1,
) -> SourceMaterialVersion:
    from app.models.course_build_model import MaterialStatus
    v = SourceMaterialVersion(
        material_id=material_id,
        course_id=course_id,
        version=version,
        file_path="oss://test/lesson.pdf",
        file_hash=uuid.uuid4().hex,
        file_size=1024,
        mime_type="application/pdf",
        parse_status=MaterialStatus.UPLOADED,
        is_current=True,
        created_by=teacher_id,
    )
    session.add(v)
    session.commit()
    session.refresh(v)
    return v


def _parse_run(
    session, course_id: int, material_id: str, material_version_id: str, teacher_id: int,
    *, status: ParseRunStatus = ParseRunStatus.SUCCEEDED,
) -> DocumentParseRun:
    run = DocumentParseRun(
        course_id=course_id,
        material_id=material_id,
        material_version_id=material_version_id,
        pipeline=ParsePipeline.FULL,
        status=status,
        stale_strategy=StaleStrategy.MARK_STALE,
        initiated_by=teacher_id,
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow() if status == ParseRunStatus.SUCCEEDED else None,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _evidence_span(
    session, course_id: int, run_id: str, teacher_id: int, *,
    status: EvidenceSpanStatus = EvidenceSpanStatus.CONFIRMED,
) -> EvidenceSpan:
    from app.models.document_parse_model import BlockType, DocumentBlock

    block = DocumentBlock(
        course_id=course_id,
        run_id=run_id,
        page_number=1,
        block_type=BlockType.TEXT,
        text="test block content",
        content_hash=uuid.uuid4().hex,
    )
    session.add(block)
    session.commit()
    session.refresh(block)

    span = EvidenceSpan(
        course_id=course_id,
        run_id=run_id,
        block_id=block.block_id,
        page_number=1,
        text_snippet="test evidence snippet",
        content_hash=uuid.uuid4().hex,
        status=status,
        confirmed_by=teacher_id if status == EvidenceSpanStatus.CONFIRMED else None,
        confirmed_at=datetime.utcnow() if status == EvidenceSpanStatus.CONFIRMED else None,
    )
    session.add(span)
    session.commit()
    session.refresh(span)
    return span


def _candidate_batch(
    session, course_id: int, run_id: str, teacher_id: int, *,
    snapshot_id: str | None = None, status: CandidateBatchStatus = CandidateBatchStatus.PENDING,
) -> GraphCandidateBatch:
    b = GraphCandidateBatch(
        course_id=course_id,
        parse_run_id=run_id,
        status=status,
        node_candidate_count=5,
        relation_candidate_count=3,
        initiated_by=teacher_id,
        snapshot_id=snapshot_id,
    )
    session.add(b)
    session.commit()
    session.refresh(b)
    return b


def _active_release(session, course_id: int, teacher_id: int) -> CourseRelease:
    r = CourseRelease(
        course_id=course_id,
        version=1,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        label="v1",
        published_by=teacher_id,
        published_at=datetime.utcnow(),
        created_by=teacher_id,
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


# ---------------------------------------------------------------------------
# 全局清单权限与基础返回
# ---------------------------------------------------------------------------


class TestGlobalChecklistPermissions:
    """全局清单端点的权限矩阵。"""

    def test_anonymous_rejected(self, client):
        resp = client.get(f"{HIST_REBUILD}/checklist")
        assert resp.status_code == 401

    def test_student_rejected(self, client, session, student_user):
        """学生无 platform.course.audit 权限，拒绝访问全局清单。"""
        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(student_user)),
        )
        assert resp.status_code == 403

    def test_teacher_without_audit_rejected(self, client, session, teacher_user):
        """普通教师无 platform.course.audit，拒绝访问全局清单。"""
        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 403

    def test_platform_auditor_can_access(self, client, session, teacher_user):
        """平台审计员可访问全局清单。"""
        _grant_platform_audit(session, teacher_user.id)
        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        assert "items" in body["data"]
        assert "total" in body["data"]
        assert "stages" in body["data"]
        stages = body["data"]["stages"]
        assert len(stages) == 6

    def test_status_filter_param_accepted(self, client, session, teacher_user):
        """状态过滤参数被接受（不报错）。"""
        _grant_platform_audit(session, teacher_user.id)
        resp = client.get(
            f"{HIST_REBUILD}/checklist?status=published",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 6 阶段流水线识别
# ---------------------------------------------------------------------------


class TestRebuildStageIdentification:
    """验证 6 个阶段的状态识别逻辑。"""

    def test_stage1_material_pending_version(self, client, session, teacher_user):
        """阶段1：课程有 SourceMaterial 但无 SourceMaterialVersion。"""
        _grant_platform_audit(session, teacher_user.id)
        course = _course(session, teacher_user.id, title="Stage1 Course")
        _material(session, course.id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert any(i["course_id"] == course.id for i in items)
        item = next(i for i in items if i["course_id"] == course.id)
        assert item["stage"] == "material_pending_version"
        assert item["pending_count"] >= 1

    def test_stage2_version_pending_parse(self, client, session, teacher_user):
        """阶段2：课程有 SourceMaterialVersion 但无 succeeded DocumentParseRun。"""
        _grant_platform_audit(session, teacher_user.id)
        course = _course(session, teacher_user.id, title="Stage2 Course")
        m = _material(session, course.id, teacher_user.id)
        _material_version(session, course.id, m.material_id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        items = resp.json()["data"]["items"]
        item = next(i for i in items if i["course_id"] == course.id)
        assert item["stage"] == "version_pending_parse"

    def test_stage2_failed_parse_still_pending(self, client, session, teacher_user):
        """解析失败的 run 不算 succeeded，仍停留在阶段2。"""
        _grant_platform_audit(session, teacher_user.id)
        course = _course(session, teacher_user.id, title="Stage2 Failed Parse")
        m = _material(session, course.id, teacher_user.id)
        v = _material_version(session, course.id, m.material_id, teacher_user.id)
        _parse_run(
            session, course.id, m.material_id, v.version_id, teacher_user.id,
            status=ParseRunStatus.FAILED,
        )

        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        items = resp.json()["data"]["items"]
        item = next(i for i in items if i["course_id"] == course.id)
        assert item["stage"] == "version_pending_parse"

    def test_stage3_parse_pending_evidence(self, client, session, teacher_user):
        """阶段3：课程有 succeeded DocumentParseRun 但无 confirmed EvidenceSpan。"""
        _grant_platform_audit(session, teacher_user.id)
        course = _course(session, teacher_user.id, title="Stage3 Course")
        m = _material(session, course.id, teacher_user.id)
        v = _material_version(session, course.id, m.material_id, teacher_user.id)
        _parse_run(session, course.id, m.material_id, v.version_id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        items = resp.json()["data"]["items"]
        item = next(i for i in items if i["course_id"] == course.id)
        assert item["stage"] == "parse_pending_evidence"

    def test_stage4_evidence_pending_candidate(self, client, session, teacher_user):
        """阶段4：课程有 confirmed EvidenceSpan 但无 GraphCandidateBatch。"""
        _grant_platform_audit(session, teacher_user.id)
        course = _course(session, teacher_user.id, title="Stage4 Course")
        m = _material(session, course.id, teacher_user.id)
        v = _material_version(session, course.id, m.material_id, teacher_user.id)
        run = _parse_run(session, course.id, m.material_id, v.version_id, teacher_user.id)
        _evidence_span(session, course.id, run.run_id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        items = resp.json()["data"]["items"]
        item = next(i for i in items if i["course_id"] == course.id)
        assert item["stage"] == "evidence_pending_candidate"

    def test_stage5_candidate_pending_review(self, client, session, teacher_user):
        """阶段5：课程有 GraphCandidateBatch 但无已审核通过批次（snapshot_id 为空）。"""
        _grant_platform_audit(session, teacher_user.id)
        course = _course(session, teacher_user.id, title="Stage5 Course")
        m = _material(session, course.id, teacher_user.id)
        v = _material_version(session, course.id, m.material_id, teacher_user.id)
        run = _parse_run(session, course.id, m.material_id, v.version_id, teacher_user.id)
        _evidence_span(session, course.id, run.run_id, teacher_user.id)
        _candidate_batch(session, course.id, run.run_id, teacher_user.id)  # snapshot_id=None

        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        items = resp.json()["data"]["items"]
        item = next(i for i in items if i["course_id"] == course.id)
        assert item["stage"] == "candidate_pending_review"

    def test_stage6_review_pending_release(self, client, session, teacher_user):
        """阶段6：课程有 approved 候选但无 active CourseRelease。"""
        _grant_platform_audit(session, teacher_user.id)
        course = _course(session, teacher_user.id, title="Stage6 Course")
        m = _material(session, course.id, teacher_user.id)
        v = _material_version(session, course.id, m.material_id, teacher_user.id)
        run = _parse_run(session, course.id, m.material_id, v.version_id, teacher_user.id)
        _evidence_span(session, course.id, run.run_id, teacher_user.id)
        _candidate_batch(
            session, course.id, run.run_id, teacher_user.id,
            snapshot_id="snap_" + uuid.uuid4().hex,
        )

        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        items = resp.json()["data"]["items"]
        item = next(i for i in items if i["course_id"] == course.id)
        assert item["stage"] == "review_pending_release"

    def test_completed_course_not_in_checklist(self, client, session, teacher_user):
        """全部阶段完成的课程不出现在待办清单。"""
        _grant_platform_audit(session, teacher_user.id)
        course = _course(session, teacher_user.id, title="Completed Course")
        m = _material(session, course.id, teacher_user.id)
        v = _material_version(session, course.id, m.material_id, teacher_user.id)
        run = _parse_run(session, course.id, m.material_id, v.version_id, teacher_user.id)
        _evidence_span(session, course.id, run.run_id, teacher_user.id)
        _candidate_batch(
            session, course.id, run.run_id, teacher_user.id,
            snapshot_id="snap_" + uuid.uuid4().hex,
        )
        _active_release(session, course.id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        items = resp.json()["data"]["items"]
        assert not any(i["course_id"] == course.id for i in items)


# ---------------------------------------------------------------------------
# 全局进度汇总
# ---------------------------------------------------------------------------


class TestGlobalSummary:
    """全局进度汇总端点。"""

    def test_summary_permissions(self, client, session, student_user):
        """非审计员拒绝访问汇总。"""
        resp = client.get(
            f"{HIST_REBUILD}/summary",
            headers=_auth(_token(student_user)),
        )
        assert resp.status_code == 403

    def test_summary_returns_stage_counts(self, client, session, teacher_user):
        """审计员可获取阶段计数与完成率。"""
        _grant_platform_audit(session, teacher_user.id)
        # 构造一个阶段1课程
        c1 = _course(session, teacher_user.id, title="S1")
        _material(session, c1.id, teacher_user.id)
        # 构造一个完成课程
        c2 = _course(session, teacher_user.id, title="Done")
        m = _material(session, c2.id, teacher_user.id)
        v = _material_version(session, c2.id, m.material_id, teacher_user.id)
        run = _parse_run(session, c2.id, m.material_id, v.version_id, teacher_user.id)
        _evidence_span(session, c2.id, run.run_id, teacher_user.id)
        _candidate_batch(
            session, c2.id, run.run_id, teacher_user.id,
            snapshot_id="snap_" + uuid.uuid4().hex,
        )
        _active_release(session, c2.id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/summary",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["total_courses"] >= 2
        assert data["completed_courses"] >= 1
        assert data["pending_courses"] >= 1
        assert "stage_counts" in data
        assert "completion_rate" in data
        assert 0.0 <= data["completion_rate"] <= 1.0

    def test_summary_structure(self, client, session, teacher_user):
        """汇总响应结构完整：字段齐备、计数一致、完成率在 [0,1]。"""
        _grant_platform_audit(session, teacher_user.id)
        resp = client.get(
            f"{HIST_REBUILD}/summary",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        # 字段齐备
        for key in (
            "total_courses", "completed_courses", "pending_courses",
            "stage_counts", "completion_rate",
        ):
            assert key in data
        # 计数一致
        assert data["total_courses"] == data["completed_courses"] + data["pending_courses"]
        # stage_counts 含全部 6 阶段
        assert len(data["stage_counts"]) == 6
        # 完成率在 [0, 1]
        assert 0.0 <= data["completion_rate"] <= 1.0
        # total_courses 为 0 时 completion_rate 必为 0
        if data["total_courses"] == 0:
            assert data["completion_rate"] == 0.0


# ---------------------------------------------------------------------------
# 课程级详情
# ---------------------------------------------------------------------------


class TestCourseDetail:
    """课程级补建状态详情端点。"""

    def test_course_detail_permissions_teacher(self, client, session, teacher_user):
        """课程教师可查看本课程详情。"""
        course = _course(session, teacher_user.id, title="My Course")
        _enable_capabilities(session, course.id)
        resp = client.get(
            f"{HIST_REBUILD}/course/{course.id}",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["course_id"] == course.id
        # 全部 6 阶段计数应存在
        for stage in (
            "material_pending_version_count",
            "version_pending_parse_count",
            "parse_pending_evidence_count",
            "evidence_pending_candidate_count",
            "candidate_pending_review_count",
            "review_pending_release_count",
        ):
            assert stage in data

    def test_course_detail_not_found(self, client, session, teacher_user):
        """不存在的 course_id 返回 RESOURCE_NOT_FOUND。"""
        _grant_platform_audit(session, teacher_user.id)
        resp = client.get(
            f"{HIST_REBUILD}/course/999999",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["data"]["error_code"] == "RESOURCE_NOT_FOUND"

    def test_course_detail_cross_teacher_rejected(self, client, session):
        """非课程教师且非平台审计员拒绝访问；跨课程隔离。"""
        teacher_a = _user(session, "teacher_a_detail")
        teacher_b = _user(session, "teacher_b_detail")
        course = _course(session, teacher_a.id, title="Teacher A Course")
        _enable_capabilities(session, course.id)

        resp = client.get(
            f"{HIST_REBUILD}/course/{course.id}",
            headers=_auth(_token(teacher_b)),
        )
        # teacher_b 既不是课程教师也无 platform.course.audit
        assert resp.status_code == 403

    def test_course_detail_platform_auditor_any_course(self, client, session, teacher_user):
        """平台审计员可查看任意课程详情。"""
        teacher_other = _user(session, "teacher_other")
        course = _course(session, teacher_other.id, title="Other Course")
        _grant_platform_audit(session, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/course/{course.id}",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["course_id"] == course.id

    def test_course_detail_full_stage_breakdown(self, client, session, teacher_user):
        """详情视图包含全部 6 阶段计数与汇总字段。"""
        course = _course(session, teacher_user.id, title="Breakdown")
        _enable_capabilities(session, course.id)
        m = _material(session, course.id, teacher_user.id)
        v = _material_version(session, course.id, m.material_id, teacher_user.id)
        run = _parse_run(session, course.id, m.material_id, v.version_id, teacher_user.id)
        _evidence_span(session, course.id, run.run_id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/course/{course.id}",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["materials_total"] == 1
        assert data["versions_total"] == 1
        assert data["succeeded_runs_total"] == 1
        assert data["confirmed_evidence_total"] == 1
        # 仍待图谱候选
        assert data["evidence_pending_candidate_count"] >= 1
        assert data["candidate_batches_total"] == 0
        assert data["has_active_release"] is False


# ---------------------------------------------------------------------------
# 跨课程隔离
# ---------------------------------------------------------------------------


class TestCrossCourseIsolation:
    """跨课程数据严格隔离。"""

    def test_checklist_items_isolated(self, client, session, teacher_user):
        """课程 A 的补建状态不会污染课程 B。"""
        _grant_platform_audit(session, teacher_user.id)

        # 课程 A 处于阶段1
        course_a = _course(session, teacher_user.id, title="Course A")
        _material(session, course_a.id, teacher_user.id)

        # 课程 B 完成全部阶段
        course_b = _course(session, teacher_user.id, title="Course B")
        m = _material(session, course_b.id, teacher_user.id)
        v = _material_version(session, course_b.id, m.material_id, teacher_user.id)
        run = _parse_run(session, course_b.id, m.material_id, v.version_id, teacher_user.id)
        _evidence_span(session, course_b.id, run.run_id, teacher_user.id)
        _candidate_batch(
            session, course_b.id, run.run_id, teacher_user.id,
            snapshot_id="snap_" + uuid.uuid4().hex,
        )
        _active_release(session, course_b.id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/checklist",
            headers=_auth(_token(teacher_user)),
        )
        items = resp.json()["data"]["items"]
        # 课程 A 出现在清单，课程 B 不出现
        ids = [i["course_id"] for i in items]
        assert course_a.id in ids
        assert course_b.id not in ids

    def test_detail_does_not_leak_other_course(self, client, session, teacher_user):
        """课程详情不返回其他课程的材料/版本/解析计数。"""
        course_a = _course(session, teacher_user.id, title="CourseA Iso")
        course_b = _course(session, teacher_user.id, title="CourseB Iso")
        _enable_capabilities(session, course_a.id)
        _enable_capabilities(session, course_b.id)
        # 仅在课程 A 注入数据
        m = _material(session, course_a.id, teacher_user.id)
        v = _material_version(session, course_a.id, m.material_id, teacher_user.id)
        _parse_run(session, course_a.id, m.material_id, v.version_id, teacher_user.id)

        resp_a = client.get(
            f"{HIST_REBUILD}/course/{course_a.id}",
            headers=_auth(_token(teacher_user)),
        )
        resp_b = client.get(
            f"{HIST_REBUILD}/course/{course_b.id}",
            headers=_auth(_token(teacher_user)),
        )
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        data_a = resp_a.json()["data"]
        data_b = resp_b.json()["data"]
        # 课程 B 不应反映课程 A 的数据
        assert data_b["materials_total"] == 0
        assert data_b["succeeded_runs_total"] == 0
        assert data_a["materials_total"] == 1


# ---------------------------------------------------------------------------
# 状态过滤
# ---------------------------------------------------------------------------


class TestStatusFilter:
    """按课程状态过滤清单。"""

    def test_filter_published_only(self, client, session, teacher_user):
        """只返回 published 状态的课程。"""
        _grant_platform_audit(session, teacher_user.id)
        c_pub = _course(session, teacher_user.id, title="Pub", status=CourseStatus.PUBLISHED)
        _material(session, c_pub.id, teacher_user.id)
        c_draft = _course(session, teacher_user.id, title="Draft", status=CourseStatus.DRAFT)
        _material(session, c_draft.id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/checklist?status=published",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        ids = [i["course_id"] for i in items]
        assert c_pub.id in ids
        assert c_draft.id not in ids

    def test_filter_draft_only(self, client, session, teacher_user):
        """只返回 draft 状态的课程。"""
        _grant_platform_audit(session, teacher_user.id)
        c_pub = _course(session, teacher_user.id, title="Pub", status=CourseStatus.PUBLISHED)
        _material(session, c_pub.id, teacher_user.id)
        c_draft = _course(session, teacher_user.id, title="Draft", status=CourseStatus.DRAFT)
        _material(session, c_draft.id, teacher_user.id)

        resp = client.get(
            f"{HIST_REBUILD}/checklist?status=draft",
            headers=_auth(_token(teacher_user)),
        )
        items = resp.json()["data"]["items"]
        ids = [i["course_id"] for i in items]
        assert c_draft.id in ids
        assert c_pub.id not in ids
