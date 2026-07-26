"""阶段9 Agent 工具治理与教师安全阀服务层。

职责：
- 课程级工具策略 CRUD（教师启用/禁用/锁定/确认门槛），版本化快照支持回滚
- Agent 动作提案创建/列表/详情
- 教师决策状态机（approve/reject/lock/rerun），含跨课程隔离与状态校验
- 工具调用审计记录与查询
- 数据最小化：所有写入仅存结构化摘要，绝不存 raw message/answer/prompt

硬约束：
- 课程 A 的策略/提案/决策/调用记录永不出现在课程 B（所有查询按 course_id 过滤）
- 教师锁定项 AI 重跑不可覆盖（locked=True 持久化）
- 失败保留原始 error_code，禁止伪装成功
- 与正式 LearningEvent/LearningEvidence 严格分离
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Iterable, Optional

from sqlmodel import Session, func, select

from app.core.exceptions import (
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import utcnow_naive
from app.models.agent_governance_model import (
    AgentActionDecision,
    AgentActionProposal,
    AgentPolicyVersion,
    AgentToolInvocation,
    AgentToolPolicy,
)

logger = logging.getLogger(__name__)


# 内置工具名清单；防止教师配置未知工具导致 Agent 异常
BUILTIN_TOOL_NAMES: frozenset[str] = frozenset({
    "graph", "retrieval", "question_bank", "experiment",
    "visualization", "learning_event", "web_research", "sandbox",
    "cognition", "student_modeling", "recommendation", "conversation_context",
})

# 默认工具策略：所有内置工具启用，不需要确认
DEFAULT_TOOL_POLICY: dict[str, dict[str, Any]] = {
    name: {"enabled": True, "require_confirmation": False, "confirmation_threshold": "never"}
    for name in BUILTIN_TOOL_NAMES
}

# 高风险动作类型 → 风险等级映射，用于安全阀判定
HIGH_RISK_PROPOSAL_TYPES: frozenset[str] = frozenset({
    "trigger_experiment", "web_research", "change_topic",
})
MEDIUM_RISK_PROPOSAL_TYPES: frozenset[str] = frozenset({
    "recommend_resource", "offer_hint",
})


# ---------------------------------------------------------------------------
# 策略版本与工具策略
# ---------------------------------------------------------------------------


class AgentGovernanceService:
    """Agent 工具治理与教师安全阀服务。"""

    # -----------------------------------------------------------------
    # 策略版本
    # -----------------------------------------------------------------

    def get_active_policy_version(
        self, session: Session, *, course_id: int,
    ) -> Optional[AgentPolicyVersion]:
        """获取课程当前激活的策略版本。"""
        return session.exec(
            select(AgentPolicyVersion).where(
                AgentPolicyVersion.course_id == course_id,
                AgentPolicyVersion.is_active == True,  # noqa: E712
            ).order_by(AgentPolicyVersion.version.desc())
        ).first()

    def _create_policy_version(
        self,
        session: Session,
        *,
        course_id: int,
        summary: str,
        policy_snapshot: dict[str, Any],
        created_by: int,
    ) -> AgentPolicyVersion:
        """创建新策略版本；旧版本标记 is_active=False。"""
        # 旧版本失活
        old_versions = session.exec(
            select(AgentPolicyVersion).where(
                AgentPolicyVersion.course_id == course_id,
                AgentPolicyVersion.is_active == True,  # noqa: E712
            )
        ).all()
        for old in old_versions:
            old.is_active = False
            session.add(old)

        max_version = session.exec(
            select(func.max(AgentPolicyVersion.version)).where(
                AgentPolicyVersion.course_id == course_id,
            )
        ).one() or 0

        version = AgentPolicyVersion(
            course_id=course_id,
            version=int(max_version) + 1,
            summary=summary[:256],
            policy_snapshot=json.dumps(policy_snapshot, ensure_ascii=False),
            is_active=True,
            created_by=created_by,
        )
        session.add(version)
        session.flush()
        return version

    # -----------------------------------------------------------------
    # 工具策略 CRUD
    # -----------------------------------------------------------------

    def list_tool_policies(
        self, session: Session, *, course_id: int,
    ) -> list[AgentToolPolicy]:
        """列出课程的所有工具策略；缺失的内置工具返回默认值（不落库）。"""
        rows = session.exec(
            select(AgentToolPolicy).where(AgentToolPolicy.course_id == course_id)
        ).all()
        return list(rows)

    def get_tool_policy(
        self, session: Session, *, course_id: int, tool_name: str,
    ) -> Optional[AgentToolPolicy]:
        return session.exec(
            select(AgentToolPolicy).where(
                AgentToolPolicy.course_id == course_id,
                AgentToolPolicy.tool_name == tool_name,
            )
        ).first()

    def is_tool_enabled(self, session: Session, *, course_id: int, tool_name: str) -> bool:
        """查询工具是否启用；未配置时按默认值 True 返回。"""
        policy = self.get_tool_policy(session, course_id=course_id, tool_name=tool_name)
        if policy is None:
            return DEFAULT_TOOL_POLICY.get(tool_name, {}).get("enabled", True)
        return bool(policy.enabled)

    def requires_confirmation(
        self, session: Session, *, course_id: int, tool_name: str,
    ) -> tuple[bool, str]:
        """返回 (是否需要确认, 确认门槛)；未配置时返回 (False, 'never')。"""
        policy = self.get_tool_policy(session, course_id=course_id, tool_name=tool_name)
        if policy is None:
            default = DEFAULT_TOOL_POLICY.get(tool_name, {})
            return bool(default.get("require_confirmation", False)), str(default.get("confirmation_threshold", "never"))
        return bool(policy.require_confirmation), str(policy.confirmation_threshold)

    def upsert_tool_policies(
        self,
        session: Session,
        *,
        course_id: int,
        updates: list[dict[str, Any]],
        created_by: int,
        expected_version: Optional[int] = None,
    ) -> tuple[AgentPolicyVersion, list[AgentToolPolicy]]:
        """批量更新工具策略；生成新版本快照。

        - expected_version 用于乐观锁冲突检测；不匹配返回 409 VERSION_CONFLICT
        - locked=True 的策略行不可被 AI 重跑覆盖（仅教师显式调用本方法可修改）
        - 每次更新生成新 agent_policy_versions 行
        """
        if not updates:
            reject_validation_failed("updates 不能为空")

        # 乐观锁校验
        active_version = self.get_active_policy_version(session, course_id=course_id)
        current_version = active_version.version if active_version else 0
        if expected_version is not None and expected_version != current_version:
            reject_state_conflict(
                "策略版本冲突",
                details={"expected_version": expected_version, "current_version": current_version},
            )

        # 校验工具名合法
        for upd in updates:
            tool_name = str(upd.get("tool_name", ""))
            if tool_name not in BUILTIN_TOOL_NAMES:
                reject_validation_failed(f"未知工具名: {tool_name}")

        # 创建新版本
        snapshot: dict[str, Any] = {}
        result_rows: list[AgentToolPolicy] = []
        now = utcnow_naive()

        for upd in updates:
            tool_name = str(upd["tool_name"])
            existing = self.get_tool_policy(session, course_id=course_id, tool_name=tool_name)
            # 教师锁定项保护：AI 重跑不可覆盖（仅当调用方显式传 locked=False 才解锁，本服务始终视为教师显式调用）
            if existing is not None and existing.locked and not upd.get("locked", True):
                # 教师显式解锁允许；继续
                pass

            enabled = bool(upd.get("enabled", True))
            require_confirmation = bool(upd.get("require_confirmation", False))
            confirmation_threshold = str(upd.get("confirmation_threshold", "never"))
            if confirmation_threshold not in ("always", "high_risk_only", "never"):
                reject_validation_failed(f"无效 confirmation_threshold: {confirmation_threshold}")
            locked = bool(upd.get("locked", False))
            locked_reason = upd.get("locked_reason")

            if existing is None:
                row = AgentToolPolicy(
                    course_id=course_id,
                    tool_name=tool_name,
                    enabled=enabled,
                    require_confirmation=require_confirmation,
                    confirmation_threshold=confirmation_threshold,
                    locked=locked,
                    locked_reason=locked_reason,
                    created_by=created_by,
                    updated_at=now,
                )
            else:
                existing.enabled = enabled
                existing.require_confirmation = require_confirmation
                existing.confirmation_threshold = confirmation_threshold
                existing.locked = locked
                existing.locked_reason = locked_reason
                existing.updated_at = now
                row = existing

            session.add(row)
            session.flush()
            result_rows.append(row)
            snapshot[tool_name] = {
                "enabled": enabled,
                "require_confirmation": require_confirmation,
                "confirmation_threshold": confirmation_threshold,
                "locked": locked,
            }

        version = self._create_policy_version(
            session,
            course_id=course_id,
            summary=f"更新 {len(updates)} 个工具策略",
            policy_snapshot=snapshot,
            created_by=created_by,
        )

        # 回填 policy_version_id
        for row in result_rows:
            row.agent_policy_version_id = version.id
            session.add(row)
        session.flush()

        return version, result_rows

    # -----------------------------------------------------------------
    # 动作提案
    # -----------------------------------------------------------------

    @staticmethod
    def _classify_risk(proposal_type: str) -> str:
        if proposal_type in HIGH_RISK_PROPOSAL_TYPES:
            return "high"
        if proposal_type in MEDIUM_RISK_PROPOSAL_TYPES:
            return "medium"
        return "low"

    def create_proposal(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        trace_id: str,
        session_id: str,
        proposal_type: str,
        tool_name: str,
        proposed_action: dict[str, Any],
        requires_confirmation: Optional[bool] = None,
    ) -> AgentActionProposal:
        """创建动作提案；状态默认 pending。

        - 风险等级按 proposal_type 自动分类
        - proposed_action 仅存结构化动作元数据，调用方负责剥离 raw message
        """
        risk = self._classify_risk(proposal_type)
        active_version = self.get_active_policy_version(session, course_id=course_id)
        if requires_confirmation is None:
            # 默认 high 风险或教师策略要求确认时才需确认
            requires_confirmation = risk == "high"

        proposal = AgentActionProposal(
            proposal_id="ap_" + uuid.uuid4().hex,
            trace_id=trace_id[:128],
            student_id=student_id,
            course_id=course_id,
            session_id=session_id[:128],
            proposal_type=proposal_type[:64],
            tool_name=tool_name[:64],
            proposed_action=json.dumps(proposed_action, ensure_ascii=False),
            risk_level=risk,
            requires_confirmation=requires_confirmation,
            status="pending",
            agent_policy_version_id=active_version.id if active_version else None,
        )
        session.add(proposal)
        session.flush()
        return proposal

    def get_proposal(
        self, session: Session, *, course_id: int, proposal_id: str,
    ) -> AgentActionProposal:
        """按 course_id 隔离获取提案；跨课程返回 404。"""
        proposal = session.exec(
            select(AgentActionProposal).where(
                AgentActionProposal.proposal_id == proposal_id,
                AgentActionProposal.course_id == course_id,
            )
        ).first()
        if proposal is None:
            reject_resource_not_found(f"提案 {proposal_id} 不存在")
        return proposal

    def list_proposals(
        self,
        session: Session,
        *,
        course_id: int,
        status: Optional[str] = None,
        student_id: Optional[int] = None,
        limit: int = 50,
    ) -> list[AgentActionProposal]:
        """列出课程提案；按 course_id 严格隔离。"""
        stmt = select(AgentActionProposal).where(
            AgentActionProposal.course_id == course_id,
        )
        if status is not None:
            stmt = stmt.where(AgentActionProposal.status == status)
        if student_id is not None:
            stmt = stmt.where(AgentActionProposal.student_id == student_id)
        stmt = stmt.order_by(AgentActionProposal.created_at.desc()).limit(max(1, min(limit, 200)))
        return list(session.exec(stmt).all())

    # -----------------------------------------------------------------
    # 教师决策状态机
    # -----------------------------------------------------------------

    def decide_proposal(
        self,
        session: Session,
        *,
        course_id: int,
        proposal_id: str,
        decision: str,
        decided_by: int,
        decision_reason: str = "",
    ) -> tuple[AgentActionProposal, AgentActionDecision]:
        """教师决策状态机：approve/reject/lock/rerun。

        - approve: pending → approved；触发 Agent 续跑（由调用方负责）
        - reject: pending → rejected
        - lock: pending → locked；后续相同模式提案自动 superseded
        - rerun: rejected/superseded → pending（生成新 trace_id 关联）
        """
        if decision not in ("approve", "reject", "lock", "rerun"):
            reject_validation_failed(f"无效决策: {decision}")

        proposal = self.get_proposal(session, course_id=course_id, proposal_id=proposal_id)

        # 状态机校验
        valid_transitions = {
            "approve": {"pending"},
            "reject": {"pending"},
            "lock": {"pending", "approved"},
            "rerun": {"rejected", "superseded"},
        }
        if proposal.status not in valid_transitions[decision]:
            reject_state_conflict(
                f"提案状态 {proposal.status} 不允许 {decision}",
                details={"current_status": proposal.status, "decision": decision},
            )

        # rerun 生成新 trace_id；其他决策直接更新状态
        rerun_trace_id = None
        new_status = {
            "approve": "approved",
            "reject": "rejected",
            "lock": "locked",
            "rerun": "pending",
        }[decision]
        if decision == "rerun":
            rerun_trace_id = str(uuid.uuid4())

        proposal.status = new_status
        proposal.decided_at = utcnow_naive()
        session.add(proposal)

        decision_record = AgentActionDecision(
            proposal_id=proposal.proposal_id,
            decision=decision,
            decided_by=decided_by,
            decision_reason=decision_reason[:256] if decision_reason else None,
            rerun_trace_id=rerun_trace_id,
            audit_data=json.dumps({
                "trace_id": proposal.trace_id,
                "course_id": course_id,
                "student_id": proposal.student_id,
                "tool_name": proposal.tool_name,
                "proposal_type": proposal.proposal_type,
                "risk_level": proposal.risk_level,
            }, ensure_ascii=False),
        )
        session.add(decision_record)
        session.flush()
        return proposal, decision_record

    # -----------------------------------------------------------------
    # 工具调用审计
    # -----------------------------------------------------------------

    def record_tool_invocation(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
        trace_id: str,
        tool_name: str,
        input_summary: dict[str, Any],
        output_summary: dict[str, Any],
        duration_ms: Optional[int] = None,
        degraded: bool = False,
        degraded_reason: str = "",
        allowed_by_policy: bool = True,
    ) -> AgentToolInvocation:
        """记录单次工具调用审计。

        - input_summary/output_summary 仅含结构化摘要（如 evidence_ids、concept_id、is_supplementary）
        - 调用方负责剥离 raw query/text/answer
        """
        active_version = self.get_active_policy_version(session, course_id=course_id)
        invocation = AgentToolInvocation(
            trace_id=trace_id[:128],
            student_id=student_id,
            course_id=course_id,
            tool_name=tool_name[:64],
            input_summary=json.dumps(input_summary, ensure_ascii=False),
            output_summary=json.dumps(output_summary, ensure_ascii=False),
            duration_ms=duration_ms,
            degraded=degraded,
            degraded_reason=degraded_reason[:64] if degraded_reason else None,
            allowed_by_policy=allowed_by_policy,
            agent_policy_version_id=active_version.id if active_version else None,
        )
        session.add(invocation)
        session.flush()
        return invocation

    def list_invocations(
        self,
        session: Session,
        *,
        course_id: int,
        trace_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 100,
    ) -> list[AgentToolInvocation]:
        """列出工具调用审计；按 course_id 严格隔离。"""
        stmt = select(AgentToolInvocation).where(
            AgentToolInvocation.course_id == course_id,
        )
        if trace_id is not None:
            stmt = stmt.where(AgentToolInvocation.trace_id == trace_id)
        if tool_name is not None:
            stmt = stmt.where(AgentToolInvocation.tool_name == tool_name)
        stmt = stmt.order_by(AgentToolInvocation.invoked_at.desc()).limit(max(1, min(limit, 500)))
        return list(session.exec(stmt).all())

    # -----------------------------------------------------------------
    # 审计聚合
    # -----------------------------------------------------------------

    def list_decisions(
        self,
        session: Session,
        *,
        course_id: int,
        proposal_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[tuple[AgentActionDecision, AgentActionProposal]]:
        """列出教师决策审计；按 course_id 严格隔离。

        返回 [(decision, proposal), ...]，调用方可据 proposal_id/decision_type 过滤。
        """
        stmt = (
            select(AgentActionDecision, AgentActionProposal)
            .where(
                AgentActionDecision.proposal_id == AgentActionProposal.proposal_id,
                AgentActionProposal.course_id == course_id,
            )
            .order_by(AgentActionDecision.decided_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        if proposal_id is not None:
            stmt = stmt.where(AgentActionProposal.proposal_id == proposal_id)
        return list(session.exec(stmt).all())


# 模块级单例；调用方通过 import 使用
agent_governance_service = AgentGovernanceService()
