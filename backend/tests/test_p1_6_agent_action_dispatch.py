"""P1-6 教师批准后执行高风险动作并设 dispatched:true 验证测试

验证内容：
1. web_research 派发到 web_research_service.execute_research，dispatched=True
2. trigger_experiment 派发到 experiment_service，创建 attempt + run
3. change_topic 记录派发事件，dispatched=True（UI 消费）
4. 缺少必填字段时返回 dispatched=False 而非抛错
5. 业务异常归一化为 DISPATCH_FAILED，保留原 error_code
6. 未知 proposal_type 返回 dispatched=False, outcome=unknown_type
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.platform.tasks.handlers import (
    _dispatch_agent_action,
    _dispatch_trigger_experiment,
    _dispatch_web_research,
)


def _ctx_factory(session_mock):
    """Build a session_factory mock that yields the given session."""
    factory = MagicMock()
    factory.return_value.__enter__ = MagicMock(return_value=session_mock)
    factory.return_value.__exit__ = MagicMock(return_value=False)
    return factory


class TestChangeTopicDispatch:
    """测试1: change_topic 派发"""

    def test_change_topic_records_dispatched_event(self) -> None:
        result = asyncio.run(_dispatch_agent_action(
            proposal_type="change_topic",
            course_id=1,
            student_id=10,
            proposed_action={"target_topic": "光合作用"},
            session_factory=MagicMock(),
            decided_by=1,
            trace_id="t1",
        ))

        assert result["dispatched"] is True
        assert result["outcome"] == "topic_change_recorded"
        assert result["details"]["target_topic"] == "光合作用"
        assert result["details"]["consumer"] == "frontend_navigation"
        assert result["dispatched_at"] is not None


class TestUnknownProposalType:
    """测试2: 未知 proposal_type"""

    def test_unknown_type_returns_dispatched_false(self) -> None:
        result = asyncio.run(_dispatch_agent_action(
            proposal_type="totally_unknown",
            course_id=1,
            student_id=10,
            proposed_action={},
            session_factory=MagicMock(),
            decided_by=1,
            trace_id="t1",
        ))

        assert result["dispatched"] is False
        assert result["outcome"] == "unknown_type"
        assert result["details"]["proposal_type"] == "totally_unknown"


class TestWebResearchDispatch:
    """测试3: web_research 派发"""

    def test_web_research_dispatches_to_service(self) -> None:
        mock_result = MagicMock()
        mock_result.status = "success"
        mock_result.id = 42

        session = MagicMock()
        factory = _ctx_factory(session)

        with patch(
            "app.platform.tasks.handlers._dispatch_web_research",
            wraps=_dispatch_web_research,
        ) as wrap_mock, patch(
            "app.services.web_research_service.execute_research",
            return_value=mock_result,
        ):
            result = asyncio.run(_dispatch_agent_action(
                proposal_type="web_research",
                course_id=7,
                student_id=10,
                proposed_action={"query": "什么是光合作用"},
                session_factory=factory,
                decided_by=1,
                trace_id="t1",
            ))

        assert result["dispatched"] is True
        assert result["outcome"] == "success"
        assert result["details"]["result_id"] == 42
        assert result["details"]["query"] == "什么是光合作用"
        wrap_mock.assert_called_once()

    def test_web_research_missing_query_returns_validation_error(self) -> None:
        from app.platform.tasks.worker import TaskExecutionError

        session = MagicMock()
        factory = _ctx_factory(session)

        with pytest.raises(TaskExecutionError) as exc_info:
            asyncio.run(_dispatch_agent_action(
                proposal_type="web_research",
                course_id=7,
                student_id=10,
                proposed_action={"query": ""},
                session_factory=factory,
                decided_by=1,
                trace_id="t1",
            ))

        assert exc_info.value.error_code == "VALIDATION_FAILED"
        assert "query" in exc_info.value.message

    def test_web_research_service_exception_becomes_dispatch_failed(self) -> None:
        from app.platform.tasks.worker import TaskExecutionError

        session = MagicMock()
        factory = _ctx_factory(session)

        with patch(
            "app.services.web_research_service.execute_research",
            side_effect=RuntimeError("network timeout"),
        ):
            with pytest.raises(TaskExecutionError) as exc_info:
                asyncio.run(_dispatch_agent_action(
                    proposal_type="web_research",
                    course_id=7,
                    student_id=10,
                    proposed_action={"query": "test"},
                    session_factory=factory,
                    decided_by=1,
                    trace_id="t1",
                ))

        assert exc_info.value.error_code == "WEB_RESEARCH_DISPATCH_FAILED"
        assert "network timeout" in exc_info.value.message
        # retryable=True 因为是网络类异常
        assert exc_info.value.retryable is True


class TestTriggerExperimentDispatch:
    """测试4: trigger_experiment 派发"""

    def test_missing_experiment_id_returns_dispatched_false(self) -> None:
        result = asyncio.run(_dispatch_trigger_experiment(
            course_id=1,
            student_id=10,
            proposed_action={},
            session_factory=MagicMock(),
            decided_by=1,
            dispatched_at="2026-07-27T00:00:00",
        ))

        assert result["dispatched"] is False
        assert result["outcome"] == "missing_experiment_id"

    def test_missing_student_id_returns_dispatched_false(self) -> None:
        result = asyncio.run(_dispatch_trigger_experiment(
            course_id=1,
            student_id=None,
            proposed_action={"experiment_id": "exp_1"},
            session_factory=MagicMock(),
            decided_by=1,
            dispatched_at="2026-07-27T00:00:00",
        ))

        assert result["dispatched"] is False
        assert result["outcome"] == "missing_student_id"

    def test_creates_attempt_only_when_no_code(self) -> None:
        session = MagicMock()
        factory = _ctx_factory(session)

        attempt = MagicMock()
        attempt.attempt_id = "att_001"

        with patch(
            "app.services.experiment_service.attempt_service.create_attempt",
            return_value=attempt,
        ) as mock_create_attempt:
            result = asyncio.run(_dispatch_trigger_experiment(
                course_id=5,
                student_id=20,
                proposed_action={"experiment_id": "exp_1"},
                session_factory=factory,
                decided_by=1,
                dispatched_at="2026-07-27T00:00:00",
            ))

        assert result["dispatched"] is True
        assert result["outcome"] == "experiment_attempt_created"
        assert result["details"]["attempt_id"] == "att_001"
        assert result["details"]["run_id"] is None
        mock_create_attempt.assert_called_once()
        # 验证传入参数
        call_kwargs = mock_create_attempt.call_args.kwargs
        assert call_kwargs["course_id"] == 5
        assert call_kwargs["experiment_id"] == "exp_1"
        assert call_kwargs["student_id"] == 20

    def test_creates_attempt_and_run_when_code_provided(self) -> None:
        session = MagicMock()
        factory = _ctx_factory(session)

        attempt = MagicMock()
        attempt.attempt_id = "att_001"

        run = MagicMock()
        run.run_id = "run_001"

        with patch(
            "app.services.experiment_service.attempt_service.create_attempt",
            return_value=attempt,
        ), patch(
            "app.services.experiment_service.run_service.create_run",
            return_value=run,
        ) as mock_create_run:
            result = asyncio.run(_dispatch_trigger_experiment(
                course_id=5,
                student_id=20,
                proposed_action={
                    "experiment_id": "exp_1",
                    "language": "python",
                    "source_code": "print('hello')",
                },
                session_factory=factory,
                decided_by=1,
                dispatched_at="2026-07-27T00:00:00",
            ))

        assert result["dispatched"] is True
        assert result["outcome"] == "experiment_run_created"
        assert result["details"]["attempt_id"] == "att_001"
        assert result["details"]["run_id"] == "run_001"
        mock_create_run.assert_called_once()
        # 验证 execute=False（异步执行）
        call_kwargs = mock_create_run.call_args.kwargs
        assert call_kwargs["execute"] is False
        assert call_kwargs["language"] == "python"

    def test_service_exception_becomes_dispatch_failed(self) -> None:
        from app.platform.tasks.worker import TaskExecutionError

        session = MagicMock()
        factory = _ctx_factory(session)

        with patch(
            "app.services.experiment_service.attempt_service.create_attempt",
            side_effect=RuntimeError("db locked"),
        ):
            with pytest.raises(TaskExecutionError) as exc_info:
                asyncio.run(_dispatch_trigger_experiment(
                    course_id=5,
                    student_id=20,
                    proposed_action={"experiment_id": "exp_1"},
                    session_factory=factory,
                    decided_by=1,
                    dispatched_at="2026-07-27T00:00:00",
                ))

        assert exc_info.value.error_code == "EXPERIMENT_DISPATCH_FAILED"
        assert "db locked" in exc_info.value.message


class TestDispatchedAtTimestamp:
    """测试5: dispatched_at 时间戳"""

    def test_dispatched_at_is_iso_format(self) -> None:
        result = asyncio.run(_dispatch_agent_action(
            proposal_type="change_topic",
            course_id=1,
            student_id=10,
            proposed_action={"target_topic": "x"},
            session_factory=MagicMock(),
            decided_by=1,
            trace_id="t1",
        ))

        # 应为 ISO 格式字符串
        assert isinstance(result["dispatched_at"], str)
        assert "T" in result["dispatched_at"]
