"""智能体相关 Pydantic 模型。

阶段9：Agent 工具治理与教师安全阀契约 schema。
- 仅含结构化摘要字段；严禁 raw user_message/answer/prompt 进入请求体或响应体
- ToolPolicy / Proposal / Decision / Invocation 全部按 course_id 隔离
- 与正式 LearningEvent/LearningEvidence 严格分离，本表仅用于运营审计与教师治理
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field
from app.platform.agents.tools.catalog import BUILTIN_TOOL_NAMES as CATALOG_TOOL_NAMES


# ---------------------------------------------------------------------------
# 工具策略
# ---------------------------------------------------------------------------


class ToolPolicyItem(BaseModel):
    """工具策略项（响应/请求共享）。"""

    tool_name: str = Field(..., description="内置工具名，如 graph/retrieval/question_bank")
    enabled: bool = Field(default=True, description="教师是否启用该工具")
    require_confirmation: bool = Field(default=False, description="产出是否需要教师确认")
    confirmation_threshold: str = Field(
        default="never",
        description="always | high_risk_only | never",
    )
    locked: bool = Field(default=False, description="教师锁定项，AI 重跑不可覆盖")
    locked_reason: Optional[str] = Field(default=None, max_length=256)
    configurable: bool = Field(default=True, description="该目录项是否允许课程级修改")
    status: str = Field(default="active", description="active | deprecated_non_configurable")


class ToolPolicyUpdateRequest(BaseModel):
    """教师批量更新工具策略请求体。"""

    expected_version: Optional[int] = Field(
        default=None,
        description="乐观锁：当前激活版本号；不传则跳过校验",
    )
    updates: list[ToolPolicyItem] = Field(..., min_length=1, max_length=20)


class ToolPolicyVersionView(BaseModel):
    """策略版本视图。"""

    version: int
    summary: str
    is_active: bool
    created_by: int
    created_at: str


class ToolPolicyBatchView(BaseModel):
    """工具策略批次视图。"""

    course_id: int
    active_version: Optional[ToolPolicyVersionView]
    items: list[ToolPolicyItem]


# ---------------------------------------------------------------------------
# 动作提案
# ---------------------------------------------------------------------------


class ProposalView(BaseModel):
    """Agent 动作提案视图（剥离 raw message/answer）。"""

    proposal_id: str
    trace_id: str
    student_id: int
    course_id: int
    session_id: str
    proposal_type: str
    tool_name: str
    proposed_action: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = Field(default="low", description="low | medium | high")
    requires_confirmation: bool = True
    status: str = Field(default="pending", description="pending | approved | rejected | locked | superseded")
    agent_policy_version_id: Optional[int] = None
    created_at: str
    decided_at: Optional[str] = None


class ProposalDecisionRequest(BaseModel):
    """教师决策请求体。"""

    decision: str = Field(..., description="approve | reject | lock | rerun")
    decision_reason: str = Field(default="", max_length=256)


class ProposalDecisionView(BaseModel):
    """教师决策记录视图。"""

    proposal_id: str
    decision: str
    decided_by: int
    decision_reason: Optional[str] = None
    rerun_trace_id: Optional[str] = None
    decided_at: str


class ProposalDetailWithDecisionView(ProposalView):
    """提案详情（含最新决策）。"""

    latest_decision: Optional[ProposalDecisionView] = None


# ---------------------------------------------------------------------------
# 工具调用审计
# ---------------------------------------------------------------------------


class ToolInvocationView(BaseModel):
    """工具调用审计视图（input/output_summary 仅含结构化摘要）。"""

    trace_id: str
    student_id: int
    course_id: int
    tool_name: str
    invoked_at: str
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[int] = None
    degraded: bool = False
    degraded_reason: Optional[str] = None
    allowed_by_policy: bool = True
    agent_policy_version_id: Optional[int] = None


# ---------------------------------------------------------------------------
# 内置工具名枚举（用于前端展示）
# ---------------------------------------------------------------------------


BUILTIN_TOOL_NAMES: list[str] = sorted(CATALOG_TOOL_NAMES)
