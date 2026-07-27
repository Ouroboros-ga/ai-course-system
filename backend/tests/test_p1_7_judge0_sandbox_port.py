"""P1-7 验收测试：bootstrap.py 注入真实 Judge0 沙箱 Port（保留健康检查降级）

验证约束：
- bootstrap_teaching_agent 注入 Judge0SandboxPort（而非 UnavailableSandboxPort）
- 健康检查通过：sandbox.is_healthy 为 True，get_execution_result 返回 structured 结果
- 健康检查失败：sandbox.is_healthy 为 False，get_execution_result 返回 sandbox_unavailable
- 沙箱禁用（JUDGE0_ENABLED=False）：每次调用返回 sandbox_unavailable，不抛异常
- Agent/Q&A 主流程在 Judge0 不可用时不中断（降级语义）

约束来源：
- Hard Constraints: "TeachingAgent must be connected to real Judge0 sandbox (not UnavailableSandboxPort)"
- Lessons Learned: "TeachingAgent not connected to Judge0 (bootstrap.py:59)"
- Engineering Conventions: "When JUDGE0_ENABLED=False or sandbox unavailable, SandboxClient returns
  SANDBOX_UNAVAILABLE status (not ACCEPTED) to avoid faking execution"
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.platform.agents.tools.integration import Judge0SandboxPort, UnavailableSandboxPort


class TestJudge0SandboxPortConstruction:
    """测试1: Judge0SandboxPort 构造与健康检查缓存"""

    def test_uses_default_sandbox_client_when_none_provided(self) -> None:
        """未提供 client 时，应使用 module-level singleton"""
        with patch("app.services.sandbox_client.sandbox_client") as mock_client:
            mock_client.health_check.return_value = True
            mock_client.enabled = True
            port = Judge0SandboxPort()
        assert port.is_healthy is True
        assert port.is_enabled is True
        mock_client.health_check.assert_called_once()

    def test_uses_provided_client(self) -> None:
        """提供了 client 时，应直接使用"""
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client.enabled = True
        port = Judge0SandboxPort(client=mock_client)
        assert port.is_healthy is True
        assert port.is_enabled is True

    def test_health_check_failure_does_not_raise(self) -> None:
        """health_check 抛异常时不阻断构造，缓存为 unhealthy"""
        mock_client = MagicMock()
        mock_client.health_check.side_effect = RuntimeError("network down")
        mock_client.enabled = True
        port = Judge0SandboxPort(client=mock_client)
        assert port.is_healthy is False
        # is_enabled 仍反映 client.enabled，与 health 解耦
        assert port.is_enabled is True


class TestJudge0SandboxPortGetExecutionResult:
    """测试2: get_execution_result 降级语义"""

    def test_returns_sandbox_unavailable_when_disabled(self) -> None:
        """JUDGE0_ENABLED=False 时返回 sandbox_unavailable，不抛异常"""
        mock_client = MagicMock()
        mock_client.health_check.return_value = False
        mock_client.enabled = False
        port = Judge0SandboxPort(client=mock_client)

        result = asyncio.run(port.get_execution_result(
            student_id="s-1",
            course_id="c-1",
            code_submission_id="tok_001",
        ))
        assert result["available"] is False
        assert result["status"] == "sandbox_unavailable"
        assert "降级" in result["message"] or "未启用" in result["message"]

    def test_returns_sandbox_unavailable_when_unhealthy(self) -> None:
        """沙箱启用但健康检查失败时返回 sandbox_unavailable"""
        mock_client = MagicMock()
        mock_client.health_check.return_value = False
        mock_client.enabled = True
        port = Judge0SandboxPort(client=mock_client)
        assert port.is_enabled is True
        assert port.is_healthy is False

        result = asyncio.run(port.get_execution_result(
            student_id="s-1",
            course_id="c-1",
            code_submission_id="tok_001",
        ))
        assert result["available"] is False
        assert result["status"] == "sandbox_unavailable"

    def test_returns_structured_result_when_healthy(self) -> None:
        """沙箱健康检查通过时返回 structured 结果（available=True）"""
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_client.enabled = True
        port = Judge0SandboxPort(client=mock_client)

        result = asyncio.run(port.get_execution_result(
            student_id="s-1",
            course_id="c-1",
            code_submission_id="tok_001",
        ))
        assert result["available"] is True
        # 当前实现：Agent 端口只读，按 token 查询尚未实现，返回 not_implemented
        # 这不是伪装成功（status != accepted），调用方知道走 experiment_run_handler
        assert result["status"] == "not_implemented"
        assert result["code_submission_id"] == "tok_001"


class TestBootstrapInjectsJudge0Port:
    """测试3: bootstrap.py 注入 Judge0SandboxPort"""

    def test_bootstrap_injects_judge0_port(self, tmp_path) -> None:
        """bootstrap_teaching_agent 在 gate 全通过时注入 Judge0SandboxPort"""
        from app.platform.agents.bootstrap import bootstrap_teaching_agent
        from app.platform.retrieval_demo.service import DemoService
        from app.platform.retrieval_demo.store import DemoRunStore
        from fastapi import FastAPI

        demo_service = DemoService(
            configured_mode="demo_compare",
            environment="test",
            store=DemoRunStore(tmp_path / "runs"),
        )

        with patch("app.platform.agents.bootstrap.settings") as mock_settings, \
             patch(
                 "app.platform.agents.bootstrap.Judge0SandboxPort",
                 wraps=Judge0SandboxPort,
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
        # 必须调用 Judge0SandboxPort 构造（证明从 UnavailableSandboxPort 切换）
        mock_port_cls.assert_called_once()
        registry = app.state.teaching_agent_runtime_registry
        assert registry is not None
        # 注入的 sandbox 必须是 Judge0SandboxPort 实例，不是 UnavailableSandboxPort
        # registry 使用 _sandbox 私有字段存储
        from app.platform.agents.tools.integration import Judge0SandboxPort as _Port
        assert isinstance(registry._sandbox, _Port)
        assert not isinstance(registry._sandbox, UnavailableSandboxPort)

    def test_bootstrap_never_blocks_when_judge0_unavailable(self, tmp_path) -> None:
        """Judge0 不可用时 bootstrap 仍成功（保持降级语义，不阻断 Agent 注入）"""
        from app.platform.agents.bootstrap import bootstrap_teaching_agent
        from app.platform.retrieval_demo.service import DemoService
        from app.platform.retrieval_demo.store import DemoRunStore
        from fastapi import FastAPI

        demo_service = DemoService(
            configured_mode="demo_compare",
            environment="test",
            store=DemoRunStore(tmp_path / "runs"),
        )

        # 模拟 Judge0 健康检查失败：bootstrap 仍注入 Port，Port 自身降级
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
        # Port 已注入，但 is_healthy=False（降级）
        assert registry._sandbox.is_healthy is False
