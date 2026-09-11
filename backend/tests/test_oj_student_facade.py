"""PR-10 端到端：学生题库 façade（题库列表 / 题目详情 / 我的提交）。

安全边界钉住：
- draft / archived 题对学生 **404**（防探测，不区分"没发布"与"不存在"）；
- 学生只能看到**本人**提交 —— 他人 run 一律 404；
- 题目详情**不含任何 testcase**；
- 「未通过的学生也能看到题目」—— 题库可见性与作答结果无关。
"""
from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session as SqlSession, select

from app.core.security import create_access_token
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentRun,
    ExperimentVersion,
)
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)


EXPERIMENTS = "/api/v1/experiments"


def _token(user) -> str:
    return create_access_token({
        "sub": str(user.id), "username": user.username,
        "role": user.role.value, "school_id": user.school_id or "t",
    })


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user)}"}


@pytest.fixture
def course(session, teacher_user, student_user):
    course = Course(
        fanya_course_id=f"p10-{uuid.uuid4().hex[:8]}",
        fanya_course_name="PR10", title="PR10",
        teacher_id=teacher_user.id, status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_user.id)
    session.add(StudentEnrollment(
        student_id=student_user.id, course_id=course.id,
        overall_progress=0.0, is_active=True,
    ))
    session.commit()
    # 仅落 StudentEnrollment 不够 —— 权限上下文读的是**激活的成员关系**
    activate_student_membership(session, course.id, student_user.id)
    # baseline 已建 capability —— 必须 upsert，再插一行会撞唯一约束
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    cap.experiment = True
    cap.coding_sandbox = True
    session.add(cap)
    session.commit()
    return course


def _definition(session, course, teacher, *, title, difficulty, tags, published=True):
    d = ExperimentDefinition(
        experiment_id=f"exp_{uuid.uuid4().hex[:12]}",
        course_id=course.id, title=title, created_by=teacher.id,
        difficulty=difficulty, tags=tags,
        language_whitelist=["python3"],
        publish_status=(
            ExperimentPublishStatus.PUBLISHED if published
            else ExperimentPublishStatus.DRAFT
        ),
    )
    session.add(d)
    session.flush()
    version = ExperimentVersion(
        version_id=f"ver_{uuid.uuid4().hex[:12]}",
        experiment_id=d.experiment_id, course_id=course.id,
        created_by=teacher.id, is_locked=True, is_active=True,
        starter_code={"python3": "def solve():\n    pass\n"},
        cpu_time_limit=5, memory_limit=128_000, wall_time_limit=10,
    )
    session.add(version)
    session.flush()
    d.default_version_id = version.version_id
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


def _attempt(session, course, student, definition, *, status, passed=None, score=None):
    a = ExperimentAttempt(
        attempt_id=f"att_{uuid.uuid4().hex[:10]}",
        experiment_id=definition.experiment_id,
        version_id=definition.default_version_id,
        course_id=course.id, student_id=student.id,
        status=status, passed=passed, final_score=score,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _run(session, course, student, definition, *, outcome, score=0.5, language="python3",
         attempt=None):
    r = ExperimentRun(
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        attempt_id=attempt.attempt_id if attempt else f"att_{uuid.uuid4().hex[:10]}",
        version_id=definition.default_version_id,
        course_id=course.id, student_id=student.id,
        language=language, outcome=outcome, score=score,
        passed_count=3, total_count=5,
        cpu_time_ms=12, wall_time_ms=30, memory_kb=6400,
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


class TestProblemBank:
    def test_lists_only_published(self, client, session, teacher_user, student_user, course):
        """draft / archived 题对学生**不存在**（404 语义，列表不出现）。"""
        token = _token(student_user)
        pub = _definition(session, course, teacher_user, title="公开题",
                          difficulty="easy", tags=["数组"])
        _definition(session, course, teacher_user, title="草稿题",
                    difficulty="hard", tags=[], published=False)

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems", headers=_auth(student_user)
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        titles = [i["title"] for i in items]
        assert "公开题" in titles and "草稿题" not in titles
        _ = pub, token

    def test_my_status_and_filters(self, client, session, teacher_user, student_user, course):
        """我的状态三态 + 状态筛选 + 难度/标签/搜索。"""
        solved = _definition(session, course, teacher_user, title="已解题",
                             difficulty="easy", tags=["数组"])
        tried = _definition(session, course, teacher_user, title="尝试题",
                            difficulty="medium", tags=["树"])
        untouched = _definition(session, course, teacher_user, title="没碰题",
                                difficulty="hard", tags=["动态规划"])

        _attempt(session, course, student_user, solved, status="finalized",
                 passed=True, score=1.0)
        _attempt(session, course, student_user, tried, status="finalized",
                 passed=False, score=0.4)

        headers = _auth(student_user)
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems", headers=headers
        )
        by_title = {i["title"]: i for i in resp.json()["data"]["items"]}
        assert by_title["已解题"]["my_status"] == "solved"
        assert by_title["尝试题"]["my_status"] == "attempted"
        assert by_title["没碰题"]["my_status"] == "not_attempted"

        # 状态筛选
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?status=solved", headers=headers
        )
        items = resp.json()["data"]["items"]
        assert [i["title"] for i in items] == ["已解题"]

        # 难度 + 搜索 + 标签
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?difficulty=hard", headers=headers
        )
        assert [i["title"] for i in resp.json()["data"]["items"]] == ["没碰题"]
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?search=尝试", headers=headers
        )
        assert [i["title"] for i in resp.json()["data"]["items"]] == ["尝试题"]
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?tags=树", headers=headers
        )
        assert [i["title"] for i in resp.json()["data"]["items"]] == ["尝试题"]

        _ = untouched

    def test_pass_rate_from_class_attempts(self, client, session, teacher_user,
                                           student_user, course):
        """通过率 = 全班 finalized 通过数 / 总数（不是只有我自己的）。"""
        definition = _definition(session, course, teacher_user, title="全班题",
                                 difficulty="easy", tags=[])
        _attempt(session, course, student_user, definition,
                 status="finalized", passed=True, score=1.0)
        _attempt(session, course, teacher_user, definition,
                 status="finalized", passed=False, score=0.2)

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems", headers=_auth(student_user)
        )
        row = next(i for i in resp.json()["data"]["items"]
                   if i["title"] == "全班题")
        assert row["attempt_total"] == 2
        assert row["pass_rate"] == pytest.approx(0.5)


class TestStudentProblemDetail:
    def test_detail_public_fields_and_my_status(
        self, client, session, teacher_user, student_user, course
    ):
        definition = _definition(session, course, teacher_user, title="详情题",
                                 difficulty="medium", tags=["字符串"])
        _attempt(session, course, student_user, definition,
                 status="finalized", passed=False, score=0.6)

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems/{definition.experiment_id}",
            headers=_auth(student_user),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["title"] == "详情题"
        assert data["starter_code"] == {"python3": "def solve():\n    pass\n"}
        assert data["limits"]["cpu_time_limit"] == 5
        assert data["my_status"] == "attempted"
        assert data["my_best_score"] == 0.6
        assert data["language_whitelist"] == ["python3"]

    def test_detail_contains_no_testcase(self, client, session, teacher_user,
                                         student_user, course):
        """**不含任何 testcase** —— 用例明细是教师资产。"""
        definition = _definition(session, course, teacher_user, title="无用例题",
                                 difficulty="easy", tags=[])
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems/{definition.experiment_id}",
            headers=_auth(student_user),
        )
        body = resp.text
        assert "test_cases" not in body and "testcase" not in body.lower()

    def test_draft_is_404_for_student(self, client, session, teacher_user,
                                      student_user, course):
        definition = _definition(session, course, teacher_user, title="草稿",
                                 difficulty="easy", tags=[], published=False)
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems/{definition.experiment_id}",
            headers=_auth(student_user),
        )
        assert resp.status_code == 404, resp.text


class TestMySubmissions:
    def test_list_filter_and_ownership(self, client, session, teacher_user,
                                       student_user, course):
        definition = _definition(session, course, teacher_user, title="提交题",
                                 difficulty="easy", tags=[])
        mine = _run(session, course, student_user, definition,
                    outcome="ACCEPTED", language="python3")
        _run(session, course, student_user, definition,
             outcome="WRONG_ANSWER", language="python3")
        # 别人的 run 不许出现
        _run(session, course, teacher_user, definition, outcome="ACCEPTED")

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/submissions",
            headers=_auth(student_user),
        )
        items = resp.json()["data"]["items"]
        assert len(items) == 2
        assert all(i["run_id"] != "" for i in items)

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/submissions?outcome=accepted",
            headers=_auth(student_user),
        )
        items = resp.json()["data"]["items"]
        assert len(items) == 1 and items[0]["run_id"] == mine.run_id

    def test_filter_by_experiment_via_attempt(self, client, session, teacher_user,
                                              student_user, course):
        """按题目筛选提交：run 经 attempt 关联 experiment —— 走真实关联链。"""
        definition = _definition(session, course, teacher_user, title="筛选题",
                                 difficulty="easy", tags=[])
        other = _definition(session, course, teacher_user, title="别的题",
                            difficulty="easy", tags=[])
        attempt = _attempt(session, course, student_user, definition,
                           status="finalized", passed=True, score=1.0)
        mine = _run(session, course, student_user, definition, outcome="ACCEPTED",
                    attempt=attempt)
        _run(session, course, student_user, other, outcome="ACCEPTED")

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/submissions"
            f"?experiment_id={definition.experiment_id}",
            headers=_auth(student_user),
        )
        items = resp.json()["data"]["items"]
        assert len(items) == 1 and items[0]["run_id"] == mine.run_id
        assert items[0]["experiment_id"] == definition.experiment_id

    def test_detail_own_run_ok_other_run_404(self, client, session, teacher_user,
                                             student_user, course):
        definition = _definition(session, course, teacher_user, title="详情题",
                                 difficulty="easy", tags=[])
        mine = _run(session, course, student_user, definition, outcome="ACCEPTED")
        others = _run(session, course, teacher_user, definition, outcome="ACCEPTED")

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/submissions/{mine.run_id}",
            headers=_auth(student_user),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["outcome"] == "accepted"
        assert data["passed_count"] == 3 and data["total_count"] == 5
        assert data["cpu_time_ms"] == 12

        # 他人 run 一律 404，不透露存在性
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/submissions/{others.run_id}",
            headers=_auth(student_user),
        )
        assert resp.status_code == 404, resp.text
