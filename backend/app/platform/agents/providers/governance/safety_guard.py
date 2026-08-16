"""Session-scoped SafetyGuardPort provider for the TeachingAgent.

包装 G6 ``evaluate_content_safety``（``safety_guard_service``），把同步的
DB 安全评估转成 async Port 调用，返回与 ``POST /safety/course/{id}/evaluate``
一致的结构化决策（allowed / action / requires_confirmation / reason /
decision_factors / keyword_matched / compliance_reply / policy_version）。

设计要点：
- 按 course_id 严格隔离；无策略或策略未启用（draft/conflict）时评估放行；
- 评估异常时 fail-open（放行并记录 degraded），安全闸门自身故障不得阻断问答主链路；
- 阻断时 compliance_reply 携带预设思政合规文案，工作流直接作为回答返回。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

from sqlmodel import Session

from app.services.safety_guard_service import evaluate_content_safety

logger = logging.getLogger(__name__)


def make_session_scoped_safety_guard_port(session_factory: Callable[[], Session]):
    """构造一个 session 作用域的 SafetyGuardPort 实现。"""

    class SessionScopedSafetyGuardPort:
        async def check_content(
            self,
            *,
            course_id: str,
            user_message: str,
            user_id: Optional[str] = None,
            tool_target: Optional[str] = None,
        ) -> Mapping[str, Any]:
            try:
                course_id_int = int(course_id)
            except (TypeError, ValueError) as error:
                logger.warning("SafetyGuard.check_content invalid course_id: %s", error)
                return {
                    "allowed": True,
                    "action": "allow",
                    "reason": "invalid_course_id_fail_open",
                    "decision_factors": ["invalid_course_id"],
                    "compliance_reply": None,
                    "policy_version": "safety-policy-v2.1",
                }
            session = session_factory()
            try:
                user_id_int = int(user_id) if user_id is not None else None
                decision = evaluate_content_safety(
                    session,
                    course_id_int,
                    user_message,
                    user_id=user_id_int,
                    tool_target=tool_target,
                )
                return {
                    "allowed": decision.allowed,
                    "action": decision.action.value,
                    "requires_confirmation": decision.requires_confirmation,
                    "reason": decision.reason,
                    "decision_factors": list(decision.decision_factors),
                    "keyword_matched": decision.keyword_matched,
                    "compliance_reply": decision.compliance_reply,
                    "policy_version": decision.policy_version,
                }
            except Exception as error:  # noqa: BLE001 -- fail-open 保护问答主链路
                logger.warning(
                    "SafetyGuard.check_content failed: %s: %s",
                    type(error).__name__,
                    error,
                )
                session.rollback()
                return {
                    "allowed": True,
                    "action": "allow",
                    "reason": "safety_guard_unavailable_fail_open",
                    "decision_factors": ["evaluation_error_fail_open"],
                    "compliance_reply": None,
                    "policy_version": "safety-policy-v2.1",
                }
            finally:
                session.close()

    return SessionScopedSafetyGuardPort()
