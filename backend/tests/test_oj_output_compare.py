"""OJ 输出比对（ Judge0 只执行，比对归本域 ）。

背景：Judge0 的 ``expected_output`` 是严格（逐字节）比对，无 token/浮点
容错（上游 #224 open）。直接透传它意味着末尾换行/多余空格即 WA。
本文件钉住新语义：

- 纯函数 ``compare_outputs``：空白归一 + 整数精确 + 浮点容差；
- 服务链路：``_execute_run`` 不再向 Judge0 透传 expected（断言
  ``expected_output == ""``），判定由本域做出；
- 空期望 = 只验执行（历史语义保留）；
- 参考解预览与正式评测同规则（教师参考解不再因换行过不了自家验证）。
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlmodel import select

from app.core.security import create_access_token
from app.core.time_utils import utcnow_aware
from app.domain.oj.judging.compare import (
    compare_outputs,
    is_expected_output_asserted,
    tokenize,
)
from app.domain.oj.judging.verdicts import REASON_BY_STATUS
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.experiment_model import (
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentTestCase,
    ExperimentVersion,
    RunOutcome,
)
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from app.services.experiment_attempt_service import run_service


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
        fanya_course_id=f"cmp-{uuid.uuid4().hex[:8]}",
        fanya_course_name="CMP", title="CMP",
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
    activate_student_membership(session, course.id, student_user.id)
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    cap.experiment = True
    cap.coding_sandbox = True
    session.add(cap)
    session.commit()
    return course


def _definition(session, course, teacher, *, cases):
    """定义 + 锁定验证版本 + 用例 + 已发布（一步到位）。"""
    d = ExperimentDefinition(
        experiment_id=f"exp_{uuid.uuid4().hex[:12]}",
        course_id=course.id, title="比对题", created_by=teacher.id,
        difficulty="easy", tags=[],
        language_whitelist=["python3"],
        publish_status=ExperimentPublishStatus.PUBLISHED,
    )
    session.add(d)
    session.flush()
    version = ExperimentVersion(
        version_id=f"ver_{uuid.uuid4().hex[:12]}",
        experiment_id=d.experiment_id, course_id=course.id,
        created_by=teacher.id, is_locked=True, is_active=True,
        reference_preview_verified_at=utcnow_aware(),
        cpu_time_limit=5, memory_limit=128_000, wall_time_limit=10,
    )
    session.add(version)
    session.flush()
    for name, stdin, expected, hidden in cases:
        session.add(ExperimentTestCase(
            version_id=version.version_id, course_id=course.id,
            case_name=name, stdin=stdin, expected_stdout=expected,
            is_hidden=hidden,
        ))
    session.flush()
    d.default_version_id = version.version_id
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


def _hold_formal_queue(monkeypatch) -> None:
    from app.platform.tasks.worker import local_task_worker

    monkeypatch.setattr(local_task_worker, "submit", lambda *_a, **_k: None)


def _run_formal_task_inline(*, task_id, course_id, attempt_id, run_id, student_id):
    from app.models.database import engine
    from app.platform.tasks.handlers import register_business_handlers
    from app.platform.tasks.worker import LocalTaskWorker
    from sqlmodel import Session as SqlSession

    worker = LocalTaskWorker()
    register_business_handlers(worker)
    asyncio.run(worker.run_inline(
        lambda: SqlSession(engine),
        task_id,
        {"course_id": course_id, "attempt_id": attempt_id,
         "run_id": run_id, "student_id": student_id},
    ))


def _fake_judge(monkeypatch, stdout, calls=None):
    """Judge0 只执行：永远返回 ACCEPTED（跑通），stdout 可控。"""
    from app.domain.oj.judging.providers.judge0 import (
        SandboxResult,
        SubmissionStatus,
        sandbox_client,
    )

    def _submit(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return SandboxResult(status=SubmissionStatus.ACCEPTED, stdout=stdout)

    monkeypatch.setattr(sandbox_client, "health_check", lambda: True)
    monkeypatch.setattr(sandbox_client, "submit_code", _submit)
    return sandbox_client


def _submit_run(client, course, attempt_id, student):
    resp = client.post(
        f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
        json={"language": "python3", "source_code": "print(1)"},
        headers={**_auth(student), "Idempotency-Key": f"run-{uuid.uuid4().hex}"},
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["data"]


def _make_attempt(client, course, definition, student):
    resp = client.post(
        f"{EXPERIMENTS}/{definition.experiment_id}/attempts?course_id={course.id}",
        json={"return_anchor": {}},
        headers=_auth(student),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["attempt_id"]


class TestCompareOutputs:
    def test_exact_match(self):
        assert compare_outputs("42", "42") is True

    def test_trailing_newline_ignored(self):
        """教师写 expected 常不带换行，学生 print 自带换行 —— 必须过。"""
        assert compare_outputs("42", "42\n") is True
        assert compare_outputs("42\n", "42") is True

    def test_extra_spaces_and_tabs_ignored(self):
        assert compare_outputs("1 2 3", "1   2\t3\n") is True
        assert compare_outputs("1 2 3\n", "\n  1 2 3  \n\n") is True

    def test_crlf_ignored(self):
        assert compare_outputs("1\r\n2\r\n", "1\n2\n") is True

    def test_token_count_mismatch_fails(self):
        assert compare_outputs("1 2 3", "1 2") is False
        assert compare_outputs("1 2", "1 2 3") is False

    def test_token_order_matters(self):
        assert compare_outputs("1 2", "2 1") is False

    def test_big_int_exact(self):
        big = "12345678901234567890123"
        assert compare_outputs(big, big) is True
        # float 会吞尾数：必须判错，不能因精度丢失而过。
        assert compare_outputs(big, "12345678901234567890124") is False

    def test_int_float_form_equal(self):
        assert compare_outputs("2", "2.0") is True

    def test_float_tolerance(self):
        assert compare_outputs("0.333333", "0.3333333") is True
        assert compare_outputs("1.5", "1.500001") is True
        assert compare_outputs("0.1", "0.2") is False
        assert compare_outputs("1.5", "1.50001") is False

    def test_non_numeric_differs(self):
        assert compare_outputs("hello", "world") is False
        assert compare_outputs("abc", "ABC") is False

    def test_none_and_empty(self):
        assert compare_outputs("", "") is True
        assert compare_outputs(None, None) is True
        assert compare_outputs("", "x") is False
        assert compare_outputs("x", "") is False

    def test_asserted_predicate(self):
        assert is_expected_output_asserted("0") is True
        assert is_expected_output_asserted("42") is True
        assert is_expected_output_asserted("") is False
        assert is_expected_output_asserted("  \n\t ") is False
        assert is_expected_output_asserted(None) is False

    def test_tokenize_none(self):
        assert tokenize(None) == []

    def test_reason_vocabulary_parity(self):
        """本域 reason 取值必须与 verdicts 映射表逐字对齐（词汇唯一源）。"""
        assert REASON_BY_STATUS["accepted"] == "passed"
        assert REASON_BY_STATUS["wrong_answer"] == "wrong_answer"


class TestExecuteRunComparesLocally:
    def test_trailing_newline_passes(
        self, client, session, teacher_user, student_user, course, monkeypatch,
    ):
        """ headline：教师写 "42"，学生输出 "42\\n" —— 必须 AC（旧链 WA）。"""
        definition = _definition(
            session, course, teacher_user,
            cases=[("c1", "", "42", False)],
        )
        attempt_id = _make_attempt(client, course, definition, student_user)
        _hold_formal_queue(monkeypatch)
        calls: list = []
        _fake_judge(monkeypatch, "42\n", calls)
        submitted = _submit_run(client, course, attempt_id, student_user)
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id,
            attempt_id=attempt_id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        session.expire_all()
        run = run_service.get_run(
            session, course_id=course.id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        assert run.outcome == RunOutcome.ACCEPTED
        assert run.score == 1.0
        assert run.test_summary["cases"][0]["reason"] == "passed"

    def test_mismatch_is_wrong_answer(
        self, client, session, teacher_user, student_user, course, monkeypatch,
    ):
        """Judge0 只报"跑通"，判错必须由本域做出（mock 恒 ACCEPTED 也能红）。"""
        definition = _definition(
            session, course, teacher_user,
            cases=[("c1", "", "42", False)],
        )
        attempt_id = _make_attempt(client, course, definition, student_user)
        _hold_formal_queue(monkeypatch)
        _fake_judge(monkeypatch, "43\n")
        submitted = _submit_run(client, course, attempt_id, student_user)
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id,
            attempt_id=attempt_id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        session.expire_all()
        run = run_service.get_run(
            session, course_id=course.id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        assert run.outcome == RunOutcome.WRONG_ANSWER
        assert run.score == 0.0
        assert run.test_summary["cases"][0]["reason"] == "wrong_answer"

    def test_expected_not_forwarded_to_judge0(
        self, client, session, teacher_user, student_user, course, monkeypatch,
    ):
        """Judge0 降级为纯执行：expected 不得再透传（防严格比对借尸还魂）。"""
        definition = _definition(
            session, course, teacher_user,
            cases=[("c1", "", "42", False)],
        )
        attempt_id = _make_attempt(client, course, definition, student_user)
        _hold_formal_queue(monkeypatch)
        calls: list = []
        _fake_judge(monkeypatch, "42\n", calls)
        submitted = _submit_run(client, course, attempt_id, student_user)
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id,
            attempt_id=attempt_id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        assert calls, "Judge0 应当被调用"
        assert all(c.get("expected_output", "") == "" for c in calls)

    def test_empty_expected_means_execution_only(
        self, client, session, teacher_user, student_user, course, monkeypatch,
    ):
        """空期望 = 只验跑通（历史语义保留）：输出垃圾也过。"""
        definition = _definition(
            session, course, teacher_user,
            cases=[("c1", "", "", False)],
        )
        attempt_id = _make_attempt(client, course, definition, student_user)
        _hold_formal_queue(monkeypatch)
        _fake_judge(monkeypatch, "whatever garbage\n")
        submitted = _submit_run(client, course, attempt_id, student_user)
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id,
            attempt_id=attempt_id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        session.expire_all()
        run = run_service.get_run(
            session, course_id=course.id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        assert run.outcome == RunOutcome.ACCEPTED

    def test_float_tolerance_end_to_end(
        self, client, session, teacher_user, student_user, course, monkeypatch,
    ):
        definition = _definition(
            session, course, teacher_user,
            cases=[("c1", "", "0.333333", False)],
        )
        attempt_id = _make_attempt(client, course, definition, student_user)
        _hold_formal_queue(monkeypatch)
        _fake_judge(monkeypatch, "0.3333333\n")
        submitted = _submit_run(client, course, attempt_id, student_user)
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id,
            attempt_id=attempt_id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        session.expire_all()
        run = run_service.get_run(
            session, course_id=course.id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        assert run.outcome == RunOutcome.ACCEPTED

    def test_hidden_case_failure_leaks_nothing(
        self, client, session, teacher_user, student_user, course, monkeypatch,
    ):
        definition = _definition(
            session, course, teacher_user,
            cases=[("secret", "in\n", "out\n", True)],
        )
        attempt_id = _make_attempt(client, course, definition, student_user)
        _hold_formal_queue(monkeypatch)
        _fake_judge(monkeypatch, "nope\n")
        submitted = _submit_run(client, course, attempt_id, student_user)
        _run_formal_task_inline(
            task_id=submitted["task_id"], course_id=course.id,
            attempt_id=attempt_id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        session.expire_all()
        run = run_service.get_run(
            session, course_id=course.id, run_id=submitted["run_id"],
            student_id=student_user.id,
        )
        assert run.outcome == RunOutcome.WRONG_ANSWER
        entry = run.test_summary["cases"][0]
        assert entry["passed"] is False
        assert "stdin" not in entry and "expected" not in entry
        assert "actual" not in entry


class TestReferencePreviewComparesLocally:
    def test_trailing_newline_passes_preview(
        self, session, teacher_user, student_user, course, monkeypatch,
    ):
        """教师参考解输出多一个换行 —— 预览必须过（与正式评测同规则）。"""
        from app.services.experiment_problem_service import version_service

        definition = _definition(
            session, course, teacher_user,
            cases=[("c1", "", "42", False)],
        )
        _fake_judge(monkeypatch, "42\n")
        result = version_service.preview_reference_solution(
            session, course_id=course.id,
            version_id=definition.default_version_id,
            language="python3", source_code="print(42)",
        )
        assert result["accepted"] is True
        assert result["passed_count"] == 1

    def test_mismatch_fails_preview(
        self, session, teacher_user, student_user, course, monkeypatch,
    ):
        from app.services.experiment_problem_service import version_service

        definition = _definition(
            session, course, teacher_user,
            cases=[("c1", "", "42", False)],
        )
        _fake_judge(monkeypatch, "43\n")
        result = version_service.preview_reference_solution(
            session, course_id=course.id,
            version_id=definition.default_version_id,
            language="python3", source_code="print(43)",
        )
        assert result["accepted"] is False
