"""阶段9 工具治理端口实现。

读取 agent_tool_policies 表，按 course_id 严格隔离；
被教师禁用的工具在 workflow 节点前跳过；
工具调用审计写入 agent_tool_invocations 表。

设计要点：
- 仅存结构化摘要，绝不存 raw message/answer/prompt
- 端口本身无状态；每次调用打开新 session（请求级）
- 失败保留原始 error_code，不伪装成功
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from sqlmodel import Session

from app.models.database import engine
from app.services.agent_governance_service import agent_governance_service

logger = logging.getLogger(__name__)

# P1-E5: 高风险工具集合；治理服务异常时对这类工具 fail-closed（默认禁用/强制确认），
# 避免治理端口故障导致 web_research 等高风险动作默认放行。
HIGH_RISK_TOOLS: frozenset[str] = frozenset({
    "web_research", "trigger_experiment", "change_topic",
})


def make_session_scoped_tool_governance_port(session_factory: Callable[[], Session]):
    """构造一个 session 作用域的 ToolGovernancePort 实现。

    session_factory 通常为 `lambda: Session(engine)`。
    """

    class SessionScopedToolGovernancePort:
        async def is_tool_enabled(self, *, course_id: str, tool_name: str) -> bool:
            try:
                course_id_int = int(course_id)
            except (TypeError, ValueError):
                return True  # 课程 ID 无效时不阻断；端点层已做校验
            session = session_factory()
            try:
                return agent_governance_service.is_tool_enabled(
                    session, course_id=course_id_int, tool_name=tool_name,
                )
            except Exception as error:  # noqa: BLE001
                logger.warning("ToolGovernance.is_tool_enabled failed: %s: %s", type(error).__name__, error)
                # P1-E5: 高风险工具 fail-closed（禁用），低风险工具 fail-open（放行）
                if tool_name in HIGH_RISK_TOOLS:
                    return False
                return True
            finally:
                session.close()

        async def requires_confirmation(self, *, course_id: str, tool_name: str) -> Mapping[str, Any]:
            try:
                course_id_int = int(course_id)
            except (TypeError, ValueError):
                return {"require_confirmation": False, "threshold": "never"}
            session = session_factory()
            try:
                require, threshold = agent_governance_service.requires_confirmation(
                    session, course_id=course_id_int, tool_name=tool_name,
                )
                return {"require_confirmation": require, "threshold": threshold}
            except Exception as error:  # noqa: BLE001
                logger.warning("ToolGovernance.requires_confirmation failed: %s: %s", type(error).__name__, error)
                # P1-E5: 高风险工具 fail-closed（强制确认），低风险工具 fail-open
                if tool_name in HIGH_RISK_TOOLS:
                    return {"require_confirmation": True, "threshold": "always"}
                return {"require_confirmation": False, "threshold": "never"}
            finally:
                session.close()

        async def record_invocation(
            self,
            *,
            course_id: str,
            student_id: str,
            trace_id: str,
            tool_name: str,
            input_summary: Mapping[str, Any],
            output_summary: Mapping[str, Any],
            duration_ms: int | None = None,
            degraded: bool = False,
            degraded_reason: str = "",
            allowed_by_policy: bool = True,
        ) -> None:
            try:
                course_id_int = int(course_id)
                student_id_int = int(student_id)
            except (TypeError, ValueError):
                return  # ID 无效时跳过审计记录
            session = session_factory()
            try:
                agent_governance_service.record_tool_invocation(
                    session,
                    course_id=course_id_int,
                    student_id=student_id_int,
                    trace_id=trace_id,
                    tool_name=tool_name,
                    input_summary=dict(input_summary),
                    output_summary=dict(output_summary),
                    duration_ms=duration_ms,
                    degraded=degraded,
                    degraded_reason=degraded_reason,
                    allowed_by_policy=allowed_by_policy,
                )
                session.commit()
            except Exception as error:  # noqa: BLE001 -- 审计失败不阻断主流程
                logger.warning("ToolGovernance.record_invocation failed: %s: %s", type(error).__name__, error)
                session.rollback()
            finally:
                session.close()

    return SessionScopedToolGovernancePort()
