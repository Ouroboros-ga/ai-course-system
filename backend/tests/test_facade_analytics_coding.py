"""Facade 学情 coding 聚合回归：LabRecord 必须从 resource_model 导入。

线上实证（2026-09-13）：``GET /api/v1/facade/course/{id}/analytics`` 全量
500，``ImportError: cannot import name 'LabRecord' from
'app.models.experiment_model'``——F3-B 把延迟 import 写错了模块，而本端点
此前零测试覆盖（模块 import 在函数内，启动不爆、调用才爆）。
本测试以教师身份打通端点：修好之前 500，修好之后 200 且 coding 成形。
"""

from __future__ import annotations

import uuid

from app.models.access_control_model import CourseCapability, CourseRole
from app.models.access_control_model import CourseMembership, MembershipStatus
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_model import Course, CourseStatus
from app.models.experiment_model import ExperimentRun, RunOutcome
from app.models.resource_model import LabRecord
from app.services.course_access_service import establish_course_access_baseline
from sqlmodel import select


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _course_with_release(session, teacher_user, student_user) -> Course:
    course = Course(
        fanya_course_id=f"facade-coding-{uuid.uuid4().hex[:8]}",
        fanya_course_name="Facade Coding",
        title="Facade Coding",
        teacher_id=teacher_user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_user.id)
    session.add(CourseMembership(
        course_id=course.id,
        user_id=student_user.id,
        role=CourseRole.STUDENT,
        status=MembershipStatus.ACTIVE,
        analytics_excluded=False,
    ))
    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).first()
    capability.cognitive_analysis = True
    capability.experiment = True
    session.add(capability)
    session.add(CourseRelease(
        course_id=course.id,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        created_by=teacher_user.id,
    ))
    session.commit()
    return course


def test_learning_analytics_coding_summary_smoke(
    client, session, teacher_user, student_user, teacher_token
):
    """教师读学情：200 且 coding.students 有行（ImportError 回归锁）。"""
    course = _course_with_release(session, teacher_user, student_user)
    session.add(ExperimentRun(
        course_id=course.id,
        attempt_id="facade-coding-att",
        student_id=student_user.id,
        language="python",
        source_code="print(1)",
        outcome=RunOutcome.ACCEPTED,
        passed_count=2,
        total_count=2,
        idempotency_key="facade-coding-run",
    ))
    session.add(LabRecord(
        lab_id="facade-coding-lab",
        course_id=course.id,
        student_id=student_user.id,
        attempt_id="facade-coding-att",
        passed=True,
        trusted_source=True,
        source_kind="experiment_attempt_terminated",
    ))
    session.commit()

    response = client.get(
        f"/api/v1/facade/course/{course.id}/analytics",
        params={"days": 7},
        headers=_auth(teacher_token),
    )
    assert response.status_code == 200, response.text[:500]
    coding = response.json()["data"]["coding"]
    rows = {row["student_id"]: row for row in coding["students"]}
    assert rows[student_user.id]["submitted"] == 1
    assert rows[student_user.id]["passed"] == 1


def test_labrecord_lives_in_resource_model():
    """导入位置锁：LabRecord 唯一的家是 resource_model。"""
    import app.models.experiment_model as experiment_model
    import app.models.resource_model as resource_model

    assert not hasattr(experiment_model, "LabRecord")
    assert hasattr(resource_model, "LabRecord")
