"""阶段7 平台实验室目录 API 端到端测试。

覆盖路线图 §10 验收与 PageDesign前端API契约规划.md §3.7 Lab：
- 教师创建实验室（课程级 + 平台级）
- 实验室发布与详情
- 学生加入实验室
- catalog 列表（visibility 过滤）
- course-tasks 课程任务页（学生参与情况）
- my-experiments 我的实验页
- records 实验记录页
- 记录学生尝试结果（学生自身 + 教师代记）
- 跨课程隔离与权限拒绝
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.experiment_model import (
    AttemptStatus,
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentLabProjection,
    ExperimentPublishStatus,
    ExperimentRecommendation,
)
from app.models.resource_model import (
    LabCatalogEntry,
    LabCatalogVisibility,
    LabEnrollment,
    LabRecord,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)


LAB = "/api/v1/lab"


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
    title: str = "Stage7 Lab Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"s7lab-{teacher_id}-{datetime.utcnow().timestamp()}",
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


def _enable_experiment_capabilities(session, course_id: int) -> None:
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
        "safety_policy": False,
    }
    if cap is None:
        cap = CourseCapability(course_id=course_id, **defaults)
    else:
        for k, v in defaults.items():
            setattr(cap, k, v)
    session.add(cap)
    session.commit()


def _enroll_student(session, course_id: int, student_id: int) -> None:
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


def _create_lab_via_api(
    client, teacher_token: str, *,
    course_id: int | None = None,
    title: str = "二分查找实验室",
    visibility: LabCatalogVisibility = LabCatalogVisibility.COURSE_ONLY,
    experiment_id: str | None = None,
) -> dict:
    payload = {
        "title": title,
        "description": "实验室说明",
        "language_whitelist": ["python3"],
        "visibility": visibility.value,
        "cpu_time_limit": 5,
        "memory_limit": 128_000,
        "wall_time_limit": 10,
        "knowledge_node_ids": [],
        "statement_object_key": "stmt/key1",
    }
    if course_id is not None:
        payload["course_id"] = course_id
    if experiment_id is not None:
        payload["experiment_id"] = experiment_id
    resp = client.post(LAB, json=payload, headers=_auth(teacher_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201, body
    return body["data"]


def _publish_lab_via_api(client, token: str, lab_id: str) -> dict:
    resp = client.post(f"{LAB}/{lab_id}/publish", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# 实验室创建与发布
# ---------------------------------------------------------------------------


class LegacyIndependentLabCreateContract:
    """实验室创建与发布"""

    def test_teacher_creates_course_level_lab(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        data = _create_lab_via_api(client, _token(teacher_user), course_id=course.id)
        assert data["lab_id"].startswith("lab_")
        assert data["course_id"] == course.id
        assert data["visibility"] == "course_only"
        assert data["is_published"] is False

    def test_teacher_creates_platform_level_lab(self, client, session, teacher_user):
        # 平台级实验室不需 course 权限
        data = _create_lab_via_api(
            client, _token(teacher_user),
            course_id=None, visibility=LabCatalogVisibility.PUBLIC,
        )
        assert data["course_id"] is None
        assert data["visibility"] == "public"

    def test_publish_course_level_lab(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        lab = _create_lab_via_api(client, _token(teacher_user), course_id=course.id)
        published = _publish_lab_via_api(client, _token(teacher_user), lab["lab_id"])
        assert published["is_published"] is True
        assert published["published_at"]

    def test_student_cannot_create_course_level_lab(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        resp = client.post(
            LAB,
            json={"title": "x", "course_id": course.id, "visibility": "course_only"},
            headers=_auth(_token(student_user)),
        )
        body = resp.json()
        assert body["code"] != 201


# ---------------------------------------------------------------------------
# Catalog 与列表页
# ---------------------------------------------------------------------------


class LegacyIndependentLabCatalogContract:
    """实验室目录与列表页"""

    def test_catalog_only_lists_published_labs(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        lab_published = _create_lab_via_api(client, _token(teacher_user), course_id=course.id, title="pub")
        lab_draft = _create_lab_via_api(client, _token(teacher_user), course_id=course.id, title="draft")
        _publish_lab_via_api(client, _token(teacher_user), lab_published["lab_id"])

        resp = client.get(f"{LAB}/catalog?course_id={course.id}", headers=_auth(_token(student_user)))
        body = resp.json()
        ids = [item["lab_id"] for item in body["data"]["items"]]
        assert lab_published["lab_id"] in ids
        assert lab_draft["lab_id"] not in ids

    def test_course_tasks_lists_course_labs_with_student_progress(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        lab = _create_lab_via_api(client, _token(teacher_user), course_id=course.id)
        _publish_lab_via_api(client, _token(teacher_user), lab["lab_id"])

        resp = client.get(
            f"{LAB}/course-tasks?course_id={course.id}",
            headers=_auth(_token(student_user)),
        )
        body = resp.json()
        assert body["code"] == 200
        items = body["data"]["items"]
        assert len(items) == 1
        assert items[0]["lab_id"] == lab["lab_id"]
        assert items[0]["enrolled"] is False  # 学生未加入
        assert items[0]["best_score"] is None

    def test_my_experiments_lists_enrolled_labs(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        lab = _create_lab_via_api(client, _token(teacher_user), course_id=course.id)
        _publish_lab_via_api(client, _token(teacher_user), lab["lab_id"])

        # 学生加入
        client.post(f"{LAB}/{lab['lab_id']}/enroll", headers=_auth(_token(student_user)))

        resp = client.get(f"{LAB}/my-experiments", headers=_auth(_token(student_user)))
        body = resp.json()
        ids = [item["lab_id"] for item in body["data"]["items"]]
        assert lab["lab_id"] in ids


# ---------------------------------------------------------------------------
# 学生加入与记录
# ---------------------------------------------------------------------------


class LegacyIndependentLabEnrollAndRecordContract:
    """学生加入实验室与记录尝试结果"""

    def test_student_enrolls_lab(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        lab = _create_lab_via_api(client, _token(teacher_user), course_id=course.id)
        _publish_lab_via_api(client, _token(teacher_user), lab["lab_id"])

        resp = client.post(f"{LAB}/{lab['lab_id']}/enroll", headers=_auth(_token(student_user)))
        body = resp.json()
        assert body["code"] == 201
        assert body["data"]["lab_id"] == lab["lab_id"]
        assert body["data"]["student_id"] == student_user.id
        assert body["data"]["is_active"] is True

        # 幂等：再次加入应激活同一记录
        resp2 = client.post(f"{LAB}/{lab['lab_id']}/enroll", headers=_auth(_token(student_user)))
        assert resp2.json()["data"]["lab_id"] == lab["lab_id"]

    def test_student_records_own_attempt_result(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        lab = _create_lab_via_api(client, _token(teacher_user), course_id=course.id)
        _publish_lab_via_api(client, _token(teacher_user), lab["lab_id"])
        client.post(f"{LAB}/{lab['lab_id']}/enroll", headers=_auth(_token(student_user)))

        resp = client.post(
            f"{LAB}/{lab['lab_id']}/records",
            json={
                "attempt_id": "att_test123",
                "final_score": 0.85,
                "passed": True,
                "evidence_id": "ev_test123",
                "return_anchor": {"node_id": 1},
            },
            headers=_auth(_token(student_user)),
        )
        body = resp.json()
        assert body["code"] == 201, body
        assert body["data"]["final_score"] == 0.85
        assert body["data"]["passed"] is True
        assert body["data"]["evidence_id"] == "ev_test123"

        # 记录页可见
        resp_r = client.get(f"{LAB}/records", headers=_auth(_token(student_user)))
        body_r = resp_r.json()
        ids = [item["record_id"] for item in body_r["data"]["items"]]
        assert body["data"]["record_id"] in ids

    def test_teacher_can_record_for_student(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        lab = _create_lab_via_api(client, _token(teacher_user), course_id=course.id)
        _publish_lab_via_api(client, _token(teacher_user), lab["lab_id"])

        resp = client.post(
            f"{LAB}/{lab['lab_id']}/records",
            json={
                "attempt_id": "att_teacher_record",
                "final_score": 0.5,
                "passed": False,
                "student_id": student_user.id,
            },
            headers=_auth(_token(teacher_user)),
        )
        body = resp.json()
        assert body["code"] == 201, body
        assert body["data"]["student_id"] == student_user.id
        assert body["data"]["passed"] is False

    def test_student_cannot_record_for_others(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        s1 = _user(session, "s1_lab_rec", UserRole.STUDENT)
        s2 = _user(session, "s2_lab_rec", UserRole.STUDENT)
        _enroll_student(session, course.id, s1.id)
        _enroll_student(session, course.id, s2.id)

        lab = _create_lab_via_api(client, _token(teacher_user), course_id=course.id)
        _publish_lab_via_api(client, _token(teacher_user), lab["lab_id"])

        # s1 不可为 s2 记录
        resp = client.post(
            f"{LAB}/{lab['lab_id']}/records",
            json={
                "attempt_id": "att_s1_for_s2",
                "student_id": s2.id,
            },
            headers=_auth(_token(s1)),
        )
        body = resp.json()
        assert body["code"] != 201


class TestLabRecordsAreServerOwned:
    def test_independent_lab_lifecycle_routes_are_not_registered(
        self, client, session, teacher_user, student_user,
    ):
        """Only course-experiment projections remain public lab APIs."""
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        headers = _auth(_token(student_user))

        requests = [
            client.post(
                LAB,
                json={"title": "deprecated", "course_id": course.id},
                headers=headers,
            ),
            client.get(f"{LAB}/legacy_lab", headers=headers),
            client.post(f"{LAB}/legacy_lab/publish", headers=headers),
            client.post(f"{LAB}/legacy_lab/enroll", headers=headers),
        ]

        assert [response.status_code for response in requests] == [404, 404, 404, 404]

    def test_projection_reads_require_an_authorized_course_scope(
        self, client, session, teacher_user, student_user,
    ):
        """A lab projection can never be discovered outside Course Access v1."""
        visible_course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, visible_course.id)
        _enroll_student(session, visible_course.id, student_user.id)

        hidden_course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, hidden_course.id)
        hidden_definition = ExperimentDefinition(
            course_id=hidden_course.id,
            title="Cross-course projection",
            language_whitelist=["python3"],
            publish_status=ExperimentPublishStatus.PUBLISHED,
            created_by=teacher_user.id,
        )
        session.add(hidden_definition)
        session.commit()

        headers = _auth(_token(student_user))
        missing_scope = client.get(f"{LAB}/catalog", headers=headers)
        cross_course = client.get(
            f"{LAB}/catalog?course_id={hidden_course.id}", headers=headers,
        )
        my_experiments = client.get(
            f"{LAB}/my-experiments?course_id={hidden_course.id}", headers=headers,
        )
        records = client.get(
            f"{LAB}/records?course_id={hidden_course.id}", headers=headers,
        )

        assert missing_scope.status_code == 422
        assert cross_course.status_code == 403
        assert my_experiments.status_code == 403
        assert records.status_code == 403

    def test_public_record_write_route_is_not_registered(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        response = client.post(
            f"{LAB}/legacy_lab/records",
            json={
                "attempt_id": "att_forged",
                "final_score": 1.0,
                "passed": True,
                "evidence_id": "ev_forged",
            },
            headers=_auth(_token(student_user)),
        )

        assert response.status_code == 404
        assert response.json()["code"] == 404

    def test_lab_reads_are_course_experiment_projections_only(
        self, client, session, teacher_user, student_user,
    ):
        """The laboratory must never surface independently-written lab data."""
        course = _course(session, teacher_user.id)
        _enable_experiment_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        definition = ExperimentDefinition(
            course_id=course.id,
            title="可信课程实验",
            description="只由课程实验投影展示",
            language_whitelist=["python3"],
            publish_status=ExperimentPublishStatus.PUBLISHED,
            created_by=teacher_user.id,
        )
        session.add(definition)
        session.flush()
        projection = ExperimentLabProjection(
            course_id=course.id,
            experiment_id=definition.experiment_id,
        )
        attempt = ExperimentAttempt(
            course_id=course.id,
            experiment_id=definition.experiment_id,
            version_id="expv_projection_test",
            student_id=student_user.id,
            status=AttemptStatus.FINALIZED,
            final_score=1.0,
            passed=True,
        )
        recommendation = ExperimentRecommendation(
            course_id=course.id,
            student_id=student_user.id,
            experiment_id=definition.experiment_id,
            version_id=attempt.version_id,
        )
        session.add(projection)
        session.add(attempt)
        session.add(recommendation)
        session.flush()
        trusted = LabRecord(
            lab_id=projection.projection_id,
            projection_id=projection.projection_id,
            course_id=course.id,
            experiment_id=definition.experiment_id,
            student_id=student_user.id,
            attempt_id=attempt.attempt_id,
            final_score=1.0,
            passed=True,
            source_kind="experiment_attempt_terminated",
            trusted_source=True,
        )
        legacy = LabRecord(
            lab_id="legacy_lab",
            course_id=course.id,
            student_id=student_user.id,
            attempt_id="legacy_attempt",
            final_score=1.0,
            passed=True,
            source_kind="legacy_unverified",
            trusted_source=False,
        )
        session.add(trusted)
        session.add(legacy)
        session.commit()

        headers = _auth(_token(student_user))
        catalog = client.get(f"{LAB}/catalog?course_id={course.id}", headers=headers).json()["data"]["items"]
        assert [item["experiment_id"] for item in catalog] == [definition.experiment_id]
        assert catalog[0]["projection_id"] == projection.projection_id

        tasks = client.get(f"{LAB}/course-tasks?course_id={course.id}", headers=headers).json()["data"]["items"]
        assert [item["experiment_id"] for item in tasks] == [definition.experiment_id]
        assert tasks[0]["recommended"] is True
        assert tasks[0]["last_attempt_id"] == attempt.attempt_id

        mine = client.get(
            f"{LAB}/my-experiments?course_id={course.id}", headers=headers,
        ).json()["data"]["items"]
        assert [item["experiment_id"] for item in mine] == [definition.experiment_id]

        records = client.get(
            f"{LAB}/records?course_id={course.id}", headers=headers,
        ).json()["data"]["items"]
        assert [item["record_id"] for item in records] == [trusted.record_id]
