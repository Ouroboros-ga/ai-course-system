"""Tool-governance and teacher safety-valve ports.

``ToolGovernancePort`` is queried before each tool node; disabled tools are
skipped with audit logging. ``TeacherSafetyValvePort`` generates proposals for
high-risk actions and awaits teacher decision before execution. Both ports
are strictly isolated by ``course_id``.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ToolGovernancePort(Protocol):
    """工具治理端口：在每个工具节点前查询教师策略，被禁用则跳过。

    - is_tool_enabled(course_id, tool_name) → bool：工具是否启用
    - requires_confirmation(course_id, tool_name) → (bool, threshold)：是否需要教师确认
    - record_invocation(...) → None：记录工具调用审计
    - 端口实现按 course_id 严格隔离；课程 A 的策略不影响课程 B
    """

    async def is_tool_enabled(self, *, course_id: str, tool_name: str) -> bool: ...
    async def requires_confirmation(self, *, course_id: str, tool_name: str) -> Mapping[str, Any]: ...
    async def record_invocation(self, *, course_id: str, student_id: str, trace_id: str, tool_name: str, input_summary: Mapping[str, Any], output_summary: Mapping[str, Any], duration_ms: int | None = None, degraded: bool = False, degraded_reason: str = "", allowed_by_policy: bool = True) -> None: ...


class TeacherSafetyValvePort(Protocol):
    """教师安全阀端口：高风险动作生成提案，等待教师决策。

    - create_proposal(...) → proposal_id：创建提案，状态 pending
    - list_pending_proposals(course_id) → list[Mapping]：教师待办列表
    - decide_proposal(course_id, proposal_id, decision, decided_by, reason) → Mapping：决策状态机
    - 高风险动作（trigger_experiment/web_research/change_topic）默认需要确认
    - 教师锁定项 AI 重跑不可覆盖
    """

    async def create_proposal(self, *, course_id: str, student_id: str, trace_id: str, session_id: str, proposal_type: str, tool_name: str, proposed_action: Mapping[str, Any], requires_confirmation: bool | None = None, confirmation_mode: str | None = None) -> Mapping[str, Any]: ...
    async def list_pending_proposals(self, *, course_id: str, limit: int = 50) -> list[Mapping[str, Any]]: ...
    async def decide_proposal(self, *, course_id: str, proposal_id: str, decision: str, decided_by: str, decision_reason: str = "") -> Mapping[str, Any]: ...
    async def get_proposal(self, *, course_id: str, proposal_id: str) -> Mapping[str, Any] | None: ...


__all__ = ["ToolGovernancePort", "TeacherSafetyValvePort"]
