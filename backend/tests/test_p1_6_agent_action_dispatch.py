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
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.platform.tasks.handlers import (
    _dispatch_agent_action,
    _dispatch_trigger_experiment,
    _dispatch_web_research,
)
from app.models.access_control_model import CourseCapability
from app.models.agent_governance_model import AgentActionProposal
from app.models.course_model import Course, CourseStatus
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentRecommendation,
    ExperimentRun,
    ExperimentVersion,
)
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from sqlmodel import select


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

    @staticmethod
    def _session_factory(session):
        @contextmanager
        def factory():
            yield session
        return factory

    @staticmethod
    def _recommendable_experiment(session, teacher_user, student_user):
        course = Course(
            fanya_course_id=f"dispatch-{teacher_user.id}-{student_user.id}",
            fanya_course_name="Dispatch course",
            title="Dispatch course",
            teacher_id=teacher_user.id,
            status=CourseStatus.PUBLISHED,
        )
        session.add(course)
        session.flush()
        establish_course_access_baseline(session, course.id, teacher_user.id)
        activate_student_membership(session, course.id, student_user.id)
        capability = session.exec(select(CourseCapability).where(
            CourseCapability.course_id == course.id,
        )).first()
        capability.experiment = True
        capability.coding_sandbox = True
        definition = ExperimentDefinition(
            course_id=course.id,
            title="Published task",
            language_whitelist=["python3"],
            knowledge_node_ids=[7],
            publish_status=ExperimentPublishStatus.PUBLISHED,
            created_by=teacher_user.id,
        )
        session.add(definition)
        session.flush()
        version = ExperimentVersion(
            course_id=course.id,
            experiment_id=definition.experiment_id,
            version_number=1,
            is_active=True,
            is_locked=True,
            created_by=teacher_user.id,
        )
        definition.default_version_id = version.version_id
        session.add(version)
        session.add(definition)
        session.add(capability)
        session.commit()
        return course, definition, version

    @staticmethod
    def _proposal(session, *, course_id, student_id, experiment_id, status="approved", action=None):
        action = action or {"experiment_id": experiment_id, "outline_node_id": "7"}
        proposal = AgentActionProposal(
            proposal_id=f"ap_dispatch_{course_id}_{student_id}_{status}_{experiment_id[-8:]}",
            trace_id="trace-dispatch",
            student_id=student_id,
            course_id=course_id,
            session_id="dispatch-session",
            proposal_type="trigger_experiment",
            tool_name="experiment_dispatch",
            proposed_action=json.dumps(action),
            risk_level="medium",
            requires_confirmation=True,
            status=status,
        )
        session.add(proposal)
        session.commit()
        return proposal

    def test_missing_experiment_id_returns_dispatched_false(self) -> None:
        result = asyncio.run(_dispatch_trigger_experiment(
            course_id=1,
            student_id=10,
            proposed_action={},
            session_factory=MagicMock(),
            decided_by=1,
            proposal_id="ap_missing",
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
            proposal_id="ap_missing_student",
            dispatched_at="2026-07-27T00:00:00",
        ))

        assert result["dispatched"] is False
        assert result["outcome"] == "missing_student_id"

    def test_approved_proposal_creates_one_recommendation_not_attempt_or_run(
        self, session, teacher_user, student_user,
    ) -> None:
        course, definition, version = self._recommendable_experiment(session, teacher_user, student_user)
        proposal = self._proposal(
            session,
            course_id=course.id,
            student_id=student_user.id,
            experiment_id=definition.experiment_id,
        )
        factory = self._session_factory(session)
        action = {"experiment_id": definition.experiment_id, "outline_node_id": "7"}

        first = asyncio.run(_dispatch_trigger_experiment(
            course_id=course.id, student_id=student_user.id, proposed_action=action,
            session_factory=factory, decided_by=teacher_user.id,
            proposal_id=proposal.proposal_id, dispatched_at="2026-08-13T00:00:00+00:00",
        ))
        second = asyncio.run(_dispatch_trigger_experiment(
            course_id=course.id, student_id=student_user.id, proposed_action=action,
            session_factory=factory, decided_by=teacher_user.id,
            proposal_id=proposal.proposal_id, dispatched_at="2026-08-13T00:00:01+00:00",
        ))

        assert first["dispatched"] is True
        assert first["outcome"] == "experiment_recommendation_created"
        assert second["dispatched"] is True
        assert second["outcome"] == "experiment_recommendation_existing"
        recommendations = session.exec(select(ExperimentRecommendation).where(
            ExperimentRecommendation.course_id == course.id,
            ExperimentRecommendation.student_id == student_user.id,
            ExperimentRecommendation.proposal_id == proposal.proposal_id,
        )).all()
        assert len(recommendations) == 1
        assert recommendations[0].version_id == version.version_id
        assert recommendations[0].outline_node_id == "7"
        assert session.exec(select(ExperimentAttempt).where(
            ExperimentAttempt.course_id == course.id,
            ExperimentAttempt.student_id == student_user.id,
        )).all() == []
        assert session.exec(select(ExperimentRun).where(
            ExperimentRun.course_id == course.id,
            ExperimentRun.student_id == student_user.id,
        )).all() == []

    def test_unapproved_proposal_cannot_create_recommendation(
        self, session, teacher_user, student_user,
    ) -> None:
        course, definition, _ = self._recommendable_experiment(session, teacher_user, student_user)
        proposal = self._proposal(
            session, course_id=course.id, student_id=student_user.id,
            experiment_id=definition.experiment_id, status="pending",
        )
        result = asyncio.run(_dispatch_trigger_experiment(
            course_id=course.id, student_id=student_user.id,
            proposed_action={"experiment_id": definition.experiment_id, "outline_node_id": "7"},
            session_factory=self._session_factory(session), decided_by=teacher_user.id,
            proposal_id=proposal.proposal_id, dispatched_at="2026-08-13T00:00:00+00:00",
        ))

        assert result["dispatched"] is False
        assert result["outcome"] == "proposal_not_approved"
        assert session.exec(select(ExperimentRecommendation).where(
            ExperimentRecommendation.course_id == course.id,
            ExperimentRecommendation.student_id == student_user.id,
        )).all() == []
        assert session.exec(select(ExperimentAttempt).where(
            ExperimentAttempt.course_id == course.id,
            ExperimentAttempt.student_id == student_user.id,
        )).all() == []

    def test_code_payload_is_rejected_before_creating_recommendation(
        self, session, teacher_user, student_user,
    ) -> None:
        course, definition, _ = self._recommendable_experiment(session, teacher_user, student_user)
        action = {
            "experiment_id": definition.experiment_id,
            "outline_node_id": "7",
            "source_code": "print('must never run')",
        }
        proposal = self._proposal(
            session, course_id=course.id, student_id=student_user.id,
            experiment_id=definition.experiment_id, action=action,
        )
        result = asyncio.run(_dispatch_trigger_experiment(
            course_id=course.id, student_id=student_user.id, proposed_action=action,
            session_factory=self._session_factory(session), decided_by=teacher_user.id,
            proposal_id=proposal.proposal_id, dispatched_at="2026-08-13T00:00:00+00:00",
        ))

        assert result["dispatched"] is False
        assert result["outcome"] == "invalid_trigger_payload"
        assert session.exec(select(ExperimentRecommendation).where(
            ExperimentRecommendation.course_id == course.id,
            ExperimentRecommendation.student_id == student_user.id,
        )).all() == []
        assert session.exec(select(ExperimentAttempt).where(
            ExperimentAttempt.course_id == course.id,
            ExperimentAttempt.student_id == student_user.id,
        )).all() == []


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
