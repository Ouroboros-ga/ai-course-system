"""阶段9 Agent 工具治理与教师安全阀数据模型。

设计要点（与 agent_log.py 一致的数据最小化策略）：
- 所有结构化字段仅存审计/治理元数据，绝不存原始 user_message、final_answer、prompt 或完整 LLM trace。
- 严格按 course_id 隔离；课程 A 的策略、提案、决策、调用记录永不出现在课程 B。
- 与正式 LearningEvent/LearningEvidence 严格分离：本表只用于运营审计与教师治理，绝不更新掌握度或认知结果。
- 版本化策略快照支持乐观锁与回滚；每个写操作携带 policy_version_id 用于审计追溯。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# 策略版本快照
# ---------------------------------------------------------------------------


class AgentPolicyVersion(SQLModel, table=True):
    """Agent 策略版本快照。

    每次教师修改工具策略生成新版本；旧版本保留以支持审计与回滚。
    is_active=True 的版本是当前生效版本。
    """

    __tablename__ = "agent_policy_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(index=True)
    version: int = Field(description="单调递增版本号")
    summary: str = Field(default="", max_length=256)
    policy_snapshot: str = Field(default="{}", description="JSON: 完整策略快照")
    is_active: bool = Field(default=True, index=True)
    created_by: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# 课程级工具策略
# ---------------------------------------------------------------------------


class AgentToolPolicy(SQLModel, table=True):
    """课程级 Agent 工具策略行。

    每个 (course_id, tool_name) 一行，记录教师是否启用、是否需要确认、是否锁定。
    教师锁定的工具 AI 重跑不可覆盖；agent_policy_version_id 用于版本审计。
    """

    __tablename__ = "agent_tool_policies"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(index=True)
    tool_name: str = Field(index=True, max_length=64, description="如 graph/retrieval/question_bank/experiment/visualization/learning_event/web_research/sandbox")
    enabled: bool = Field(default=True, description="教师是否启用该工具")
    require_confirmation: bool = Field(default=False, description="该工具产出是否需要教师确认才生效")
    confirmation_threshold: str = Field(default="never", max_length=32, description="always | high_risk_only | never")
    locked: bool = Field(default=False, description="教师锁定项，AI 重跑不可覆盖")
    locked_reason: str | None = Field(default=None, max_length=256)
    agent_policy_version_id: Optional[int] = Field(default=None, foreign_key="agent_policy_versions.id", index=True)
    created_by: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    data_policy_version: str = Field(default="agent-governance/1", max_length=64)


# ---------------------------------------------------------------------------
# Agent 动作提案
# ---------------------------------------------------------------------------


class AgentActionProposal(SQLModel, table=True):
    """Agent 高风险动作提案。

    Agent 工作流在执行高风险动作前生成提案；教师通过决策端点确认/拒绝/锁定/重跑。
    状态机：pending → approved | rejected | locked | superseded。
    proposal_payload 仅含结构化动作元数据，绝不存 raw message/answer。
    """

    __tablename__ = "agent_action_proposals"

    id: Optional[int] = Field(default=None, primary_key=True)
    proposal_id: str = Field(unique=True, index=True, max_length=64, description="ap_ 前缀 + UUID hex")
    trace_id: str = Field(index=True, max_length=128)
    student_id: int = Field(index=True)
    course_id: int = Field(index=True)
    session_id: str = Field(max_length=128)
    proposal_type: str = Field(max_length=64, description="如 recommend_resource / change_topic / trigger_experiment / offer_hint / web_research")
    tool_name: str = Field(max_length=64)
    proposed_action: str = Field(default="{}", description="JSON: 结构化动作载荷，不含 raw message")
    risk_level: str = Field(default="low", max_length=16, description="low | medium | high")
    requires_confirmation: bool = Field(default=True)
    status: str = Field(default="pending", index=True, max_length=16, description="pending | approved | rejected | locked | superseded")
    agent_policy_version_id: Optional[int] = Field(default=None, foreign_key="agent_policy_versions.id")
    data_policy_version: str = Field(default="agent-governance/1", max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    decided_at: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# 教师决策
# ---------------------------------------------------------------------------


class AgentActionDecision(SQLModel, table=True):
    """教师对 Agent 动作提案的决策记录。

    每次 approve/reject/lock/rerun 生成一行；rerun_trace_id 用于追踪重跑关联的新 trace。
    audit_data 仅含审计元数据，绝不存 raw message/answer。
    """

    __tablename__ = "agent_action_decisions"

    id: Optional[int] = Field(default=None, primary_key=True)
    proposal_id: str = Field(index=True, max_length=64, description="外键 → agent_action_proposals.proposal_id")
    decision: str = Field(max_length=16, description="approve | reject | lock | rerun")
    decided_by: int = Field(index=True)
    decision_reason: str | None = Field(default=None, max_length=256)
    rerun_trace_id: str | None = Field(default=None, max_length=128, description="重跑时关联新 trace_id")
    audit_data: str = Field(default="{}", description="JSON: 审计元数据")
    data_policy_version: str = Field(default="agent-governance/1", max_length=64)
    decided_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# 工具调用审计
# ---------------------------------------------------------------------------


class AgentToolInvocation(SQLModel, table=True):
    """Agent 工具调用审计记录。

    每次工具被调用生成一行；input_summary/output_summary 仅含结构化摘要，绝不存 raw payload。
    allowed_by_policy=False 表示该调用被教师策略拒绝（用于审计与可观测性）。
    """

    __tablename__ = "agent_tool_invocations"

    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True, max_length=128)
    student_id: int = Field(index=True)
    course_id: int = Field(index=True)
    tool_name: str = Field(index=True, max_length=64)
    invoked_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    input_summary: str = Field(default="{}", description="JSON: 结构化输入摘要，不含 raw query/text")
    output_summary: str = Field(default="{}", description="JSON: 结构化输出摘要，如 evidence_ids/concept_id/is_supplementary")
    duration_ms: int | None = Field(default=None)
    degraded: bool = Field(default=False)
    degraded_reason: str | None = Field(default=None, max_length=64)
    allowed_by_policy: bool = Field(default=True)
    agent_policy_version_id: Optional[int] = Field(default=None, foreign_key="agent_policy_versions.id")
    data_policy_version: str = Field(default="agent-governance/1", max_length=64)
