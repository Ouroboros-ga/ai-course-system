"""阶段9 教师安全阀端口实现。

高风险动作（trigger_experiment/web_research/change_topic）默认生成提案，状态 pending；
教师通过 /agent-governance/proposals/{id}/decision 端点决策 approve/reject/lock/rerun；
提案与决策均按 course_id 严格隔离。

设计要点：
- 仅存结构化动作元数据（concept_id/resource_id/tool_name/proposal_type），绝不存 raw message/answer
- 教师锁定项 AI 重跑不可覆盖：lock 决策后 proposal.status=locked，相同模式后续提案自动 superseded
- 与正式 LearningEvent/LearningEvidence 严格分离
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Mapping

from sqlmodel import Session

from app.models.database import engine
from app.services.agent_governance_service import agent_governance_service

logger = logging.getLogger(__name__)


def _proposal_to_dict(proposal) -> dict[str, Any]:
    """将 AgentActionProposal ORM 对象转为字典；剥离 raw payload。"""
    return {
        "proposal_id": proposal.proposal_id,
        "trace_id": proposal.trace_id,
        "student_id": proposal.student_id,
        "course_id": proposal.course_id,
        "session_id": proposal.session_id,
        "proposal_type": proposal.proposal_type,
        "tool_name": proposal.tool_name,
        "proposed_action": json.loads(proposal.proposed_action) if proposal.proposed_action else {},
        "risk_level": proposal.risk_level,
        "requires_confirmation": proposal.requires_confirmation,
        "status": proposal.status,
        "agent_policy_version_id": proposal.agent_policy_version_id,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "decided_at": proposal.decided_at.isoformat() if proposal.decided_at else None,
    }


def make_session_scoped_teacher_safety_valve_port(session_factory: Callable[[], Session]):
    """构造一个 session 作用域的 TeacherSafetyValvePort 实现。"""

    class SessionScopedTeacherSafetyValvePort:
        async def create_proposal(
            self,
            *,
            course_id: str,
            student_id: str,
            trace_id: str,
            session_id: str,
            proposal_type: str,
            tool_name: str,
            proposed_action: Mapping[str, Any],
            requires_confirmation: bool | None = None,
        ) -> Mapping[str, Any]:
            try:
                course_id_int = int(course_id)
                student_id_int = int(student_id)
            except (TypeError, ValueError) as error:
                logger.warning("TeacherSafetyValve.create_proposal invalid id: %s", error)
                return {"proposal_id": "", "status": "invalid_id"}
            session = session_factory()
            try:
                proposal = agent_governance_service.create_proposal(
                    session,
                    course_id=course_id_int,
                    student_id=student_id_int,
                    trace_id=trace_id,
                    session_id=session_id,
                    proposal_type=proposal_type,
                    tool_name=tool_name,
                    proposed_action=dict(proposed_action),
                    requires_confirmation=requires_confirmation,
                )
                # P1-E6: 工具/动作模式已被教师锁定，拒绝创建提案
                if proposal is None:
                    return {"proposal_id": "", "status": "tool_locked_by_teacher"}
                session.commit()
                return _proposal_to_dict(proposal)
            except Exception as error:  # noqa: BLE001
                logger.warning("TeacherSafetyValve.create_proposal failed: %s: %s", type(error).__name__, error)
                session.rollback()
                return {"proposal_id": "", "status": "error", "error": type(error).__name__}
            finally:
                session.close()

        async def list_pending_proposals(self, *, course_id: str, limit: int = 50) -> list[Mapping[str, Any]]:
            try:
                course_id_int = int(course_id)
            except (TypeError, ValueError):
                return []
            session = session_factory()
            try:
                rows = agent_governance_service.list_proposals(
                    session, course_id=course_id_int, status="pending", limit=limit,
                )
                return [_proposal_to_dict(p) for p in rows]
            except Exception as error:  # noqa: BLE001
                logger.warning("TeacherSafetyValve.list_pending_proposals failed: %s: %s", type(error).__name__, error)
                return []
            finally:
                session.close()

        async def decide_proposal(
            self,
            *,
            course_id: str,
            proposal_id: str,
            decision: str,
            decided_by: str,
            decision_reason: str = "",
        ) -> Mapping[str, Any]:
            try:
                course_id_int = int(course_id)
                decided_by_int = int(decided_by)
            except (TypeError, ValueError) as error:
                logger.warning("TeacherSafetyValve.decide_proposal invalid id: %s", error)
                return {"status": "invalid_id"}
            session = session_factory()
            try:
                proposal, decision_record = agent_governance_service.decide_proposal(
                    session,
                    course_id=course_id_int,
                    proposal_id=proposal_id,
                    decision=decision,
                    decided_by=decided_by_int,
                    decision_reason=decision_reason,
                )
                session.commit()
                result = _proposal_to_dict(proposal)
                result["decision"] = {
                    "decision": decision_record.decision,
                    "decided_by": decision_record.decided_by,
                    "decision_reason": decision_record.decision_reason,
                    "rerun_trace_id": decision_record.rerun_trace_id,
                    "decided_at": decision_record.decided_at.isoformat() if decision_record.decided_at else None,
                }
                return result
            except Exception as error:  # noqa: BLE001
                logger.warning("TeacherSafetyValve.decide_proposal failed: %s: %s", type(error).__name__, error)
                session.rollback()
                return {"status": "error", "error": type(error).__name__}
            finally:
                session.close()

        async def get_proposal(self, *, course_id: str, proposal_id: str) -> Mapping[str, Any] | None:
            try:
                course_id_int = int(course_id)
            except (TypeError, ValueError):
                return None
            session = session_factory()
            try:
                proposal = agent_governance_service.get_proposal(
                    session, course_id=course_id_int, proposal_id=proposal_id,
                )
                return _proposal_to_dict(proposal)
            except Exception as error:  # noqa: BLE001
                logger.warning("TeacherSafetyValve.get_proposal failed: %s: %s", type(error).__name__, error)
                return None
            finally:
                session.close()

    return SessionScopedTeacherSafetyValvePort()
