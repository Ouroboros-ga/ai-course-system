"""OJ PR-01：Run 状态与判定分离（`RunState` / `RunVerdict` / `RunType`）。

覆盖三件事：

1. **领域语义**（无 DB）：映射是否完备、是否引入第二套判定词汇、边界输入是否安全。
2. **持久化一致性**：模型的默认值是否跟随领域枚举；监听器是否保证
   `run_state` 与 `outcome` / `cancel_requested_at` 不脱节。
3. **迁移与响应体约束**：迁移链是否真的加上了两列两索引
   （测试库由 `alembic upgrade head` 建，见 `conftest.py::test_engine`）；
   以及新的两列**不得**出现在 API 响应里（PR-01 的 DoD 要求响应体不变）。

为什么值得单独一个文件：`RunOutcome` 是**原生 PG enum**（类型名 `runoutcome`），
DB 里存的是**大写成员名**，而 API 暴露的是小写 `.value`。两层表示之间的
映射一旦写错就是静默错误（回填一行不中、排名算错），因此每个映射分支都单独立用例。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from app.core.time_utils import utcnow_aware
from app.domain.oj.judging.verdicts import (
    UNKNOWN_REASON,
    RunState,
    RunVerdict,
    is_system_verdict,
    is_terminal_state,
    reason_for_status,
    state_for_outcome,
    verdict_for_outcome,
)
from app.domain.oj.submissions.run_types import (
    DEFAULT_RUN_TYPE,
    RunType,
    is_scored_run_type,
    normalize_run_type,
)
from app.models.course_model import Course, CourseStatus
from app.models.experiment_model import ExperimentRun, RunOutcome
from app.models.user_model import User, UserRole

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session: Session) -> User:
    user = User(
        username=f"oj-{uuid.uuid4().hex[:10]}",
        email=f"oj-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        role=UserRole.STUDENT,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _fixture_course(session: Session) -> tuple[Course, User]:
    """建一门最小课程 + 一名学生，返回 (course, student)。"""
    student = _user(session)
    course = Course(
        fanya_course_id=f"oj-{uuid.uuid4().hex[:10]}",
        fanya_course_name="OJ PR-01",
        title="OJ PR-01",
        teacher_id=_user(session).id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course, student


def _run(session: Session, *, course_id: int, student_id: int, **kwargs) -> ExperimentRun:
    run = ExperimentRun(
        course_id=course_id,
        attempt_id=f"attempt-{uuid.uuid4().hex[:10]}",
        student_id=student_id,
        language="python3",
        source_code="print('ok')",
        **kwargs,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


# ---------------------------------------------------------------------------
# 1. 领域语义（无 DB）
# ---------------------------------------------------------------------------


class TestRunVerdictVocabulary:
    def test_run_verdict_values_match_run_outcome_minus_pending(self) -> None:
        """不引入第二套判定词汇：RunVerdict 必须恰好等于 RunOutcome 去掉 PENDING。

        这条断言是 PR-01 的核心约束。一旦有人在 RunVerdict 里加了 RunOutcome
        没有的判定（或漏了一个），迁移期的映射就不再无损，排名与掌握度会读到
        两套词汇的并集。
        """
        expected = {member.value for member in RunOutcome} - {"pending"}
        actual = {member.value for member in RunVerdict}
        assert actual == expected

    @pytest.mark.parametrize("outcome", [m for m in RunOutcome if m.value != "pending"])
    def test_verdict_for_outcome_maps_every_terminal_outcome(self, outcome) -> None:
        assert verdict_for_outcome(outcome) is RunVerdict(outcome.value)

    def test_verdict_for_outcome_accepts_raw_strings(self) -> None:
        """领域层不 import models，因此必须能吃业务层的裸值字符串。

        也要能吃**大写成员名** —— 那是 PG 原生 enum ``runoutcome`` 在库里的
        实际存储形式。只认小写会把已完成的 run 读成「还没判完」。
        """
        assert verdict_for_outcome("wrong_answer") is RunVerdict.WRONG_ANSWER
        assert verdict_for_outcome("WRONG_ANSWER") is RunVerdict.WRONG_ANSWER

    def test_verdict_for_outcome_returns_none_for_pending(self) -> None:
        assert verdict_for_outcome(RunOutcome.PENDING) is None
        assert verdict_for_outcome("pending") is None

    def test_verdict_for_outcome_tolerates_unknown_values(self) -> None:
        """历史脏数据不应让读取路径抛异常。"""
        assert verdict_for_outcome(None) is None
        assert verdict_for_outcome("") is None
        assert verdict_for_outcome("not_a_verdict") is None


class TestRunStateDerivation:
    def test_pending_without_cancel_is_queued(self) -> None:
        assert state_for_outcome(RunOutcome.PENDING) is RunState.QUEUED

    def test_pending_with_cancel_is_cancelled(self) -> None:
        """假不可能先取消再判定：取消只在没有结论时才成为终态。"""
        assert (
            state_for_outcome(RunOutcome.PENDING, cancel_requested_at=utcnow_aware())
            is RunState.CANCELLED
        )

    @pytest.mark.parametrize(
        "outcome", [RunOutcome.INTERNAL_ERROR, RunOutcome.SANDBOX_UNAVAILABLE]
    )
    def test_system_failures_are_system_error(self, outcome) -> None:
        """沙箱挂了不是学生的作答结论，必须与 WA 区分开。"""
        assert state_for_outcome(outcome) is RunState.SYSTEM_ERROR

    @pytest.mark.parametrize(
        "outcome",
        [
            RunOutcome.ACCEPTED,
            RunOutcome.WRONG_ANSWER,
            RunOutcome.TIME_LIMIT_EXCEEDED,
            RunOutcome.MEMORY_LIMIT_EXCEEDED,
            RunOutcome.RUNTIME_ERROR,
            RunOutcome.COMPILATION_ERROR,
        ],
    )
    def test_student_facing_verdicts_are_finished(self, outcome) -> None:
        assert state_for_outcome(outcome) is RunState.FINISHED

    def test_cancel_requested_does_not_override_a_real_verdict(self) -> None:
        """已经判出结论的 run，后来点取消不应把它变成 cancelled。"""
        assert (
            state_for_outcome(
                RunOutcome.WRONG_ANSWER, cancel_requested_at=utcnow_aware()
            )
            is RunState.FINISHED
        )

    def test_derivation_is_total_over_every_run_outcome(self) -> None:
        """全部 9 个既有取值都必须映射到一个合法状态，不允许漏网。"""
        for outcome in RunOutcome:
            assert isinstance(state_for_outcome(outcome), RunState)

    def test_unknown_outcome_degrades_to_queued(self) -> None:
        assert state_for_outcome("garbage") is RunState.QUEUED

    def test_derivation_accepts_uppercase_member_names(self) -> None:
        """库里的原生 enum 值是大写；映射对大小写不敏感。"""
        assert state_for_outcome("SANDBOX_UNAVAILABLE") is RunState.SYSTEM_ERROR
        assert state_for_outcome("ACCEPTED") is RunState.FINISHED
        assert state_for_outcome("PENDING") is RunState.QUEUED


class TestStateAndVerdictHelpers:
    def test_terminal_states(self) -> None:
        assert is_terminal_state(RunState.FINISHED)
        assert is_terminal_state(RunState.CANCELLED)
        assert is_terminal_state(RunState.SYSTEM_ERROR)
        assert not is_terminal_state(RunState.QUEUED)
        assert not is_terminal_state(RunState.RUNNING)

    def test_terminal_state_accepts_raw_strings_and_rejects_junk(self) -> None:
        assert is_terminal_state("finished")
        assert is_terminal_state("FINISHED")  # DB 大写成员名
        assert not is_terminal_state("garbage")
        assert not is_terminal_state(None)

    def test_system_verdicts(self) -> None:
        assert is_system_verdict(RunVerdict.INTERNAL_ERROR)
        assert is_system_verdict(RunVerdict.SANDBOX_UNAVAILABLE)
        assert is_system_verdict("SANDBOX_UNAVAILABLE")  # DB 大写成员名
        assert not is_system_verdict(RunVerdict.WRONG_ANSWER)
        assert not is_system_verdict(None)


class TestRunType:
    def test_only_submission_is_scored(self) -> None:
        """排名与掌握度只看正式提交；自测跑多少次都不该进成绩。"""
        assert is_scored_run_type(RunType.SUBMISSION)
        assert is_scored_run_type("submission")
        assert not is_scored_run_type(RunType.TEST)
        assert not is_scored_run_type(RunType.REFERENCE_PREVIEW)
        assert not is_scored_run_type(None)

    def test_normalize_accepts_both_casings(self) -> None:
        assert normalize_run_type("test") is RunType.TEST
        assert normalize_run_type("TEST") is RunType.TEST
        assert normalize_run_type("reference_preview") is RunType.REFERENCE_PREVIEW
        assert normalize_run_type("REFERENCE_PREVIEW") is RunType.REFERENCE_PREVIEW
        assert normalize_run_type("garbage") is None
        assert normalize_run_type(None) is None


# ---------------------------------------------------------------------------
# 2. 持久化一致性
# ---------------------------------------------------------------------------


class TestModelTracksDomainEnums:
    def test_column_defaults_track_domain_enums(self) -> None:
        """模型的默认值必须来自领域枚举，不能各处硬编码字面量。"""
        fields = ExperimentRun.model_fields
        assert fields["run_state"].default == RunState.QUEUED.value
        assert fields["run_type"].default == DEFAULT_RUN_TYPE == RunType.SUBMISSION.value

    def test_run_outcome_is_untouched(self) -> None:
        """兼容承诺：RunOutcome 成员一个不改，既有读取方不受影响。"""
        assert {m.value for m in RunOutcome} == {
            "pending",
            "accepted",
            "wrong_answer",
            "time_limit_exceeded",
            "memory_limit_exceeded",
            "runtime_error",
            "compilation_error",
            "internal_error",
            "sandbox_unavailable",
        }


class TestRunStateIsKeptInSync:
    def test_new_run_defaults_to_queued_submission(self, session: Session) -> None:
        course, student = _fixture_course(session)
        run = _run(session, course_id=course.id, student_id=student.id)
        assert run.run_state == RunState.QUEUED.value
        assert run.run_type == RunType.SUBMISSION.value

    def test_outcome_update_recomputes_state(self, session: Session) -> None:
        """直接改 outcome 的 11 处业务代码无需各自补写 run_state。"""
        course, student = _fixture_course(session)
        run = _run(session, course_id=course.id, student_id=student.id)

        run.outcome = RunOutcome.WRONG_ANSWER
        session.add(run)
        session.commit()
        session.refresh(run)
        assert run.run_state == RunState.FINISHED.value

    def test_system_failure_marks_system_error(self, session: Session) -> None:
        course, student = _fixture_course(session)
        run = _run(session, course_id=course.id, student_id=student.id)

        run.outcome = RunOutcome.SANDBOX_UNAVAILABLE
        session.add(run)
        session.commit()
        session.refresh(run)
        assert run.run_state == RunState.SYSTEM_ERROR.value

    def test_cancel_request_derives_cancelled(self, session: Session) -> None:
        course, student = _fixture_course(session)
        run = _run(session, course_id=course.id, student_id=student.id)

        run.cancel_requested_at = utcnow_aware()
        session.add(run)
        session.commit()
        session.refresh(run)
        assert run.run_state == RunState.CANCELLED.value

    def test_explicit_running_is_not_clobbered(self, session: Session) -> None:
        """编排层显式声明「正在判题」时，监听器不得用 outcome(PENDING) 压回 queued。

        这是 PR-04 的前置约定：那时 run 会先置 RUNNING 再写 outcome。
        """
        course, student = _fixture_course(session)
        run = _run(session, course_id=course.id, student_id=student.id)

        run.run_state = RunState.RUNNING.value
        session.add(run)
        session.commit()
        session.refresh(run)
        assert run.run_state == RunState.RUNNING.value

    def test_finalising_a_running_run_lands_on_finished(self, session: Session) -> None:
        """RUNNING 只是「暂留」：一旦有了结论，状态必须跟着结论走。"""
        course, student = _fixture_course(session)
        run = _run(session, course_id=course.id, student_id=student.id)

        run.run_state = RunState.RUNNING.value
        session.add(run)
        session.commit()

        run.outcome = RunOutcome.ACCEPTED
        session.add(run)
        session.commit()
        session.refresh(run)
        assert run.run_state == RunState.FINISHED.value


# ---------------------------------------------------------------------------
# 3. 迁移与响应体约束
# ---------------------------------------------------------------------------


class TestMigrationApplied:
    def test_columns_exist_in_migrated_schema(self, test_engine) -> None:
        """测试库由 alembic upgrade head 建（conftest），因此这里验证的是迁移本身。"""
        columns = {
            item["name"]: item for item in sa.inspect(test_engine).get_columns("experiment_runs")
        }
        assert "run_state" in columns
        assert "run_type" in columns
        assert columns["run_state"]["nullable"] is False
        assert columns["run_type"]["nullable"] is False

    def test_indexes_exist_in_migrated_schema(self, test_engine) -> None:
        indexes = {
            item["name"] for item in sa.inspect(test_engine).get_indexes("experiment_runs")
        }
        assert "ix_experiment_runs_run_state" in indexes
        assert "ix_experiment_runs_run_type" in indexes

    def test_migration_is_recorded_in_ledger(self, session: Session) -> None:
        """项目约定：每个迁移批次写入 schema_migration_records 审计台账。"""
        rows = session.exec(
            sa.text(
                "SELECT batch_id, status FROM schema_migration_records "
                "WHERE batch_id = 'oj_run_semantics_v1'"
            )
        ).all()
        assert rows, "迁移未写入 schema_migration_records 台账"
        assert rows[0][1] == "applied"


class TestResponseShapeUnchanged:
    def test_serialize_run_does_not_expose_new_columns(self, session: Session) -> None:
        """PR-01 的 DoD：响应体逐字节不变，新列只在库内，不进 API。

        `_serialize_run` 是逐字段显式拼装的，所以新列不会自动泄漏；
        这条用例把「不泄漏」变成受保护的约束，而不只是当前事实。
        """
        from app.api.v1.endpoints.experiments import _serialize_run

        course, student = _fixture_course(session)
        run = _run(session, course_id=course.id, student_id=student.id)

        payload = _serialize_run(run)
        assert "run_state" not in payload
        assert "run_type" not in payload
        # 旧字段仍在，且 outcome 仍以小写 .value 暴露
        assert payload["outcome"] == "pending"


# ---------------------------------------------------------------------------
# 4. 迁移回填（最高风险路径）
# ---------------------------------------------------------------------------


class TestMigrationBackfill:
    """验证 `oj20260911v1` 的历史行回填。

    为什么单独立组：回填是 PR-01 唯一会**改写既有数据**的步骤，而且写错了不会报错 ——
    `outcome` 是 PG 原生 enum（类型名 ``runoutcome``），库里存的是**大写成员名**，
    若按小写 ``.value`` 比较，``WHERE`` 一行都不匹配，全部历史 run 静默留成 ``queued``，
    表现为「所有旧提交看起来都没判完」。这条只能靠带数据的真实迁移往返来测。

    既有测试库里 `experiment_runs` 是空的，所以 `applied_rows=0`，覆盖不到这里。

    数据库路径放在工作区内的 ``backend/.pytest_tmp/``（与 `conftest.py` 的
    `_TEST_TMP_PARENT` 同一约定），**不用 pytest 的 `tmp_path`** ——
    本机沙箱会拒绝写 ``%TEMP%\\pytest-of-*``（`PermissionError [WinError 5]`），
    表现为 setup ERROR。仓库既有测试本身也刻意避开了 `tmp_path`。
    """

    @staticmethod
    def _db_path(name: str) -> str:
        """每次调用给一个**唯一**文件名。

        为什么不用固定名：`run_alembic` 起的 alembic engine 在 Windows 上不会立刻
        释放文件句柄，固定文件名会被上一次运行（或同批次里被 kill 掉的会话）留下的
        `.db` / `-journal` 锁住，表现为「单跑绿、合跑红」的 flaky。
        （实测：本组曾在与 `test_experiments.py` 同批运行时偶发一条失败。）
        """
        root = Path.cwd() / ".pytest_tmp" / "oj_run_semantics"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{name}-{uuid.uuid4().hex[:8]}.db"
        path.unlink(missing_ok=True)
        return path.as_posix()

    @staticmethod
    def _seed(db_path: str) -> None:
        """按 DB 实际存储形式（大写成员名）造行，覆盖回填的每个分支。"""
        engine = sa.create_engine(f"sqlite:///{db_path}")
        rows = [
            ("run_pending", "PENDING", None),
            ("run_pending_cancelled", "PENDING", "2026-09-11 00:00:00"),
            ("run_sandbox_unavailable", "SANDBOX_UNAVAILABLE", None),
            ("run_internal_error", "INTERNAL_ERROR", None),
            ("run_accepted", "ACCEPTED", None),
            ("run_wrong_answer", "WRONG_ANSWER", None),
        ]
        with engine.begin() as conn:
            for run_id, outcome, cancel_requested_at in rows:
                conn.execute(
                    sa.text(
                        "INSERT INTO experiment_runs "
                        "(run_id, attempt_id, course_id, student_id, language, source_code, "
                        " outcome, passed_count, total_count, compile_ok, compile_message, "
                        " runtime_message, error_code, error_message, submitted_at, "
                        " cancel_requested_at) "
                        "VALUES (:run_id, 'a', 1, 1, 'python3', 'x', :outcome, 0, 0, 1, '', "
                        " '', '', '', '2026-09-11 00:00:00', :cancel)"
                    ),
                    {"run_id": run_id, "outcome": outcome, "cancel": cancel_requested_at},
                )
        engine.dispose()

    @staticmethod
    def _states(db_path: str) -> dict[str, str]:
        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            result = dict(
                conn.execute(sa.text("SELECT run_id, run_state FROM experiment_runs")).all()
            )
        engine.dispose()
        return result

    def test_backfill_maps_every_outcome_branch(self, run_alembic) -> None:
        db_path = self._db_path("backfill_branches")

        run_alembic(db_path, "upgrade", "head")
        # 先退回前一版（此时还没有 run_state 列），再造历史数据 ——
        # 这样数据一定经过回填路径，而不是直接落到列默认值上。
        run_alembic(db_path, "downgrade", "dk20260909v5")
        self._seed(db_path)
        run_alembic(db_path, "upgrade", "head")

        states = self._states(db_path)
        assert states == {
            "run_pending": "queued",
            "run_pending_cancelled": "cancelled",
            "run_sandbox_unavailable": "system_error",
            "run_internal_error": "system_error",
            "run_accepted": "finished",
            "run_wrong_answer": "finished",
        }

    def test_backfill_sets_submission_for_every_historical_row(self, run_alembic) -> None:
        """参考解预览不创建 ExperimentRun 行，所以历史行全部是学生提交。"""
        db_path = self._db_path("backfill_run_type")

        run_alembic(db_path, "upgrade", "head")
        run_alembic(db_path, "downgrade", "dk20260909v5")
        self._seed(db_path)
        run_alembic(db_path, "upgrade", "head")

        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            types = {row[0] for row in conn.execute(sa.text("SELECT DISTINCT run_type FROM experiment_runs"))}
        engine.dispose()
        assert types == {"submission"}

    def test_downgrade_drops_columns_and_keeps_rows(self, run_alembic) -> None:
        """回退必须无损：删列时不能连带丢数据（SQLite 走 batch 重建表，是真会丢的那种）。"""
        db_path = self._db_path("downgrade_keeps_rows")

        run_alembic(db_path, "upgrade", "head")
        run_alembic(db_path, "downgrade", "dk20260909v5")
        self._seed(db_path)
        run_alembic(db_path, "upgrade", "head")
        run_alembic(db_path, "downgrade", "dk20260909v5")

        engine = sa.create_engine(f"sqlite:///{db_path}")
        columns = {item["name"] for item in sa.inspect(engine).get_columns("experiment_runs")}
        with engine.connect() as conn:
            remaining = conn.execute(sa.text("SELECT COUNT(*) FROM experiment_runs")).scalar()
        engine.dispose()

        assert "run_state" not in columns
        assert "run_type" not in columns
        assert remaining == 6


# ---------------------------------------------------------------------------
# 5. 判定 → test_summary reason 词汇（PR-05 搬入判题域）
# ---------------------------------------------------------------------------


class TestReasonVocabulary:
    """``REASON_BY_STATUS`` / ``reason_for_status()`` 的契约。

    这段映射原先手写在 ``services/experiment_service.py::_outcome_to_reason`` 里
    （10 条分支），PR-05 搬进判题域。它的输出会进
    ``ExperimentRun.test_summary[].reason`` 并出现在 API 响应里，
    所以**必须逐条锁住**——搬错一个分支就是静默改掉学生看到的反馈。

    特别注意 ``ACCEPTED`` 的 reason 是 ``"passed"`` 而**不是** ``"accepted"``：
    reason 词汇与 ``RunVerdict`` 的值域不是同一套，别顺手统一。
    """

    @staticmethod
    def _submission_status():
        from app.domain.oj.judging.providers.judge0 import SubmissionStatus

        return SubmissionStatus

    def test_every_submission_status_has_a_reason(self) -> None:
        for status in self._submission_status():
            reason = reason_for_status(status)
            assert reason != UNKNOWN_REASON, f"{status} 落到了 unknown"

    def test_reason_table_matches_the_original_service_behaviour(self) -> None:
        """逐条对照搬迁前那张表 —— 这是「搬家不改行为」的唯一判据。"""
        S = self._submission_status()
        expected = {
            S.ACCEPTED: "passed",
            S.WRONG_ANSWER: "wrong_answer",
            S.TIME_LIMIT_EXCEEDED: "time_limit_exceeded",
            S.MEMORY_LIMIT_EXCEEDED: "memory_limit_exceeded",
            S.RUNTIME_ERROR: "runtime_error",
            S.COMPILATION_ERROR: "compilation_error",
            S.INTERNAL_ERROR: "internal_error",
            S.IN_QUEUE: "pending",
            S.PROCESSING: "pending",
            S.SANDBOX_UNAVAILABLE: "sandbox_unavailable",
        }
        for status, reason in expected.items():
            assert reason_for_status(status) == reason, f"{status} 的 reason 变了"

    def test_both_queue_states_map_to_pending(self) -> None:
        """``IN_QUEUE`` 与 ``PROCESSING`` 都映射到 ``pending``，不能拆成两个词。"""
        S = self._submission_status()
        assert reason_for_status(S.IN_QUEUE) == reason_for_status(S.PROCESSING) == "pending"

    def test_accepts_raw_strings_and_member_names(self) -> None:
        """域层不 import provider，所以要能吃裸值；DB 层给的是大写成员名。"""
        assert reason_for_status("accepted") == "passed"
        assert reason_for_status("ACCEPTED") == "passed"
        assert reason_for_status("sandbox_unavailable") == "sandbox_unavailable"

    def test_unknown_values_degrade_to_unknown(self) -> None:
        for bad in (None, "", "not_a_status", 123):
            assert reason_for_status(bad) == UNKNOWN_REASON

    def test_vocabulary_is_distinct_from_run_verdict_values(self) -> None:
        """``ACCEPTED`` 的 reason 是 ``passed``，不是 ``accepted`` —— 两套词汇，别合并。"""
        assert reason_for_status("accepted") != RunVerdict.ACCEPTED.value
