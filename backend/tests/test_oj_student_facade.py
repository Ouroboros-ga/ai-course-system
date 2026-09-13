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
    ExperimentTestCase,
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


def _definition(session, course, teacher, *, title, difficulty, tags, published=True,
                source=None, year=None):
    d = ExperimentDefinition(
        experiment_id=f"exp_{uuid.uuid4().hex[:12]}",
        course_id=course.id, title=title, created_by=teacher.id,
        difficulty=difficulty, tags=tags,
        source=source, year=year,
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
        """隐藏用例明细绝不出现；公开样例以 `samples` 形态返回（设计稿②「样例」区）。
        用例管理字段（weight/is_hidden 等）仍是教师资产，不得出现。"""
        definition = _definition(session, course, teacher_user, title="无用例题",
                                 difficulty="easy", tags=[])
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems/{definition.experiment_id}",
            headers=_auth(student_user),
        )
        body = resp.text
        assert "test_cases" not in body and "testcase" not in body.lower()
        # 防作弊红线：隐藏标记与用例权重不得出现在学生详情
        assert "is_hidden" not in body and '"weight"' not in body

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


class TestSubmissionPathSplit:
    def test_teacher_list_lives_on_teacher_path(self, client, session,
                                                teacher_user, student_user,
                                                course):
        """教师全量流水在 /teacher/submissions；学生打该路径 403。"""
        definition = _definition(session, course, teacher_user, title="分流题",
                                 difficulty="easy", tags=[])
        _run(session, course, student_user, definition, outcome="ACCEPTED")
        _run(session, course, teacher_user, definition, outcome="ACCEPTED")

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/teacher/submissions",
            headers=_auth(teacher_user),
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert len(items) == 2
        assert all("username" in i for i in items)

        denied = client.get(
            f"{EXPERIMENTS}/course/{course.id}/teacher/submissions",
            headers=_auth(student_user),
        )
        assert denied.status_code == 403

    def test_student_list_reachable_on_own_path(self, client, session,
                                                teacher_user, student_user,
                                                course):
        """学生 /submissions 不再被教师路由遮蔽（路由冲突回归）。"""
        definition = _definition(session, course, teacher_user, title="可达题",
                                 difficulty="easy", tags=[])
        _run(session, course, student_user, definition, outcome="ACCEPTED")

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/submissions",
            headers=_auth(student_user),
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["data"]["items"]) == 1


class TestProblemBankB1:
    """B1（2026-09-13）：`search_in` / 难度区间 / `tag_mode` / `source` / `year` /
    服务端排序 / 服务端题号。"""

    def test_problem_no_is_sequential_over_the_catalog(
        self, client, session, teacher_user, student_user, course
    ):
        """题号 = 课程目录里的序号，按 experiment_id code-point 升序。

        服务端下发即为权威 —— 前端只在其缺失时降级派生。
        """
        a = _definition(session, course, teacher_user, title="甲", difficulty="easy", tags=[])
        b = _definition(session, course, teacher_user, title="乙", difficulty="easy", tags=[])
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems", headers=_auth(student_user)
        )
        by_id = {i["experiment_id"]: i for i in resp.json()["data"]["items"]}
        expected = sorted([a.experiment_id, b.experiment_id])
        assert by_id[expected[0]]["problem_no"] == "#001"
        assert by_id[expected[1]]["problem_no"] == "#002"
        assert by_id[expected[0]]["sort_index"] == 1

    def test_problem_no_does_not_shift_when_filtered(
        self, client, session, teacher_user, student_user, course
    ):
        """反向验证：筛掉前后两道题，被筛剩的那道题号**不得**平移。

        这正是「服务端统一下发题号」要拦的退化 —— 若按筛选结果编号，
        原本的 #002 会变成 #001，学生会以为自己看错了题。
        """
        for title in ("甲", "乙", "丙"):
            _definition(session, course, teacher_user, title=title,
                        difficulty="easy", tags=[], source="自编")
        headers = _auth(student_user)

        full = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?source=自编", headers=headers
        ).json()["data"]["items"]
        assert [i["problem_no"] for i in full] == ["#001", "#002", "#003"]
        middle = full[1]
        assert middle["problem_no"] == "#002"

        filtered = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?search={middle['title']}",
            headers=headers,
        ).json()["data"]["items"]
        assert len(filtered) == 1
        assert filtered[0]["experiment_id"] == middle["experiment_id"]
        # 反向验证：若按筛选结果编号，这里会退化成 #001
        assert filtered[0]["problem_no"] == "#002"

    def test_server_sort_covers_the_whole_result_set_not_just_the_page(
        self, client, session, teacher_user, student_user, course
    ):
        """**B1 的核心修复**：排序在分页之前、在全量命中集上做。

        3 道题、page_size=2。按通过率降序时，第 1 页第一行必须是**全局**最高，
        而不是「当前这 2 条里最高的那条」。
        """
        low = _definition(session, course, teacher_user, title="低通过率",
                          difficulty="easy", tags=[])
        high = _definition(session, course, teacher_user, title="高通过率",
                           difficulty="easy", tags=[])
        mid = _definition(session, course, teacher_user, title="中通过率",
                          difficulty="easy", tags=[])

        # 通过率 = passed / finalized 总数
        for definition, passed_flags in (
            (low, [False, False, False, False]),
            (mid, [True, False]),
            (high, [True, True]),
        ):
            for passed in passed_flags:
                _attempt(session, course, student_user, definition,
                         status="finalized", passed=passed, score=1.0 if passed else 0.0)

        headers = _auth(student_user)
        first = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems"
            "?sort_by=pass_rate&sort_order=desc&page=1&page_size=2",
            headers=headers,
        ).json()["data"]
        assert first["total"] == 3
        assert [i["title"] for i in first["items"]] == ["高通过率", "中通过率"]

        second = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems"
            "?sort_by=pass_rate&sort_order=desc&page=2&page_size=2",
            headers=headers,
        ).json()["data"]
        assert [i["title"] for i in second["items"]] == ["低通过率"]

        _ = high, mid, low

    def test_sort_by_problem_no_is_the_default_order(
        self, client, session, teacher_user, student_user, course
    ):
        """默认顺序 = 题号升序（课程目录顺序），排序口径与前端 default 一致。"""
        for title in ("甲", "乙", "丙"):
            _definition(session, course, teacher_user, title=title,
                        difficulty="easy", tags=[])
        data = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems", headers=_auth(student_user)
        ).json()["data"]
        assert [i["problem_no"] for i in data["items"]] == ["#001", "#002", "#003"]

    def test_search_in_statement_finds_body_keyword(
        self, client, session, teacher_user, student_user, course
    ):
        """「搜索题面」未勾时搜不到题面关键词，勾了才搜得到 —— 否则勾选框形同虚设。"""
        d = _definition(session, course, teacher_user, title="两数之和",
                        difficulty="easy", tags=[])
        d.description = "本题请用 dijkstra 求最短路。"
        session.add(d)
        session.commit()

        headers = _auth(student_user)
        default_scope = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?search=dijkstra", headers=headers
        ).json()["data"]
        assert default_scope["items"] == []

        statement_scope = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems"
            "?search=dijkstra&search_in=statement",
            headers=headers,
        ).json()["data"]
        assert [i["title"] for i in statement_scope["items"]] == ["两数之和"]

        both = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?search=dijkstra&search_in=both",
            headers=headers,
        ).json()["data"]
        assert [i["title"] for i in both["items"]] == ["两数之和"]

    def test_difficulty_range_bounds(
        self, client, session, teacher_user, student_user, course
    ):
        """区间是闭区间；单端给出时另一端自动取边界。"""
        _definition(session, course, teacher_user, title="易", difficulty="easy", tags=[])
        _definition(session, course, teacher_user, title="中", difficulty="medium", tags=[])
        _definition(session, course, teacher_user, title="难", difficulty="hard", tags=[])
        headers = _auth(student_user)

        at_least_medium = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?difficulty_min=medium",
            headers=headers,
        ).json()["data"]
        assert sorted(i["title"] for i in at_least_medium["items"]) == ["中", "难"]

        at_most_medium = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?difficulty_max=medium",
            headers=headers,
        ).json()["data"]
        assert sorted(i["title"] for i in at_most_medium["items"]) == ["中", "易"]

        # 端点写反 → 空结果集，而不是 422
        reversed_bounds = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems"
            "?difficulty_min=hard&difficulty_max=easy",
            headers=headers,
        )
        assert reversed_bounds.status_code == 200, reversed_bounds.text
        assert reversed_bounds.json()["data"]["items"] == []

    def test_tag_mode_or(
        self, client, session, teacher_user, student_user, course
    ):
        """`and`（默认）收窄，`or` 发散。"""
        _definition(session, course, teacher_user, title="数组题",
                    difficulty="easy", tags=["数组"])
        _definition(session, course, teacher_user, title="哈希题",
                    difficulty="easy", tags=["哈希"])
        headers = _auth(student_user)

        both = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?tags=数组,哈希", headers=headers
        ).json()["data"]
        assert both["items"] == []

        either = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?tags=数组,哈希&tag_mode=or",
            headers=headers,
        ).json()["data"]
        assert sorted(i["title"] for i in either["items"]) == ["哈希题", "数组题"]

    def test_source_and_year_filter_and_expose(
        self, client, session, teacher_user, student_user, course
    ):
        """来源筛选大小写不敏感；年份精确匹配；两字段原样回给前端。"""
        _definition(session, course, teacher_user, title="CF 题", difficulty="easy",
                    tags=[], source="Codeforces", year=2026)
        _definition(session, course, teacher_user, title="自编题", difficulty="easy",
                    tags=[], source=None, year=None)
        headers = _auth(student_user)

        by_source = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?source=codeforces", headers=headers
        ).json()["data"]
        assert [i["title"] for i in by_source["items"]] == ["CF 题"]
        assert by_source["items"][0]["source"] == "Codeforces"
        assert by_source["items"][0]["year"] == 2026

        by_year = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems?year=2026", headers=headers
        ).json()["data"]
        assert [i["title"] for i in by_year["items"]] == ["CF 题"]

        # 自编题的来源/年份是 null，不是空串/0 —— 前端靠 null 判断「没填」
        everything = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems", headers=headers
        ).json()["data"]
        selfmade = next(i for i in everything["items"] if i["title"] == "自编题")
        assert selfmade["source"] is None and selfmade["year"] is None

    def test_invalid_query_values_are_422_not_500(
        self, client, session, teacher_user, student_user, course
    ):
        """取值合法性由域层判定，路由不做第二套校验 —— 非法值必须是 422。"""
        _definition(session, course, teacher_user, title="任意题",
                    difficulty="easy", tags=[])
        headers = _auth(student_user)
        for query in (
            "sort_by=popularity",
            "sort_order=sideways",
            "search_in=everywhere",
            "tag_mode=xor",
            "difficulty_min=impossible",
            "year=1800",
        ):
            resp = client.get(
                f"{EXPERIMENTS}/course/{course.id}/problems?{query}", headers=headers
            )
            assert resp.status_code == 422, f"{query} → {resp.status_code}"


class TestStudentProblemDetailB2:
    """B2（2026-09-13）：详情页补充题号 / 来源 / 年份 / 题面语言 / 样例稳定 id。"""

    def test_detail_exposes_b2_fields(
        self, client, session, teacher_user, student_user, course
    ):
        d = _definition(session, course, teacher_user, title="B2 详情题",
                        difficulty="medium", tags=["最短路"],
                        source="UVA", year=2019)
        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems/{d.experiment_id}",
            headers=_auth(student_user),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["problem_no"] == "#001"
        assert data["source"] == "UVA"
        assert data["year"] == 2019
        assert data["statement_locales"] == ["zh"]
        assert data["statement_default_locale"] == "zh"

    def test_detail_problem_no_matches_the_list(
        self, client, session, teacher_user, student_user, course
    ):
        """⚠️ 详情页与列表页必须是同一个题号。

        「列表显示 #007、点进去显示 #009」是这类规则分裂的经典症状 ——
        两边现在共用 `build_problem_no_index`，这条测试把它钉住。
        """
        target = _definition(session, course, teacher_user, title="目标题",
                             difficulty="easy", tags=[])
        for title in ("甲", "乙"):
            _definition(session, course, teacher_user, title=title,
                        difficulty="easy", tags=[])
        headers = _auth(student_user)

        listed = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems", headers=headers
        ).json()["data"]["items"]
        from_list = next(i for i in listed if i["experiment_id"] == target.experiment_id)
        detail = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems/{target.experiment_id}",
            headers=headers,
        ).json()["data"]
        assert detail["problem_no"] == from_list["problem_no"]

    def test_public_samples_carry_a_stable_id(
        self, client, session, teacher_user, student_user, course
    ):
        """公开样例带 stable `sample_id`（= 用例 `case_id`），隐藏用例仍不出现。"""
        d = _definition(session, course, teacher_user, title="样例题",
                        difficulty="easy", tags=[])
        public = ExperimentTestCase(
            version_id=d.default_version_id, course_id=course.id,
            case_name="样例 1", stdin="1 2\n", expected_stdout="3\n", is_hidden=False,
        )
        hidden = ExperimentTestCase(
            version_id=d.default_version_id, course_id=course.id,
            case_name="隐藏 1", stdin="9 9\n", expected_stdout="18\n", is_hidden=True,
        )
        session.add(public)
        session.add(hidden)
        session.commit()
        session.refresh(public)

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/problems/{d.experiment_id}",
            headers=_auth(student_user),
        )
        data = resp.json()["data"]
        assert len(data["samples"]) == 1
        assert data["samples"][0]["sample_id"] == public.case_id
        assert data["samples"][0]["input"] == "1 2\n"
        # 防作弊红线不变
        assert hidden.case_id not in resp.text
        assert "9 9" not in resp.text
        assert "is_hidden" not in resp.text


def test_oj_router_paths_have_no_duplicates():
    """三 OJ 路由 method+path 全局唯一（路由遮蔽回归：教师/学生曾经撞车）。"""
    import collections

    from app.api.v1.endpoints import (
        experiment_activities,
        experiment_student,
        experiments,
    )

    seen = collections.Counter()
    for module in (experiments, experiment_activities, experiment_student):
        for router_name in ("experiment_router", "activity_router",
                            "student_router"):
            router = getattr(module, router_name, None)
            if router is None:
                continue
            for route in router.routes:
                methods = tuple(sorted(getattr(route, "methods", None) or ()))
                if methods:
                    seen[(methods, route.path)] += 1
    dups = {key: count for key, count in seen.items() if count > 1}
    assert not dups, f"duplicate OJ routes: {dups}"
