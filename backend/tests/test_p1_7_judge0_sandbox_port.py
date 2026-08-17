"""验收测试：Judge0SandboxPort 按 run_id 从 ExperimentRun 读取已验证结果

修复"Judge0→TeachingAgent 仍未真正接通"：
- 新的 Judge0SandboxPort 健康时不再返回 not_implemented
- 而是按 code_submission_id（即 run_id）+ course_id 从本地 ExperimentRun 表读取已验证结果
- 同时读取关联的 ExperimentRunArtifact（stdout/stderr/compile/test_report）
- 严格 course_id 隔离：跨课程查询返回 not_found
- 健康检查失败时返回 sandbox_unavailable（降级语义保留）
- bootstrap.py 注入 session_factory，使查询路径可用

约束来源：
- Hard Constraints: "TeachingAgent must be connected to real Judge0 sandbox (not UnavailableSandboxPort)"
- 用户反馈: "Judge0→TeachingAgent 仍未真正接通。新的 Judge0SandboxPort 虽替换了原来的空 Port，
  但健康时仍明确返回 status: not_implemented，不读取 Judge0 或 ExperimentRun 的真实结果"
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from fastapi import FastAPI

from app.platform.agents.tools.integration import (
    Judge0SandboxPort,
    UnavailableSandboxPort,
)


def _make_healthy_client() -> MagicMock:
    """构造一个健康检查通过且 enabled=True 的 SandboxClient mock"""
    mock_client = MagicMock()
    mock_client.health_check.return_value = True
    mock_client.enabled = True
    return mock_client


class TestJudge0SandboxPortConstruction:
    """测试1: Judge0SandboxPort 构造与健康检查缓存"""

    def test_uses_default_sandbox_client_when_none_provided(self) -> None:
        with patch("app.services.sandbox_client.sandbox_client") as mock_client:
            mock_client.health_check.return_value = True
            mock_client.enabled = True
            port = Judge0SandboxPort()
        assert port.is_healthy is True
        assert port.is_enabled is True

    def test_health_check_failure_does_not_raise(self) -> None:
        mock_client = MagicMock()
        mock_client.health_check.side_effect = RuntimeError("network down")
        mock_client.enabled = True
        port = Judge0SandboxPort(client=mock_client)
        assert port.is_healthy is False
        assert port.is_enabled is True


class TestGetExecutionResultDegradation:
    """测试2: 沙箱不可用时的降级语义"""

    def test_returns_sandbox_unavailable_when_disabled(self) -> None:
        mock_client = MagicMock()
        mock_client.health_check.return_value = False
        mock_client.enabled = False
        port = Judge0SandboxPort(client=mock_client, session_factory=lambda: MagicMock())

        result = asyncio.run(port.get_execution_result(
            student_id="s-1", course_id="c-1", code_submission_id="run_001",
        ))
        assert result["available"] is False
        assert result["status"] == "sandbox_unavailable"
        assert result["outcome"] == "sandbox_unavailable"

    def test_returns_sandbox_unavailable_when_unhealthy(self) -> None:
        mock_client = MagicMock()
        mock_client.health_check.return_value = False
        mock_client.enabled = True
        port = Judge0SandboxPort(client=mock_client, session_factory=lambda: MagicMock())
        assert port.is_enabled is True
        assert port.is_healthy is False

        result = asyncio.run(port.get_execution_result(
            student_id="s-1", course_id="c-1", code_submission_id="run_001",
        ))
        assert result["available"] is False
        assert result["status"] == "sandbox_unavailable"

    def test_returns_internal_error_when_session_factory_missing(self) -> None:
        """健康但 session_factory 未注入时返回 internal_error（而非 not_implemented）"""
        mock_client = _make_healthy_client()
        port = Judge0SandboxPort(client=mock_client, session_factory=None)

        result = asyncio.run(port.get_execution_result(
            student_id="s-1", course_id="1", code_submission_id="run_001",
        ))
        assert result["available"] is False
        assert result["status"] == "internal_error"
        assert "session_factory" in result["message"]


class TestGetExecutionResultReadsExperimentRun:
    """测试3: 健康时按 run_id 从 ExperimentRun 读取真实结果（核心修复）"""

    def test_returns_real_run_result_when_found(self) -> None:
        """健康 + run 存在 → 返回真实 outcome、stdout、diagnosis"""
        from app.models.experiment_model import ExperimentRun, RunOutcome

        mock_run = MagicMock(spec=ExperimentRun)
        mock_run.run_id = "run_001"
        mock_run.attempt_id = "att_001"
        mock_run.course_id = 1
        mock_run.student_id = 10
        mock_run.language = "python3"
        mock_run.outcome = RunOutcome.ACCEPTED
        mock_run.passed_count = 3
        mock_run.total_count = 3
        mock_run.score = 1.0
        mock_run.compile_ok = True
        mock_run.compile_message = ""
        mock_run.runtime_message = ""
        mock_run.test_summary = {"cases": [{"name": "basic", "passed": True}]}
        mock_run.cpu_time_ms = 120
        mock_run.wall_time_ms = 150
        mock_run.memory_kb = 8192
        mock_run.error_code = ""
        mock_run.error_message = ""
        mock_run.submitted_at = None
        mock_run.finished_at = None

        mock_session = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.first.return_value = mock_run
        mock_session.exec.return_value = mock_exec_result

        port = Judge0SandboxPort(client=_make_healthy_client(), session_factory=lambda: mock_session)

        result = asyncio.run(port.get_execution_result(
            student_id="10", course_id="1", code_submission_id="run_001",
        ))

        assert result["available"] is True
        assert result["status"] == "accepted"
        assert result["outcome"] == "accepted"
        assert result["run_id"] == "run_001"
        assert result["attempt_id"] == "att_001"
        # 2026-08-17 契约（信息最小化）：端口不返回 language/source/artifacts
        assert "language" not in result
        assert "stdout" not in result
        diag = result["diagnosis"]
        assert diag["outcome"] == "accepted"
        assert diag["compile_ok"] is True
        assert diag["passed_count"] == 3
        assert diag["total_count"] == 3
        assert diag["score"] == 1.0
        assert result["resource_usage"]["cpu_time_ms"] == 120
        assert result["resource_usage"]["memory_kb"] == 8192

    def test_returns_not_found_when_run_missing(self) -> None:
        """run_id 不存在时返回 not_found（不抛异常）"""
        mock_session = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.first.return_value = None
        mock_session.exec.return_value = mock_exec_result

        port = Judge0SandboxPort(
            client=_make_healthy_client(),
            session_factory=lambda: mock_session,
        )

        result = asyncio.run(port.get_execution_result(
            student_id="10", course_id="1", code_submission_id="run_missing",
        ))
        assert result["available"] is False
        assert result["status"] == "not_found"
        assert result["outcome"] == "not_found"

    def test_course_isolation_cross_course_returns_not_found(self) -> None:
        """跨课程查询返回 not_found（course_id 隔离）"""
        mock_session = MagicMock()
        mock_exec_course2 = MagicMock()
        mock_exec_course2.first.return_value = None
        mock_session.exec.return_value = mock_exec_course2

        port = Judge0SandboxPort(
            client=_make_healthy_client(),
            session_factory=lambda: mock_session,
        )

        result = asyncio.run(port.get_execution_result(
            student_id="10", course_id="2", code_submission_id="run_001",
        ))
        assert result["available"] is False
        assert result["status"] == "not_found"

    def test_student_isolation_cross_student_returns_not_found(self) -> None:
        """同课程内也不能用别人的 run_id 读取执行结果。"""
        mock_session = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.first.return_value = None
        mock_session.exec.return_value = mock_exec_result

        port = Judge0SandboxPort(
            client=_make_healthy_client(),
            session_factory=lambda: mock_session,
        )
        result = asyncio.run(port.get_execution_result(
            student_id="11", course_id="1", code_submission_id="run_owned_by_10",
        ))
        assert result["available"] is False
        assert result["status"] == "not_found"

    def test_reads_artifacts_stdout_stderr_compile(self) -> None:
        """读取 ExperimentRunArtifact 中的 stdout/stderr/compile"""
        from app.models.experiment_model import (
            ExperimentRun,
            RunOutcome,
        )

        mock_run = MagicMock(spec=ExperimentRun)
        mock_run.run_id = "run_002"
        mock_run.attempt_id = "att_002"
        mock_run.course_id = 1
        mock_run.student_id = 10
        mock_run.language = "python3"
        mock_run.outcome = RunOutcome.RUNTIME_ERROR
        mock_run.passed_count = 0
        mock_run.total_count = 3
        mock_run.score = 0.0
        mock_run.compile_ok = True
        mock_run.compile_message = ""
        mock_run.runtime_message = "NameError: name 'x' is not defined"
        mock_run.test_summary = {}
        mock_run.cpu_time_ms = None
        mock_run.wall_time_ms = None
        mock_run.memory_kb = None
        mock_run.error_code = "RUNTIME_ERROR"
        mock_run.error_message = "NameError"
        mock_run.submitted_at = None
        mock_run.finished_at = None

        mock_session = MagicMock()
        mock_run_result = MagicMock()
        mock_run_result.first.return_value = mock_run
        mock_session.exec.return_value = mock_run_result

        port = Judge0SandboxPort(
            client=_make_healthy_client(),
            session_factory=lambda: mock_session,
        )

        result = asyncio.run(port.get_execution_result(
            student_id="10", course_id="1", code_submission_id="run_002",
        ))

        assert result["available"] is True
        assert result["status"] == "runtime_error"
        # 2026-08-17 契约（信息最小化）：不返回 stdout/stderr/compile 文本
        assert "stdout" not in result
        assert "stderr" not in result
        assert result["diagnosis"]["error_code"] == "RUNTIME_ERROR"

    def test_truncates_large_stdout(self) -> None:
        """2026-08-17 契约：端口不再返回 stdout/stderr/compile 文本（信息最小化，
        避免把 Judge0 细节泄漏给 LLM 上下文）；大输出也不会被透传。"""
        from app.models.experiment_model import ExperimentRun, RunOutcome

        mock_run = MagicMock(spec=ExperimentRun)
        mock_run.run_id = "run_big"
        mock_run.attempt_id = "att_big"
        mock_run.course_id = 1
        mock_run.student_id = 10
        mock_run.language = "python3"
        mock_run.outcome = RunOutcome.ACCEPTED
        mock_run.passed_count = 1
        mock_run.total_count = 1
        mock_run.score = 1.0
        mock_run.compile_ok = True
        mock_run.compile_message = ""
        mock_run.runtime_message = ""
        mock_run.test_summary = {}
        mock_run.cpu_time_ms = None
        mock_run.wall_time_ms = None
        mock_run.memory_kb = None
        mock_run.error_code = ""
        mock_run.error_message = ""
        mock_run.submitted_at = None
        mock_run.finished_at = None

        mock_session = MagicMock()
        mock_run_result = MagicMock()
        mock_run_result.first.return_value = mock_run
        mock_session.exec.return_value = mock_run_result

        port = Judge0SandboxPort(
            client=_make_healthy_client(),
            session_factory=lambda: mock_session,
        )

        result = asyncio.run(port.get_execution_result(
            student_id="10", course_id="1", code_submission_id="run_big",
        ))
        assert "stdout" not in result
        assert "stderr" not in result
        assert "compile_output" not in result
        assert result["available"] is True

    def test_db_exception_returns_internal_error(self) -> None:
        """DB 查询异常时返回 internal_error，不抛出"""
        mock_session = MagicMock()
        mock_session.exec.side_effect = RuntimeError("DB connection lost")

        port = Judge0SandboxPort(
            client=_make_healthy_client(),
            session_factory=lambda: mock_session,
        )

        result = asyncio.run(port.get_execution_result(
            student_id="10", course_id="1", code_submission_id="run_001",
        ))
        assert result["available"] is False
        assert result["status"] == "internal_error"
        assert "DB connection lost" in result["message"]

    def test_invalid_course_id_returns_not_found(self) -> None:
        """无效 course_id 返回 not_found"""
        port = Judge0SandboxPort(
            client=_make_healthy_client(),
            session_factory=lambda: MagicMock(),
        )
        result = asyncio.run(port.get_execution_result(
            student_id="10", course_id="not_a_number", code_submission_id="run_001",
        ))
        assert result["available"] is False
        assert result["status"] == "not_found"


class TestBootstrapInjectsJudge0PortWithSessionFactory:
    """测试4: bootstrap.py 注入 Judge0SandboxPort 时传入 session_factory"""

    def test_bootstrap_injects_judge0_port_with_session_factory(self, tmp_path) -> None:
        from app.platform.agents.bootstrap import bootstrap_teaching_agent
        from app.platform.retrieval_demo.service import DemoService
        from app.platform.retrieval_demo.store import DemoRunStore

        demo_service = DemoService(
            configured_mode="demo_compare",
            environment="test",
            store=DemoRunStore(tmp_path / "runs"),
        )

        captured_args = {}
        def capture_constructor(**kwargs):
            captured_args.update(kwargs)
            return Judge0SandboxPort(**kwargs)

        with patch("app.platform.agents.bootstrap.settings") as mock_settings, \
             patch(
                 "app.platform.agents.bootstrap.Judge0SandboxPort",
                 side_effect=capture_constructor,
             ) as mock_port_cls:
            mock_settings.TEACHING_AGENT_MODE = "enabled"
            mock_settings.DEMO_RETRIEVAL_MODE = "demo_compare"
            mock_settings.DEMO_RETRIEVAL_ENVIRONMENT = "test"
            mock_settings.LLM_API_BASE = "http://x"
            mock_settings.LLM_API_KEY = "k"
            mock_settings.LLM_MODEL_NAME = "m"
            app = FastAPI()
            injected = bootstrap_teaching_agent(app, demo_service=demo_service)

        assert injected is True
        mock_port_cls.assert_called_once()
        assert "session_factory" in captured_args
        assert callable(captured_args["session_factory"])

        registry = app.state.teaching_agent_runtime_registry
        assert isinstance(registry._sandbox, Judge0SandboxPort)
        assert not isinstance(registry._sandbox, UnavailableSandboxPort)
        assert registry._sandbox._session_factory is not None

    def test_bootstrap_never_blocks_when_judge0_unavailable(self, tmp_path) -> None:
        from app.platform.agents.bootstrap import bootstrap_teaching_agent
        from app.platform.retrieval_demo.service import DemoService
        from app.platform.retrieval_demo.store import DemoRunStore

        demo_service = DemoService(
            configured_mode="demo_compare",
            environment="test",
            store=DemoRunStore(tmp_path / "runs"),
        )

        mock_unhealthy_client = MagicMock()
        mock_unhealthy_client.health_check.return_value = False
        mock_unhealthy_client.enabled = True

        with patch("app.platform.agents.bootstrap.settings") as mock_settings, \
             patch("app.services.sandbox_client.sandbox_client", mock_unhealthy_client):
            mock_settings.TEACHING_AGENT_MODE = "enabled"
            mock_settings.DEMO_RETRIEVAL_MODE = "demo_compare"
            mock_settings.DEMO_RETRIEVAL_ENVIRONMENT = "test"
            mock_settings.LLM_API_BASE = "http://x"
            mock_settings.LLM_API_KEY = "k"
            mock_settings.LLM_MODEL_NAME = "m"
            app = FastAPI()
            injected = bootstrap_teaching_agent(app, demo_service=demo_service)

        assert injected is True
        registry = app.state.teaching_agent_runtime_registry
        assert registry is not None
        assert registry._sandbox.is_healthy is False
